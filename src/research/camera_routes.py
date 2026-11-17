# -*- coding: utf-8 -*-
"""カメラの利益ルート A〜D の計算（純粋な関数。ファイルにも通信にも触らない）。

    ROUTE A  正規店 / メーカー → 買取店       買取 − 仕入 − 購入送料 − 買取店への発送など − その他
    ROUTE B  正規店 / メーカー → 二次流通     SOLD_MEDIAN − 仕入 − 購入送料 − 販売手数料 − 発送 − その他
    ROUTE C  二次流通の最安 → 買取店          買取 − LISTING_LOW − 購入送料 − 買取店への発送など − その他
    ROUTE D  二次流通の最安 → 二次流通の成約  SOLD_MEDIAN − LISTING_LOW − 購入送料 − 販売手数料 − 発送 − その他

価格の種別は混ぜない（OFFICIAL_RETAIL / RETAIL_PRICE / BUYBACK_PRICE / LISTING_LOW / LISTING_HIGH /
SOLD_LOW / SOLD_HIGH / SOLD_MEDIAN）。売値に使ってよいのは BUYBACK_PRICE と、条件を満たした SOLD_MEDIAN だけ
（LISTING_HIGH・LISTING_LOW・単発の SOLD は売値にしない）。
成約の中央値は price_types.sold_median（既存の正本。件数 3 以上・期間・個別の根拠）を使う。足りなければ
期待売値 UNAVAILABLE・利益 NOT_CALCULATED。手数料は市場ごとに config/camera_routes.yaml から取り、未確認なら
NOT_CALCULATED（0 円にしない）。購入送料が分からないときも NOT_CALCULATED（0 円にしない）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.market import price_types as pt

JST = timezone(timedelta(hours=9))

# 価格の種別
OFFICIAL_RETAIL, RETAIL_PRICE, BUYBACK_PRICE = "OFFICIAL_RETAIL", "RETAIL_PRICE", "BUYBACK_PRICE"
LISTING_LOW, LISTING_HIGH = "LISTING_LOW", "LISTING_HIGH"
SOLD_LOW, SOLD_HIGH, SOLD_MEDIAN = "SOLD_LOW", "SOLD_HIGH", "SOLD_MEDIAN"
SELL_TYPES = frozenset({BUYBACK_PRICE, SOLD_MEDIAN})          # 売値に使ってよい種別

# 状態（condition）
NEW, UNOPENED, LIKE_NEW, USED, UNKNOWN = "NEW", "UNOPENED", "LIKE_NEW", "USED", "UNKNOWN"
_FAMILY = {NEW: "NEW", UNOPENED: "NEW", LIKE_NEW: "LIKE_NEW", USED: "USED"}   # UNKNOWN は互換にしない

# 在庫
AVAILABLE, OUT_OF_STOCK, LOTTERY_DEPENDENT, RESERVATION, STOCK_UNKNOWN = (
    "AVAILABLE", "OUT_OF_STOCK", "LOTTERY_DEPENDENT", "RESERVATION", "UNKNOWN")

# 鮮度
FRESH, STALE, UNKNOWN_FRESHNESS = "FRESH", "STALE", "UNKNOWN_FRESHNESS"

# 利益の状態・判定
PROFITABLE, NO_PROFIT, NOT_CALCULATED = "PROFITABLE", "NO_PROFIT", "NOT_CALCULATED"
BUY, WATCH, WAIT, SKIP = "BUY", "WATCH", "WAIT", "SKIP"

ROUTE_LABEL = {"A": "正規店・メーカー → 買取店", "B": "正規店・メーカー → 二次流通（成約中央値）",
               "C": "二次流通の最安 → 買取店", "D": "二次流通の最安 → 二次流通（成約中央値）"}

# 市場名 → 手数料の設定キー（config/camera_routes.yaml の fees）
_MARKET_KEYS = (("yahooフリマ", "yahoo_flea"), ("paypayフリマ", "yahoo_flea"), ("yahoo!フリマ", "yahoo_flea"),
                ("ヤフオク", "yahoo_auction"), ("yahoo!オークション", "yahoo_auction"), ("yahooオークション", "yahoo_auction"),
                ("メルカリ", "mercari"), ("mercari", "mercari"), ("ラクマ", "rakuma"), ("rakuma", "rakuma"), ("ebay", "ebay"))


def market_from_url(url) -> Optional[str]:
    h = host_of(url)
    u = str(url or "")
    if h.endswith("mercari.com"):
        return None if "/shops/product/" in u else "mercari"          # メルカリ Shops は料率が別（確認していない）
    if h.endswith("auctions.yahoo.co.jp"):
        return "yahoo_auction"
    if h == "item.fril.jp" or h.endswith("fril.jp"):
        return "rakuma"
    if h.endswith("ebay.com"):
        return "ebay"
    return None


def market_key(name) -> Optional[str]:
    t = re.sub(r"\s", "", str(name or "")).lower()
    if "shops" in t or "ショップ" in t:
        return None                      # メルカリ Shops などは料率が別。確認していないので手数料未確認として扱う
    for w, k in _MARKET_KEYS:
        if w in t:
            return k
    return None


# ---------------------------------------------------------------- 同一性（機種・版）
_VARIANTS = (("hdf", r"HDF|HIGHLIGHTDIFFUSION|ハイライトディフュージョン"), ("mono", r"MONOCHROME?|モノクロ"),
             ("limited", r"LIMITED|限定|ANNIVERSARY|記念|周年|30TH|アニバーサリー|EDITION|エディション|GOLD|ゴールド|SPECIAL|特別"),
             ("kit", r"キット|KIT|ズーム|ZOOM|レンズ付"), ("v2025", r"2025版|2025年版|\(2025\)|（2025）|2025モデル"), ("overseas", r"海外|並行|グレー|輸入|US版|USA版|GLOBAL|香港|台湾|韓国|中国|アジア|ASIA|EU版|北米|欧州"), ("bilingual", r"日英|二言語|BILINGUAL"))
_COLORS = (("silver", r"シルバー?|SILVER|銀"), ("black", r"ブラック?|BLACK|黒"), ("white", r"ホワイト?|WHITE|白"))
# 状態・品質に難がある出品（仕入れにも売値の根拠にも使わない）
_USED_WORDS = re.compile(r"(?i)中古|USED|ユーズド|リユース|新品同様|ほぼ新品|新古品|美品|良品|並品|極上|開封品|展示|[A-DS]ランク|ランク[A-DS]|B級|アウトレット|再生品|整備済|リファービッシュ|REFURB")
_NEWISH = frozenset({"NEW", "UNOPENED"})
_JUNK = re.compile(r"(?i)[+＋]|同梱|付属(?!品?(?:完備|あり|全て|すべて|フル))|セット|グリップ|保護フィルム|フィルム貼|フィルム付|液晶フィルム|バッテリー|ケース|FTZ|ストラップ|アダプター|レンズのみ|フード|"
                   r"ジャンク|JUNK|部品|故障|訳|難(?:あり|アリ)|動作未確認|動作不良|現状|不動|破損|不良|不具合|カビ|傷(?!なし|無し)|キズ|割れ|欠品|欠け|"
                   r"要修理|修理|展示|開封済|使用感|汚れ|剥がれ|空箱|箱のみ|取扱説明書のみ|レンズ不良|ガタ|サビ|錆")
# 機種名の中核の直後に続くと別の機種になる語（Z8 II・GR III x・Zf Gold・M11 Monochrom など）
_CONT = re.compile(r"^(?:I{1,3}|IV|V|VI{1,3}|IX|X|XI{1,2}|[0-9]+|[A-Z]|GOLD|MONOCHROM|PRO|PLUS|SE|LITE|MINI|(?:MARK|MK)[0-9]*|マーク[0-9]*)$")
# 集約サイト・店名が分からない出所（個別の価格を採用も公開もしない）
_AGG = re.compile(r"集約|店名不明|店名非公開|みんなのカメラ|査定サイト|相場サイト|uridoki|価格\.com|kakaku")
_STRIP0 = None
_STRIP = re.compile(r"[\s　\-‐ー_・/]+")


import unicodedata


def _nfkc(text) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _norm(text) -> str:
    return _STRIP.sub("", _nfkc(text)).upper().replace("Α", "A").replace("α", "A").replace("Α", "A")


def variant_flags(text) -> frozenset:
    text = re.sub(r"数量限定|台数限定|期間限定|店舗限定|限定特価|数量限定特価", " ", _nfkc(text))        # 販促の「限定」は特別版ではない
    t1, t2 = _norm(text), _up(text)                  # 記号（ー・空白）を除いた形と、除かない形の両方で調べる
    return frozenset(k for k, rx in _VARIANTS if re.search(rx, t1) or re.search(rx, t2))


def color_of(text) -> Optional[str]:
    t1, t2 = _norm(text), _up(text)                     # 長音「ー」を残した形（シルバー）でも判定する
    hits = [k for k, rx in _COLORS if re.search(rx, t1) or re.search(rx, t2)]
    return hits[0] if len(hits) == 1 else None


_MAKERS = ("RICOH", "FUJIFILM", "SONY", "CANON", "NIKON", "EOS", "ILCE", "リコー", "富士フイルム", "ソニー", "キヤノン", "ニコン")


def _up(text) -> str:
    """大文字化・α→A。空白は 1 つに詰めて残す（境界の判定に使う）。"""
    return re.sub(r"\s+", " ", _nfkc(text).upper().replace("Α", "A").replace("α", "A")).strip()


def _core_pattern(product: str):
    """機種名から、メーカー名・版・ボディーの語を除いた中核を、区切りの揺れを許す正規表現にする。
    例: 'RICOH GR IV HDF' → 'GR[\\s\\-_・]*IV'、'Nikon Z8' → 'Z8'。中核の前後は英数字でないこと（GR IV は GR IIIx にも GR IVx にも一致しない）。"""
    s = _up(product)
    for w in _MAKERS:
        s = s.replace(_up(w), " ")
    for _, rx in _VARIANTS:
        s = re.sub(rx, " ", s)
    s = re.sub(r"BODY|ボディー|ボディ", " ", s)
    tokens = s.split()
    if not tokens:
        return None
    sep = r"[\s\-_・]*"          # 「Z8」と「Z 8」、「Z f」と「Zf」を同じ機種として読む（1 文字ごとに区切りの揺れを許す）
    return re.compile(r"(?<![A-Z0-9])" + sep.join(sep.join(re.escape(c) for c in t) for t in tokens) + r"(?![A-Z0-9])")


def name_key(name) -> str:
    """機種名の照合キー（ボディー表記・空白・記号の揺れを除く）。登録名との突き合わせ・重複のまとめに使う。"""
    t = re.sub(r"BODY|ボディー|ボディ", "", _up(name))
    return re.sub(r"[\s\-_・（）()]+", "", t)


def identity_ok(product: str, item_title, *, allow_junk: bool = False) -> tuple[bool, str]:
    """店のページの商品名が、この機種（版を含む）と同じか。機種の中核が境界つきで含まれ、版の旗が食い違わないこと。"""
    title = str(item_title or "").strip()
    if not title:
        return False, "item_title_missing"
    pat = _core_pattern(product)
    if pat is None:
        return False, "core_missing"
    up = _up(title)
    m = pat.search(up)
    if not m:
        return False, "model_not_in_title"
    nxt = re.match(r"[\s\-_]*([A-Z0-9ァ-ヶー]+)", up[m.end():])
    if nxt and _CONT.match(nxt.group(1)) and not re.match(r"^ILCE|^EOS|^DSC", nxt.group(1)):
        return False, "model_continues"
    if not allow_junk and _JUNK.search(_nfkc(title)):
        return False, "junk_or_defective"
    if variant_flags(product) != variant_flags(title):
        return False, "variant_mismatch"
    return True, ""


# ---------------------------------------------------------------- 日付・鮮度
def _d(v) -> Optional[datetime]:
    s = _nfkc(v).strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})[/.年-](\d{1,2})[/.月-](\d{1,2})日?", s)               # 2026/11/17・2026年11月17日・2026.11.17 を ISO に
    if m:
        s = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    try:
        if len(s) == 10:
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=JST)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(JST) if dt.tzinfo else dt.replace(tzinfo=JST)
    except ValueError:
        return None


_URL = re.compile(r"^(?P<scheme>https?)://(?P<auth>[^/?#]*)(?P<path>/[^?#]*)?(?:\?(?P<query>[^#]*))?(?:#.*)?$", re.I)


class _U:
    """URL の分解結果（scheme・host・path・query）。userinfo・ポート・不正な形は host を空にする。"""
    __slots__ = ("scheme", "hostname", "path", "query", "username", "password")

    def __init__(self, raw: str):
        m = _URL.match(raw)
        self.scheme = (m.group("scheme").lower() if m else "")
        auth = (m.group("auth") if m else "") or ""
        self.username = self.password = "x" if "@" in auth else None
        host = auth.rsplit("@", 1)[-1].split(":", 1)[0].lower() if m else ""
        self.hostname = host
        self.path = (m.group("path") if m else "") or ""
        self.query = (m.group("query") if m else "") or ""


def urlparse(raw) -> "_U":
    return _U(str(raw or "").strip())


def query_keys(query: str) -> set:
    return {kv.split("=", 1)[0].lower() for kv in query.split("&") if kv}


def domain_of(url) -> str:
    """URL の登録ドメイン（www を除き、co.jp は 3 ラベル、それ以外は 2 ラベル）。https 以外・読めない URL は空。"""
    raw = str(url or "").strip()
    if not raw or re.search(r"[\\\s\x00-\x1f\x7f@]|%(?:5c|40|2f|00)", raw, re.I):      # バックスラッシュ・空白・制御文字・@・エンコードされた区切りは、ブラウザと解釈がずれるので拒否
        return ""
    try:
        u = urlparse(raw)
    except ValueError:
        return ""
    if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password or not re.fullmatch(r"[a-z0-9.-]+", u.hostname.lower()):
        return ""
    parts = u.hostname.lower().split(".")
    if parts and parts[0] == "www":
        parts = parts[1:]
    n = 3 if len(parts) >= 3 and ".".join(parts[-2:]) in ("co.jp", "or.jp", "ne.jp", "co.uk") else 2
    return ".".join(parts[-n:])


_SEARCH_KEYS = frozenset({"word", "q", "keyword", "keywords", "kw", "search", "query", "s", "k", "searchword", "freeword", "key"})
_LIST_PATH = re.compile(r"/(search|list|lists|category|categories|ct\d*|brand|brands|shopbrand|results?|tag|tags|ranking|campaign|feature)(/|$)", re.I)


def is_listing_page_url(url) -> bool:
    """検索結果・一覧・トップページの URL か（商品ページでない）。"""
    u = urlparse(url)
    qs = query_keys(u.query)
    detail = bool(re.search(r"detail|product_detail|/item/\d", u.path, re.I))          # 「…/search/detail/」のような詳細ページは一覧と見なさない
    return bool(qs & _SEARCH_KEYS) or (bool(_LIST_PATH.search(u.path)) and not detail) or u.path in ("", "/")


def host_of(url) -> str:
    if not domain_of(url):
        return ""
    h = (urlparse(str(url).strip()).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _item_page_reason(url, cfg: dict) -> Optional[str]:
    """商品ページの URL か。ドメイン（ホスト）ごとの形の許可リストがあればそれで、無ければ「検索・一覧・トップでない」ことだけを検査する。"""
    pats = cfg.get("item_url_patterns") or {}
    pat = pats.get(host_of(url)) or pats.get(domain_of(url))
    if pat:
        u = urlparse(str(url).strip())
        tail = u.path + (("?" + u.query) if u.query else "")
        return None if any(re.search(x, tail) for x in ([pat] if isinstance(pat, str) else list(pat))) else "not_item_page"
    return "not_item_page" if (is_listing_page_url(url) and not pt.is_item_url(url)) else None


def _host_reason(kind: str, url, cfg: dict) -> Optional[str]:
    """許可ドメインの検査（None なら通る）。成約は個別の商品ページ URL（price_types.is_item_url）で検査する。"""
    d = domain_of(url)
    allowed = cfg.get("allowed_hosts") or {}
    if d and kind in ("retail", "listing", "official", "buyback") and not pt.is_item_url(url):
        why = _item_page_reason(url, cfg)
        if why:
            return why
    if kind == "sold":
        return None if pt.is_item_url(url) else "no_item_url"
    if kind == "listing":
        return None if (d in (allowed.get("retail") or []) or pt.is_item_url(url)) else "host_not_allowed"
    return None if d in (allowed.get(kind if kind in ("official", "retail", "buyback") else "retail") or []) else "host_not_allowed"


def freshness(row: dict, now: datetime, cfg: dict) -> tuple[str, Optional[int]]:
    """(鮮度, 経過日数)。未来の日付・日付なし・更新日が確認日より新しい（不整合）は UNKNOWN_FRESHNESS（今日確認したことにしない）。
    買取は source_updated_at があればそれも見る（取得日が新しくても、店の価格が古ければ STALE。古い方を基準にする）。"""
    fr = cfg.get("freshness") or {}
    lim = int(fr.get("executable_days", 7))
    chk = _d(row.get("checked_at"))
    if chk is None or chk.date() > now.date():
        return UNKNOWN_FRESHNESS, None
    upd = _d(row.get("source_updated_at"))
    if str(row.get("source_updated_at") or "").strip() and upd is None:
        return UNKNOWN_FRESHNESS, None                    # 更新日が書いてあるのに解釈できない → 古い価格を新しいとみなさない
    if upd is not None and (upd.date() > now.date() or upd.date() > chk.date()):
        return UNKNOWN_FRESHNESS, None
    basis = upd if upd is not None else chk
    age = max(0, (now.date() - min(basis, chk).date()).days)
    return (FRESH if age <= lim else STALE), age


_LOT_WORDS = re.compile(r"抽選|LOTTERY|応募|エントリー|予約|RESERV|先着|受付中")


_STOCK_NEG = re.compile(r"ありません|在庫なし|在庫無|在庫0|無し|切れ|欠品|取り寄せ|取寄|納期|入荷|店頭|取扱|終了|僅少|残りわずか|制限|受注|ウェイト|WAIT-?LIST|"
                        r"SOLD[ _-]?OUT|OUT[ _-]?OF[ _-]?STOCK|NOT[ _-]?AVAILABLE|UNAVAILABLE|NO[ _-]?STOCK|LOTTERY|売り?切|品切|完売|PRE-?ORDER|BACK-?ORDER|"
                        r"限定|先着|応募|エントリー|予約|抽選|受付|在庫未定|できません|いただけません|ございません|が無い|が無く|がない|販売停止|販売中止|休止|不可|未定|"
                        r"お届け|出荷目安|発送目安|週間|か月|ヶ月|カ月|営業日|店舗のみ|店舗限定|SCHEMA\.ORG/(?:OUTOFSTOCK|SOLDOUT|PREORDER|BACKORDER|LIMITED)")
_STOCK_POS = re.compile(r"購入ボタン|カートに入れる|カート|在庫あり|在庫有り|在庫有|IN[ _-]?STOCK|購入可能|購入できる|ご注文可能|注文可能|ADD TO CART")
_STOCK_OK = frozenset({"AVAILABLE", "INSTOCK", "IN_STOCK", "在庫あり", "在庫有り", "在庫有"})
# 「…の表示なし」「…の記載なし」「…ではない」のような否定の否定は、否定語として数えない（「在庫切れ表示なし」「予約・抽選の表示なし」「日付なし」）
_NEGATED = re.compile(r"(在庫切れ|売り?切れ|品切れ|完売|SOLD[ _-]?OUT|OUT[ _-]?OF[ _-]?STOCK|抽選|予約|応募|受付|限定|先着|入荷|取り寄せ|欠品|制限)(?:待ち|未定)?"
                      r"[・、,\s]*(?:(?:抽選|予約|応募|受付|限定|先着|入荷|取り寄せ|欠品|制限)(?:待ち|未定)?[・、,\s]*)*(?:の|は|が)?(?:表示|記載|情報|案内|表記)?(?:は|が)?(?:なし|無し|ない|なく|ではない|ではなく)")
_DATELESS = re.compile(r"(?:ページ|日付|更新日|更新)[^、。,.]{0,8}(?:なし|無し)")


def stock_of(row: dict) -> str:
    """在庫の状態。AVAILABLE は、stock が「AVAILABLE」「在庫あり」と構造的に明示され、**どの記述にも**否定・取り寄せ・店頭のみ・
    抽選・予約・限定・受付などの語が無いときだけ（「在庫切れ表示なし」のような否定の否定は除いて見る）。"""
    raw = _nfkc(row.get("stock") or "").strip()
    ctx_raw = _nfkc(" ".join(str(row.get(k) or "") for k in ("stock_evidence", "note", "reason", "item_title", "availability"))).upper()
    ctx = _DATELESS.sub(" ", _NEGATED.sub(" ", ctx_raw.replace("注文受付中", " ")))
    ctx = ctx + " " + re.sub(r"\s+", "", ctx)                # 「在庫 なし」のような空白入りの否定語も拾う
    s = raw.upper()
    if row.get("lottery") or "LOTTERY" in s or "抽選" in s or "抽選" in ctx or "LOTTERY" in ctx:
        return LOTTERY_DEPENDENT
    if "RESERV" in s or "予約" in s or "予約" in ctx or "PREORDER" in ctx or "PRE-ORDER" in ctx:
        return RESERVATION
    if _STOCK_NEG.search(s) and s not in _STOCK_OK:
        return OUT_OF_STOCK if re.search(r"切れ|ありません|在庫なし|在庫無|在庫0|SOLD[ _-]?OUT|OUT[ _-]?OF[ _-]?STOCK|NOT[ _-]?AVAILABLE|UNAVAILABLE|NO[ _-]?STOCK|完売|売り?切|品切|欠品", s) else STOCK_UNKNOWN
    if s in _STOCK_OK or raw in _STOCK_OK:
        if re.search(r"要約|未検証|未確認|文字化け|SNIPPET|推測|推定", ctx):
            return STOCK_UNKNOWN                          # 要約・文字化け・推測など、自認した不確かな根拠は AVAILABLE の根拠にしない
        if _STOCK_NEG.search(ctx) or not _STOCK_POS.search(ctx):
            return STOCK_UNKNOWN                          # 否定語がある・購入できる肯定の根拠が無い
        return AVAILABLE
    return STOCK_UNKNOWN


def condition_of(v) -> str:
    c = str(v or "").upper().strip()
    return c if c in (NEW, UNOPENED, LIKE_NEW, USED) else UNKNOWN


def compatible(buy_cond: str, sell_cond: str) -> bool:
    """買った状態と売る状態が同じ区分か（新品 ≠ 新品同様 ≠ 中古。UNKNOWN は互換にしない）。"""
    a, b = _FAMILY.get(buy_cond), _FAMILY.get(sell_cond)
    return a is not None and a == b


# ---------------------------------------------------------------- 入力 → 観測
def observations(rec: dict, now: datetime, cfg: dict) -> list[dict]:
    """1 機種の調査レコード（kind 別の行）を、種別つきの観測の一覧にする。使えない行も reason つきで残す。"""
    product = rec["product"]
    out: list[dict] = []

    def base(r, kind, ptype, price, cond, market, **extra):
        fr, age = freshness(r, now, cfg)
        ok, why = identity_ok(product, r.get("item_title")) if (kind != "official" or r.get("item_title") != product) else (True, "")
        reasons = [] if ok else [why]
        if not (isinstance(price, int) and not isinstance(price, bool) and price > 0):
            reasons.append("price_missing")
        if _AGG.search(str(market or "") + str(r.get("item_title") or "")) and kind != "official":
            reasons.append("aggregator_source")
        if kind == "buyback" and re.search(r"(?i)\d+\s*%\s*UP|増額|アップ|キャンペーン|期間限定|上限|最大|条件付|アプリ限定|最低保証|会員限定|クーポン",
                                           _nfkc(" ".join(str(r.get(k) or "") for k in ("reason", "note", "price_note", "evidence", "item_title")))):
            reasons.append("conditional_price")                  # キャンペーン・条件つきの買取価格は、誰でもその額で売れる価格ではない
        if kind != "official" and re.search(r"要約|文字化け|未検証|SNIPPET|推測|推定", _nfkc(" ".join(str(r.get(k) or "") for k in ("reason", "note", "price_note", "evidence"))).upper()):
            reasons.append("unverified_evidence")                # 要約・文字化け・推測と自認した根拠の価格は採用しない
        hr = _host_reason(kind, r.get("url"), cfg)
        if hr:
            reasons.append(hr)
        title_n = _nfkc(r.get("item_title"))
        if kind in ("retail", "listing", "buyback", "sold") and cond in (NEW, UNOPENED) and (
                _USED_WORDS.search(title_n) or ("未使用" in title_n and "新品" not in title_n)):
            reasons.append("title_condition_mismatch")           # 商品名が中古・新品同様・ランク付きなのに、申告が新品
        o = {"product": product, "kind": kind, "price_type": ptype, "price": price if (isinstance(price, int) and not isinstance(price, bool)) else None,
             "condition": cond, "source": market, "item_title": r.get("item_title"), "url": r.get("url") or "",
             "checked_at": r.get("checked_at"), "source_updated_at": r.get("source_updated_at"),
             "freshness": fr, "age_days": age, "identity_ok": ok, "reasons": reasons, "carried": bool(r.get("carried")), "from_pipeline": bool(r.get("from_pipeline")),
             "shop_key": _company(domain_of(r.get("url")), cfg) or _shop_key(market),
             "color": color_of(r.get("item_title"))}
        o.update(extra)
        out.append(o)

    off = rec.get("official") or {}
    if off:
        price = off.get("price_jpy") if off.get("price_kind") == "OFFICIAL_RETAIL" else None
        price = price if (isinstance(price, int) and not isinstance(price, bool)) else None
        r = dict(off)
        r["item_title"] = off.get("item_title") or product         # 公式の商品名が書かれていれば同一性を検査する（無ければ調査員の申告）
        base(r, "official", OFFICIAL_RETAIL, price, NEW, off.get("shop") or "メーカー公式", stock=stock_of(off),
             shipping_jpy=off.get("purchase_shipping_jpy"), shipping_url=off.get("purchase_shipping_url"), price_kind=off.get("price_kind"))
        if not (isinstance(price, int) and price > 0):
            out[-1]["reasons"] = sorted(set(out[-1]["reasons"] + [f"price_kind_{off.get('price_kind') or 'unknown'}"]))
    for r in rec.get("retail") or []:
        base(r, "retail", RETAIL_PRICE, r.get("price_jpy"), NEW if condition_of(r.get("condition")) in (NEW, UNOPENED) else condition_of(r.get("condition")),
             r.get("shop"), stock=stock_of(r), shipping_jpy=r.get("shipping_jpy"), shipping_url=r.get("shipping_url"))
    for r in rec.get("buyback") or []:
        o_reasons = []
        if not r.get("is_product_page", False):
            o_reasons.append("not_product_page")
        base(r, "buyback", BUYBACK_PRICE, r.get("price_jpy"), condition_of(r.get("condition")), r.get("shop"),
             updated_known=bool(_d(r.get("source_updated_at"))))
        out[-1]["reasons"] = out[-1]["reasons"] + o_reasons
    for r in rec.get("listing") or []:
        cond = condition_of(r.get("condition"))
        extra = []
        if r.get("purchasable_now") is not True:
            extra.append("not_purchasable_now")
        if cond == UNKNOWN:
            extra.append("condition_unknown")
        base(r, "listing", LISTING_LOW, r.get("price_jpy"), cond, r.get("market"), shipping_jpy=r.get("shipping_jpy"),
             shipping_url=r.get("shipping_url"), stock=AVAILABLE if r.get("purchasable_now") is True else STOCK_UNKNOWN)
        out[-1]["reasons"] = out[-1]["reasons"] + extra
    for r in rec.get("sold") or []:
        base(r, "sold", pt.SOLD, r.get("price_jpy"), condition_of(r.get("condition")), r.get("market"), sold_at=r.get("sold_at"))
    return out


# ---------------------------------------------------------------- 二次流通の集計
def _sold_key(url) -> str:
    """成約ページの同一性キー（市場 + 商品 ID）。クエリ・フラグメント・末尾の / ・大文字小文字の違いで別の件に数えない。"""
    u = str(url or "").strip().split("#", 1)[0].split("?", 1)[0].rstrip("/")
    m = re.search(r"jp\.mercari\.com/(?:item|shops/product)/([A-Za-z0-9]+)", u)
    if m:
        return "mercari:" + m.group(1).lower()
    m = re.search(r"auctions\.yahoo\.co\.jp/jp/auction/([A-Za-z0-9]+)", u)
    if m:
        return "yauc:" + m.group(1).lower()
    m = re.search(r"item\.fril\.jp/([A-Za-z0-9]+)", u)
    if m:
        return "fril:" + m.group(1).lower()
    m = re.search(r"ebay\.[a-z.]+/itm/(\d+)", u)
    if m:
        return "ebay:" + m.group(1)
    return u.lower()


_MARKET_LABEL = {"mercari": "メルカリ", "yahoo_auction": "Yahoo!オークション", "yahoo_flea": "Yahoo!フリマ", "rakuma": "ラクマ", "ebay": "eBay"}


def _market_label(o: dict) -> str:
    """成約の市場は、自由記述の市場名ではなく URL のホストで決める（手数料率の取り違えを防ぐ）。決められなければ「不明な市場」。"""
    return _MARKET_LABEL.get(market_from_url(o.get("url")) or "", "不明な市場")


def secondary_summary(rec: dict, obs: list[dict], now: datetime, cfg: dict) -> dict:
    """状態の区分ごとの LISTING_LOW / LISTING_HIGH と、市場ごとの SOLD_LOW / SOLD_HIGH / SOLD_MEDIAN（件数・期間つき）。
    LISTING_HIGH は表示専用（売値にしない）。成約が足りないときは median=None・status=insufficient_samples。"""
    product = rec["product"]
    lst: dict = {}
    for o in obs:
        if o["kind"] != "listing" or o["reasons"] or o["freshness"] != FRESH:
            continue
        lst.setdefault(_FAMILY.get(o["condition"], "?"), []).append(o)
    listing = {fam: {"low": min(x["price"] for x in rows), "high": max(x["price"] for x in rows), "n": len(rows),
                     "low_source": min(rows, key=lambda x: x["price"])["source"], "price_types": [LISTING_LOW, LISTING_HIGH],
                     "note": "出品中の希望価格（売れた価格ではない。LISTING_HIGH は売値に使わない）"} for fam, rows in lst.items()}
    days = int((cfg.get("sold") or {}).get("period_days", 90))
    pe_, ps = now, now - timedelta(days=days)
    sold: dict = {}
    groups: dict = {}
    seen = set()
    for o in obs:
        if o["kind"] != "sold" or not o["identity_ok"] or o["reasons"]:
            continue
        key = _sold_key(o.get("url"))
        if key in seen:                                   # 同じ成約ページの重複は 1 件（件数の水増しを許さない）
            o["reasons"] = o["reasons"] + ["duplicate_sold"]
            continue
        seen.add(key)
        groups.setdefault((_market_label(o), _FAMILY.get(o["condition"], "?"), o.get("color") or ""), []).append(o)
    for (market, fam, color), rows in groups.items():
        samples = [pt.MarketSample(price=x["price"] or 0, price_type=pt.SOLD, identity=product,
                                   condition=x["condition"], item_url=x["url"], sold_at=x["sold_at"] or "") for x in rows]
        conds = {c for c, f in _FAMILY.items() if f == fam}
        st = pt.sold_median(samples, identity=product, period_start=ps, period_end=pe_, conditions=conds)
        dts = [str(x["sold_at"])[:10] for x in rows if x.get("sold_at")]
        sold[f"{market}|{fam}|{color}"] = {
            "market": market, "family": fam, "color": color or None, "price_types": [SOLD_LOW, SOLD_HIGH, SOLD_MEDIAN],
            "low": st.get("min"), "high": st.get("max"), "median": st.get("median"),
            "sample_count": st["sample_count"], "min_samples": st["min_samples"],
            "period_start": st["period_start"][:10], "period_end": st["period_end"][:10],
            "latest_sold_at": max(dts) if dts else None,
            "status": st["status"], "eligible": pt.is_sold_median_eligible(st)}
    return {"listing": listing, "sold": sold}


# ---------------------------------------------------------------- 費用
def _shipping(o: dict, official_shipping_fn, cfg_hosts: Optional[dict] = None) -> tuple[Optional[int], str]:
    """購入送料。研究の値は根拠の URL があるものだけ。既存の公式送料の表（official_shipping）が分かればそれを使う。分からなければ None。"""
    if official_shipping_fn is not None and o.get("kind") == "official":      # 既存の送料の表はメーカー公式の購入先のもの（別の店に流用しない）
        try:
            r = official_shipping_fn(o.get("product_id") or "", o.get("url") or "", o.get("price"))
            if isinstance(r.get("fee"), int):
                return r["fee"], f"official_shipping:{r.get('source')}"
        except Exception:
            pass
    s = o.get("shipping_jpy")
    su = str(o.get("shipping_url") or "")
    ok_url = bool(domain_of(su)) and su != str(o.get("url") or "") and domain_of(su) in (
        set((cfg_hosts or {}).get("official") or []) | set((cfg_hosts or {}).get("retail") or []))
    if isinstance(s, int) and not isinstance(s, bool) and s >= 0 and ok_url:            # 商品ページ自身ではない、許可ドメインの送料の根拠 URL があるものだけ
        return s, "research"
    return None, "unknown"


def _fee(market_name, sell_price: int, cfg: dict) -> tuple[Optional[int], Optional[dict], str]:
    k = market_key(market_name)
    f = (cfg.get("fees") or {}).get(k or "") or {}
    if not k or not f.get("confirmed") or not isinstance(f.get("rate"), (int, float)) or f["rate"] <= 0:
        return None, f or None, "fee_unconfirmed"
    return int(sell_price * f["rate"]), f, ""


# ---------------------------------------------------------------- ルート
def _rank_stock(s: str) -> int:
    return {AVAILABLE: 0, RESERVATION: 1, LOTTERY_DEPENDENT: 2, STOCK_UNKNOWN: 3, OUT_OF_STOCK: 4}.get(s, 5)


def _buy_candidates(obs: list[dict], route: str) -> tuple[list, list]:
    """(使える候補, 除外の理由つき)。A・B は正規店・メーカー（新品）、C・D は二次流通の出品（現在購入可能のもの）。"""
    ok, ng = [], []
    kinds = ("official", "retail") if route in "AB" else ("listing",)
    for o in obs:
        if o["kind"] not in kinds:
            continue
        reasons = list(o["reasons"])
        if o["freshness"] != FRESH:
            reasons.append(f"buy_{o['freshness'].lower()}")
        if o["kind"] == "retail" and o["condition"] != NEW:
            reasons.append("retail_not_new")
        if o.get("price") and any(b["kind"] == "buyback" and not b["reasons"] and b.get("price") and compatible(o["condition"], b["condition"])
                                  and o["price"] < 0.5 * b["price"] for b in obs):
            reasons.append("price_implausible")                  # 買取の最高の半分未満の仕入れ価格は誤取得（桁落ち等）の疑い。BUY にしない
        (ng if reasons else ok).append({**o, "reasons": reasons})
    return ok, ng


def _sell_candidates_buyback(obs, fam_ok) -> tuple[list, list]:
    ok, ng = [], []
    for o in obs:
        if o["kind"] != "buyback":
            continue
        reasons = list(o["reasons"])
        if o["freshness"] != FRESH:
            reasons.append(f"sell_{o['freshness'].lower()}")
        (ng if reasons else ok).append({**o, "reasons": reasons})
    return ok, ng


def _routes_for_product(rec: dict, obs: list[dict], sec: dict, cfg: dict, now: datetime, official_shipping_fn,
                        fixed_cost_fn, registered: bool) -> list[dict]:
    routes = []
    min_roi = float((cfg.get("decision") or {}).get("buy_min_roi_pct", 8.0))
    other = int((cfg.get("costs") or {}).get("other_jpy", 0))
    sec_out = int((cfg.get("costs") or {}).get("secondary_outbound_shipping_jpy", 0))
    bb_ok, bb_ng = _sell_candidates_buyback(obs, None)
    for route in "ABCD":
        buy_ok, buy_ng = _buy_candidates(obs, route)
        base = {"route_type": route, "route_label": ROUTE_LABEL[route], "product": rec["product"], "registered": registered}
        if not buy_ok:
            routes.append({**base, "profit_status": NOT_CALCULATED, "decision": WATCH if buy_ng else SKIP, "buy": None, "sell": None,
                           "reasons": sorted({r for o in buy_ng for r in o["reasons"]} or {"no_buy_candidate"}),
                           "costs": None, "net_profit": None, "roi_pct": None, "executable": False, "confidence": "low"})
            continue
        def _ship_known(o):
            return _shipping(o, official_shipping_fn, cfg.get("allowed_hosts"))[0] is not None
        buy = sorted(buy_ok, key=lambda o: (not _ship_known(o), _rank_stock(o.get("stock", STOCK_UNKNOWN)), o["price"]))[0]
        # 売り先
        if route in "AC":
            comp = [o for o in bb_ok if compatible(buy["condition"], o["condition"])
                    and (not buy.get("color") or o.get("color") == buy["color"])]        # 色指定の仕入れには、同じ色が確認できる買取だけ（色不明の行は使わない）
            if not comp:
                why = sorted({r for o in bb_ng for r in o["reasons"]} | ({"condition_mismatch"} if bb_ok else set()) or {"no_buyback"})
                routes.append({**base, "profit_status": NOT_CALCULATED, "decision": WATCH, "buy": _view(buy), "sell": None,
                               "reasons": why, "costs": None, "net_profit": None, "roi_pct": None, "executable": False, "confidence": "low"})
                continue
            if buy.get("color") is None:                       # 仕入側が色を指定していない → 色違いのうち最も低い価格で保守的に
                colors = {o.get("color") for o in comp}
                sell = min(comp, key=lambda o: o["price"]) if len(colors) > 1 else max(comp, key=lambda o: o["price"])
            else:
                sell = max(comp, key=lambda o: o["price"])
            sell_view = {**_view(sell), "price_type": BUYBACK_PRICE, "evidence": {"shops": len({o.get("shop_key") or _shop_key(o["source"]) for o in comp if not o.get("carried") and not o.get("from_pipeline") and o["freshness"] == FRESH
                              and (o.get("color") or None) == (sell.get("color") or None)}), "outlier": _outlier([o for o in comp if not o.get("carried") and not o.get("from_pipeline") and o["freshness"] == FRESH
                                                                                                   and (o.get("color") or None) == (sell.get("color") or None)])}}
            fee, fee_cfg, fee_why = 0, None, ""
            outbound = int(fixed_cost_fn())
            fee_applies = False
        else:
            sold_ok = [s for s in sec["sold"].values() if s["eligible"] and compatible(buy["condition"], {"NEW": NEW, "LIKE_NEW": LIKE_NEW, "USED": USED}.get(s["family"], UNKNOWN))]
            if buy.get("color"):                               # 色指定の仕入れには同じ色の成約だけ（色でプレミアが違う）
                sold_ok = [s for s in sold_ok if s.get("color") == buy["color"]]
            else:                                              # 色を指定しない仕入れ: 色なしの成約があればそれ、無ければ色違いのうち最も低い中央値
                plain = [s for s in sold_ok if not s.get("color")]
                sold_ok = plain or ([min(sold_ok, key=lambda s: s["median"])] if sold_ok else [])
            if not sold_ok:
                why = ["sold_insufficient"] + (["sold_none"] if not sec["sold"] else [])
                routes.append({**base, "profit_status": NOT_CALCULATED, "decision": WATCH, "buy": _view(buy), "sell": None,
                               "sell_unavailable": {"price_type": SOLD_MEDIAN, "status": "UNAVAILABLE"},
                               "reasons": why, "costs": None, "net_profit": None, "roi_pct": None, "executable": False, "confidence": "low"})
                continue
            def _net_of(g):
                f_, _, w_ = _fee(g["market"], g["median"], cfg)
                return (0, g["median"] - f_) if f_ is not None else (-1, g["median"])
            best = max(sold_ok, key=_net_of)                    # 手数料を引いた後が最大の市場（手数料が確認できる市場を優先）
            # 売値の日付は「最新の成約日」（今日ではない）。最新の成約が古ければ STALE
            sfr, sage = freshness({"checked_at": best["latest_sold_at"]}, now, cfg)
            sell = {"price": best["median"], "source": best["market"], "condition": best["family"], "freshness": sfr,
                    "url": "", "checked_at": best["latest_sold_at"], "source_updated_at": None}
            sell_view = {"price": best["median"], "price_type": SOLD_MEDIAN, "source": best["market"], "condition": best["family"],
                         "color": best.get("color"),
                         "evidence": {"sample_count": best["sample_count"], "period": f"{best['period_start']}〜{best['period_end']}",
                                      "low": best["low"], "high": best["high"], "latest_sold_at": best["latest_sold_at"]},
                         "freshness": sfr, "age_days": sage, "url": "", "checked_at": best["latest_sold_at"], "source_updated_at": None}
            fee, fee_cfg, fee_why = _fee(best["market"], best["median"], cfg)
            outbound = sec_out
            fee_applies = True
        ship, ship_src = _shipping(buy, official_shipping_fn, cfg.get("allowed_hosts"))
        why = []
        if ship is None:
            why.append("purchase_shipping_unknown")
        if fee is None:
            why.append(fee_why)
        if why:
            routes.append({**base, "profit_status": NOT_CALCULATED, "decision": WATCH, "buy": _view(buy), "sell": sell_view,
                           "reasons": why, "costs": None, "net_profit": None, "roi_pct": None, "executable": False, "confidence": "low"})
            continue
        costs = {"purchase_shipping": ship, "purchase_shipping_source": ship_src, "outbound_shipping": outbound,
                 "selling_fee": fee, "selling_fee_applies": fee_applies,
                 "selling_fee_rate": (fee_cfg or {}).get("rate") if fee_applies else None, "other": other}
        net = sell_view["price"] - buy["price"] - ship - outbound - fee - other
        roi = round(100.0 * net / buy["price"], 2) if buy["price"] else None
        status = PROFITABLE if net > 0 else NO_PROFIT
        stock = buy.get("stock", STOCK_UNKNOWN)
        stock_days = int((cfg.get("freshness") or {}).get("stock_days", 2))
        stock_fresh = isinstance(buy.get("age_days"), int) and buy["age_days"] <= stock_days and not buy.get("carried")
        executable = (stock == AVAILABLE and stock_fresh and buy["freshness"] == FRESH and sell["freshness"] == FRESH
                      and not sell_view.get("carried") and not buy.get("carried"))
        decision, why2 = _decide(status, stock, roi, min_roi, registered, route, sell_view, executable, buy)
        routes.append({**base, "profit_status": status, "decision": decision, "buy": _view(buy), "sell": sell_view,
                       "costs": costs, "net_profit": net, "roi_pct": roi, "executable": executable, "reasons": why2,
                       "confidence": _confidence(status, executable, route, sell_view, buy)})
    return routes


def _view(o: dict) -> dict:
    return {k: o.get(k) for k in ("source", "price", "price_type", "condition", "stock", "url", "checked_at", "source_updated_at",
                                  "freshness", "age_days", "item_title", "color", "carried")}


def _company(domain: str, cfg: dict) -> str:
    """ドメイン → 会社（同じ会社の別ドメインを 2 店に数えない）。表に無ければドメインのまま。"""
    return ((cfg.get("shop_company") or {}).get(domain)) or domain


def count_shops(p: dict, buy_cond: str, sell_color=None) -> tuple[int, bool]:
    """観測から数え直した「比較できた買取店数」と外れ値の有無。売値と同じ色の行だけを数える。carried・STALE・自動収集の行・理由つきの行は数えない。"""
    rows = [o for o in p["observations"] if o["kind"] == "buyback" and not o["reasons"] and o.get("price") and o["freshness"] == FRESH
            and not o.get("carried") and not o.get("from_pipeline") and compatible(buy_cond, o["condition"])
            and (o.get("color") or None) == (sell_color or None)]
    return len({o.get("shop_key") for o in rows}), _outlier(rows)


def _shop_key(name) -> str:
    """店名の正規化（空白・括弧書き・記号の揺れを同じ店にする）。"""
    return _norm(re.sub(r"[（(].*$", "", str(name or "")))


def _outlier(comp: list) -> bool:
    ps = sorted((o["price"] for o in comp), reverse=True)
    return len(ps) >= 2 and ps[0] > ps[1] * 1.15


def _decide(status, stock, roi, min_roi, registered, route, sell_view, executable, buy) -> tuple[str, list]:
    if status == NO_PROFIT:
        return SKIP, ["no_profit"]
    if roi is not None and roi > 100:
        return WATCH, ["roi_implausible"]                        # ROI 100% 超は誤取得（桁落ち等）の疑い。BUY にしない
    why = []
    if stock in (LOTTERY_DEPENDENT, RESERVATION):
        return WAIT, [f"stock_{stock.lower()}"]                 # 抽選・予約が必要な商品を BUY にしない
    if stock == OUT_OF_STOCK:
        return WAIT, ["out_of_stock"]
    if stock != AVAILABLE:
        return WATCH, ["stock_unknown"]
    if not registered:
        why.append("unregistered_product")
    if roi is None or roi < min_roi:
        why.append("roi_below_threshold")
    if route == "A":
        ev = sell_view.get("evidence") or {}
        if ev.get("shops", 0) < 2:
            why.append("single_buyback_shop")
        if ev.get("outlier"):
            why.append("buyback_outlier_review")
        if not sell_view.get("source_updated_at"):
            why.append("buyback_update_date_unknown")
    else:
        why.append("secondary_route_not_auto_buy")              # 二次流通（成約の売値・出品の仕入れ）は、自動の BUY にしない（実在と状態を人が確認する）
    if not executable:
        why.append("not_executable" if not (isinstance(buy.get("age_days"), int) and buy["age_days"] > 2) else "stock_check_old")
    if why:
        return (WAIT if "roi_below_threshold" in why else WATCH), why
    return BUY, []


def _confidence(status, executable, route, sell_view, buy) -> str:
    if status != PROFITABLE or not executable:
        return "low"
    ev = sell_view.get("evidence") or {}
    if route == "A" and ev.get("shops", 0) >= 2 and sell_view.get("source_updated_at") and not ev.get("outlier"):
        return "high"
    return "medium"


# ---------------------------------------------------------------- 全体
def build_market(records: list[dict], now: datetime, cfg: dict, *, registered_names: set,
                 official_shipping_fn=None, fixed_cost_fn=lambda: 1800) -> dict:
    """機種ごとの観測・二次流通の集計・ルート A〜D・最良のルートを作る。"""
    products, all_routes = [], []
    for rec in records:
        obs = observations(rec, now, cfg)
        for o in obs:
            o["product_id"] = rec.get("product_id")
        sec = secondary_summary(rec, obs, now, cfg)
        reg = name_key(rec["product"]) in {name_key(n) for n in registered_names}
        routes = _routes_for_product(rec, obs, sec, cfg, now, official_shipping_fn, fixed_cost_fn, reg)
        calc = [r for r in routes if r["profit_status"] != NOT_CALCULATED]
        rank = {BUY: 3, WAIT: 2, WATCH: 1, SKIP: 0}
        best = max(calc, key=lambda r: (rank.get(r["decision"], 0), r["net_profit"]))["route_type"] if calc else None
        products.append({"product": rec["product"], "brand": rec.get("brand"), "product_id": rec.get("product_id"), "registered": reg,
                         "identity_note": rec.get("identity_note"), "observations": obs, "secondary": sec, "routes": routes,
                         "best_route": best})
        all_routes += routes
    return {"products": products, "routes": all_routes}


def quality_checks(market: dict, now: datetime, research_date: str, cfg: dict, *, fixed_cost: Optional[int] = None) -> dict:
    """出力された観測・二次流通の集計・ルートだけから、品質の数を**独立に**数え直す（すべて 0 でなければならない）。
    ルートに書かれたラベル・数値を信じず、生の観測・設定から再計算して突き合わせる。"""
    q = {"wrong_identity": 0, "wrong_condition": 0, "listing_high_used_as_sell": 0, "insufficient_sold_used_as_expected_sell": 0,
         "stale_price_used_as_fresh": 0, "fake_checked_at": 0, "double_count_fee": 0, "missing_fee": 0}
    rd = _d(research_date)
    other = int((cfg.get("costs") or {}).get("other_jpy", 0))
    sec_out = int((cfg.get("costs") or {}).get("secondary_outbound_shipping_jpy", 0))
    for p in market["products"]:
        good_bb = {(o["price"], o["source"]) for o in p["observations"] if o["kind"] == "buyback" and o.get("price") and not o["reasons"]}
        for o in p["observations"]:
            if o["kind"] != "official" and not o["reasons"] and not identity_ok(p["product"], o.get("item_title"))[0]:
                q["wrong_identity"] += 1
            chk = _d(o.get("checked_at"))
            if chk is not None and (chk.date() > now.date() or (rd is not None and chk.date() > rd.date())):
                q["fake_checked_at"] += 1                       # 未来・調査日より新しい日付（引き継いだ行も、元の日付のまま）
        for r in p["routes"]:
            if r["profit_status"] == cr_NC:
                if r.get("net_profit") is not None:
                    q["missing_fee"] += 1
                continue
            b, s, c = r["buy"], r["sell"], r["costs"]
            ev = s.get("evidence") or {}
            if s["price_type"] not in SELL_TYPES:
                q["listing_high_used_as_sell"] += 1
            elif r["route_type"] in "AC":
                if (s["price"], s["source"]) not in good_bb:              # 売値が、実在する確認済みの買取価格のどれとも一致しない
                    q["listing_high_used_as_sell"] += 1
                if not identity_ok(p["product"], s.get("item_title"))[0]:
                    q["wrong_identity"] += 1
            else:
                grp = [g for g in p["secondary"]["sold"].values() if g["median"] == s["price"] and g["market"] == s["source"]]
                if not grp:
                    q["listing_high_used_as_sell"] += 1                  # 売値が成約中央値のどの集計とも一致しない
                elif not any(g["eligible"] and g["sample_count"] >= pt.MIN_SOLD_SAMPLES and g["period_start"] and g["period_end"] for g in grp):
                    q["insufficient_sold_used_as_expected_sell"] += 1
                if int(ev.get("sample_count") or 0) < pt.MIN_SOLD_SAMPLES or not ev.get("period"):
                    q["insufficient_sold_used_as_expected_sell"] += 1
            if r["route_type"] in "CD" and not identity_ok(p["product"], b.get("item_title"))[0]:
                q["wrong_identity"] += 1
            if not compatible(b["condition"], s["condition"]) or (r["route_type"] in "AC" and b.get("color") and s.get("color") != b["color"]) \
                    or (b.get("color") and s.get("color") and b["color"] != s["color"]):
                q["wrong_condition"] += 1
            # 費用: 設定から再計算して突き合わせる（手数料の欠落・料率違い・二重計上・買取への手数料）
            if r["route_type"] in "BD":
                rate = ((cfg.get("fees") or {}).get(market_key(s["source"]) or "") or {})
                expect = int(s["price"] * rate["rate"]) if rate.get("confirmed") and isinstance(rate.get("rate"), (int, float)) else None
                if expect is None or not c["selling_fee"] or c["selling_fee"] <= 0:
                    q["missing_fee"] += 1
                elif c["selling_fee"] != expect:
                    q["double_count_fee"] += 1
                if c["outbound_shipping"] != sec_out:
                    q["double_count_fee"] += 1
            else:
                if c["selling_fee"] or c["selling_fee_applies"]:
                    q["double_count_fee"] += 1
                if fixed_cost is not None and c["outbound_shipping"] != fixed_cost:
                    q["double_count_fee"] += 1
            if c["other"] != other or r["net_profit"] != s["price"] - b["price"] - c["purchase_shipping"] - c["outbound_shipping"] - c["selling_fee"] - c["other"]:
                q["double_count_fee"] += 1
            # 鮮度は日付から再計算（ラベルを信じない）。実行可能・BUY は FRESH の価格だけ
            if r["executable"] or r["decision"] == BUY:
                bf = freshness({"checked_at": b.get("checked_at"), "source_updated_at": b.get("source_updated_at")}, now, cfg)[0]
                sf = freshness({"checked_at": s.get("checked_at"), "source_updated_at": s.get("source_updated_at")}, now, cfg)[0]
                if bf != FRESH or sf != FRESH or b.get("freshness") != FRESH or s.get("freshness") != FRESH:
                    q["stale_price_used_as_fresh"] += 1
                if b.get("carried") or s.get("carried") or b.get("stock") != AVAILABLE or (r["decision"] == BUY and not r["executable"]):
                    q["stale_price_used_as_fresh"] += 1
            for side in (b, s):
                chk = _d(side.get("checked_at"))
                if chk is not None and chk.date() > now.date():
                    q["fake_checked_at"] += 1
            if r["decision"] == BUY:                                     # BUY の関門を独立に再検証する
                obs_prices = {(o["price"], o["source"]) for o in p["observations"] if o["kind"] in ("official", "retail") and o.get("price") and not o["reasons"]}
                shops_n, outl = count_shops(p, b["condition"], s.get("color"))              # 自己申告ではなく、観測から数え直す
                bad = (r["route_type"] != "A" or not p.get("registered") or r["profit_status"] != PROFITABLE
                       or (r["roi_pct"] is None or r["roi_pct"] < float((cfg.get("decision") or {}).get("buy_min_roi_pct", 8.0)))
                       or shops_n < 2 or outl or (b["price"], b["source"]) not in obs_prices
                       or c.get("purchase_shipping_source") in (None, "unknown") or not s.get("source_updated_at"))
                if bad:
                    q["stale_price_used_as_fresh"] += 1
    return q


cr_NC = NOT_CALCULATED


# ---------------------------------------------------------------- 差分（イベント）
PRICE_STEP = 5000


def route_key(r: dict) -> str:
    return f"{r['product']}|{r['route_type']}"


def obs_key(product: str, o: dict) -> tuple:
    """観測の比較キー。公開データ（店名・商品名がラベル化される）とこの実行の生の観測で同じになるよう、URL（無ければ店のドメイン）を使う。"""
    return (product, o["kind"], str(o.get("url") or o.get("shop_key") or ""), o["condition"], o.get("color") or "")


def diff_events(old: Optional[dict], new: dict) -> list[dict]:
    """前回との差。既存の語彙: PRICE_DROP / PRICE_RISE / BUYBACK_SURGE / LOSS_TO_PROFIT / PROFIT_TO_LOSS /
    WAIT_TO_BUY / BUY_TO_WAIT / BEST_ROUTE_CHANGE。前回が無ければ出さない。"""
    if not old:
        return []
    ev: list[dict] = []
    old_obs = {obs_key(p["product"], o): o for p in old.get("products", []) for o in p.get("observations", []) if o.get("price")}
    for p in new["products"]:
        for o in p["observations"]:
            prev = old_obs.get(obs_key(p["product"], o))
            if not (prev and o.get("price") and not o.get("carried")):
                continue
            d = o["price"] - prev["price"]
            if abs(d) < PRICE_STEP:
                continue
            t = "BUYBACK_SURGE" if (o["kind"] == "buyback" and d > 0) else ("PRICE_RISE" if d > 0 else "PRICE_DROP")
            ev.append({"type": t, "product": p["product"], "market_type": o["kind"], "source": o.get("shop_key") or "",
                       "condition": o["condition"], "from": prev["price"], "to": o["price"]})
    old_routes = {route_key(r): r for p in old.get("products", []) for r in p.get("routes", [])}
    old_best = {p["product"]: p.get("best_route") for p in old.get("products", [])}
    for p in new["products"]:
        for r in p["routes"]:
            prev = old_routes.get(route_key(r))
            if not prev:
                continue
            a, b = prev["profit_status"], r["profit_status"]
            if a == NO_PROFIT and b == PROFITABLE:
                ev.append({"type": "LOSS_TO_PROFIT", "product": p["product"], "route": r["route_type"], "from": a, "to": b})
            elif a == PROFITABLE and b == NO_PROFIT:
                ev.append({"type": "PROFIT_TO_LOSS", "product": p["product"], "route": r["route_type"], "from": a, "to": b})
            if prev["decision"] == WAIT and r["decision"] == BUY:
                ev.append({"type": "WAIT_TO_BUY", "product": p["product"], "route": r["route_type"], "from": prev["decision"], "to": r["decision"]})
            elif prev["decision"] == BUY and r["decision"] == WAIT:
                ev.append({"type": "BUY_TO_WAIT", "product": p["product"], "route": r["route_type"], "from": prev["decision"], "to": r["decision"]})
        if p["product"] in old_best and old_best[p["product"]] and p.get("best_route") and old_best[p["product"]] != p["best_route"]:
            ev.append({"type": "BEST_ROUTE_CHANGE", "product": p["product"], "from": old_best[p["product"]], "to": p["best_route"]})
    return ev
