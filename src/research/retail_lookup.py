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


ADAPTERS: tuple = (NikonDirectAdapter(), SonyStoreAdapter(), SamsungAdapter())


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
        return [e for e in entries if e.get("jan") == v], "jan_exact"
    if basis in ("MODEL_CODE", "PART_NUMBER"):
        v = _norm_code(value)
        return [e for e in entries if v and _norm_code(e.get("model")) == v], "model_exact"
    return [], "no_exact_identity"


def lookup(identity: dict, indexes: dict, adapters=ADAPTERS) -> dict:
    """1件の識別を、取得済みの一覧（indexes: adapter_id → {"entries": [...], "observed_at": ISO}）から引く。

    indexes に無い取得器（取得に失敗した・遮断された）は UNSUPPORTED にする（古い価格を使わない）。
    """
    base = {"status": UNSUPPORTED, "retailer": "", "product_url": "", "price": None, "availability_state": AVAIL_UNKNOWN,
            "observed_at": "", "identity_evidence": {}}
    ad = adapter_for(identity, adapters)
    if ad is None:
        return base
    base["retailer"] = ad.retailer
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
    res = {**base, "product_url": h.get("url", ""), "price": h.get("price"), "price_caveat": getattr(ad, "price_note", ""),
           "availability_state": h.get("availability") or AVAIL_UNKNOWN, "identity_evidence": ev}
    if res["availability_state"] == AVAIL_OUT:
        res["status"] = NOT_PURCHASABLE          # 在庫なし・販売終了の価格は、仕入れ値に使わない
        return res
    res["status"] = MATCHED
    return res


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
        ad = adapter_for({"name": r.get("name", "")}, adapters)
        if ad is not None and not getattr(ad, "per_item", False):
            wanted_index.add(ad.adapter_id)
    for r in tri["queue"]:
        ad = adapter_for({"name": r.get("name", "")}, adapters)
        if ad is not None and getattr(ad, "per_item", False):
            k = ad.item_key({"name": r.get("name", "")})
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
        res = lookup({"basis": c.get("identity_basis"), "value": _identity_value(c), "name": c.get("name", "")}, indexes, adapters)
        counts[res["status"]] = counts.get(res["status"], 0) + 1
        if res["status"] != UNSUPPORTED:
            results[c["candidate_id"]] = res
    return {"schema": 1, "generated_at": now.isoformat(timespec="seconds"), "lookups": results, "status_counts": counts,
            "fetched_adapters": sorted(indexes), "index_sizes": {k: len(v.get("entries") or []) for k, v in indexes.items()},
            "queue_size": tri["stats"]["top_queue"]}


def _identity_value(c: dict) -> str:
    """候補の識別子の値。JAN は candidate の jan、型番・部品番号は名前から取り直さず rank 時の値（identity_value）を使う。"""
    if c.get("identity_basis") == "JAN":
        return str(c.get("jan") or "")
    return str(c.get("identity_value") or "")
