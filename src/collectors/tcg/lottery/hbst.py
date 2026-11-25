# -*- coding: utf-8 -*-
"""HobbyStationLotteryAdapter — ホビーステーション（hbst.net）のお知らせから、ポケカ・ONE PIECE の抽選販売の告知を取得する。

Market Research Coverage Wave 2。公式のお知らせ（WordPress）に、抽選販売の告知が静的 HTML のテキストで載り、
応募期間・当選発表・当選者購入期間が「■応募期間：…」の固定の書式で本文にある
（robots.txt は /wordpress/wp-admin/ だけを禁止していて、対象ページは禁止していない（確認日 2026-10-28）。
利用規約の本文は未読で、許可も禁止も未確認。自動取得は既存の polite 経由の取得 HTML の解析のみで、取得を増やしていない）。

- 一覧: /result/?category=news（1ページ目。カード = 件名の先頭 30 文字ほど + 詳細の URL ?p=<ID>）
- 詳細: /?p=<ID>。件名は <title>、公開日は time.time-date、本文は <section id="article"> の中（数値文字参照で書かれることがある → unescape）
- 応募は Livepocket（外部のサービス）。公式ドメインではないので entry_url は作らない（応募先の URL は記録しない）
- 店舗横断の1本の告知（対象店舗から1店舗だけ応募）。店舗ごとの抽選ではない（store_specific にしない）
- 日程は本文のテキストだけ。年が不自然な日付（誤記）は共通の解析器が捨てる（日程の日付を作らない）。価格は定価にしない
  （「販売価格：各7,200円」が1個の定価か組の合計か本文だけでは分からないため）
- 取得は LotteryAdapter（polite 経由）。遮断（401/403/429・robots 禁止）されたら、その実行ではこれ以上取得しない

販売価格（既存の取得 HTML から同時に読む。取得は増やさない）:
- 本文の「販売価格：<商品名><金額>円 <商品名><金額>円」から、商品名と金額が隣り合うものだけを商品別に読む（parse_prices）。
  「各7,200円」のように商品との対応が曖昧なものは価格にしない。件名が「二種」のように複数商品を指すときは件名から商品名を作らない
- 単位が BOX と確定できるのは、(a) 価格が 1 つだけで、価格（円）の直後に価格単位の BOX 表記（空白・括弧・スラッシュ・「あたり」「につき」程度を挟む BOX／ボックス／1BOX）がある、
  (b) 商品名の直後に BOX 表記がある、のどちらかだけ。「各N BOX」「N BOXまで」等の購入数の制限は単位の根拠にしない。
  「6,000円 ※BOX特典なし」「6,000円 ボックス購入者のみ」「6,000円 BOXの中身」のように、他の語に続く BOX は単位ではない。
  入数（30 パック）から単位を逆算しない・パック価格×入数で BOX 価格を作らない。確定できなければ UNKNOWN（利益に使わない）

規約確認の状況・BLOCKED 理由（2026-11-25）:
- ホビーステーション: robots.txt は対象ページを禁止していない（確認日 2026-10-28）。利用規約の本文は未読で、許可も禁止も未確認。
  自動取得は既存の polite 経由の取得 HTML の解析のみで、取得を増やしていない。
  「要規約確認」の扱いを機械的に強制する仕組みはまだ無い（規約本文を読んだら、この記述と取得可否を見直す）
- 三洋堂: 規約本文が未読のため、この変更では collector を作らない（手動台帳 config/tcg_retailer_box_prices.yaml のまま）。BLOCKED 理由 = 規約未確認
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter, product_code_of
from .clabo import MIN_BOX_PRICE_JPY          # BOX 価格の下限（clabo と共有。1,000 円未満はパック単価・誤読の疑いで採用しない）

BASE_URL = "https://www.hbst.net"
LISTING_URL = BASE_URL + "/result/?category=news"
_CARD_SPLIT = re.compile(r'(?=<div class="blogb[ "])')
_CARD_TITLE = re.compile(r'<p class="text-left">\s*(.*?)\s*</p>', re.S)
_CARD_LINK = re.compile(r'href="(https://www\.hbst\.net/\?p=(\d+))"')
_CARD_DATE = re.compile(r"【(\d{4})\.(\d{1,2})\.(\d{1,2})】")
_TITLE_TAG = re.compile(r"<title>(.*?)</title>", re.S)
_ARTICLE = re.compile(r'<section id="article".*?</section>', re.S)
_PRODUCT_IN_TITLE = re.compile(r"[「『](.+?)[」』]")
_NAME_BAD = re.compile(r"[※。]|[：:]\s|お一人様|抽選|応募|当選|注意|期間|発売日")
_MULTI = re.compile(r"[二三四五六七八九十\d]+\s*種")                      # 「拡張パック二種」= 複数商品の告知（1 つの商品名ではない）
_PRICE_BLOCK = re.compile(r"販売価格\s*[：:](.{0,240}?)(?=■|応募方法|応募期間|$)")
_PRICE_PAIR = re.compile(r"([^\d円■：:]{2,40}?)\s*(\d{1,3}(?:,\d{3})+|\d{4,6})\s*円")
_UNIT_WORDS = frozenset({"BOX", "ボックス", "パック", "PACK", "セット", "SET", "枚", "個", "入り", "種"})      # 数字で名前が切れたときの残りかす（商品名ではない）
_NAME_BOX_TAIL = re.compile(r"\s*[(（\[【]?\s*(?:1\s*)?(?:BOX|ボックス)\s*[)）\]】]?\s*$", re.I)
_N_BOX_BEFORE_PRICE = re.compile(r"(?<![\d,])1\s*((?:BOX|ボックス)(?=\s*\d))", re.I)
_MULTI_BOX_PRICE = re.compile(r"(?<![\d,])[2-9]\d*\s*(?:BOX|ボックス)\s*\d", re.I)      # 「2BOX 14,400円」のような複数個の価格（1BOX の価格と混ぜない）
# 価格単位としての BOX は、円の直後（空白・括弧・スラッシュ・「あたり」「につき」程度だけを挟む）の BOX／ボックス／1BOX／1ボックス で、
# かつ BOX の直後が許可リスト（行末・空白だけの後の行末・閉じ括弧・句読点・スラッシュ・「・」・次のブロック記号 ■▼◆●※・「あたり」「当たり」「につき」・
# 区切りのある「で」「です」「となります」）のときだけ（許可リスト方式。「BOX特典」「BOXセット」「BOX在庫」「BOXs」「BOX1個まで」のように日本語・英数字が続くものは単位にしない）。
# 円と BOX の間に「※」等の他の語が入るものも単位にしない。本文は NFKC 正規化・空白の圧縮後に渡される（改行は空白）
_PRICE_UNIT_AFTER = re.compile(
    r"^[\s(（\[【/／]*(?:あたり|当たり|につき)?[\s(（\[【/／]*(?:1\s*)?(?:BOX|ボックス)"
    r"(?=\s*(?:$|[)）\]】、。，．,./／・■▼◆●※]|あたり|当たり|につき|(?:で|です|となります)(?:\s|$|[)）\]】、。，．,./／・■▼◆●※])))", re.I)


def _tcg_of(text: str):
    if re.search(r"ポケモンカード|ポケカ", text):
        return "POKEMON"
    if re.search(r"ONE ?PIECE|ワンピース", text, re.I):
        return "ONE_PIECE"
    return None


def parse_listing(html: str) -> list[dict]:
    """一覧のカード（件名の先頭・詳細の URL・公開日）。件名の無いカード・詳細の URL の無いカードは読まない。"""
    out = []
    for block in _CARD_SPLIT.split(html or ""):
        t = _CARD_TITLE.search(block)
        lk = _CARD_LINK.search(block)
        if not t or not lk:
            continue
        title = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", t.group(1)))).strip()
        d = _CARD_DATE.search(title)
        published = None
        if d:
            try:
                published = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)), tzinfo=JST).isoformat()
            except ValueError:
                published = None
        out.append({"url": lk.group(1), "post_id": lk.group(2), "title": title, "published_at": published})
    return out


def parse_detail(html: str) -> dict:
    """詳細ページ: 完全な件名（<title> から店名の接尾辞を除く）・本文のテキスト（数値文字参照を戻したもの）。"""
    m = _TITLE_TAG.search(html or "")
    title = re.sub(r"\s*-\s*ホビーステーション\s*$", "", unescape(m.group(1)).strip()) if m else ""
    a = _ARTICLE.search(html or "")
    # <article> に当たる本文の領域が無いページは、ページ全体（サイドバー・他の記事）の日程を読まない
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(a.group(0)))).strip() if a else ""
    return {"title": title, "body": body}


def subject_product(title: str) -> str:
    """件名の「…」の中の商品名（複数商品の「二種」も含めた従来の読み方）。未紐付けイベントの名前に使う。読めなければ空。"""
    m = _PRODUCT_IN_TITLE.search(title or "")
    n = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return n if 4 <= len(n) <= 80 and not _NAME_BAD.search(n) else ""


def product_of(title: str) -> str:
    """件名の「…」の中の商品名。商品名として読めない（説明文・日付が混ざる・長すぎる）ときは空。"""
    m = _PRODUCT_IN_TITLE.search(title or "")
    n = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    if _MULTI.search(n):
        return ""                      # 「二種」など複数商品の件名は、商品名として使わない（本文の商品別の価格から読む）
    return n if 4 <= len(n) <= 80 and not _NAME_BAD.search(n) else ""


_KIND_QUOTED = re.compile(r"(強化拡張パック|拡張パック|ハイクラスパック|ブースターパック|エクストラブースター|プレミアムブースター)\s*((?:[「『][^」』]{2,60}[」』]\s*)+)")


def _with_kind(name: str, text: str) -> str:
    """本文に「拡張パック「A」「B」」と種別つきで並んでいて、name が A/B のどれかなら「拡張パック「name」」にする（本文に書かれた種別だけ。推測しない）。"""
    for m in _KIND_QUOTED.finditer(text):
        if name in re.findall(r"[「『]([^」』]+)[」』]", m.group(2)):
            return f"{m.group(1)}「{name}」"
    return name


def parse_prices(body: str, registry: list | None = None) -> list[dict]:
    """本文の「販売価格：名前 金額円 名前 金額円」から、商品別の販売価格を読む（商品名と金額が隣り合うものだけ）。

    - 単位が BOX と確定できるのは、価格が 1 つで価格の直後に BOX 表記があるか、商品名の直後に BOX 表記があるときだけ（購入数の制限は根拠にしない）。確定できなければ UNKNOWN（価格は持つが利益に使わない）
    - 「各7,200円」のように商品名が無いもの・名前に「各」を含むものは読まない（商品と価格の対応が曖昧）
    - 名前が単位語（BOX・パック等）・数字だけのものは無効（数字で名前が切れた残り）。有効な価格が 1 つも無ければ空を返す（呼び出し側が件名由来にフォールバックする）
    - registry を渡すと（collect は必ず渡す）、商品として照合できる（none でない）名前だけを返す。渡さないときは名前と金額の隣接だけで返し、
      商品の同一性（exact か）は後段の resolve_product が決める（exact でない価格は台帳側で採用しない）
    """
    import unicodedata
    text = unicodedata.normalize("NFKC", re.sub(r"\s+", " ", body or ""))
    out, seen = [], set()
    for blk in _PRICE_BLOCK.finditer(text):
        blk_text = re.sub(r"[(（]\s*税[込抜]\s*[)）]", " ", blk.group(1))
        if not _MULTI_BOX_PRICE.search(blk_text):
            blk_text = _N_BOX_BEFORE_PRICE.sub(r"\1", blk_text)          # 「商品名 1BOX 6,000円」の「1」を落とし、商品名の直後の BOX 表記として読む
        pairs = list(_PRICE_PAIR.finditer(blk_text))
        for pm in pairs:
            name = re.sub(r"\s+", " ", pm.group(1)).strip(" 　・、,/")
            raw_name = name
            # 商品名の直後の BOX 表記（「商品名（BOX）6,000円」「商品名 BOX 6,000円」）は価格の単位。名前からは取り除く
            name_box = bool(_NAME_BOX_TAIL.search(name))
            name = _NAME_BOX_TAIL.sub("", name).strip(" 　・、,/")
            if len(name) < 2 or "各" in name or name in seen or _NAME_BAD.search(name):
                continue
            if name.upper() in _UNIT_WORDS or re.fullmatch(r"[\d\s,./BOXboxパック]+", name):
                continue                 # 「1BOX 7,200円」「30パック 7,200円」で数字の手前で切れた「BOX」「パック」は商品名ではない
            # BOX と確定できるのは、(a) 価格が 1 つだけで、その価格の直後に価格単位の BOX 表記がある、(b) 商品名の直後に BOX 表記がある、のどちらかだけ。
            # 「各N BOX」「N BOXまで」「お一人様」「当選者は」は購入数の制限で、価格の単位ではない（根拠にしない。確定できなければ UNKNOWN）
            after_price = len(pairs) == 1 and bool(_PRICE_UNIT_AFTER.search(blk_text[pm.end():]))
            unit = "BOX" if name_box or after_price else "UNKNOWN"
            price = int(pm.group(2).replace(",", ""))
            if unit == "BOX" and price < MIN_BOX_PRICE_JPY:
                continue                 # BOX として 1,000 円未満はパック単価・桁落ちの疑い。採用しない
            name = _with_kind(name, text)
            if registry is not None:
                from src.tcg.lottery.products import resolve_product
                if resolve_product(name, registry).get("product_match") in (None, "none"):
                    continue
            seen.add(name)
            out.append({"product_name": name, "retail_price": price, "price_unit": unit,
                        "product_code": product_code_of(name), "price_text": f"{raw_name}{pm.group(2)}円"})
    return out


def build_targets(title: str, body: str, registry: list) -> list[dict] | None:
    """対象商品。registry で商品と照合できた価格つきの行（紐付けを推測しない）＋、照合できなかった商品がある告知は
    件名由来の未紐付けイベント（価格なし。従来どおり）。新商品・新イベントの発見を落とさないため、両方を返す。"""
    priced = parse_prices(body, registry)
    all_named = parse_prices(body)                       # registry なし = 名前と金額が隣り合うもの全部
    dropped = len(all_named) > len(priced)
    out = list(priced)
    if not priced or dropped:
        subject = subject_product(title)
        if subject:
            out.append({"product_name": subject, "retail_price": None})
    return out or None


def _registry() -> list:
    """商品 registry（exports/tcg/pokemon_registry.json）。読めなければ空（価格つきの商品名を作らず、件名由来の商品名にフォールバックする）。"""
    import json
    from pathlib import Path
    try:
        path = Path(__file__).resolve().parents[4] / "exports" / "tcg" / "pokemon_registry.json"
        prods = json.loads(path.read_text(encoding="utf-8")).get("products")
        return [p for p in prods if isinstance(p, dict)] if isinstance(prods, list) else []
    except Exception:  # noqa: BLE001
        return []


class HobbyStationLotteryAdapter(LotteryAdapter):
    source_id = "HOBBY_STATION"
    retailer = "HOBBY_STATION"
    retailer_name = "ホビーステーション"
    source_name = "ホビーステーション（公式お知らせの抽選販売）"
    tcg = "POKEMON"
    channel = "STORE"
    max_detail_fetch = 10
    lottery_source_type = "STORE_OFFICIAL"

    def _stop_if_blocked(self) -> bool:
        if self.health.get("blocked"):
            self.funnel.notes.append("アクセス制限（401/403/429）を受けたので、この実行ではこれ以上取得しない")
            return True
        return False

    def collect(self) -> list[dict]:
        from src.tcg.models import now_jst
        self.health["last_checked"] = now_jst().isoformat()
        self.funnel.requires_news_pages = True
        html = self.fetch_listing(LISTING_URL)
        cands: list[dict] = []
        if html:
            self.health["last_success"] = now_jst().isoformat()
            cards = parse_listing(html)
            if not cards:
                # 取得はできたが、記事のカードを1件も読めない（HTML の構造の変更の可能性）。静かに「0件」にしない
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append("一覧は取得できたが記事のカードを読めなかった（HTML の構造の変更の可能性）")
            for c in cards:
                self.funnel.news_pages_discovered += 1
                if not re.search(r"抽選|予約", c["title"]) or not _tcg_of(c["title"]):
                    self.funnel.reject(REJECT_NOT_CANDIDATE)          # 抽選・予約でない告知（休業・イベント等）やカード以外
                    continue
                cands.append(c)
        self.funnel.product_links_discovered = len(cands)
        # 応募が終わった告知（件名に「応募は終了」）は後ろへ。残りは公開日の新しい順
        cands.sort(key=lambda c: ("応募は終了" not in c["title"], str(c.get("published_at") or "")[:10], c["post_id"]), reverse=True)
        n_open = sum(1 for c in cands if "応募は終了" not in c["title"])
        fetched = 0
        for c in cands[:self.max_detail_fetch]:
            if self._stop_if_blocked():
                break
            fetched += 1
            page = self.fetch_detail(c["url"], referer=LISTING_URL)
            if not page:
                continue
            d = parse_detail(page)
            if not d["body"]:
                self.funnel.structure_changed_pages += 1         # 詳細に本文の領域が無い（HTML の構造の変更の疑い）。日程は読まない
                self.health["error_messages"].append("詳細ページに本文の領域（article）が無かった（HTML の構造の変更の可能性）")
            title = d["title"] or c["title"]
            # 同じ本文から価格も読む（取得は増やさない）。registry で商品と照合できた価格だけを価格つきの対象にし、
            # 照合できない商品・価格が読めない告知は件名由来の未紐付けイベント（価格なし）で残す
            targets = build_targets(title, d["body"], _registry())
            self.lottery_events.extend(self.build_from_article(
                title=title, body=d["body"], url=c["url"], published_at=c["published_at"],
                entry_url=None, result_url=None, tcg_hint=_tcg_of(title), targets=targets))
        skipped_open = max(0, n_open - self.max_detail_fetch)
        self.health.update({"detail_candidates": len(cands), "detail_fetched": fetched, "skipped_due_to_limit": skipped_open,
                            "skipped_ended": max(0, (len(cands) - n_open) - max(0, self.max_detail_fetch - n_open))})
        if skipped_open > 0:
            self.health["truncated"] = True
            self.funnel.notes.append(f"詳細は {fetched}/{len(cands)} 件のみ取得。応募中らしい告知 {skipped_open} 件を上限のため読めていない")
        return self.finish()
