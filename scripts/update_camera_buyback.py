#!/usr/bin/env python3
"""カメラ新品/未使用買取価格 取得コレクター（Task 2 / 次フェーズ）。

対象カメラ × カメラ買取店から「新品・未使用・未開封」の買取価格を毎日取得する。
取得できた店舗は auto_scraped（condition=new_unopened）として buyback_prices に保存。
取得できない店舗は理由を記録し、manual_buyback_prices.csv の manual_today（手動確認）を
フォールバックとして温存する（このスクリプトは manual 行を削除しない）。

取得失敗理由（fetch_failed）:
  timeout / http_error / site_blocked / price_not_found / product_not_listed / not_supported

出力:
  exports/camera_buyback_status.json   （店舗×商品の成功/失敗・理由・成功率）

実行:
  python scripts/update_camera_buyback.py [--verbose] [--no-scrape]

注意:
  各買取店の新品/未使用買取見積は多くが JS フォーム・要ログインで、HTML から確定値を
  取得できないことが多い。その場合は本スクリプトが理由を記録し、manual_today を使う。
  実セレクタが用意でき次第、_parse_buyback_price() を店舗別に拡張する。
"""
import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATUS_PATH = ROOT / "exports" / "camera_buyback_status.json"

logger = logging.getLogger("update_camera_buyback")

# ── カメラ機種マスター（Camera Buyback Expansion）──
# 1機種= alias(=product_id の prod_ 抜き) / brand / name / retail(概算定価) /
#   variants(検索キーワード候補) / strict 一致ルール:
#     require_any  : 大文字・空白除去トークン（いずれか含む）
#     include_all  : 大文字・空白除去トークン（すべて含む）
#     include_raw_any: 生テキスト部分一致（いずれか含む。日本語語句用）
#     exclude      : 大文字・空白除去トークン（含んだら不一致）
#     exclude_raw  : 生テキスト部分一致（含んだら不一致）
CAMERA_MODELS = {
    # FUJIFILM
    "x100vi":   {"brand": "FUJIFILM", "name": "FUJIFILM X100VI", "retail": 280000,
                 "variants": ["X100VI", "X100 VI", "FUJIFILM X100VI"],
                 "require_any": ["X100VI"]},
    "gfx100rf": {"brand": "FUJIFILM", "name": "FUJIFILM GFX100RF", "retail": 750000,
                 "variants": ["GFX100RF", "GFX 100RF", "FUJIFILM GFX100RF"],
                 "require_any": ["GFX100RF"]},
    "xt5":      {"brand": "FUJIFILM", "name": "FUJIFILM X-T5", "retail": 280000,
                 "variants": ["X-T5", "FUJIFILM X-T5", "XT5"],
                 "require_any": ["X-T5", "XT5"]},
    # RICOH
    "gr3":      {"brand": "RICOH", "name": "RICOH GR III", "retail": 110000,
                 "variants": ["RICOH GR III", "GR III", "GR3"],
                 "require_any": ["GRIII", "GR3"], "exclude": ["IIIX", "3X", "HDF"],
                 "exclude_raw": ["Monochrome", "モノクローム"]},
    "gr3x":     {"brand": "RICOH", "name": "RICOH GR IIIx", "retail": 130000,
                 "variants": ["RICOH GR IIIx", "GR IIIx", "GR3x"],
                 "require_any": ["GRIIIX", "GR3X", "IIIX"]},
    "gr4":      {"brand": "RICOH", "name": "RICOH GR IV", "retail": 195000,
                 "variants": ["RICOH GR IV", "GR IV", "GR4"],
                 "require_any": ["GRIV", "GR4"], "exclude": ["HDF", "IIIX", "3X", "MONOCHROME"],
                 "exclude_raw": ["モノクローム", "モノクロ"]},
    "gr4_hdf":  {"brand": "RICOH", "name": "RICOH GR IV HDF", "retail": 200000,
                 "variants": ["RICOH GR IV HDF", "GR IV HDF", "GR4 HDF"],
                 "require_any": ["GRIV", "GR4"], "include_all": ["HDF"]},
    "gr4_mono": {"brand": "RICOH", "name": "RICOH GR IV Monochrome", "retail": 210000,
                 "variants": ["RICOH GR IV Monochrome", "GR IV Monochrome", "GR4 モノクローム"],
                 "require_any": ["GRIV", "GR4"], "include_raw_any": ["Monochrome", "MONOCHROME", "モノクローム", "モノクロ"]},
    # SONY
    # Sony は曖昧な α 表記（A7RV⊂A7RVI 等の連結誤一致）を避け、明確な ILCE/ILME 型番コードで判定。
    "a7rv":     {"brand": "SONY", "name": "SONY α7R V", "retail": 440000,
                 "variants": ["SONY α7R V", "α7R V ILCE-7RM5", "ILCE-7RM5"],
                 "require_any": ["ILCE7RM5"]},
    "a1ii":     {"brand": "SONY", "name": "SONY α1 II", "retail": 990000,
                 "variants": ["SONY α1 II", "α1 II ILCE-1M2", "ILCE-1M2"],
                 "require_any": ["ILCE1M2"]},
    "a7cr":     {"brand": "SONY", "name": "SONY α7CR", "retail": 330000,
                 "variants": ["SONY α7CR", "α7CR ILCE-7CR", "ILCE-7CR"],
                 "require_any": ["ILCE7CR"]},
    "fx3":      {"brand": "SONY", "name": "SONY FX3", "retail": 520000,
                 "variants": ["SONY FX3", "ILME-FX3"],
                 "require_any": ["ILMEFX3"], "exclude": ["ILMEFX3A"]},
    # CANON
    "r5ii":     {"brand": "CANON", "name": "Canon EOS R5 Mark II", "retail": 620000,
                 "variants": ["Canon EOS R5 Mark II", "EOS R5 Mark II", "R5 Mark II"],
                 "require_any": ["R5MARKII", "R5II", "R5M2"], "exclude": ["R5MARKIII", "R5III", "R5M3"]},
    "r6ii":     {"brand": "CANON", "name": "Canon EOS R6 Mark II", "retail": 390000,
                 "variants": ["Canon EOS R6 Mark II", "EOS R6 Mark II", "R6 Mark II"],
                 "require_any": ["R6MARKII", "R6II", "R6M2"], "exclude": ["R6MARKIII", "R6III", "R6M3"]},
    "r3":       {"brand": "CANON", "name": "Canon EOS R3", "retail": 830000,
                 "variants": ["Canon EOS R3", "EOS R3"],
                 "require_any": ["EOSR3"]},
    # NIKON
    "z8":       {"brand": "NIKON", "name": "Nikon Z8", "retail": 590000,
                 "variants": ["Nikon Z8", "Z8"],
                 "require_any": ["NIKONZ8", "Z8"], "exclude": ["Z80"]},
    "zf":       {"brand": "NIKON", "name": "Nikon Zf", "retail": 290000,
                 "variants": ["Nikon Zf", "Z f"],
                 "require_any": ["NIKONZF", "Z F"], "exclude": ["ZFC"],
                 "include_raw_any": ["Zf", "Ｚｆ", "NIKON"]},
    "z9":       {"brand": "NIKON", "name": "Nikon Z9", "retail": 700000,
                 "variants": ["Nikon Z9", "Z9"],
                 "require_any": ["NIKONZ9", "Z9"]},
    # LEICA
    "q3":       {"brand": "LEICA", "name": "Leica Q3", "retail": 880000,
                 "variants": ["Leica Q3", "LEICA Q3", "ライカ Q3"],
                 "require_any": ["LEICAQ3", "ライカQ3", "Q3"],
                 "exclude": ["Q30", "Q3X"]},
    "m11":      {"brand": "LEICA", "name": "Leica M11", "retail": 1180000,
                 "variants": ["Leica M11", "LEICA M11"],
                 "require_any": ["LEICAM11", "M11"]},
}

