#!/usr/bin/env python3
"""公式の価格・在庫の再確認（Phase 15）。

手で一回確認した公式の価格・在庫は、期限（価格: price_evidence の基準・在庫: 7日）で切れる。ここでは、すでに
確認済み（src/market/official_registry.VERIFIED_URLS）の商品のうち、公式ページの静的な HTML で価格・在庫・型番を
読み取れるもの（RECHECK_TARGETS）だけを、取得の共通の作法（src/collectors/polite.py: robots.txt・同じドメインの
間隔・正直な User-Agent）で取り直し、結果を記録する。45商品に一度に広げない。

結果（status）:
- unchanged: 型番が一致し、価格が記録と同じ
- changed: 型番は一致したが、価格が記録と違う（確認済みの価格を自動で書き換えない。人が確かめるまで確定に使わない）
- sale_ended: ページに販売終了・生産終了の表示がある
- failed: 取得できない・型番や価格を読み取れない（前回の価格は消さない。確認日も新しくしない）
- blocked: robots.txt の禁止・到達できない・403・429（取りに行かない／打ち切る）
在庫（stock）は、明示の表示（在庫切れの表示・購入できる表示）を読み取れたときだけ記録する（無ければ空）。

出力: exports/official_recheck/latest.json（今回の結果）・history.json（直近の結果の履歴。上限つき）
使い方:
  python scripts/recheck_official.py            # 再確認する
  python scripts/recheck_official.py --plan     # 期限と対象の一覧だけ（ネットワークに出ない）
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JST = timezone(timedelta(hours=9))
OUT = ROOT / "exports" / "official_recheck"
HISTORY_LIMIT = 300

# 静的な HTML で読み取れる公式ページ（ホスト → 読み取りの種類）。My Nintendo Store は JavaScript で描画する
# （静的な HTML に価格・在庫が無い）ので、ここには入れない。Phase 16 でキヤノン・ニコン・フジフイルムモールの直販と
# Apple の iPhone の購入ページを加えた（2026-10-08: store.canon.jp・nij.nikon.com・mall-jp.fujifilm.com の robots.txt に
# 禁止なし。Apple は Phase 15 から同じホスト。静的な HTML に価格がある。Playwright は使わない。実行時も毎回
# polite.robots_allowed で確かめる）
PARSERS = {"pur.store.sony.jp": "sony_store", "www.apple.com": "apple_jsonld",
           "store.canon.jp": "canon_store", "nij.nikon.com": "nikon_direct", "mall-jp.fujifilm.com": "fuji_mall"}
# 同じホストでも読み方が違う商品（iPhone の購入ページは構造化データの offers が無く、商品データの部品番号で読む）
PARSER_OVERRIDE = {"prod_iphone17_256": "apple_parts"}
# 再確認する商品（すでに確認済みで、照合のキーが登録され、上の読み取りで確かめられるもの）。
# 公式直販価格は確認から14日で確認済みでなくなる（normalized_prices.OFFICIAL_DIRECT_STALE_DAYS）ので、全部を対象にする
RECHECK_TARGETS = ("prod_ps5_pro", "prod_airpods_pro3", "prod_r5ii", "prod_z8", "prod_iphone17_256", "prod_x100vi")
# 読み取りごとの照合のキー（ページのどの値で「この商品」と確かめるか）。既定は型番（model_number）
# - canon_store: 購入ページの URL の商品コード（6536C001 = ボディー。レンズキットは別のコード）
# - nikon_direct: JAN（型番 Z8 は短く、ページの別の場所にも出る）
# - apple_parts: 同じ容量の色違いの部品番号の組（official_registry.IDENTITY_EVIDENCE の variant_skus）
# - fuji_mall: 公式の証拠の JAN（色ごとに別なので、購入ページの色の JAN）と型番
UNMAPPED_INTERVAL_SEC = 120
MATCH_KEYS = {"canon_store": "url_code", "nikon_direct": "jan_code", "apple_parts": "variant_skus",
              "fuji_mall": "evidence_jan"}



def _text(h: str) -> str:
    t = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", t)))


_STOCK_WORDS = ("入荷待ち", "在庫切れ", "在庫あり", "販売終了")


def parse_sony_store(h: str, model: str) -> dict:
    """Sony Store の購入ページ: 「<型番> <在庫の表示> <価格> 円(税込)」の並び。

    在庫の欄が決まった語（入荷待ち・在庫切れ・在庫あり・販売終了）のときだけ価格を採用する（型番の後に別の商品の
    価格が並んでも拾わない）。販売終了は、この商品の在庫の欄が「販売終了」のときだけ（ページの別の場所の
    「販売終了」では判定しない。Phase 15 監査 M-1・M-2）。
    """
    t = _text(h)
    ms = list(re.finditer(re.escape(model) + r"\s+(" + "|".join(_STOCK_WORDS) + r")\s*([\d,]{4,})\s*円\s*\(税込\)", t))
    # 並びが無い・2つ以上ある（どれがこの商品か決められない）ときは読み取らない（監査 N-1）
    if len({(x.group(1), x.group(2)) for x in ms}) != 1:
        return {"model_found": model in t, "price": None, "stock": "", "ended": False}
    m = ms[0]
    stock = m.group(1)
    return {"model_found": True, "price": int(m.group(2).replace(",", "")),
            "stock": "" if stock == "販売終了" else stock, "ended": stock == "販売終了"}


def _offers(d) -> list:
    """構造化データの Product の offers（配列・1件の dict・@graph の中、のどれでも）。"""
    if isinstance(d, list):
        return [o for x in d for o in _offers(x)]
    if not isinstance(d, dict):
        return []
    if isinstance(d.get("@graph"), list):
        return _offers(d["@graph"])
    if d.get("@type") != "Product":
        return []
    offers = d.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    return [o for o in offers or [] if isinstance(o, dict)]


def parse_apple_jsonld(h: str, model: str) -> dict:
    """Apple の購入ページの構造化データ（Product → offers）: sku が型番と一致する offer の価格。在庫は読まない。"""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', h, flags=re.S):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        for o in _offers(d):
            if str(o.get("sku") or "") == model:
                try:
                    return {"model_found": True, "price": int(o.get("price")), "stock": "", "ended": False}
                except (TypeError, ValueError):
                    break
    return {"model_found": False, "price": None, "stock": "", "ended": False}


def _ld_blocks(h: str) -> list:
    out = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', h, flags=re.S):
        try:
            out.append(json.loads(block, strict=False))     # 説明文に改行がそのまま入っているページがある
        except ValueError:
            continue
    return out


def _products_ld(d) -> list:
    if isinstance(d, list):
        return [x for y in d for x in _products_ld(y)]
    if not isinstance(d, dict):
        return []
    if isinstance(d.get("@graph"), list):
        return _products_ld(d["@graph"])
    return [d] if d.get("@type") == "Product" else []


def parse_canon_store(h: str, code: str) -> dict:
    """キヤノンオンラインショップの購入ページ: 構造化データの Product（offers の url に商品コード・商品名にボディー）の価格。

    在庫は記録しない（構造化データに availability が無く、静的な HTML のカートのボタンは在庫の根拠にしない方針。
    stock_state・collectors/official/_generic と同じ。Phase 16 監査 M-2）。在庫は人の確認の記録（7日）だけ。
    """
    for d in _ld_blocks(h):
        for prod in _products_ld(d):
            name = str(prod.get("name") or "")
            for o in _offers(prod):
                if f"/g{code}/" not in str(o.get("url") or "") or "ボディー" not in name:
                    continue
                try:
                    price = int(str(o.get("price")))
                except (TypeError, ValueError):
                    return {"model_found": True, "price": None, "stock": "", "ended": False}
                return {"model_found": True, "price": price, "stock": "", "ended": False}
    return {"model_found": False, "price": None, "stock": "", "ended": False}


def parse_nikon_direct(h: str, jan: str) -> dict:
    """ニコンダイレクトの購入ページ: 「ニコンダイレクト販売価格 575,300円 523,000円 2023/05/26 発売 JANコード： <JAN>」の並び。

    価格のすぐ後に（税抜きの価格・発売日をはさんで）この商品の JAN が続くときだけ読む（おすすめのレンズなど別の商品の
    価格は拾わない）。在庫は在庫の欄（spec_stock_msg）が決まった語のときだけ記録する（空なら記録しない）。
    """
    t = _text(h)
    ms = list(re.finditer(r"ニコンダイレクト販売価格\s*([\d,]{4,})\s*円\s*(?:[\d,]{4,}\s*円\s*)?"
                          r"(?:\d{4}/\d{1,2}/\d{1,2}\s*発売\s*)?JANコード\s*[：:]\s*" + re.escape(jan) + r"(?!\d)", t))
    if len({m.group(1) for m in ms}) != 1:
        return {"model_found": jan in t, "price": None, "stock": "", "ended": False}
    m = re.search(r'<dd[^>]*id="spec_stock_msg"[^>]*>(.*?)</dd>', h, flags=re.S)
    msg = _text(m.group(1)).strip() if m else ""
    ended = "販売終了" in msg
    stock = msg if msg in ("在庫あり", "在庫なし", "在庫切れ", "入荷待ち", "品切れ") else ""
    return {"model_found": True, "price": int(ms[0].group(1).replace(",", "")), "stock": stock, "ended": ended}


def parse_apple_parts(h: str, skus: str) -> dict:
    """Apple の購入ページの商品データ: 部品番号（partNumber）ごとの価格（fullPrice）。

    組の部品番号がすべてページにあり、価格がすべて同じときだけ読む（容量・価格の違う番号が混ざれば読まない）。
    """
    prices = []
    for sku in [x for x in skus.split(",") if x]:
        ms = set(re.findall(r'"partNumber"\s*:\s*"' + re.escape(sku) + r'"\s*,\s*"price"\s*:\s*\{\s*"fullPrice"\s*:\s*'
                            r'([\d.]+)', h))
        if len(ms) != 1:
            return {"model_found": False, "price": None, "stock": "", "ended": False}
        prices.append(int(float(ms.pop())))
    if not prices or len(set(prices)) != 1:
        return {"model_found": bool(prices), "price": None, "stock": "", "ended": False}
    return {"model_found": True, "price": prices[0], "stock": "", "ended": False}


def parse_fuji_mall(h: str, match: str) -> dict:
    """フジフイルムモールの購入ページ: meta の keywords に色の JAN があり、「<型番> <価格>円（税込）」の並びが1種類。

    在庫は「カラーを選択」の欄の色ごとの表示が全色同じとき（全色 在庫なし / 全色 在庫あり）だけ記録する（色を区別
    しない商品なので、色によって違うときは記録しない）。
    """
    jan, _, model = match.partition("|")
    m = re.search(r'<meta[^>]+name="keywords"[^>]+content="([^"]*)"', h)
    if not (jan and model and m and jan in m.group(1).split(",")):
        return {"model_found": False, "price": None, "stock": "", "ended": False}
    t = _text(h)
    ps = {x.replace(",", "") for x in re.findall(re.escape(model) + r"\s+([\d,]{4,})\s*円\s*（税込）", t)}
    if len(ps) != 1:
        return {"model_found": True, "price": None, "stock": "", "ended": False}
    # 「カラーを選択」の欄が「<色> <在庫の表示>」の組だけで（2色以上）、区切りの「フジフイルムモール購入者」まで続くときだけ
    # 読む（区切りが無い・予約などほかの語がある・おすすめの商品まで読んでしまう形では記録しない。再監査の Medium）
    stock = ""
    # 「カラーを選択」が1回だけのページで、その位置から読む（別の商品の欄を読まない。再々監査 Low）
    sel = (re.match(r"カラーを選択\s+((?:[^\s]+\s+(?:在庫なし|在庫あり)\s+){2,})フジフイルムモール購入者",
                    t[t.find("カラーを選択"):]) if t.count("カラーを選択") == 1 else None)
    if sel:
        pairs = re.findall(r"([^\s]+)\s+(在庫なし|在庫あり)", sel.group(1))
        states = {st for _c, st in pairs}
        if len(pairs) >= 2 and len(states) == 1:
            stock = states.pop() + "（全色）"
    return {"model_found": True, "price": int(ps.pop()), "stock": stock, "ended": False}


PARSE = {"sony_store": parse_sony_store, "apple_jsonld": parse_apple_jsonld,
         "canon_store": parse_canon_store, "nikon_direct": parse_nikon_direct,
         "apple_parts": parse_apple_parts, "fuji_mall": parse_fuji_mall}


def classify(rec: dict, parsed: dict) -> str:
    if parsed.get("ended"):
        return "sale_ended"
    if not parsed.get("model_found") or not parsed.get("price"):
        return "failed"
    return "unchanged" if parsed["price"] == rec.get("price") else "changed"


def _targets() -> list[dict]:
    import yaml

    from src.market.official_registry import IDENTITY_EVIDENCE, VERIFIED_URLS
    products = {p["id"]: p for p in (yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))
                                    or {}).get("products", [])}
    out = []
    for pid in RECHECK_TARGETS:
        v = VERIFIED_URLS.get(pid)
        model = str((products.get(pid) or {}).get("model_number") or "")
        host = re.sub(r"^https?://([^/]+)/.*$", r"\1", (v or {}).get("url", ""))
        parser = PARSER_OVERRIDE.get(pid) or PARSERS.get(host)
        if not (v and parser):
            continue
        key = MATCH_KEYS.get(parser, "model_number")
        ev = IDENTITY_EVIDENCE.get(pid) or {}
        if key == "url_code":
            m = re.search(r"/g/g([0-9A-Za-z]+)/", v["url"])
            match = m.group(1) if m else ""
        elif key == "variant_skus":
            match = ",".join(sorted(ev.get("variant_skus") or {}))
        elif key == "evidence_jan":
            jans = list((ev.get("colors") or {}).values())
            match = f"{jans[0]}|{model}" if jans and model and v["url"].endswith(f"/g{_fuji_code(v['url'])}/") else ""
        else:
            match = str((products.get(pid) or {}).get(key) or "")
        if match:
            out.append({"product_id": pid, "url": v["url"], "model": model, "match": match, "parser": parser,
                        "price": v.get("price"), "price_checked_on": v.get("checked_on"),
                        "stock_checked_at": v.get("stock_checked_at") or ""})
    return out


def _fuji_code(url: str) -> str:
    m = re.search(r"/g/g(\d+)/$", url)
    return m.group(1) if m else "-"


def plan(now: datetime) -> dict:
    """再確認の対象と期限（価格と在庫を分ける）。ネットワークに出ない。"""
    from src.market import price_evidence as pe
    from src.market.official_registry import VERIFIED_URLS
    rows = []
    for pid, v in VERIFIED_URLS.items():
        if not v.get("price"):
            continue
        pc = datetime.fromisoformat(v.get("checked_on")).replace(tzinfo=JST)
        sc = v.get("stock_checked_at") or ""
        rows.append({"product_id": pid, "price_checked_on": v.get("checked_on"),
                     "price_due": (pc + timedelta(days=pe.CURRENT_DAYS)).date().isoformat(),
                     "stock_checked_at": sc,
                     "stock_due": (datetime.fromisoformat(sc) + timedelta(days=pe.CURRENT_DAYS)).isoformat()
                     if sc else "",
                     "auto_recheck": pid in RECHECK_TARGETS})
    return {"generated_at": now.isoformat(timespec="seconds"), "items": rows,
            "note": "価格・在庫の期限は price_evidence.CURRENT_DAYS（7日）。auto_recheck が true の商品だけ自動で再確認する"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib の約束どおり
        return None                       # たどらない（HTTPError として受け取る）


def _fetch(url: str) -> tuple[str | None, str]:
    from src.collectors import polite
    if not polite.robots_allowed(url):
        return None, polite.robots_block_reason(url)
    polite.polite_wait(url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": polite.HONEST_UA,
                                                   "Accept-Language": "ja,en;q=0.8"})
        # リダイレクトをたどらない（移動先へ robots.txt・間隔の確認なしにリクエストを送らない。販売終了で別の
        # ページへ移ったことがある。Phase 15 監査 L-3・N-2）。3xx は moved として読まない
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(req, timeout=20) as r:
            body = r.read()
            # 文字コードはレスポンスの宣言かページの meta の charset（キヤノンは Shift_JIS）。無ければ UTF-8
            cs = r.headers.get_content_charset() if hasattr(r, "headers") else None
            if not cs:
                m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', body[:4096])
                cs = m.group(1).decode("ascii") if m else "utf-8"
            # Shift_JIS と宣言したページは Windows の拡張文字を含むことがあるので cp932 で読む（レビュー L-3）
            if cs.lower().replace("_", "-") in ("shift-jis", "sjis", "x-sjis", "ms-kanji", "windows-31j"):
                cs = "cp932"
            try:
                return body.decode(cs, "ignore"), ""
            except LookupError:
                return body.decode("utf-8", "ignore"), ""
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            return None, "moved"
        return None, "site_blocked" if e.code in (401, 403) else polite.status_reason(e.code)
    except Exception as e:  # noqa: BLE001
        return None, "timeout" if "timeout" in type(e).__name__.lower() else "connection_error"


def _host_interval(url: str) -> float:
    """その取得元の間隔（config/sources.yaml の rate_limit_sec・Crawl-delay・60秒の大きいほう）。"""
    from src.collectors import polite
    try:
        sid = polite.source_id_for_url(url)
        # sources.yaml の取得元に対応しないホスト（nij.nikon.com・mall-jp.fujifilm.com）は、公式ストアの取得元と同じ
        # 120秒にする（最低の60秒に落とさない。Phase 16 監査 L-6）
        return float(max((polite.source_rate_limit_sec(sid) or 0) if sid else UNMAPPED_INTERVAL_SEC,
                         polite.robots_checker().get_crawl_delay(url) or 0, polite.MIN_INTERVAL_SEC))
    except Exception:  # noqa: BLE001
        return 120.0


def recheck(now: datetime, fetch=_fetch, sleep=None, wait_first: bool | None = None) -> list[dict]:
    """wait_first: 取得元ごとの最初の取得の前に間隔の分を待つか（既定は実際の取得のときだけ）。sleep は待ちの関数。"""
    import time as _time

    from src.collectors.polite import CUTOFF_IMMEDIATE
    results = []
    started, seen_hosts = _time.monotonic(), set()
    for t in _targets():
        host = re.sub(r"^https?://([^/]+)/.*$", r"\1", t["url"])
        if (fetch is _fetch if wait_first is None else wait_first) and host not in seen_hosts:
            # 直前の CI のステップ（公式の価格の取得）が同じ取得元を取ったばかりかもしれない。間隔の記録は
            # プロセスをまたがないので、この実行での最初の取得の前に、その取得元の間隔の分だけ待つ（Phase 15 L-1）
            wait = _host_interval(t["url"]) - (_time.monotonic() - started)
            if wait > 0:
                (sleep or _time.sleep)(wait)
        seen_hosts.add(host)
        h, why = fetch(t["url"])
        # 取得した時刻（実行の開始時刻ではない）。テストで now を渡したときは now
        at = datetime.now(tz=JST) if fetch is _fetch else now
        base = {"product_id": t["product_id"], "url": t["url"], "model": t["model"], "match": t["match"],
                "recorded_price": t["price"], "observed_at": at.isoformat(timespec="seconds")}
        if h is None:
            results.append({**base, "status": "blocked" if why in CUTOFF_IMMEDIATE else "failed", "reason": why,
                            "price": None, "stock": ""})
            continue
        parsed = PARSE[t["parser"]](h, t["match"])
        st = classify(t, parsed)
        results.append({**base, "status": st, "reason": "", "price": parsed.get("price"),
                        "stock": parsed.get("stock") if st in ("unchanged", "changed") else ""})
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true", help="期限と対象の一覧だけを出す（ネットワークに出ない）")
    args = ap.parse_args(argv)
    now = datetime.now(tz=JST)
    if args.plan:
        print(json.dumps(plan(now), ensure_ascii=False, indent=2))
        return 0
    results = recheck(now)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps({"generated_at": now.isoformat(timespec="seconds"),
                                                 "results": results, "plan": plan(now)["items"]},
                                                ensure_ascii=False, indent=2), encoding="utf-8")
    hist_path = OUT / "history.json"
    try:
        hist = json.loads(hist_path.read_text(encoding="utf-8")).get("results") or []
    except (OSError, ValueError):
        hist = []
    hist = (hist + results)[-HISTORY_LIMIT:]
    hist_path.write_text(json.dumps({"note": "公式の再確認の結果の履歴（直近のみ）", "results": hist},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
    for r in results:
        print(f"[公式の再確認] {r['product_id']}: {r['status']} 価格 {r.get('price')} 在庫 {r.get('stock') or '—'}"
              + (f"（{r['reason']}）" if r.get("reason") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
