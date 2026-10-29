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


class SofmapAdapter(RetailAdapter):
    """ソフマップ（www.sofmap.com・新品）の詳細ページ。**人が確かめた JAN ↔ sku の固定登録（config/sofmap_products.yaml）だけ**を取る。

    詳細ページは静的で、JSON-LD の価格（現金・税込）・在庫、本文の JAN・ソフマップポイント・お一人様の制限が分けて読める。一覧から発見できず、
    JAN → sku の規則も無いので、検索結果・一覧・推測した URL は使わない。ポイントは現金から引かない（points）。「お一人様」の制限は数量限定
    （条件）。中古は対象外。販売終了・在庫切れ（OutOfStock）の価格は仕入れ値に使わない。送料は「送料無料キャンペーン」の表示が条件つきなので、ここでは読まない。
    """

    adapter_id = "sofmap_new"
    retailer = "ソフマップ"
    source_type = LARGE_RETAILER
    brands = tuple(b for b, _rx in _BRAND_RES)
    source_id = "src_sofmap"
    per_item = True
    MAX_ITEMS = 3
    _table: dict | None = None

    @classmethod
    def table(cls) -> dict:
        if cls._table is None:
            import yaml
            from pathlib import Path
            try:
                doc = yaml.safe_load((Path(__file__).resolve().parent.parent.parent / "config" / "sofmap_products.yaml").read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                doc = {}
            cls._table = {str(i["jan"]): i for i in doc.get("items") or []
                          if isinstance(i, dict) and re.fullmatch(r"\d{13}", str(i.get("jan") or "")) and re.fullmatch(r"\d{5,12}", str(i.get("sku") or ""))}
        return cls._table

    def item_key(self, identity: dict) -> str:
        if identity.get("basis") != "JAN":
            return ""
        row = self.table().get(str(identity.get("value") or ""))
        return str(row["sku"]) if row else ""

    def supports(self, identity: dict) -> bool:
        return super().supports(identity) and bool(self.item_key(identity))

    def item_url(self, key: str) -> str:
        return f"https://www.sofmap.com/product_detail.aspx?sku={key}"

    def parse_item(self, html: str, key: str) -> list[dict]:
        import json
        row = next((r for r in self.table().values() if str(r["sku"]) == key), None)
        if not row or not html:
            return []
        text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", html, flags=re.S))))
        jans = set(re.findall(r"JANコード\s*(\d{13})", text))
        if jans != {str(row["jan"])}:
            return []                                          # ページの JAN が表と違う・決まらない（別の商品）
        offer = None
        name = ""
        for b in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S):
            try:
                d = json.loads(b)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("@type") == "Product" and str(d.get("sku")) == key:
                offer, name = d.get("offers") if isinstance(d.get("offers"), dict) else None, str(d.get("name") or "")
        if not offer or "中古" in name:
            return []                                          # sku が違う・構造化データが無い・中古
        price = _int(offer.get("price"))
        av = str(offer.get("availability") or "")
        pt = re.search(r"ソフマップポイント\s*([\d,]+)\s*ポイント", text)
        return [{"name": name or row.get("name", ""), "price": price, "url": offer.get("url") or self.item_url(key), "jan": str(row["jan"]),
                 "model": str(row.get("model") or ""), "points": _int(pt.group(1)) if pt else 0,
                 "limited_quantity": "お一人様" in text,
                 "availability": AVAIL_IN_STOCK if av.endswith("InStock") else AVAIL_OUT if av.endswith(("OutOfStock", "Discontinued", "SoldOut")) else AVAIL_UNKNOWN}]


ADAPTERS: tuple = (NikonDirectAdapter(), SonyStoreAdapter(), SamsungAdapter(), AppleStoreAdapter(), CanonStoreAdapter(), SofmapAdapter())


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
    if how == "part_exact":
        # 部品番号の一致に、容量・世代（機種の行）の一致を結び付ける（買取店の名前と公式の商品名の両方が読めて同じときだけ確認済み）。
        # 両方読めて違えば別の商品（部品番号と名前が食い違う行）なので一致にしない。読めなければ確認済みにしない（部分的な識別のまま）
        attrs = _apple_attributes(identity.get("name", ""), h.get("name", ""))
        if attrs["status"] == "MISMATCH":
            return {**base, "status": IDENTITY_MISMATCH, "identity_evidence": {**ev, **attrs}}
        ev.update(attrs)
        ev["attributes_verified"] = attrs["status"] == "MATCH"
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