# 派生リスト（既存コードとの互換用）
CAMERA_ALIASES = list(CAMERA_MODELS.keys())
CAMERA_KEYWORDS = {a: (m.get("variants") or [m["name"]])[0] for a, m in CAMERA_MODELS.items()}
CAMERA_MODEL_KW = {a: (m.get("variants") or [m["name"]])[0] for a, m in CAMERA_MODELS.items()}
# フジヤ用：機種ごとの検索キーワード候補（最大3件で実行時間を抑制）
FUJIYA_KEYWORD_VARIANTS = {a: (m.get("variants") or [m["name"]])[:3] for a, m in CAMERA_MODELS.items()}

# 優先実装対象（Task 2: まず3店舗に絞る）
PRIORITY_SHOPS = {"src_mapcamera", "src_fujiya", "src_kitamura"}


def _strict_model_match(item_text: str, alias: str) -> bool:
    """商品名テキストが対象機種に厳密一致するか（データ駆動・全機種対応）。
    require_any / include_all / include_raw_any / exclude / exclude_raw で判定。
    """
    m = CAMERA_MODELS.get(alias)
    if not m:
        return False
    raw = item_text or ""
    # Sony の「α」(ギリシャ文字/全角) を A に正規化してから判定
    t = (raw.replace("α", "A").replace("Α", "A").replace("ａ", "A")
         .upper().replace(" ", "").replace("　", "").replace("-", ""))
    # 除外条件（先に評価）
    for ex in m.get("exclude", []):
        if ex.upper().replace(" ", "").replace("-", "") in t:
            return False
    for exr in m.get("exclude_raw", []):
        if exr in raw:
            return False
    # require_any: いずれか必須
    req = [r.upper().replace(" ", "").replace("-", "") for r in m.get("require_any", [])]
    if req and not any(r in t for r in req):
        return False
    # include_all: すべて必須
    inc = [i.upper().replace(" ", "").replace("-", "") for i in m.get("include_all", [])]
    if inc and not all(i in t for i in inc):
        return False
    # include_raw_any: 生テキストでいずれか必須
    incr = m.get("include_raw_any", [])
    if incr and not any(i in raw for i in incr):
        return False
    return True


def _pick_item_url(alias: str, item_link_candidates: list, base_url: str) -> tuple[Optional[str], bool]:
    """機種に厳密一致する商品個別ページURLを選ぶ。

    DOM から収集した item_link_candidates（[{text, href}]）のうち、機種一致した
    アンカーの href を商品URLとして返す。相対URLは base_url で絶対化する。

    Returns:
        (item_url, verified): 個別ページが見つかれば (絶対URL, True)。
                              見つからなければ (None, False)。
    """
    if not item_link_candidates:
        return None, False
    import urllib.parse as _up
    for c in item_link_candidates:
        text = (c or {}).get("text", "") or ""
        href = (c or {}).get("href", "") or ""
        if not href:
            continue
        if _strict_model_match(text, alias):
            try:
                abs_url = _up.urljoin(base_url, href)
            except Exception:
                abs_url = href
            # 検索ページ自身（list.aspx?keyword=...）は個別ページではないので除外
            if "list.aspx" in abs_url and "keyword=" in abs_url:
                continue
            if abs_url.startswith("http"):
                return abs_url, True
    return None, False


import re as _re_tier  # noqa: E402
# 富士屋等の段階表示「(段) 新品同様 ￥X 良品 ￥Y」から段ラベルと新品同様価格を抽出。
# 段ラベル例: 基準査定額 / 買取のみ10%UP / 下取は15%UP
_TIER_RE = _re_tier.compile(
    r"(基準査定額|買取のみ[0-9]+%UP|下取は?[0-9]*%?UP|下取り?|トレードイン)"
    r"[^¥￥]{0,12}新品同様[^¥￥\d]{0,4}[¥￥]\s?([0-9]{2,3}(?:,[0-9]{3})+)"
)


