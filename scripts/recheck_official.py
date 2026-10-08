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
# （静的な HTML に価格・在庫が無い）ので、ここには入れない
PARSERS = {"pur.store.sony.jp": "sony_store", "www.apple.com": "apple_jsonld"}
# 再確認する商品（すでに確認済みで、型番が登録され、上の読み取りで確かめられるもの）。少数から始める
RECHECK_TARGETS = ("prod_ps5_pro", "prod_airpods_pro3")



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


def classify(rec: dict, parsed: dict) -> str:
    if parsed.get("ended"):
        return "sale_ended"
    if not parsed.get("model_found") or not parsed.get("price"):
        return "failed"
    return "unchanged" if parsed["price"] == rec.get("price") else "changed"


def _targets() -> list[dict]:
    import yaml

    from src.market.official_registry import VERIFIED_URLS
    products = {p["id"]: p for p in (yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))
                                    or {}).get("products", [])}
    out = []
    for pid in RECHECK_TARGETS:
        v = VERIFIED_URLS.get(pid)
        model = str((products.get(pid) or {}).get("model_number") or "")
        host = re.sub(r"^https?://([^/]+)/.*$", r"\1", (v or {}).get("url", ""))
        if v and model and host in PARSERS:
            out.append({"product_id": pid, "url": v["url"], "model": model, "parser": PARSERS[host],
                        "price": v.get("price"), "price_checked_on": v.get("checked_on"),
                        "stock_checked_at": v.get("stock_checked_at") or ""})
    return out


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
            return r.read().decode("utf-8", "ignore"), ""
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
        return float(max((polite.source_rate_limit_sec(sid) or 0) if sid else 0,
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
        base = {"product_id": t["product_id"], "url": t["url"], "model": t["model"],
                "recorded_price": t["price"], "observed_at": at.isoformat(timespec="seconds")}
        if h is None:
            results.append({**base, "status": "blocked" if why in CUTOFF_IMMEDIATE else "failed", "reason": why,
                            "price": None, "stock": ""})
            continue
        parsed = parse_sony_store(h, t["model"]) if t["parser"] == "sony_store" else parse_apple_jsonld(h, t["model"])
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