def _apple_attributes(row_name: str, official_name: str) -> dict:
    """買取店の商品名と Apple 公式の商品名から、機種の行（世代・種類）と容量を読んで比べる。色は記録だけ（表記が違うので条件にしない）。"""
    from src.discovery.apple import parse_name
    a, b = parse_name(re.sub(r"^[【\[][^】\]]{0,12}[】\]]\s*", "", str(row_name or ""))), parse_name(official_name)
    if not a or not b:
        return {"status": "UNREADABLE"}
    same = a["line_key"] == b["line_key"] and a["capacity"] == b["capacity"]
    return {"status": "MATCH" if same else "MISMATCH", "line": b["line"], "capacity": b["capacity"], "official_color": b.get("color", "")}


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
    alts = [{"retailer": r["retailer"], "source_type": r["source_type"], "price": r["price"], "status": r["status"],
             "availability": r.get("availability_state") or AVAIL_UNKNOWN}
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


HTTP_BUDGET = 24         # 1 回の実行で照会のために取る小売のページの総数（上限。ブランド枠を作っても無制限に取らない）
ITEM_MIN = 3             # 商品ごとにページを取る取得器（Sony・Canon）の最低の取得枠（対象があれば、他のブランドがどれだけ多くても取る）


def allocate_budget(plans: list[dict], budget: int = HTTP_BUDGET) -> dict:
    """取得器ごとの取得枠を決める（ブランドの公平な配分）。戻りは {adapter_id: {"index": bool, "keys": [...], "http": n}}。

    plans の各要素: {"adapter_id", "kind": "index"|"item", "cost": 一覧のページ数（index）, "keys": [(key, score)]（item。点の高い順）,
                    "min_items": 最低枠, "cap": 上限, "score": 取得器の点（index の優先順）}。
    1. まず全取得器に最低枠を渡す（item は min_items 件、index は一覧の全ページ。予算が足りなければ点の低い index から外す）
    2. 余った予算を、item の残りのキーに点の高い順で配る（取得器ごとの上限 cap まで）
    どのブランドも、対象があれば最低枠だけは取る（Apple の候補が 100 件あっても Sony・Canon が飢えない）。総数は budget を超えない。
    """
    left = int(budget)
    out = {p["adapter_id"]: {"index": False, "keys": [], "http": 0} for p in plans}
    # 1. 最低枠（item は点の高い取得器から。index は点の高い順に、全ページ取れるときだけ）
    for p in sorted(plans, key=lambda p: -float(p.get("score") or 0)):
        if p["kind"] == "index":
            if p["cost"] <= left:
                out[p["adapter_id"]].update({"index": True, "http": p["cost"]})
                left -= p["cost"]
    items = sorted((p for p in plans if p["kind"] == "item"), key=lambda p: -float(p.get("score") or 0))
    for step in (1, None):                 # まず全ブランドに 1 件ずつ、次に最低枠（min_items）まで。予算が少なくても、どのブランドも 1 件は取る
        for p in items:
            if not p["keys"]:
                continue                       # 対象が無い取得器に枠を使わない
            have = len(out[p["adapter_id"]]["keys"])
            want = min(int(p.get("min_items") or 0), int(p.get("cap") or 0), len(p["keys"]))
            n = min((1 if step else want) - have, left) if step else min(want - have, left)
            if n > 0 and (step is None or have == 0):
                out[p["adapter_id"]]["keys"] += [k for k, _s in p["keys"][have:have + n]]
                out[p["adapter_id"]]["http"] += n
                left -= n
    # 2. 余りを、点の高い順に配る
    spare = sorted(((sc, p["adapter_id"], k) for p in plans if p["kind"] == "item"
                    for k, sc in p["keys"][len(out[p["adapter_id"]]["keys"]):int(p.get("cap") or 0)]), key=lambda x: (-x[0], x[1], x[2]))
    for sc, aid, k in spare:
        if left <= 0:
            break
        out[aid]["keys"].append(k)
        out[aid]["http"] += 1
        left -= 1
    return out


class RunFetchCache:
    """同一実行（このプロセス）の中だけで、同じ URL を二度取りに行かないための薄い包み（Coverage Wave 5 Stage S）。

    - 保存はメモリだけ（ファイル・次回の実行に残さない）。結果（本文・理由）は取得した時のまま返し、取得時刻を新しくしない
    - 失敗（遮断・タイムアウト）も同じ実行の中では繰り返さない（遮断された後に同じ URL を取り直さない）
    - 別の実行・別の日の値は使わない（鮮度を偽らない）
    """

    def __init__(self, fetch):
        import threading
        self._fetch = fetch
        self._mem: dict[str, tuple] = {}
        self._lock = threading.Lock()
        self.requests = 0
        self.hits = 0

    def __call__(self, url: str):
        with self._lock:
            if url in self._mem:
                self.hits += 1
                return self._mem[url]
        res = self._fetch(url)
        with self._lock:
            self.requests += 1
            self._mem[url] = res
        return res


def _fetch_all(tasks: dict, fetch) -> dict:
    """取得器ごとの取得（別のドメイン）を並列に行う。同じドメインへは取得器の中で順に取る（間隔は polite が守る）。
    tasks: {adapter_id: callable(fetch) -> index|dict}。戻りは {adapter_id: 結果}（失敗した取得器は {}）。"""
    from concurrent.futures import ThreadPoolExecutor
    out: dict = {}
    if not tasks:
        return out
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futs = {aid: ex.submit(fn, fetch) for aid, fn in sorted(tasks.items())}
        for aid, f in futs.items():
            try:
                out[aid] = f.result() or {}
            except Exception as exc:  # noqa: BLE001 - 1 つの取得器の失敗で他を止めない（その取得器は UNSUPPORTED になる）
                import logging
                logging.getLogger(__name__).warning("retail lookup adapter failed: %s (%s)", aid, type(exc).__name__)   # 型名だけ（値は出さない）
                out[aid] = {}
    return out


def run_lookups(unmatched_candidates: list[dict], now: datetime, fetch, adapters=ADAPTERS, budget: int = HTTP_BUDGET) -> dict:
    """買取起点の候補（rank_product_candidates の行）の小売の価格を、実際に取得して照会する。戻りは保存用の記録。

    1. 選別（triage）で、候補ごとの点・段階を決める（REJECTED は照会しない）
    2. 一覧を取る取得器（ニコン・Samsung・Apple）は、対応する商品が HIGH / MEDIUM にあるときだけ一覧を取る
    3. 商品ごとにページを取る取得器（ソニー・Canon）は、**待ち行列ではなく全候補**から、取得器ごとに点の高い順の型番（重複なし）を選ぶ
    4. 取得枠は allocate_budget で公平に配る（最低枠を保証・総数は budget まで）
    5. 全候補を、取得できた一覧・ページから引く。取得できなかった取得器は UNSUPPORTED（古い価格を使わない）

    fetch(url) -> (html|None, reason)。呼び出し側が polite 経由のものを渡す。遮断された取得元は、その実行では取りに行かない。
    """
    from src.research import triage as tr
    tri = tr.triage(unmatched_candidates, now, lookup_ready_of=lambda c: ready_for_triage({"name": c.get("name", "")}, adapters))
    plans: dict[str, dict] = {}
    supported: dict[str, int] = {}
    for r in sorted((x for x in tri["rows"] if x["triage"]["tier"] != tr.REJECTED),
                    key=lambda x: (-x["triage"]["score"], -int(x.get("observed_sell_price") or 0), x.get("candidate_id", ""))):
        ident = _identity_of(r)
        ad = adapter_for(ident, adapters)
        if ad is None:
            continue
        supported[ad.adapter_id] = supported.get(ad.adapter_id, 0) + 1
        top = r["triage"]["tier"] in (tr.HIGH, tr.MEDIUM)
        if getattr(ad, "per_item", False):
            k = ad.item_key(ident)
            pl = plans.setdefault(ad.adapter_id, {"adapter_id": ad.adapter_id, "kind": "item", "keys": [], "min_items": ITEM_MIN,
                                                  "cap": getattr(ad, "MAX_ITEMS", 4), "score": 0})
            if k and k not in [x for x, _s in pl["keys"]]:
                pl["keys"].append((k, r["triage"]["score"]))
                pl["score"] = max(pl["score"], r["triage"]["score"])
        elif top:
            pl = plans.setdefault(ad.adapter_id, {"adapter_id": ad.adapter_id, "kind": "index", "cost": len(ad.INDEX_URLS), "score": 0})
            pl["score"] = max(pl["score"], r["triage"]["score"])
    alloc = allocate_budget(list(plans.values()), budget)
    by_id = {a.adapter_id: a for a in adapters}
    # 同一実行の中の同じ URL は二度取らない。取得器（= ドメイン）ごとに並列で取る（同じドメインへの間隔は fetch の中の polite が守る）
    fetch = fetch if isinstance(fetch, RunFetchCache) else RunFetchCache(fetch)
    tasks = {}
    for aid, a in alloc.items():
        if a["index"]:
            tasks[aid] = (lambda f, _ad=by_id[aid]: build_indexes([_ad], f, now).get(_ad.adapter_id) or {})
        elif a["keys"]:
            tasks[aid] = (lambda f, _ad=by_id[aid], _k=list(a["keys"]): build_item_index(_ad, _k, f, now))
    indexes = {aid: idx for aid, idx in _fetch_all(tasks, fetch).items() if idx}
    results, counts = {}, {}
    per: dict[str, dict] = {aid: {"supported": n, "requested": 0, "fetched": 0, "matched": 0, "no_match": 0}
                            for aid, n in supported.items()}
    for aid, a in alloc.items():
        per[aid]["requested"] = a["http"]
        per[aid]["fetched"] = (len(by_id[aid].INDEX_URLS) if a["index"] and aid in indexes else
                               len((indexes.get(aid) or {}).get("covered") or []))
    for c in unmatched_candidates:
        ident = _identity_of(c)
        res = lookup(ident, indexes, adapters)
        counts[res["status"]] = counts.get(res["status"], 0) + 1
        if res["status"] != UNSUPPORTED:
            results[c["candidate_id"]] = res
        ad = adapter_for(ident, adapters)
        if ad is not None and ad.adapter_id in per and res["status"] in (MATCHED, NO_MATCH):
            per[ad.adapter_id]["matched" if res["status"] == MATCHED else "no_match"] += 1
    return {"schema": 1, "generated_at": now.isoformat(timespec="seconds"), "lookups": results, "status_counts": counts,
            "fetched_adapters": sorted(indexes), "index_sizes": {k: len(v.get("entries") or []) for k, v in indexes.items()},
            "queue_size": tri["stats"]["top_queue"], "adapter_stats": per,
            "http_requested": sum(a["http"] for a in alloc.values()), "http_budget": int(budget),
            "http_actual": fetch.requests, "http_cache_hits": fetch.hits,
            "api_sources": api_source_statuses()}


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


# ── 仕入れ元の API（Coverage Wave 4 Stage G）──────────────────────────────────────────────────
# 量販店・EC はほぼ静的取得できない。検索結果のスクレイピングはしない（公式 API だけ）。API の鍵（Secrets）が無ければ
# PENDING_USER_CONFIGURATION として止める（取りに行かない・代わりのスクレイピングをしない）。
RETAIL_API_SOURCES = (
    {"id": "yahoo_shopping_v3", "name": "Yahoo!ショッピング 商品検索 API v3", "source_type": EC_RETAILER, "required_env": ("YAHOO_SHOPPING_APP_ID",),
     "enable_env": "ENABLE_YAHOO_API", "jan_lookup": "supported",
     "docs": "https://developer.yahoo.co.jp/webapi/shopping/v3/itemsearch.html",
     "note": "JAN で商品を引ける（jan_code）。アプリケーション ID（appid）が必須。ポイント・クーポンは現金と分けて読む。利用規約の保存・再配布の条件を確認してから"},
    {"id": "rakuten_ichiba_item_search", "name": "楽天市場商品検索 API", "source_type": EC_RETAILER, "required_env": ("RAKUTEN_APP_ID",),
     "enable_env": "ENABLE_RAKUTEN_API", "jan_lookup": "unverified",
     "docs": "https://webservice.rakuten.co.jp/documentation/ichiba-item-search",
     "note": "アプリケーション ID（と新しいエンドポイントではアクセスキー）が必要。JAN 指定の可否・保存の条件は公式の仕様で未確認（確認してから実装）"},
)
API_PENDING, API_DISABLED, API_READY = "PENDING_USER_CONFIGURATION", "KILL_SWITCH_OFF", "READY_NOT_IMPLEMENTED"


def api_source_statuses(env=None) -> list[dict]:
    """仕入れ元 API の状態（鍵の値は読まない・出さない。存在の有無だけ）。鍵が無ければ PENDING_USER_CONFIGURATION。"""
    import os
    env = os.environ if env is None else env
    out = []
    for a in RETAIL_API_SOURCES:
        has_keys = all(bool(str(env.get(k) or "").strip()) for k in a["required_env"])
        enabled = str(env.get(a["enable_env"]) or "").strip().lower() in ("1", "true", "yes", "on")
        out.append({"id": a["id"], "source_type": a["source_type"], "jan_lookup": a["jan_lookup"], "docs": a["docs"],
                    "status": API_PENDING if not has_keys else (API_DISABLED if not enabled else API_READY)})
    return out