def _select_cash_buyback_price(item_text: str):
    """段階表示テキストから「下取(トレードイン)を除いた現金買取の最高値」を返す。

    富士屋は 基準査定額 < 買取のみX%UP < 下取はX%UP の3段階を併記するため、
    最高値をそのまま採ると下取(trade-in)価格を買取価格として誤採用してしまう。
    下取段を除外し、基準査定額・買取のみ段の中から最高値（現金買取の最高額）を返す。
    段構造が無ければ None（呼び出し側で従来の候補価格にフォールバック）。
    """
    raw = item_text or ""
    tiers = _TIER_RE.findall(raw)
    if not tiers:
        return None
    cash = []
    for label, price in tiers:
        if ("下取" in label) or ("トレードイン" in label):
            continue  # 下取(trade-in)段は現金買取ではないため除外
        try:
            cash.append(int(price.replace(",", "")))
        except ValueError:
            continue
    return max(cash) if cash else None


def _select_camera_buyback(candidates: list, alias: str) -> dict:
    """買取候補から機種厳密一致の価格を選び、採用/不採用の追跡情報を返す（Task 2）。
    戻り値 dict:
      price, confidence(high/None), matched_item, used_for_save(bool),
      all_price_candidates, rejected_candidates(rejection_reason付)
    strict model match + 買取文脈 + price>0 → high。
    strict 一致が無ければ採用しない（販売/別機種価格の誤採用を防ぐ）。
    """
    cands = [c for c in (candidates or []) if (c.get("price", 0) or 0) > 0]
    out = {"price": None, "confidence": None, "matched_item": "", "used_for_save": False,
           "all_price_candidates": [], "rejected_candidates": []}
    for c in cands:
        it = (c.get("item_text", "") or "")
        rec = {"price": c.get("price"), "item": it[:70], "near_buyback": bool(c.get("near_buyback"))}
        out["all_price_candidates"].append(rec)
        if not c.get("near_buyback"):
            out["rejected_candidates"].append({**rec, "rejection_reason": "not_buyback_context"})
        elif not _strict_model_match(it, alias):
            out["rejected_candidates"].append({**rec, "rejection_reason": "model_mismatch"})
    strict = [c for c in cands if c.get("near_buyback") and _strict_model_match(c.get("item_text", ""), alias)]
    if strict:
        best = max(strict, key=lambda c: c.get("price", 0))
        item_text = best.get("item_text", "") or ""
        price = best["price"]
        # 段階表示（基準査定額/買取のみ%UP/下取は%UP）がある場合は、
        # 下取(trade-in)段を除いた現金買取の最高値を採用する。
        cash_price = _select_cash_buyback_price(item_text)
        if cash_price and cash_price != price:
            out["tradein_tier_excluded"] = True
            out["raw_max_price"] = price  # 参考: 段込みの最高値（下取段の可能性）
            price = cash_price
        out.update(price=price, confidence="high",
                   matched_item=item_text[:140], used_for_save=True)
    return out

# 対象買取店（shop_id, 表示名, 買取検索URLテンプレート {kw}=URLエンコード済キーワード）
CAMERA_SHOPS = [
    # マップカメラ 買取検索（新品/新品同様の買取価格が掲載される検索ページ）
    ("src_mapcamera", "マップカメラ",
     "https://www.mapcamera.com/search?keyword={kw}&sell=1"),
    # フジヤカメラ 買取（ネット販売・買取の検索）
    ("src_fujiya", "フジヤカメラ",
     "https://www.fujiya-camera.co.jp/shop/goods/search.aspx?search.x=0&keyword={kw}"),
    # カメラのキタムラ ネットワンプライス買取（新品/未使用買取参考）
    ("src_kitamura", "カメラのキタムラ",
     "https://www.net-chuko.com/sell/search-list.do?goodsname={kw}"),
    # 以下は補助（フォーム/JS のため取得困難・失敗理由を記録）
    ("src_sofmap", "ソフマップ", "https://www.sofmap.com/"),
    ("src_janpara", "じゃんぱら", "https://www.janpara.co.jp/sell/"),
    ("src_kaitori_shouten", "買取商店", "https://www.kaitorishouten-co.jp/"),
]

# オンライン見積もり非対応（HTML から新品買取が取れない）店舗 → not_supported
NOT_SUPPORTED = {"src_kaitori_shouten"}

# 店舗別 買取価格抽出パターン（新品/未使用の買取価格を優先的に拾う）
import re as _re_shop  # noqa: E402
_SHOP_PRICE_PATTERNS = {
    # マップカメラ: 「買取価格」「新品」近接の金額
    "src_mapcamera": [
        _re_shop.compile(r"(?:買取|新品|未使用)[^¥￥\d]{0,30}[¥￥]\s?([0-9]{2,3}(?:,[0-9]{3})+)"),
    ],
    "src_fujiya": [
        _re_shop.compile(r"(?:買取|新品|未使用)[^¥￥\d]{0,30}[¥￥]\s?([0-9]{2,3}(?:,[0-9]{3})+)"),
    ],
    "src_kitamura": [
        _re_shop.compile(r"(?:買取|新品|未使用)[^¥￥\d]{0,30}[¥￥]\s?([0-9]{2,3}(?:,[0-9]{3})+)"),
    ],
}


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _fetch_html(url: str, timeout: int = 15) -> tuple[Optional[str], str]:
    """URL を取得して (html, reason) を返す。成功時 reason=''。"""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "ja,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status in (403, 429):
                return None, "site_blocked"
            if status == 404:
                return None, "product_not_listed"
            if status >= 500:
                return None, "service_unavailable"
            data = resp.read(400_000)
            html = data.decode("utf-8", errors="ignore")
            if any(k in html.lower() for k in ("captcha", "are you a robot", "cloudflare")):
                return None, "site_blocked"
            return html, ""
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__.lower()
        if "timeout" in name:
            return None, "timeout"
        if "http" in name and "403" in str(e):
            return None, "site_blocked"
        return None, "http_error"


