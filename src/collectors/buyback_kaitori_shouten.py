"""買取商店 買取価格コレクター（CSV更新用）。
URL: https://www.kaitorishouten-co.jp/
注: サイト側で 403 Forbidden が返ることが多い。
    取得できた場合のパーサーも実装しているが、失敗時は fetch_failed として記録される。
"""
import re
from typing import Optional
from urllib.parse import urljoin

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# iPhone はカテゴリページ（全容量・全色の表）を使う。まとめページ /keitai は各機種3件しか載せないため
# 512GB が常に「未掲載」になる（2026-10-02 確認: /category/1/710 = iPhone17 Pro、711 = Pro Max）
PRODUCT_URLS = {
    "iphone17pro256":  "https://www.kaitorishouten-co.jp/category/1/710",
    "iphone17pro512":  "https://www.kaitorishouten-co.jp/category/1/710",
    "iphone17pm256":   "https://www.kaitorishouten-co.jp/category/1/711",
    "iphone17pm512":   "https://www.kaitorishouten-co.jp/category/1/711",
    "switch2":         "https://www.kaitorishouten-co.jp/kaden",
    "ps5_pro":         "https://www.kaitorishouten-co.jp/kaden",
    # Phase 11（2026-10-07 確認）: /category/1/708 = iPhone17、689 = iPhone16 Pro。
    # AirPods Pro 第3世代（MFHP4J/A）は /kaden の表に載っている
    "iphone17_256":    "https://www.kaitorishouten-co.jp/category/1/708",
    "iphone16pro256":  "https://www.kaitorishouten-co.jp/category/1/689",
    "airpods_pro3":    "https://www.kaitorishouten-co.jp/kaden",
    # Phase 17（2026-10-08 確認）: カメラの一覧（新品・未開封の買取価格表）。/category/2/368 = デジタルカメラ、
    # /category/2/108 = デジタル一眼カメラ。どちらも1ページに全件（153件・228件）の構造化データ（商品名・JAN・
    # 新品の価格・商品ページの URL）が載る（?pageno= を変えても同じ内容なので、1ページを1回だけ取る）
    "x100vi":          "https://www.kaitorishouten-co.jp/category/2/368",
    "gr4":             "https://www.kaitorishouten-co.jp/category/2/368",
    "gr4_hdf":         "https://www.kaitorishouten-co.jp/category/2/368",
    "gr4_mono":        "https://www.kaitorishouten-co.jp/category/2/368",
    "z8":              "https://www.kaitorishouten-co.jp/category/2/108",
    "r5ii":            "https://www.kaitorishouten-co.jp/category/2/108",
}

# カメラは構造化データ（schema.org の Product）の JAN（gtin13）で1行だけを照合する（Phase 17）。
# 商品名の条件（機種・ボディー/キット・版・色）も満たし、JAN が同じ行が1つの価格だけのときに採用する。
# - x100vi: 色・版で価格が違う（2026-10-08: シルバー 2025版 ¥260,000・シルバー ¥280,000・ブラック 2025版 ¥250,000・
#   ブラック ¥256,000）。公式のフジフイルムモールで買う版（シルバー 2025版。official_registry の IDENTITY_EVIDENCE の
#   colors の JAN）と同じ JAN の行だけを使う（色・版の違う行を同じ商品にしない）
# - z8 / r5ii: ボディーだけ（R5 II のレンズキット 4549292229226 を除く）。JAN は公式の製品ページで確かめた値
# - gr4 系: GR IV・HDF・Monochrome・30周年記念キットを分ける（JAN は店の構造化データの値。商品名でも確かめる）
JAN_RULES = {
    "x100vi":   {"jan": "4547410554281", "pattern": r"FUJIFILM\s?X100VI\s*\[シルバー\]\s*2025版$", "exclude": []},
    # ボディーで終わる名前だけ（「ボディ（中古）」「ボディ FTZ II 同梱」などの状態・同梱の表記を通さない。レビュー M1）
    "z8":       {"jan": "4960759909947", "pattern": r"(?:^|\s)Z\s?8\s*ボディ\s*$",
                 "exclude": ["キット", "kit", "レンズ", "中古", "未使用", "同梱", "セット", "付き"]},
    "r5ii":     {"jan": "4549292229141", "pattern": r"EOS\s?R5\s?Mark\s?II\s*ボディ\s*$",
                 "exclude": ["キット", "kit", "RF", "中古", "未使用", "同梱", "セット", "付き"]},
    "gr4":      {"jan": "4549212311291", "pattern": r"RICOH\s?GR\s?IV$",
                 "exclude": ["HDF", "Monochrome", "Anniversary", "30th", "Kit", "キット", "Edition"]},
    "gr4_hdf":  {"jan": "4549212311871", "pattern": r"RICOH\s?GR\s?IV\s?HDF$",
                 "exclude": ["Monochrome", "Anniversary", "30th", "Kit", "キット", "Edition"]},
    "gr4_mono": {"jan": "4549212311994", "pattern": r"RICOH\s?GR\s?IV\s?Monochrome$",
                 "exclude": ["HDF", "Anniversary", "30th", "Kit", "キット", "Edition"]},
}
_DETAIL_URL = re.compile(r"^https://www\.kaitorishouten-co\.jp/products/detail/\d+$")

