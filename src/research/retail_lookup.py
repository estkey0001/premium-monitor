"""小売（公式直販）の価格の照会 — 買取起点の候補を、実際の仕入れ値に結び付ける共通の仕組み（Coverage Wave 2）。

商品の識別（JAN・部品番号・型番コード）から、公式直販の価格を**同一性つきで**引く。

    lookup(identity, adapters, indexes) → {status, retailer, product_url, price, availability_state, observed_at, identity_evidence}

- 取得は一覧（カテゴリ）ページを1回 → その中の全商品を引く。商品ごとのページが要る取得器（ソニー）は、名前の型番（ILCE-… / ILME-…）
  から URL の規則で組み立てる（取得数に上限。型番が1つに決まらなければ取らない）
- 同一性: JAN は完全一致、型番は完全一致（大文字小文字だけ無視）。名前だけの一致は使わない。ブランドが違えば一致にしない
- 一致が複数で価格が分かれれば AMBIGUOUS（どれかを選ばない）。販売終了・在庫なしの価格は仕入れ値に使わない（NOT_PURCHASABLE）
- 観測の時刻は、一覧を実際に取得した時刻。取得できなかった一覧の価格は使わない（呼び出し側が index を渡さない）
- 取得は必ず src/collectors/polite.py を通す（robots・間隔・遮断後の打ち切り。呼び出し側の fetch が担う）
- 確定の利益ではない。ここで引けた価格は調査候補の「小売の価格のヒント」で、正本には入れない
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape

MATCHED, NO_MATCH, AMBIGUOUS = "MATCHED", "NO_MATCH", "AMBIGUOUS"
IDENTITY_MISMATCH, NOT_PURCHASABLE, UNSUPPORTED = "IDENTITY_MISMATCH", "NOT_PURCHASABLE", "UNSUPPORTED"
STATUSES = (MATCHED, NO_MATCH, AMBIGUOUS, IDENTITY_MISMATCH, NOT_PURCHASABLE, UNSUPPORTED)

AVAIL_IN_STOCK, AVAIL_OUT, AVAIL_UNKNOWN = "IN_STOCK", "OUT_OF_STOCK", "UNKNOWN"

# 仕入れ元の種別（Coverage Wave 3）。公式だけに限らない
OFFICIAL_DIRECT, AUTHORIZED_RETAILER, LARGE_RETAILER = "OFFICIAL_DIRECT", "AUTHORIZED_RETAILER", "LARGE_RETAILER"
EC_RETAILER, OUTLET, SECONDARY_NEW = "EC_RETAILER", "OUTLET", "SECONDARY_NEW"
SOURCE_TYPES = (OFFICIAL_DIRECT, AUTHORIZED_RETAILER, LARGE_RETAILER, EC_RETAILER, OUTLET, SECONDARY_NEW)

# 価格の条件（現金の仕入れ値を安く見せうるもの）。ポイント・キャッシュバックは条件ではなく別の項目（現金から引かない）
COND_COUPON, COND_CAMPAIGN, COND_MEMBER, COND_LIMITED = "COUPON_REQUIRED", "CAMPAIGN_CONDITIONAL", "MEMBER_ONLY", "LIMITED_QUANTITY"
BASIS_UNCONDITIONAL, BASIS_REGULAR, BASIS_CONDITIONAL_UNKNOWN = "UNCONDITIONAL", "REGULAR_PRICE", "CONDITIONAL_UNKNOWN_REGULAR"


def price_evidence(e: dict) -> dict:
    """一覧・商品ページの1行から、仕入れ値の証拠（表示価格と実際の取得価格を分ける）を作る。

    - listed_price: 表示されている現金の税込価格。regular_price: 通常の価格（分かるとき）
    - immediate_discount: **誰でも・即時に**値引きされる額だけ（取得器が条件なしと確かめたものだけ入れる）
    - required_coupon / campaign_conditions / member_only / limited_quantity: 条件つきの値引き。**現金の仕入れ値に使わない**
    - points / cashback: ポイント還元・キャッシュバック。**現金と同額として控除しない**（別の項目として残す）
    - effective_price（確定の仕入れ値の根拠にしてよい現金の価格）:
        条件なし → listed_price − immediate_discount
        条件つき（クーポン・キャンペーン・会員限定・数量限定）で通常の価格が分かる → regular_price（条件つきの値引きを使わない）
        条件つきで通常の価格が分からない → listed_price（値引き込みかもしれない価格。price_basis で区別し、高優先にしない）
    """
    listed = _int(e.get("price"))
    regular = _int(e.get("regular_price"))
    imm = _int(e.get("immediate_discount")) or 0
    conds = []
    if str(e.get("required_coupon") or "").strip():
        conds.append(COND_COUPON)
    if str(e.get("campaign_conditions") or "").strip() or _int(e.get("campaign_price")):
        conds.append(COND_CAMPAIGN)
    if e.get("member_only"):
        conds.append(COND_MEMBER)
    if e.get("limited_quantity"):
        conds.append(COND_LIMITED)
    if not conds:
        basis, eff = BASIS_UNCONDITIONAL, (listed - imm if listed else None)
        if eff is not None and eff <= 0:
            eff = None
    elif regular:
        basis, eff = BASIS_REGULAR, regular
    else:
        basis, eff = BASIS_CONDITIONAL_UNKNOWN, listed
    return {"listed_price": listed, "regular_price": regular, "campaign_price": _int(e.get("campaign_price")),
            "campaign_conditions": str(e.get("campaign_conditions") or ""), "immediate_discount": imm,
            "required_coupon": str(e.get("required_coupon") or ""), "points": _int(e.get("points")) or 0,
            "cashback": _int(e.get("cashback")) or 0, "effective_price": eff, "price_conditions": conds, "price_basis": basis}

# 名前から推定するブランド（取得器の対応・ブランド違いの棄却に使う）
_BRAND_RES = (
    ("nikon", re.compile(r"Nikon|ニコン|\bZ ?(?:\d|f|fc)(?![A-Za-z0-9])", re.I)),
    ("samsung", re.compile(r"Galaxy|Samsung|サムスン|\bSM-[A-Z]\d", re.I)),
    ("canon", re.compile(r"\bEOS\b|Canon|キヤノン|PowerShot", re.I)),
    ("sony", re.compile(r"\bILCE|\bILME|\bα ?\d|Sony|ソニー|Xperia|PlayStation|\bPS ?5", re.I)),
    ("fujifilm", re.compile(r"FUJIFILM|富士フイルム|\bX100|\bX-[TSHE]\d|\bGFX", re.I)),
    ("apple", re.compile(r"iPhone|iPad|MacBook|Apple Watch|AirPods|\bMac\b", re.I)),
)


def brand_of(name: str) -> str:
    """名前から、ブランドを1つだけ推定する。複数に当たる・当たらないときは空（取得器の対象にしない）。"""
    hits = [b for b, rx in _BRAND_RES if rx.search(str(name or ""))]
    return hits[0] if len(hits) == 1 else ""


def _norm_code(v) -> str:
    return re.sub(r"\s+", "", str(v or "")).upper()


def _int(v):
    try:
        n = int(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


class RetailAdapter:
    """小売の取得器の共通の形。サブクラスは INDEX_URLS と parse_index を持つ。"""

    adapter_id = ""
    retailer = ""
    source_type = OFFICIAL_DIRECT
    brands: tuple = ()
    source_id = ""            # polite の取得元 ID（取得の間隔・打ち切りの単位）
    INDEX_URLS: tuple = ()

    def parse_index(self, html: str, url: str = "") -> list[dict]:
        """一覧ページの全商品: {name, price, url, jan, model, availability}。読めない行は入れない。"""
        raise NotImplementedError

    def supports(self, identity: dict) -> bool:
        """この識別（ブランド）を扱えるか。実際に引けるか（一覧に載っているか）は別。"""
        return brand_of(identity.get("name", "")) in self.brands


class NikonDirectAdapter(RetailAdapter):
    """ニコンダイレクト（nij.nikon.com の直販）のミラーレスの一覧。1行ごとに JAN（URL が /shop/g/g<JAN>/）・商品名・税込の価格。"""

    adapter_id = "nikon_direct"
    retailer = "ニコンダイレクト"
    brands = ("nikon",)
    _MIRRORLESS = re.compile(r"(?<![A-Za-z0-9])Z ?(?:\d|fc?(?![A-Za-z0-9]))|ミラーレス", re.I)
    source_id = "src_nikon_direct"
    INDEX_URLS = ("https://nij.nikon.com/shop/r/r1010/", "https://nij.nikon.com/shop/r/r1010_p2/")

    def supports(self, identity: dict) -> bool:
        """一覧はミラーレス（Z シリーズ）だけ。一眼レフ（D シリーズ）・コンパクトは載らないので対象にしない（引けるとは言わない）。"""
        name = identity.get("name", "")
        return (super().supports(identity) and bool(self._MIRRORLESS.search(str(name)))
                and not re.search(r"NIKKOR|レンズ(?!キット)|ストラップ|ケース", str(name), re.I))   # 一覧はボディ。単体のレンズ・付属品は載らない

    _BLOCK = re.compile(r'<dl class="block-thumbnail-t--goods[^"]*"[^>]*>(.*?)</dl>', re.S)
    _LINK = re.compile(r'href="(/shop/g/g(\d{13})/)"[^>]*?title="([^"]*)"')
    _PRICE = re.compile(r'block-thumbnail-t--price[^>]*>\s*([\d,]{4,})\s*円')

    def parse_index(self, html: str, url: str = "") -> list[dict]:
        out, seen = [], set()
        for m in self._BLOCK.finditer(html or ""):
            blk = m.group(1)
            lk = self._LINK.search(blk)
            pr = self._PRICE.search(blk)
            if not lk or not pr:
                continue
            jan, name, price = lk.group(2), unescape(lk.group(3)).strip(), _int(pr.group(1))
            if jan in seen or not price or not name:
                continue
            seen.add(jan)
            out.append({"name": name, "price": price, "url": "https://nij.nikon.com" + lk.group(1), "jan": jan,
                        "model": _norm_code(name), "availability": AVAIL_UNKNOWN})
        return out


class SamsungAdapter(RetailAdapter):
    """Samsung Japan（samsung.com/jp）のスマートフォン一覧。構造化データ（ItemList）の各商品の型番（?modelCode=SM-…）・税込価格・在庫。

    一覧の価格はキャンペーンの割引込みのことがある（購入ページの価格と違う機種がある）。確定の定価ではなく「小売の価格のヒント」。
    容量は一覧に無い（型番で一致させる）。在庫なし（OutOfStock）の機種の価格は仕入れ値に使わない。
    """

    adapter_id = "samsung_jp"
    retailer = "Samsung Japan"
    brands = ("samsung",)
    source_id = "src_samsung_jp"
    INDEX_URLS = ("https://www.samsung.com/jp/smartphones/all-smartphones/",)
    price_note = "一覧の価格はキャンペーン割引込みの可能性（定価ではない）"

    def parse_index(self, html: str, url: str = "") -> list[dict]:
        import json
        out, seen = [], set()
        for b in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html or "", re.S):
            try:
                d = json.loads(b)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("@type") != "ItemList":
                continue
            for it in d.get("itemListElement") or []:
                p = (it or {}).get("item") if isinstance(it, dict) else None
                if not isinstance(p, dict):
                    continue
                offers = p.get("offers") if isinstance(p.get("offers"), dict) else {}
                m = re.search(r"modelCode=(SM-[A-Z0-9]+)", str(p.get("url") or p.get("@id") or ""))
                price = _int(offers.get("price"))
                if not m or not price or m.group(1) in seen:
                    continue
                seen.add(m.group(1))
                av = str(offers.get("availability") or "")
                out.append({"name": str(p.get("name") or ""), "price": price, "url": str(p.get("url") or ""), "jan": "",
                            "campaign_conditions": self.price_note,
                            "model": m.group(1), "availability": AVAIL_IN_STOCK if av.endswith("InStock") else
                            AVAIL_OUT if av.endswith(("OutOfStock", "Discontinued", "SoldOut")) else AVAIL_UNKNOWN})
        return out


class SonyStoreAdapter(RetailAdapter):
    """ソニーストアの購入ページ（型番ごとに1ページ）。「<型番> <在庫の表示> <価格> 円(税込)」の並び。JAN がページに1種類だけある。

    一覧に価格が無いので商品ごとに取る（取得数に上限）。色違いの型番（ILCE-7CR/S など）は URL の規則が違うので扱わない。
    在庫の語は 翌日出荷・当日出荷・在庫あり = 在庫あり、入荷待ち・在庫切れ・販売終了 = 在庫なし。
    """

    adapter_id = "sony_store"
    retailer = "ソニーストア"
    brands = ("sony",)
    source_id = "src_sony_store"
    per_item = True
    MAX_ITEMS = 4

    def supports(self, identity: dict) -> bool:
        """型番（ILCE-… / ILME-…）が名前に1つだけあるときだけ（PlayStation・Xperia など型番の無い Sony 製品は引けない）。"""
        return super().supports(identity) and bool(self.item_key(identity))
    _MODEL = re.compile(r"\b(IL(?:CE|ME)-[0-9A-Z]{2,8})\b")
    _STOCK_IN = ("翌日出荷", "当日出荷", "在庫あり")
    _STOCK_OUT = ("入荷待ち", "在庫切れ", "販売終了")

    def item_key(self, identity: dict) -> str:
        """型番（ILCE-… / ILME-…）が名前に1つだけあるときの型番。無い・複数・色違いの表記は空。"""
        found = sorted(set(self._MODEL.findall(str(identity.get("name") or "").upper())))
        return found[0] if len(found) == 1 else ""

    def item_url(self, key: str) -> str:
        return f"https://pur.store.sony.jp/ichigan/products/{key}/{key}_purchase/"

    def parse_item(self, html: str, key: str) -> list[dict]:
        t = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", html or "", flags=re.S))))
        words = "|".join(self._STOCK_IN + self._STOCK_OUT)
        ms = list(re.finditer(re.escape(key) + r"\s+(" + words + r")\s*([\d,]{4,})\s*円\s*\(税込\)", t))
        if len({(m.group(1), m.group(2)) for m in ms}) != 1:
            return []                                                     # 並びが無い・複数（どれがこの商品か決められない）は読まない
        jans = set(re.findall(r"(?<!\d)(45\d{11})(?!\d)", html or ""))
        if len(jans) != 1:
            return []                                                     # JAN が1種類に決まらないページは、同一性の根拠にしない
        m = ms[0]
        return [{"name": key, "price": _int(m.group(2)), "url": self.item_url(key), "jan": jans.pop(), "model": key,
                 "availability": AVAIL_IN_STOCK if m.group(1) in self._STOCK_IN else AVAIL_OUT}]


class AppleStoreAdapter(RetailAdapter):
    """Apple 公式（apple.com/jp/shop/buy-iphone/<機種>）の機種のページ。商品データの部品番号（MYMX3J/A など）ごとの現行の価格。

    Apple 公式は直販の定価（クーポン・ポイントの値引きの表示なし）。部品番号の完全一致だけ（買取店の名前に部品番号がある行）。
    在庫は機種のページに無いので UNKNOWN（在庫ありにしない）。現行の販売ページに載らない旧機種は NO_MATCH（引けなかった）。
    """

    adapter_id = "apple_jp"
    retailer = "Apple（公式）"
    brands = ("apple",)
    source_id = "src_apple_jp"
    FAMILIES = ("iphone-18-pro", "iphone-duo", "iphone-17", "iphone-17e", "iphone-air", "iphone-16")
    INDEX_URLS = tuple(f"https://www.apple.com/jp/shop/buy-iphone/{f}" for f in FAMILIES)

    def parse_index(self, html: str, url: str = "") -> list[dict]:
        from src.discovery.apple import parse_products
        return [{"name": p["name"], "price": p["price"], "url": url, "jan": "", "model": p["part_number"],
                 "availability": AVAIL_UNKNOWN} for p in parse_products(html)]


class CanonStoreAdapter(RetailAdapter):
    """キヤノンオンラインショップ（store.canon.jp）の購入ページ。商品コードごとに1ページ（JAN は購入ページに無い）。

    JAN → 商品コードは、公式の製品ページで確かめた表（config/canon_codes.yaml）だけで引く（許可リスト方式。表に無いコード・整備済みの別コード・
    発売前・販売終了は取らない）。価格は購入ページの構造化データ（Product.offers.price。税込の現金）。構造化データが無いページは
    本文の「ご注文概要 価格」で読む。在庫は納期の文言から作らない（UNKNOWN）。送料は購入ページ・ご利用案内の文言（別の台帳）。
    """

    adapter_id = "canon_store"
    retailer = "キヤノンオンラインショップ"
    brands = ("canon",)
    source_id = "src_canon_official"
    per_item = True
    MAX_ITEMS = 5
    _table: dict | None = None

    @classmethod
    def table(cls) -> dict:
        """JAN → {code, model, kind}。表が読めなければ空（何も引かない）。"""
        if cls._table is None:
            import yaml
            from pathlib import Path
            try:
                doc = yaml.safe_load((Path(__file__).resolve().parent.parent.parent / "config" / "canon_codes.yaml").read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                doc = {}
            cls._table = {str(i["jan"]): i for i in doc.get("items") or []
                          if isinstance(i, dict) and re.fullmatch(r"\d{13}", str(i.get("jan") or "")) and re.fullmatch(r"[0-9A-Z]{8}", str(i.get("code") or ""))}
        return cls._table

    def item_key(self, identity: dict) -> str:
        if identity.get("basis") != "JAN":
            return ""
        row = self.table().get(str(identity.get("value") or ""))
        return row["code"] if row else ""

    def supports(self, identity: dict) -> bool:
        return super().supports(identity) and bool(self.item_key(identity))

    def item_url(self, key: str) -> str:
        return f"https://store.canon.jp/online/g/g{key}/"

    def parse_item(self, html: str, key: str) -> list[dict]:
        import json
        row = next((r for r in self.table().values() if r["code"] == key), None)
        if not row or key not in (html or ""):
            return []
        if re.search(r"販売を?終了|予約受付を?終了|生産終了", re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>", " ", html or "", flags=re.S))):
            return []                                   # 販売終了のページの価格は、仕入れ値にしない
        price = None
        for b in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html or "", re.S):
            try:
                d = json.loads(b)
            except ValueError:
                continue
            for prod in (d if isinstance(d, list) else [d]):
                offers = prod.get("offers") if isinstance(prod, dict) else None
                for o in (offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []):
                    if f"/g{key}/" in str(o.get("url") or ""):
                        price = _int(o.get("price")) or price
        if price is None:                       # 構造化データが無いページ（本文の「ご注文概要 価格 111,100 円(税込)」）
            t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", html or "", flags=re.S)))
            ms = {m for m in re.findall(r"ご注文概要\s*価格\s*([\d,]{4,})\s*円\s*\(税込\)", t)}
            price = _int(next(iter(ms))) if len(ms) == 1 else None
        if not price:
            return []
        return [{"name": row.get("model", ""), "price": price, "url": self.item_url(key), "jan": str(row["jan"]), "model": key,
                 "availability": AVAIL_UNKNOWN}]


ADAPTERS: tuple = (NikonDirectAdapter(), SonyStoreAdapter(), SamsungAdapter(), AppleStoreAdapter(), CanonStoreAdapter())


def ready_for_triage(identity: dict, adapters=ADAPTERS) -> bool:
    """選別で「小売の価格を引ける見込み」と数えてよいか。一覧を取る取得器（1回の取得で全商品を引ける）だけ。
    商品ごとのページを取る取得器（Sony）は、取得数に上限があり引けるとは限らないので数えない（引けたときに初めて HIGH）。"""
    ad = adapter_for(identity, adapters)
    return ad is not None and not getattr(ad, "per_item", False)


def adapter_for(identity: dict, adapters=ADAPTERS):
    for a in adapters:
        if a.supports(identity):
            return a
    return None


def match_identity(identity: dict, entries: list[dict]) -> tuple[list[dict], str]:
    """識別子の完全一致だけで、一覧の行を探す。(一致した行, 理由)。名前の一致は使わない。

    JAN: 13 桁の完全一致。MODEL_CODE: 型番の完全一致（空白・大文字小文字だけ無視）。PART_NUMBER: 部品番号の完全一致。
    """
    basis, value = identity.get("basis"), identity.get("value")
    if basis == "JAN":
        v = str(value or "").strip()
        hits = [e for e in entries if e.get("jan") == v]
        part = _norm_code(identity.get("part_number"))
        if not hits and part:          # 一覧に JAN が無い取得元（Apple）は、同じ行の部品番号の完全一致で引く
            return [e for e in entries if _norm_code(e.get("model")) == part], "part_exact"
        return hits, "jan_exact"
    if basis in ("MODEL_CODE", "PART_NUMBER"):
        v = _norm_code(value)
        return [e for e in entries if v and _norm_code(e.get("model")) == v], "model_exact"
    return [], "no_exact_identity"


def _lookup_one(ad, identity: dict, indexes: dict) -> dict:
    base = {"status": UNSUPPORTED, "retailer": ad.retailer, "source_type": getattr(ad, "source_type", OFFICIAL_DIRECT),
            "product_url": "", "price": None, "availability_state": AVAIL_UNKNOWN, "observed_at": "", "identity_evidence": {}}
    idx = indexes.get(ad.adapter_id)
    if not idx or not idx.get("observed_at") or (not idx.get("entries") and not idx.get("covered")):
        return base
    if getattr(ad, "per_item", False):
        key = ad.item_key(identity)
        if not key or key not in (idx.get("covered") or ()):
            return base                                                   # この実行で取っていない商品は、引けなかった（NO_MATCH にしない）
    base["observed_at"] = idx["observed_at"]
    hits, how = match_identity(identity, idx["entries"])
    if not hits:
        return {**base, "status": NO_MATCH, "identity_evidence": {"basis": identity.get("basis"), "method": how}}
    if len({(h.get("url"), h.get("price")) for h in hits}) != 1:
        return {**base, "status": AMBIGUOUS, "identity_evidence": {"basis": identity.get("basis"), "method": how, "hits": len(hits)}}
    h = hits[0]
    ev = {"basis": identity.get("basis"), "value": identity.get("value"), "method": how, "matched_name": h.get("name", "")}
    # ブランドが一致しない行（たとえば型番が別メーカーの商品に偶然一致）は一致にしない
    if brand_of(h.get("name", "")) not in ("", *ad.brands):
        return {**base, "status": IDENTITY_MISMATCH, "identity_evidence": ev}
    pe = price_evidence(h)
    res = {**base, "product_url": h.get("url", ""), "price": pe["effective_price"], "availability_state": h.get("availability") or AVAIL_UNKNOWN,
           "identity_evidence": ev, **{k: v for k, v in pe.items() if k != "effective_price"}, "effective_price": pe["effective_price"],
           "condition": h.get("condition") or "new"}
    res["price_caveat"] = "; ".join(filter(None, [res["campaign_conditions"], *res["price_conditions"]]))
    if res["availability_state"] == AVAIL_OUT or not pe["effective_price"]:
        res["status"] = NOT_PURCHASABLE          # 在庫なし・販売終了・価格が読めない行は、仕入れ値に使わない
        return res
    res["status"] = MATCHED
    return res


_RANK = {MATCHED: 0, NOT_PURCHASABLE: 1, AMBIGUOUS: 2, IDENTITY_MISMATCH: 3, NO_MATCH: 4, UNSUPPORTED: 5}


def lookup(identity: dict, indexes: dict, adapters=ADAPTERS) -> dict:
    """1件の識別を、取得済みの一覧（indexes: adapter_id → {"entries": [...], "observed_at": ISO}）から引く。

    対応する取得器が複数あれば全部で引き、MATCHED のうち現金の仕入れ値（effective_price）が最も安いものを返す（条件つきの値引きを
    使った価格を、条件なしの価格より優先しない）。他の取得元の一致は alternatives に残す。
    indexes に無い取得器（取得に失敗した・遮断された）は UNSUPPORTED にする（古い価格を使わない）。
    """
    cands = [a for a in adapters if a.supports(identity)]
    if not cands:
        return {"status": UNSUPPORTED, "retailer": "", "source_type": "", "product_url": "", "price": None,
                "availability_state": AVAIL_UNKNOWN, "observed_at": "", "identity_evidence": {}}
    results = [_lookup_one(a, identity, indexes) for a in cands]
    # 条件なしの価格を、条件つき（通常価格が不明を最後）の安い価格より先にする。同じ条件なら現金の仕入れ値が安いもの
    _basis = {BASIS_UNCONDITIONAL: 0, BASIS_REGULAR: 1, BASIS_CONDITIONAL_UNKNOWN: 2}
    results.sort(key=lambda r: (_RANK[r["status"]], _basis.get(r.get("price_basis"), 3), r["price"] if r["price"] is not None else 10**12))
    best = dict(results[0])
    alts = [{"retailer": r["retailer"], "source_type": r["source_type"], "price": r["price"], "status": r["status"]}
            for r in results[1:] if r["status"] in (MATCHED, NOT_PURCHASABLE)]
    if alts:
        best["alternatives"] = alts
    return best


def build_item_index(ad, keys, fetch, now: datetime) -> dict:
    """商品ごとのページを取る取得器（Sony など）の indexes。keys のうち上限まで。取れた・読めた型番を covered に入れる。

    遮断（fetch が html なしを返し、理由が遮断）されたら、残りは取らない（回避しない）。取得に失敗した型番は covered に入れない。
    """
    entries, covered = [], []
    for key in list(dict.fromkeys(keys))[:getattr(ad, "MAX_ITEMS", 4)]:
        html, err = fetch(ad.item_url(key))
        if not html:
            if err in _cutoff_reasons():
                break
            continue
        covered.append(key)
        entries.extend(ad.parse_item(html, key))
    if not covered:
        return {}
    return {"entries": entries, "covered": covered, "observed_at": now.isoformat(timespec="seconds"), "retailer": ad.retailer}


def build_indexes(adapters, fetch, now: datetime) -> dict:
    """各取得器の一覧を取得して indexes を作る（fetch(url) -> (html|None, err)。polite を通す呼び出し側が渡す）。

    遮断・取得失敗の一覧が1つでもあれば、その取得器の indexes は作らない（途中の一覧だけで引くと、載っているはずの商品が
    NO_MATCH になるため）。遮断された取得器は、その実行では取りに行かない。
    """
    out: dict = {}
    for ad in adapters:
        if getattr(ad, "per_item", False):
            continue                       # 商品ごとのページは build_item_index（取得数に上限）
        entries, ok = [], True
        for url in ad.INDEX_URLS:
            html, err = fetch(url)
            if not html:
                ok = False
                break
            entries.extend(ad.parse_index(html, url))
        if ok and entries:
            out[ad.adapter_id] = {"entries": entries, "observed_at": now.isoformat(timespec="seconds"), "retailer": ad.retailer}
    return out


def _cutoff_reasons() -> frozenset:
    """遮断・規約上の拒否の理由（polite の CUTOFF_IMMEDIATE。403・429・robots 禁止など）。これを受けた取得元は、その実行で取りに行かない。"""
    from src.collectors.polite import CUTOFF_IMMEDIATE
    return CUTOFF_IMMEDIATE | {"blocked"}


def run_lookups(unmatched_candidates: list[dict], now: datetime, fetch, adapters=ADAPTERS) -> dict:
    """買取起点の候補（rank_product_candidates の行）の小売の価格を、実際に取得して照会する。戻りは保存用の記録。

    1. 選別（triage）で上位 50 件の待ち行列を作る（小売の取得器に対応する商品を優先）
    2. 一覧を取る取得器（ニコン・Samsung）は、対応する商品が HIGH / MEDIUM にあるときだけ一覧を取る
    3. 商品ごとのページを取る取得器（ソニー）は、待ち行列の順に、型番が重複しない最大 MAX_ITEMS 件だけ取る
    4. 全候補を、取得できた一覧・ページから引く。取得できなかった取得器は UNSUPPORTED（古い価格を使わない）

    fetch(url) -> (html|None, reason)。呼び出し側が polite 経由のものを渡す。遮断された取得元は、その実行では取りに行かない。
    """
    from src.research import triage as tr
    tri = tr.triage(unmatched_candidates, now, lookup_ready_of=lambda c: ready_for_triage({"name": c.get("name", "")}, adapters))
    wanted_index, item_keys = set(), {}
    for r in tri["rows"]:
        if r["triage"]["tier"] not in (tr.HIGH, tr.MEDIUM):
            continue
        ad = adapter_for(_identity_of(r), adapters)
        if ad is not None and not getattr(ad, "per_item", False):
            wanted_index.add(ad.adapter_id)
    for r in tri["queue"]:
        ident = _identity_of(r)
        ad = adapter_for(ident, adapters)
        if ad is not None and getattr(ad, "per_item", False):
            k = ad.item_key(ident)
            if k:
                item_keys.setdefault(ad.adapter_id, []).append(k)
    indexes = build_indexes([a for a in adapters if a.adapter_id in wanted_index], fetch, now)
    for a in adapters:
        if getattr(a, "per_item", False) and item_keys.get(a.adapter_id):
            idx = build_item_index(a, item_keys[a.adapter_id], fetch, now)
            if idx:
                indexes[a.adapter_id] = idx
    results, counts = {}, {}
    for c in unmatched_candidates:
        res = lookup(_identity_of(c), indexes, adapters)
        counts[res["status"]] = counts.get(res["status"], 0) + 1
        if res["status"] != UNSUPPORTED:
            results[c["candidate_id"]] = res
    return {"schema": 1, "generated_at": now.isoformat(timespec="seconds"), "lookups": results, "status_counts": counts,
            "fetched_adapters": sorted(indexes), "index_sizes": {k: len(v.get("entries") or []) for k, v in indexes.items()},
            "queue_size": tri["stats"]["top_queue"]}


def _identity_of(c: dict) -> dict:
    """候補（rank_product_candidates の行）の識別: 基準（JAN・部品番号・型番）・値・名前・名前の部品番号。"""
    return {"basis": c.get("identity_basis"), "value": _identity_value(c), "name": c.get("name", ""), "part_number": _part_of(c)}


def _identity_value(c: dict) -> str:
    """候補の識別子の値。JAN は candidate の jan、型番・部品番号は名前から取り直さず rank 時の値（identity_value）を使う。"""
    if c.get("identity_basis") == "JAN":
        return str(c.get("jan") or "")
    return str(c.get("identity_value") or "")


_PART = re.compile(r"\b[A-Z0-9]{4,5}J/A\b")


def _part_of(c: dict) -> str:
    """名前に部品番号（メーカーの型番 ○○J/A）が1つだけあるときの値（Apple）。無い・複数は空。"""
    found = sorted(set(_PART.findall(str(c.get("name") or ""))))
    return found[0] if len(found) == 1 else ""