# 店舗別 検索フォーム/結果セレクタ（Playwright 用）
_PW_SHOP_CONFIG = {
    "src_fujiya": {
        # rendered DOM 解析で発見した「買取金額を調べる」買取専用ページ /shop/purchase/list.aspx を使用。
        # （/shop/goods/search.aspx は販売カタログ＝買取価格でないため不採用）
        "search_url": "https://www.fujiya-camera.co.jp/shop/purchase/list.aspx?keyword={mkw}&search=検索",
        "buyback_landing": "https://www.fujiya-camera.co.jp/shop/kaitori/pc/0c-kaitor/",
        "search_input": "input[name='keyword']",
        "result_wait": "[class*='kaitori'], [class*='price'], [class*='purchase'], table td",
        "strategy": "fujiya_buyback",
    },
    "src_kitamura": {
        # net-chuko 買取検索（UA/viewport調整で bot 回避を試行）。site_blocked 継続なら manual fallback。
        "search_url": "https://www.net-chuko.com/ec/sell/category/itemList?keyword={mkw}",
        "search_input": "input[type='search'], input[name*='keyword']",
        "result_wait": "[class*='price'], .itemList, .goodsList, .product",
        "strategy": "kitamura_render",
    },
    "src_mapcamera": {
        "search_url": "https://www.mapcamera.com/search?keyword={kw}",
        "search_input": "input[name*='keyword'], input[type='search']",
        "result_wait": "[class*='price'], .item, .goods",
        "strategy": "mapcamera_retry",
    },
}


# Playwright DOM内で価格候補を総当り探索する JS（selector brute force）
_PW_DOM_PROBE_JS = r"""
() => {
  const PRICE_RE = /[¥￥]?\s?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,7})\s*円?/;
  const SELECTORS = ["table td", ".price", ".kaitori", ".estimate",
                     "[class*='price']", "[id*='price']", "[class*='kaitori']",
                     "[class*='assess']", "[class*='satei']", ".goods", ".item"];
  const KW = ["買取", "査定", "査定額", "税込", "円", "¥"];
  const bodyText = (document.body ? (document.body.innerText||"") : "");
  // 該当件数 N件 を抽出（フジヤ等の検索結果件数）
  let hit_count = null;
  const hm = bodyText.match(/該当件数\s*([0-9,]+)\s*件/);
  if (hm) hit_count = parseInt(hm[1].replace(/,/g,''),10);
  else if (/該当件数\s*[―ー\-]\s*件/.test(bodyText)) hit_count = 0;
  const out = {readyState: document.readyState,
               iframe_count: document.querySelectorAll('iframe').length,
               shadow_dom: false, hit_count: hit_count,
               body_text_preview: bodyText.slice(0,500),
               matched_selectors: [], selector_candidates: [], best_price: null};
  // shadow DOM 検出
  try { out.shadow_dom = Array.from(document.querySelectorAll('*')).some(e => e.shadowRoot); } catch(e){}
  // 買取ページへのリンク候補を収集（買取/査定/下取/kaitori/purchase/trade-in）
  const blinks = [];
  try {
    for (const a of document.querySelectorAll('a[href]')) {
      const t = (a.textContent||"").trim();
      const href = a.getAttribute('href')||"";
      const hl = href.toLowerCase();
      if (/買取|査定|下取/.test(t) || /kaitori|purchase|satei|trade|sell|oneprice|one-price/.test(hl)) {
        blinks.push({text: t.slice(0,30), href: href});
      }
    }
  } catch(e){}
  out.buyback_link_candidates = blinks.slice(0,20);
  // 商品個別ページへのリンク候補（ブランド/型番を含むアンカー）を収集。
  // 店舗トップ/検索URLではなく、機種一致した商品詳細URLを買取リンクに使うため。
  const ilinks = [];
  try {
    const BRANDL = /FUJIFILM|RICOH|SONY|CANON|NIKON|LEICA|ソニー|キヤノン|ニコン|ライカ|富士フイルム|リコー|X100|GFX|X-?T5|GR\s?I|GRIII|ILCE|ILME|EOS|α7|α1|Z8|Z9|Q3|M11/i;
    for (const a of document.querySelectorAll('a[href]')) {
      const t = (a.textContent||"").replace(/\s+/g," ").trim();
      const href = a.getAttribute('href')||"";
      if (t.length >= 4 && BRANDL.test(t)) {
        ilinks.push({text: t.slice(0,120), href: href});
      }
    }
  } catch(e){}
  out.item_link_candidates = ilinks.slice(0,40);
  const cands = [];
  for (const sel of SELECTORS) {
    let els;
    try { els = document.querySelectorAll(sel); } catch(e){ continue; }
    let hit = 0;
    for (const el of els) {
      const t = (el.textContent||"").trim();
      const m = t.match(PRICE_RE);
      if (!m) continue;
      const v = parseInt(m[1].replace(/,/g,''),10);
      if (!(v>=10000 && v<=1500000)) continue;
      hit++;
      const nearKw = KW.some(k => t.includes(k));
      // 「買取/査定」の文脈か（要素or祖先テキスト）— 販売価格と区別するため判定。
      // フジヤ買取リストは class に「kitr」(=買取)、ラベルは「基準査定額/買取申し込み」。
      let ctx = t; let item_text = "";
      try {
        // 価格要素から親方向へ辿り、ブランド/型番トークンを含む最初の祖先を商品単位とみなす。
        // （フジヤ買取は商品名 __boxName01 と価格 __boxPrice01 が兄弟のため、共通の親まで上る）
        const BRAND = /FUJIFILM|RICOH|SONY|CANON|NIKON|LEICA|ソニー|キヤノン|ニコン|ライカ|富士フイルム|リコー|X100|GFX|X-?T5|GR\s?I|GR\s?V|GR\s?3|GRIII|A7|A1|FX3|EOS|R5|R6|R3|Z8|Z9|ZF|Q3|M11/i;
        let node = el;
        for (let lvl=0; lvl<7 && node; lvl++){
          node = node.parentElement;
          if (!node) break;
          const ct = (node.textContent||"");
          if (BRAND.test(ct)) { item_text = ct.replace(/\s+/g," ").trim().slice(0,240); break; }
        }
        if (!item_text && el.parentElement) {
          item_text = (el.parentElement.textContent||"").replace(/\s+/g," ").trim().slice(0,200);
        }
        ctx += " " + item_text;
      } catch(e){}
      const nearBuyback = /買取|査定|基準査定額|買取申し込み/.test(ctx)
                        || /kitr|kaitori|satei/i.test(el.className||"");
      // 下取（トレードイン）価格の検出。フジヤ等は「下取15%UP」等の販促で
      // 現金買取より高い下取価格を併記するため、現金買取価格と分離する。
      // 直近の文脈（要素+直親）のみで判定し、7階層上の祖先まで巻き込まない（過剰除外防止）。
      let localCtx = t;
      try { if (el.parentElement) localCtx += " " + (el.parentElement.textContent||"").slice(0,150); } catch(e){}
      const isTradein = /下取|トレードイン|trade-?in|[0-9]+\s?%\s?(?:UP|アップ|増)/i.test(localCtx);
      cands.push({selector: sel, text: t.slice(0,60), price: v, near_kw: nearKw, near_buyback: nearBuyback, is_tradein: isTradein, item_text: item_text});
    }
    if (hit>0) out.matched_selectors.push({selector: sel, hits: hit});
  }
  // 買取/査定 文脈かつ「下取(トレードイン)でない」候補のみを現金買取価格として採用。
  // （販売価格カタログ・下取UP価格は採用しない）
  const buybackCands = cands.filter(c => c.near_buyback && !c.is_tradein);
  out.tradein_excluded = cands.filter(c => c.near_buyback && c.is_tradein).length;
  buybackCands.sort((a,b)=> b.price - a.price);
  cands.sort((a,b)=> (b.near_kw - a.near_kw) || (b.price - a.price));
  out.selector_candidates = cands.slice(0,15);
  out.has_buyback_context = buybackCands.length > 0;
  // best_price は「買取文脈」がある場合のみ設定（販売価格の誤抽出を防ぐ）
  out.best_price = buybackCands.length ? buybackCands[0].price : null;
  out.sales_price_sample = cands.length ? cands[0].price : null;  // 参考（販売価格の可能性）
  return out;
}
"""