# 商品行（<li><a>商品名</a> <span class="num">¥価格</span></li>）の商品名に対する照合ルール。
# 機種・Pro / Pro Max・容量・SIMフリー・セット品の違いを区別する（部分一致で別商品を拾わない）。
# 一覧ページに無い商品（例: 512GB がまとめページに載っていない日）は「未掲載」とし、
# 見出しの「最高¥…」やページ全体の価格では代用しない（2026-10-02 の ¥435,000 / ¥900,000 誤取得の原因）。
ROW_RULES = {
    "iphone17pro256": {"pattern": r"^iPhone\s?17\s?Pro\s+256GB\b", "require": ["SIMフリー"],
                       "exclude": ["Max", "au", "docomo", "ドコモ", "softbank", "ソフトバンク", "楽天"]},
    "iphone17pro512": {"pattern": r"^iPhone\s?17\s?Pro\s+512GB\b", "require": ["SIMフリー"],
                       "exclude": ["Max", "au", "docomo", "ドコモ", "softbank", "ソフトバンク", "楽天"]},
    "iphone17pm256":  {"pattern": r"^iPhone\s?17\s?Pro\s?Max\s+256GB\b", "require": ["SIMフリー"],
                       "exclude": ["au", "docomo", "ドコモ", "softbank", "ソフトバンク", "楽天"]},
    "iphone17pm512":  {"pattern": r"^iPhone\s?17\s?Pro\s?Max\s+512GB\b", "require": ["SIMフリー"],
                       "exclude": ["au", "docomo", "ドコモ", "softbank", "ソフトバンク", "楽天"]},
    # 本体のみ（セット品・ソフトを除く）
    "switch2":        {"pattern": r"^Nintendo\s?Switch\s?2\s*日本語・国内専用$", "require": [],
                       "exclude": ["セット", "Edition", "/Switch 2"]},
    # 型番 CFI-7000 / CFI-7100 系（デジタル・エディション等を除く）
    "ps5_pro":        {"pattern": r"^プレイステーション5\s?Pro\s*\[CFI-7[01]00B01\]", "require": [],
                       "exclude": ["デジタル", "セット"]},
    # 無印 iPhone 17（Pro / Air / 17e を除く）。行の例: 「iPhone 17 256GB ブラック MG674J/A SIMフリー」
    "iphone17_256":   {"pattern": r"^iPhone\s?17\s+256GB\b", "require": ["SIMフリー"],
                       "exclude": ["Pro", "Max", "Air", "au", "docomo", "ドコモ", "softbank", "ソフトバンク", "楽天"]},
    "iphone16pro256": {"pattern": r"^iPhone\s?16\s?Pro\s+256GB\b", "require": ["SIMフリー"],
                       "exclude": ["Max", "au", "docomo", "ドコモ", "softbank", "ソフトバンク", "楽天"]},
    # 型番まで一致するものだけ（第2世代・ケース単体などを拾わない）
    "airpods_pro3":   {"pattern": r"^AirPods\s?Pro\s*(?:第3世代|3)\s+MFHP4J/A$", "require": [],
                       "exclude": ["ケース", "イヤーチップ"]},
}

_PRICE_RE = re.compile(r"[¥￥]\s?([0-9]{1,3}(?:,[0-9]{3})+)")