def _fetch_with_playwright(url: str, shop_id: str, alias: str, dbg_dir, shot_dir=None,
                           timeout_ms: int = 25000) -> dict:
    """Playwright(chromium headless) で URL をレンダリングし、DOM診断＋価格抽出を行う。

    戻り値 dict: html, screenshot_saved, rendered_html_size, selector_waited,
      reason, strategy, extracted_price, body_text_preview, matched_selectors,
      selector_candidates, iframe_count, shadow_dom_detected, dom_ready_state
    Playwright 未導入時は reason='playwright_not_installed'。
    """
    out = {"html": None, "screenshot_saved": False, "rendered_html_size": 0,
           "selector_waited": False, "reason": "", "strategy": "",
           "extracted_price": None, "body_text_preview": "", "matched_selectors": [],
           "selector_candidates": [], "iframe_count": 0,
           "shadow_dom_detected": False, "dom_ready_state": "", "hit_count": None,
           "has_buyback_context": False, "sales_price_sample": None,
           "buyback_link_candidates": [], "buyback_page_url": None}
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        out["reason"] = "playwright_not_installed"
        return out

    cfg = _PW_SHOP_CONFIG.get(shop_id, {})
    out["strategy"] = cfg.get("strategy", "generic")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
                locale="ja-JP", timezone_id="Asia/Tokyo",
                viewport={"width": 1366, "height": 900},
                extra_http_headers={"Accept-Language": "ja,en-US;q=0.9,en;q=0.8"},
            )
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as e2:
                    out["reason"] = "timeout" if "imeout" in type(e2).__name__ else "nav_error"
                    browser.close()
                    return out
            rw = cfg.get("result_wait")
            if rw:
                try:
                    page.wait_for_selector(rw, timeout=8000)
                    out["selector_waited"] = True
                except Exception:
                    out["selector_waited"] = False
            html = page.content()
            out["html"] = html
            out["rendered_html_size"] = len(html)
            # DOM 診断 + selector brute force（page.evaluate）
            try:
                probe = page.evaluate(_PW_DOM_PROBE_JS)
                out["dom_ready_state"] = probe.get("readyState", "")
                out["iframe_count"] = probe.get("iframe_count", 0)
                out["shadow_dom_detected"] = bool(probe.get("shadow_dom", False))
                out["body_text_preview"] = probe.get("body_text_preview", "")
                out["matched_selectors"] = probe.get("matched_selectors", [])
                out["selector_candidates"] = probe.get("selector_candidates", [])
                out["hit_count"] = probe.get("hit_count")
                out["has_buyback_context"] = bool(probe.get("has_buyback_context", False))
                out["sales_price_sample"] = probe.get("sales_price_sample")
                out["buyback_link_candidates"] = probe.get("buyback_link_candidates", [])
                out["item_link_candidates"] = probe.get("item_link_candidates", [])
                out["tradein_excluded"] = probe.get("tradein_excluded", 0)
                _bp = probe.get("best_price")
                # 「買取文脈」のある価格のみ採用（販売価格は buyback として保存しない）
                if isinstance(_bp, (int, float)) and 10000 <= _bp <= 1500000:
                    out["extracted_price"] = int(_bp)
            except Exception:
                pass
            # debug: rendered HTML 保存 + スクリーンショット保存（別ディレクトリ）
            try:
                if dbg_dir is not None:
                    dbg_dir.mkdir(parents=True, exist_ok=True)
                    (dbg_dir / f"{shop_id}_{alias}.pw.html").write_text(html[:300_000], encoding="utf-8")
                _sd = shot_dir or dbg_dir
                if _sd is not None:
                    _sd.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(_sd / f"{shop_id}_{alias}.png"), full_page=False)
                    out["screenshot_saved"] = True
            except Exception:
                pass
            browser.close()
    except Exception as e:  # noqa: BLE001
        out["reason"] = f"playwright_error_{type(e).__name__}"
    return out


def _parse_buyback_price(html: str, alias: str, shop_id: str = "") -> Optional[int]:
    """HTML から新品/未使用買取価格を抽出する（店舗別パターン優先）。

    店舗別パターン（_SHOP_PRICE_PATTERNS）→ 汎用パターンの順に試行。
    妥当範囲（¥10,000〜¥1,500,000）に収まる最初の金額を返す。
    取得できない場合は None（price_not_found として記録、manual_today にフォールバック）。
    """
    def _valid(v: int) -> bool:
        return 10_000 <= v <= 1_500_000

    # 1) 店舗別パターン
    for pat in _SHOP_PRICE_PATTERNS.get(shop_id, []):
        m = pat.search(html)
        if m:
            try:
                v = int(m.group(1).replace(",", ""))
                if _valid(v):
                    return v
            except (ValueError, IndexError):
                pass
    # 2) 汎用パターン（新品/未使用/未開封 近接の金額）
    for m in re.finditer(r"(新品|未使用|未開封)[^¥￥\d]{0,20}[¥￥]?\s?([0-9]{2,3}(?:,[0-9]{3})+)\s*円?", html):
        try:
            v = int(m.group(2).replace(",", ""))
            if _valid(v):
                return v
        except ValueError:
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="カメラ新品/未使用買取価格コレクター")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-scrape", action="store_true", help="取得せず status のみ出力")
    parser.add_argument("--priority-only", action="store_true",
                        help="優先3店舗（マップ/フジヤ/キタムラ）のみ取得")
    parser.add_argument("--debug-html", action="store_true",
                        help="取得HTMLを exports/debug_camera/ に保存（全店舗）")
    parser.add_argument("--playwright", action="store_true",
                        help="requests 失敗時に Playwright(chromium) でレンダリング取得")
    args = parser.parse_args()
    setup_logging(args.verbose)

    now = datetime.now(tz=JST)
    logger.info("update_camera_buyback 開始: %s", now.strftime("%Y-%m-%d %H:%M JST"))

    try:
        from src.db.database import Database
        from src.db.repository import Repository
        from src.models.buyback_price import BuybackPriceModel
        repo = Repository(Database())
    except Exception as e:  # noqa: BLE001
        logger.error("DB初期化失敗: %s", e)
        repo = None

    import urllib.parse as _up
    results = []  # list of dict（診断フィールド付き）
    saved = 0
    _dbg = ROOT / "exports" / "debug_camera"
    _shot = ROOT / "exports" / "debug_camera_screenshots"

    def _diag(alias, shop_id, status, price, reason, **kw):
        d = {"product_alias": alias, "shop_id": shop_id, "status": status,
             "brand": CAMERA_MODELS.get(alias, {}).get("brand", ""),
             "price": price, "reason": reason,
             "html_saved": False, "html_size": 0, "cloudflare_detected": False,
             "js_required": False, "selector_found": False, "extracted_price": None,
             # Playwright 診断
             "playwright_attempted": False, "playwright_success": False,
             "screenshot_saved": False, "rendered_html_size": 0,
             "selector_waited": False, "extraction_strategy": "requests",
             # DOM 診断（Playwright）
             "body_text_preview": "", "matched_selectors": [], "selector_candidates": [],
             "iframe_count": 0, "shadow_dom_detected": False, "dom_ready_state": "",
             "hit_count": None, "keyword_hit_counts": {}, "best_keyword": None,
             "has_buyback_context": False, "sales_price_sample": None,
             "buyback_link_candidates": [], "buyback_page_url": None,
             "buyback_page_html_size": 0, "buyback_page_text_preview": "",
             "buyback_price_candidates": [], "buyback_extracted_price": None,
             "confidence": None, "matched_item": "",
             "all_price_candidates": [], "rejected_candidates": [], "used_for_save": False}
        d.update(kw)
        return d

    for alias in CAMERA_ALIASES:
        kw = CAMERA_KEYWORDS.get(alias, alias)
        kw_enc = _up.quote(kw)
        mkw_enc = _up.quote(CAMERA_MODEL_KW.get(alias, kw))
        for shop_id, shop_name, url_tmpl in CAMERA_SHOPS:
            if args.priority_only and shop_id not in PRIORITY_SHOPS:
                continue
            if args.no_scrape:
                results.append(_diag(alias, shop_id, "SKIP", 0, "scrape_skipped"))
                continue
            if shop_id in NOT_SUPPORTED:
                results.append(_diag(alias, shop_id, "FAILED", 0, "not_supported"))
                continue
            url = url_tmpl.format(kw=kw_enc) if "{kw}" in url_tmpl else url_tmpl

            # 1) requests 取得
            html, reason = _fetch_html(url)
            _saved = False
            _size = len(html) if html else 0
            if html and (args.debug_html or shop_id in PRIORITY_SHOPS):
                try:
                    _dbg.mkdir(parents=True, exist_ok=True)
                    (_dbg / f"{shop_id}_{alias}.html").write_text(html[:200_000], encoding="utf-8")
                    _saved = True
                except Exception:
                    pass
            price = _parse_buyback_price(html, alias, shop_id) if html else None
            _strategy = "requests"
            _pw = {}

            _kw_hit_counts = {}
            _best_keyword = None
            _confidence = "medium"   # auto_scraped の confidence（strict一致でhigh）
            _matched_item = ""
            _sel = {}                # _select_camera_buyback の追跡結果（all/rejected）
            # 2) requests で価格が取れない/失敗 → Playwright fallback（--playwright 時）
            if (not price) and args.playwright and shop_id in _PW_SHOP_CONFIG:
                _cfg = _PW_SHOP_CONFIG[shop_id]
                # フジヤ：複数キーワードを試し、機種厳密一致の買取価格が取れるものを採用
                if shop_id == "src_fujiya" and alias in FUJIYA_KEYWORD_VARIANTS:
                    _best = None
                    for _var in FUJIYA_KEYWORD_VARIANTS[alias]:
                        # 買取専用ページ /shop/purchase/list.aspx（search=検索 必須）
                        _vurl = ("https://www.fujiya-camera.co.jp/shop/purchase/list.aspx"
                                 f"?keyword={_up.quote(_var)}&search=検索")
                        _try = _fetch_with_playwright(_vurl, shop_id, alias, _dbg, shot_dir=_shot)
                        _try["buyback_page_url"] = _vurl
                        _hc = _try.get("hit_count")
                        _kw_hit_counts[_var] = _hc
                        # 機種厳密一致の買取価格を選定（Task 1/2）
                        _selr = _select_camera_buyback(_try.get("selector_candidates", []), alias)
                        _sp = _selr.get("price")
                        # 厳密一致価格が取れた or ヒット数最大 の候補を保持
                        _score = (1 if _sp else 0, _hc or 0)
                        if _best is None or _score > _best[0]:
                            _best = (_score, _var, _try, _selr)
                        if _sp:
                            break  # 厳密一致の買取価格取得で確定
                    if _best is not None:
                        _best_keyword = _best[1]; _pw = _best[2]; _sel = _best[3]
                        if _sel.get("price"):
                            price = _sel["price"]; _confidence = _sel.get("confidence") or "high"
                            _matched_item = _sel.get("matched_item", "")
                            html = _pw.get("html") or html
                            _size = _pw.get("rendered_html_size", _size)
                            _strategy = _pw.get("strategy", "playwright")
                else:
                    _pw_url = _cfg.get("search_url", url).format(kw=kw_enc, mkw=mkw_enc)
                    _pw = _fetch_with_playwright(_pw_url, shop_id, alias, _dbg, shot_dir=_shot)
                    if _pw.get("html"):
                        _sel = _select_camera_buyback(_pw.get("selector_candidates", []), alias)
                        if _sel.get("price"):
                            price = _sel["price"]; _confidence = _sel.get("confidence") or "high"
                            _matched_item = _sel.get("matched_item", "")
                            html = _pw["html"]
                            _size = _pw.get("rendered_html_size", len(html))
                            _strategy = _pw.get("strategy", "playwright")

            _low = (html or "").lower()
            _cf = any(k in _low for k in ("just a moment", "challenge-platform",
                                          "cf-browser-verification", "captcha", "ロボットではありません"))
            _js = (("__next_data__" in _low) or ("window.__nuxt__" in _low)
                   or (0 < _size < 3000 and "<script" in _low))
            _pw_attempted = bool(_pw)
            _pw_success = bool(_pw.get("html")) if _pw else False
            _pw_kw = dict(playwright_attempted=_pw_attempted,
                          playwright_success=_pw_success,
                          screenshot_saved=_pw.get("screenshot_saved", False) if _pw else False,
                          rendered_html_size=_pw.get("rendered_html_size", 0) if _pw else 0,
                          selector_waited=_pw.get("selector_waited", False) if _pw else False,
                          extraction_strategy=_strategy,
                          body_text_preview=_pw.get("body_text_preview", "") if _pw else "",
                          matched_selectors=_pw.get("matched_selectors", []) if _pw else [],
                          selector_candidates=_pw.get("selector_candidates", []) if _pw else [],
                          iframe_count=_pw.get("iframe_count", 0) if _pw else 0,
                          shadow_dom_detected=_pw.get("shadow_dom_detected", False) if _pw else False,
                          dom_ready_state=_pw.get("dom_ready_state", "") if _pw else "",
                          hit_count=_pw.get("hit_count") if _pw else None,
                          keyword_hit_counts=_kw_hit_counts,
                          best_keyword=_best_keyword,
                          has_buyback_context=_pw.get("has_buyback_context", False) if _pw else False,
                          sales_price_sample=_pw.get("sales_price_sample") if _pw else None,
                          buyback_link_candidates=_pw.get("buyback_link_candidates", []) if _pw else [],
                          buyback_page_url=_pw.get("buyback_page_url") if _pw else None,
                          buyback_page_html_size=_pw.get("rendered_html_size", 0) if _pw else 0,
                          buyback_page_text_preview=_pw.get("body_text_preview", "") if _pw else "",
                          buyback_price_candidates=[c for c in (_pw.get("selector_candidates", []) if _pw else [])
                                                    if c.get("near_buyback")],
                          buyback_extracted_price=_pw.get("extracted_price") if _pw else None,
                          confidence=_confidence, matched_item=_matched_item,
                          all_price_candidates=_sel.get("all_price_candidates", []),
                          rejected_candidates=_sel.get("rejected_candidates", []),
                          used_for_save=bool(_sel.get("used_for_save", False)))

            if not price or price <= 0:
                # 失敗理由の決定（requests 失敗理由 / Playwright 理由 / 抽出不可）
                if _pw and _pw.get("reason"):
                    _r = _pw["reason"]
                elif _pw and _pw.get("sales_price_sample") and not _pw.get("has_buyback_context"):
                    # 検索結果に価格はあるが「買取」文脈でない＝販売価格カタログ
                    _r = "sales_catalog_no_buyback"
                elif html is None:
                    _r = reason
                elif _cf:
                    _r = "site_blocked"
                elif 0 < _size < 3000:
                    _r = "js_required" if _js else "empty_html"
                else:
                    _r = "price_not_found"
                results.append(_diag(alias, shop_id, "FAILED", 0, _r,
                                     html_saved=_saved, html_size=_size,
                                     cloudflare_detected=_cf, js_required=_js,
                                     selector_found=False, extracted_price=None, **_pw_kw))
                continue

            # 取得成功 → auto_scraped（新品未開封）で保存（manual_today より優先される）
            results.append(_diag(alias, shop_id, "OK", price, "",
                                 html_saved=_saved, html_size=_size,
                                 cloudflare_detected=_cf, js_required=_js,
                                 selector_found=True, extracted_price=price, **_pw_kw))
            if repo is not None:
                try:
                    pid = "prod_" + alias if not alias.startswith("prod_") else alias
                    # 商品個別ページURLを優先。見つからなければ買取ページURL→検索URLにフォールバック。
                    # link_verified は「商品個別URLを特定できた」場合のみ True にする。
                    _item_links = _pw.get("item_link_candidates", []) if _pw else []
                    _detail_url, _url_verified = _pick_item_url(alias, _item_links, url)
                    _save_url = _detail_url or (_pw.get("buyback_page_url") if _pw else None) or url
                    bp = BuybackPriceModel(
                        id=f"camera_auto_{alias}_{shop_id}",  # 決定論的ID（再実行で同一行を更新）
                        product_id=pid, shop_id=shop_id, shop_name=shop_name,
                        buyback_price=price, condition="new_unopened", buyback_url=_save_url,
                        observed_at=now, data_source="auto_scraped",
                        link_verified=_url_verified, confidence=_confidence,
                        notes=(_matched_item or "")[:120],  # matched_item を notes に保存（LP表示用）
                    )
                    repo.insert_buyback_price(bp)
                    saved += 1
                except Exception as e:  # noqa: BLE001
                    logger.debug("保存失敗 %s/%s: %s", alias, shop_id, e)

    ok = sum(1 for r in results if r["status"] == "OK")
    failed = sum(1 for r in results if r["status"] == "FAILED")
    skip = sum(1 for r in results if r["status"] == "SKIP")
    total = len(results)
    from collections import Counter
    reasons = Counter(r["reason"] for r in results if r["status"] == "FAILED" and r["reason"])

    # 店舗別の診断サマリ（原因分類）
    shop_diag = {}
    for r in results:
        sid = r["shop_id"]
        d = shop_diag.setdefault(sid, {"jobs": 0, "ok": 0, "html_saved": 0,
                                       "cloudflare": 0, "js_required": 0,
                                       "playwright_attempted": 0, "playwright_success": 0,
                                       "screenshot_saved": 0, "top_reason": {}})
        d["jobs"] += 1
        if r["status"] == "OK":
            d["ok"] += 1
        if r.get("html_saved"):
            d["html_saved"] += 1
        if r.get("cloudflare_detected"):
            d["cloudflare"] += 1
        if r.get("js_required"):
            d["js_required"] += 1
        if r.get("playwright_attempted"):
            d["playwright_attempted"] += 1
        if r.get("playwright_success"):
            d["playwright_success"] += 1
        if r.get("screenshot_saved"):
            d["screenshot_saved"] += 1
        if r["status"] == "FAILED" and r["reason"]:
            d["top_reason"][r["reason"]] = d["top_reason"].get(r["reason"], 0) + 1
    for sid, d in shop_diag.items():
        d["diagnosis"] = (max(d["top_reason"], key=d["top_reason"].get) if d["top_reason"]
                          else ("ok" if d["ok"] else "unknown"))

    status = {
        "generated_at": now.isoformat(timespec="seconds"),
        "summary": {"total": total, "ok": ok, "failed": failed, "skip": skip,
                    "success_rate_pct": round(100.0 * ok / total, 1) if total else 0.0,
                    "saved_to_db": saved},
        "failure_reasons": [{"reason": k, "count": v} for k, v in reasons.most_common()],
        "shop_diagnostics": shop_diag,
        "detail": results,
        "fallback_note": ("HTMLから新品買取を確定できない店舗は manual_buyback_prices.csv の "
                          "manual_today（手動確認）を使用。auto_scraped 取得時はそちらを優先。"
                          "14日超は利益判定から除外。"),
        "analysis_2026_06": ("マップカメラ=サンドボックスからtimeout（到達不可）/ "
                             "キタムラ net-chuko=JSシェル(~2KB,JS必須) / "
                             "フジヤ=検索フォームページ（価格はASP.NETポストバック/JSでレンダリング、静的HTMLに価格なし）。"
                             "→ 静的HTTPでは取得不可。Playwright(JSレンダリング)が必要。"),
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("camera_buyback_status 保存: OK=%d / FAILED=%d / SKIP=%d (saved_to_db=%d)",
                ok, failed, skip, saved)
    if ok == 0:
        logger.warning("WARNING: カメラ買取の自動取得は0件。manual_today（手動確認）で表示します。"
                       "（理由: %s）", dict(reasons))
    return 0


if __name__ == "__main__":
    sys.exit(main())