def parse_rows(html: str) -> list[tuple[str, int, str]]:
    """一覧ページの商品行を (商品名, 新品買取価格, 詳細URL) の一覧にする。

    2つの形式に対応する:
    - まとめページ: <li><a>商品名</a> <span class="num">¥価格</span></li>
    - カテゴリページ: <table> の見出し「品目 / 新品買取 / 中古買取」と <tr><td><a>商品名</a></td><td class="num">…
      「新品買取」の列だけを読む（中古買取の価格を新品として扱わない）
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        heads = [th.get_text(strip=True) for th in table.find_all("th")]
        if "新品買取" not in heads:
            continue
        col = heads.index("新品買取")          # 0 列目が品目
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            a = tr.find("a", href=True)
            if not a or len(tds) <= col:
                continue
            m = _PRICE_RE.search(tds[col].get_text(" ", strip=True))
            if m:
                rows.append((a.get_text(" ", strip=True), int(m.group(1).replace(",", "")), a["href"]))
    for li in soup.select("li"):
        a = li.find("a", href=True)
        num = li.select_one("span.num")
        if not a or not num:
            continue
        m = _PRICE_RE.search(num.get_text(" ", strip=True))
        if not m:
            continue
        rows.append((a.get_text(" ", strip=True), int(m.group(1).replace(",", "")), a["href"]))
    return rows


def parse_jsonld_rows(html: str) -> list[dict]:
    """一覧ページの構造化データ（<script type="application/ld+json"> の Product）を商品行にする。

    返り値: [{"name", "jan", "price", "url"}]。価格は offers.price（新品・未開封の買取価格表の値。商品ページの「新品 ¥…」と
    同じ値であることを 2026-10-08 に確認）。JAN・価格・商品ページの URL のどれかが無い行は使わない。
    """
    import json as _json
    out = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, flags=re.S):
        try:
            d = _json.loads(block, strict=False)
        except ValueError:
            continue
        for item in (d if isinstance(d, list) else [d]):
            if not isinstance(item, dict) or item.get("@type") != "Product":
                continue
            offers = item.get("offers") if isinstance(item.get("offers"), dict) else {}
            # 新品でない（itemCondition が NewCondition でない）・円でない行は使わない（Phase 17 監査 M1）
            cond = str(item.get("itemCondition") or offers.get("itemCondition") or "")
            if cond and not cond.endswith("NewCondition"):
                continue
            if str(offers.get("priceCurrency") or "JPY") != "JPY":
                continue
            try:
                price = int(str(offers.get("price")))
            except (TypeError, ValueError):
                continue
            jan = str(item.get("gtin13") or "").strip()
            url = str(offers.get("url") or item.get("url") or "").strip()
            if re.fullmatch(r"\d{13}", jan) and price > 0 and _DETAIL_URL.match(url):
                out.append({"name": str(item.get("name") or "").strip(), "jan": jan, "price": price, "url": url})
    return out


def match_jan_rows(rows: list[dict], product_alias: str) -> list[dict]:
    """JAN と商品名の条件に合う行（JAN_RULES）。同じ JAN の行が複数あっても、価格が違えば呼び出し側で使わない。"""
    rule = JAN_RULES.get(product_alias)
    if not rule:
        return []
    out = []
    for r in rows:
        if r["jan"] != rule["jan"] or not re.search(rule["pattern"], r["name"]):
            continue
        if any(re.search(r"(?<![A-Za-z])" + re.escape(x) + r"(?![A-Za-z])", r["name"], re.IGNORECASE)
               for x in rule["exclude"]):
            continue
        out.append(r)
    return out


def match_rows(rows: list[tuple[str, int, str]], product_alias: str) -> list[tuple[str, int, str]]:
    """照合ルールに一致する商品行だけを返す（色違いは同じ商品として複数返る）。"""
    rule = ROW_RULES.get(product_alias)
    if not rule:
        return []
    out = []
    for name, price, href in rows:
        if not re.search(rule["pattern"], name):
            continue
        if any(r not in name for r in rule["require"]):
            continue
        # 除外の語は大文字・小文字を区別しない（「AU版」なども除く。除く方向にだけ働く）
        if any(re.search(r"(?<![A-Za-z])" + re.escape(x) + r"(?![A-Za-z])", name, re.IGNORECASE)
               for x in rule["exclude"]):
            continue
        out.append((name, price, href))
    return out


class KaitoriShoutenCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "kaitori_shouten"
    SHOP_NAME = "買取商店"
    BASE_URL  = "https://www.kaitorishouten-co.jp/"
    REQUIRES_JS = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 同じ一覧ページ（/kaden など）を商品ごとに取り直さないキャッシュは共通の _polite_fetch にある（Phase 12）
        self.last_matched_rows: list[tuple[str, int, str]] = []

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        """採用した価格の商品行の詳細ページ（/products/detail/…。JAN と状態別の価格が載る）の URL。

        一覧ページの URL ではなく商品ページの URL を出典にする（Phase 11）。
        採用した価格の行が特定できないときは一覧ページの URL のまま。
        """
        rows = getattr(self, "last_matched_rows", None) or []
        if not rows:
            return fallback_url
        best = max(p for _n, p, _h in rows)
        href = next((h for _n, p, h in rows if p == best and h), "")
        if not href.startswith(("/products/detail/", "https://www.kaitorishouten-co.jp/products/detail/")):
            return fallback_url
        return urljoin(self.BASE_URL, href)

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """商品行の照合だけで価格を決める。一致する行が無ければ未掲載（None）。

        汎用のフォールバック（見出しの「最高¥…」・ページ全体の最初の価格）は使わない。
        色違いが複数あるときは、同じ機種・容量の中の最高値（その商品の最高買取）を採用する。
        """
        if product_alias in JAN_RULES:
            # カメラ: JAN で1行だけ（同じ JAN に違う価格が並べば、どれか1つを選ばない）
            hits = match_jan_rows(parse_jsonld_rows(html), product_alias)
            if len({(h["url"], h["price"]) for h in hits}) != 1:
                self.last_matched_rows = []
                self.last_failure_reason = "product_not_listed" if not hits else "ambiguous_rows"
                return None
            matched = [(hits[0]["name"], hits[0]["price"], hits[0]["url"])]
        else:
            matched = match_rows(parse_rows(html), product_alias)
        self.last_matched_rows = matched
        if not matched:
            self.last_failure_reason = "product_not_listed"
            return None
        price = max(p for _n, p, _h in matched)
        if not (10000 <= price <= 5_000_000):
            self.last_failure_reason = "price_out_of_range"
            return None
        return price
