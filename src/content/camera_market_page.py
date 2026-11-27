"""カメラ せどり判断ページ（docs/camera-research.html）の描画。

入力は exports/camera_research/camera_market.json（src/research/camera_refresh.py が作る）。
「どこで買い・いくらで・どこで売り・いくらで・利益と ROI はいくらか・その売値は買取か成約中央値か」を 1 枚で判断できるようにする。
- 価格の種別を混ぜない（買取価格 / 成約中央値 / 出品中の価格）。出品の最高値は売値にしない（参考として別枠に出すだけ）。
- 計算できないルートは、理由を出して「未計算」と書く（0 円・架空の商品で埋めない）。利益商品が 0 件なら 0 件と書く。
- 調査が古いときは BUY を出さず「調査が古い」と書く（ページを作るたびに現在日時で決める）。
- すべての文字は HTML エスケープ。リンクは http(s) だけ。
"""
from __future__ import annotations

import html as _html
import re
from datetime import datetime, timedelta, timezone

from src.content.iphone_buyback_page import CSS as _CSS, age_banner, _md, _plain
from src.content.ui.shared_css import legacy_css, site_nav
from src.research.camera_routes import conditional_blockers, conditional_hide_reasons, conditional_notes
from src.tcg import runtime_freshness as rf
from src.tcg.models import parse_dt

JST = timezone(timedelta(hours=9))

COND = {"NEW": "新品", "UNOPENED": "新品未開封", "LIKE_NEW": "新品同様", "USED": "中古", "UNKNOWN": "状態不明"}
STOCK = {"AVAILABLE": "購入できる", "OUT_OF_STOCK": "在庫なし", "LOTTERY_DEPENDENT": "抽選に当選が必要", "RESERVATION": "予約のみ", "UNKNOWN": "在庫不明",
         "LOTTERY_ENDED": "抽選は終了", "LOTTERY_UPCOMING": "抽選は開始前（予定）", "SALES_SUSPENDED": "販売休止"}
STOCK_TONE = {"OUT_OF_STOCK": "off", "LOTTERY_ENDED": "off", "SALES_SUSPENDED": "off", "LOTTERY_DEPENDENT": "wait", "LOTTERY_UPCOMING": "wait", "RESERVATION": "wait"}    # 緑にしない（購入できる・不明は文字だけ）
PTYPE = {"BUYBACK_PRICE": "買取価格", "SOLD_MEDIAN": "成約中央値", "OFFICIAL_RETAIL": "公式の販売価格", "RETAIL_PRICE": "販売店の価格",
         "LISTING_LOW": "出品中の最安（売れた価格ではない）"}
DECISION = {"BUY": "BUY（買う）", "WATCH": "WATCH（様子見・要確認）", "WAIT": "WAIT（待つ）", "SKIP": "SKIP（見送り）"}
DECISION_JA = {"BUY": "購入候補", "WATCH": "様子見", "WAIT": "様子見", "SKIP": "見送り"}
CONF_JA = {"high": "高", "medium": "中", "low": "低"}
PROFIT = {"PROFITABLE": "黒字", "NO_PROFIT": "赤字・利益なし", "NOT_CALCULATED": "未計算"}
REASON = {
    "conditional_price": "条件つきの価格（無条件の確定価格ではない）", "no_profit": "利益が出ない", "stock_lottery_dependent": "抽選に当選しないと買えない", "stock_reservation": "予約のみで今は買えない",
    "out_of_stock": "在庫なし", "stock_lottery_ended": "抽選は終了している", "stock_lottery_upcoming": "抽選は開始前", "stock_sales_suspended": "販売休止中",
    "conditional_profit_only": "店舗印なしの場合だけ黒字（条件付き・購入推奨ではない）", "stock_unknown": "在庫が確認できない", "unregistered_product": "監視対象に未登録の機種",
    "roi_below_threshold": "ROI が基準（8%）に届かない", "single_buyback_shop": "買取が 1 店だけ（比較できない）",
    "buyback_outlier_review": "買取の最高が他店より極端に高い（外れ値の確認）", "buyback_update_date_unknown": "買取の更新日が不明",
    "secondary_route_not_auto_buy": "二次流通の売値は成約の実在を人が確認するまで BUY にしない", "not_executable": "実行できる条件がそろっていない",
    "condition_mismatch": "買う状態と売る状態が違う", "sold_insufficient": "成約が足りない（3 件以上・期間・個別の根拠が必要）",
    "sold_none": "成約の実績なし", "fee_unconfirmed": "売り先の販売手数料が確認済み（一次情報の本文）でない", "purchase_shipping_unknown": "購入送料が不明",
    "no_buy_candidate": "買える価格が確認できていない", "no_buyback": "買取価格が確認できていない",
    "price_missing": "価格が読めていない", "not_product_page": "商品ページでない（一覧だけ）", "model_not_in_title": "商品名が機種と一致しない",
    "variant_mismatch": "版・仕様が違う", "item_title_missing": "商品名を確認できない", "buy_stale": "仕入れ価格が古い",
    "buy_unknown_freshness": "仕入れ価格の日付を確認できない", "sell_stale": "買取価格が古い", "sell_unknown_freshness": "買取価格の日付を確認できない",
    "not_purchasable_now": "今買えるか確認できない", "condition_unknown": "状態を確認できない", "retail_not_new": "新品でない",
    "host_not_allowed": "価格の根拠にできないサイト", "aggregator_source": "集約サイト由来（採用しない）", "not_item_page": "商品ページでない（検索・一覧）",
    "title_condition_mismatch": "商品名の状態が申告と違う", "junk_or_defective": "ジャンク・訳あり・付属品など", "model_continues": "別の機種の表記",
    "price_implausible": "価格が不自然（誤取得の疑い）", "roi_implausible": "ROI が不自然（誤取得の疑い）", "stock_check_old": "在庫の確認が古い",
    "cross_border_cost_unknown": "海外の出品（送料・関税が不明のため仕入れに使わない）", "fx_unconfirmed": "為替が未確認（円換算しない）", "fx_mismatch": "円換算が為替と合わない", "currency_unspecified": "通貨・原価格の記載がない（海外の行は必須）",
    "duplicate_sold": "同じ成約の重複", "no_item_url": "個別の成約ページの URL がない",
    "price_kind_OPEN_PRICE": "オープン価格で金額が確認できない", "price_kind_NOT_FOUND": "公式の価格を確認できない",
}


MKT_STATUS = {"AVAILABLE": "取得できた", "PARTIAL": "一部取得", "BLOCKED": "取得できない（未取得）", "FAILED": "取得に失敗（未取得）", "NOT_SUPPORTED": "提供されていない（未取得）",
              "NOT_CONFIGURED": "未設定（未取得）", "PENDING_APPROVAL": "承認待ち（未取得）"}
MKT_REASON = {
    "no_official_api_search_scrape_prohibited": "公式 API が無く、検索結果の取得は行わない方針のため",
    "official_api_discontinued": "公式 API が 2020 年に終了しているため",
    "no_official_api_robots_disallow_search": "公式 API が無く、robots.txt が検索を禁止しているため",
    "official_api_not_configured": "公式 API の資格情報が未登録のため",
    "official_api_not_enabled": "公式 API が有効化されていないため",
    "adapter_not_implemented": "公式 API のアダプターが未実装のため",
    "rows_from_research_file": "調査員が根拠 URL つきで読んだ行だけ",
    "adapter_not_run": "公式 API のアダプターを今回は実行していないため",
    "api_listing_only": "公式 API で出品中の価格だけ（成約は審査制で未承認）", "api_ok": "公式 API で取得",
    "api_dry_run": "API_DRY_RUN が有効のため通信していない", "ebay_insights_not_approved": "成約（Marketplace Insights）が未承認のため",
    "sold_license_unconfirmed": "成約データの保存ライセンスが未確認のため", "listing_failed_sold_ok": "出品の取得に失敗（成約だけ取得）",
}
FEE_STATUS = {"CONFIRMED": "確認済み（一次情報の本文）", "UNVERIFIED": "未検証（本文を読めていない）", "UNKNOWN": "不明", "NOT_APPLICABLE": "なし（買取）"}
CRED = {"NOT_CONFIGURED": "未登録", "CONFIGURED": "登録済み", "NOT_REQUIRED": "不要（API なし）"}


def _rows(n) -> str:
    return "未取得" if n is None else f"{int(n)} 件"        # 未取得（None）を「0 件」と書かない


def _markets(market: dict) -> str:
    mk = market.get("secondary_markets") or []
    if not mk:
        return ""
    rows = "".join(
        f'<tr><th scope="row">{_e(m.get("label"))}</th><td><b title="{_e(m.get("status"))}">{_e(MKT_STATUS.get(m.get("status"), "状態を確認中"))}</b></td>'
        f'<td>{_e(MKT_REASON.get(m.get("reason"), m.get("reason")))}{"（公式 API の取得に失敗しました）" if m.get("api_error") else ""}</td><td>{_e(CRED.get(m.get("credentials"), m.get("credentials")))}</td>'
        f'<td class="num">{_e(_rows(m.get("listing_rows")))}</td><td class="num">{_e(_rows(m.get("sold_rows")))}</td>'
        f'<td>{_e(FEE_STATUS.get(m.get("fee_status"), m.get("fee_status")))}{" ・" + str(round(100 * m["fee_rate"], 1)) + "%" if m.get("fee_rate") else ""}</td>'
        f'<td>{_e(m.get("checked_on"))}</td></tr>' for m in mk)
    apis = "".join(f'<li>{_e(a.get("label"))}の公式 API: {_e(CRED.get(a.get("reason"), "未登録" if a.get("reason") == "NOT_CONFIGURED" else "未有効・未実装"))}（{_e(a.get("scope"))}）</li>'
                   for a in market.get("retail_apis") or [])
    return ('<h2>二次流通の取得状況（市場ごと）</h2>'
            '<div class="note">取得できなかった市場は「未取得」であって、出品や成約が無いという意味ではありません。検索結果の取得は行わず、公式 API と、根拠 URL つきで読んだ行だけを使います。</div>'
            '<details class="spec"><summary>市場ごとの表を開く</summary><div class="tw"><table><thead><tr><th>市場</th><th>状態</th><th>理由</th><th>API 資格情報</th><th>出品（Listing）</th><th>成約（Sold）</th><th>販売手数料</th><th>確認日</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></details>'
            + (f'<ul class="mut">{apis}</ul>' if apis else ""))


def _kinds(summ: dict, market: dict | None = None) -> str:
    fd = summ.get("found") or {}
    mk = (market or {}).get("secondary_markets") or []
    no_l = bool(mk) and all(m.get("listing_rows") is None for m in mk)      # 全市場が未取得なら「0 件」と書かない
    no_s = bool(mk) and all(m.get("sold_rows") is None for m in mk)
    return ('<h2>価格の種類ごとの確認状況</h2><div class="grid">'
            f'<div class="kv"><span title="Primary Market">新品の公式・販売店の価格</span><b>{_e(fd.get("official_or_retail_prices"))} 件</b></div>'
            f'<div class="kv"><span title="Buyback">買取価格</span><b>{_e(fd.get("buyback"))} 件</b></div>'
            f'<div class="kv"><span title="Secondary Listings">二次流通の出品中</span><b>{"未取得（全市場）" if no_l and not fd.get("listing") else _e(fd.get("listing")) + " 件"}</b></div>'
            f'<div class="kv"><span title="Secondary Sold">二次流通の成約</span><b>{"未取得（全市場）" if no_s and not fd.get("sold") else _e(fd.get("sold")) + " 件"}</b></div></div>')


def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _yen(v) -> str:
    return "—" if v is None else f"¥{int(v):,}"


def _signed(v) -> str:
    return "—" if v is None else ("+" if v > 0 else "−" if v < 0 else "") + f"¥{abs(int(v)):,}"


def _link(url, label) -> str:
    u = str(url or "")
    safe = u.startswith(("http://", "https://")) and not re.search(r"[\\\s\x00-\x1f\x7f@]", u)
    return f'<a href="{_e(u)}" target="_blank" rel="noopener nofollow">{_e(label)}</a>' if safe else _e(label)


HIDDEN_COND_REASON = "鮮度切れ・引き継ぎ・外れ値確認待ちのため、店舗印なしの試算は表示しません（確認日が新しくなったら再計算）"


def _reasons(rs, hide_conditional: bool = False) -> str:
    """判断の理由（文字列）。条件付きの試算を隠すカードでは、『店舗印なしの場合だけ黒字』も言い換える。"""
    return "、".join((HIDDEN_COND_REASON if (hide_conditional and r == "conditional_profit_only") else REASON.get(r, r)) for r in rs or []) or "—"


STALE_SENTINEL = 999                      # 調査日を解釈できない／未来のとき。どの経過日数の上限も超える（古い扱い）

# ---------------------------------------------------------------- runtime freshness（ページを開いた時点の鮮度。TCG と同じ data-fb-* と JS_FRESHNESS）
_FB_CSS = "[data-fb-live][hidden],[data-fb-stale][hidden]{display:none!important}"


def _load_cfg() -> dict:
    from src.research.camera_refresh import load_config      # 設定の唯一の定義は config/camera_routes.yaml（ここに数値を書かない）
    return load_config()


def _days_or_none(v) -> int | None:
    """設定の日数。正の整数または整数値の float（0 を含む。0 は当日 24:00 まで有効）だけ。無い・不正（負・bool・非整数・数値以外）は None（設定不明 = fail-closed。HOME・iPhone と同じ規則）。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if isinstance(v, int) and v >= 0 else None


def _hours_or_nan(v) -> float:
    """設定不明（None）は nan（JS は UNKNOWN_FRESHNESS = 出さない）。"""
    d = _days_or_none(v)
    return float("nan") if d is None else rf.days_to_hours(d)


class _FB:
    """Camera ページの表示時の鮮度。期間は config/camera_routes.yaml の freshness から（在庫 stock_days → 72 時間、価格 executable_days → 192 時間）。
    1 要素は 1 組の obs/max しか持てないため、複数の期限に依存する要素は期限ごとに入れ子の data-fb-live で包む。
    観測時刻は各行の checked_at（日付）の 00:00 JST（rf.date_obs）だけ。生成時刻を使って新しく見せない。"""

    def __init__(self, cfg: dict | None = None):
        if cfg is None:
            try:
                cfg = _load_cfg()
            except Exception:  # noqa: BLE001 — 設定が読めないときは fail-closed（設定不明 = 購入候補・条件付き試算を出さない側。HOME と同じ）
                cfg = {}
        self.cfg = cfg
        fr = (self.cfg or {}).get("freshness") or {}
        self.stock_h = _hours_or_nan(fr.get("stock_days"))
        self.price_h = _hours_or_nan(fr.get("executable_days"))

    def wrap(self, inner: str, group: str, deps: list, tag: str = "span") -> str:
        for date, kind in reversed(deps):
            mx = self.stock_h if kind == "stock" else self.price_h
            inner = f'<{tag} data-fb-live data-fb-group="{_e(group)}" {rf.attrs(rf.date_obs(date), self.cfg, max_hours=mx)} hidden>{inner}</{tag}>'
        return inner

    @staticmethod
    def stale(group: str, inner: str, tag: str = "span") -> str:
        return f'<{tag} data-fb-stale data-fb-group="{_e(group)}">{inner}</{tag}>'

    @staticmethod
    def act_deps(b: dict, sl: dict) -> list:
        """購入候補・購入できる: 在庫（72h）・買値の価格（192h）・売値（192h）。"""
        return [(b.get("checked_at"), "stock"), (b.get("checked_at"), "price"), ((sl or {}).get("checked_at"), "price")]

    @staticmethod
    def price_deps(b: dict, sl: dict) -> list:
        """利益・ROI・条件付き試算: 買値の価格（192h）・売値（192h）。"""
        return [(b.get("checked_at"), "price"), ((sl or {}).get("checked_at"), "price")]


STUB_PF = '<span class="mut">価格再確認待ち</span>'
STUB_EXPIRED = '<span class="mut">（期限切れ・再確認待ち）</span>'
STUB_ACT = '<span class="mut">在庫・価格の再確認待ち</span>'


def _gate(fx, kind: str, b: dict, sl: dict | None, inner: str, stub: str | None = None, tag: str = "span") -> str:
    """表示時に鮮度を確認できたときだけ見せる包み。fx=None（単体呼び出し・テスト）は包まない。kind: act（購入可否・購入候補）/ pf（利益・ROI）/ cd（条件付き試算）。"""
    if not fx or not inner:
        return inner
    fb, gid = fx
    g = f"{gid}-{kind}"
    out = fb.wrap(inner, g, fb.act_deps(b or {}, sl or {}) if kind == "act" else fb.price_deps(b or {}, sl or {}), tag)
    return out + (fb.stale(g, stub, tag) if stub else "")


_NOTE_KEY_PREFIXES = ("BUY_STOCK_", "SINGLE_BUYBACK_SHOP")


def _split_json_keys(r: dict | None) -> tuple[list, list]:
    """ルート JSON の conditional が持つ理由（blocked_reasons = 隠す／not_actionable_reasons = 注記）。
    古い出力（買えない系も blocked_reasons に入っていた）は、注記の key を注記側に寄せる。"""
    hide, note = [], []
    for c in (r or {}).get("conditional") or []:
        if not isinstance(c, dict):
            continue
        for k in (c.get("blocked_reasons") or []):
            (note if str(k).startswith(_NOTE_KEY_PREFIXES) else hide).append(k)
        note += list(c.get("not_actionable_reasons") or [])
    return hide, note


def _hide_keys(b: dict, sl: dict | None, r: dict | None = None, now_age: int | None = None) -> list:
    """試算を隠す理由のキー（鮮度切れ・引き継ぎ・外れ値確認待ち）。判定は camera_routes.conditional_hide_reasons だけ。JSON 側が付けたキーがあれば足す。"""
    keys = list(conditional_hide_reasons(b, sl or None, now_age_days=now_age))
    return keys + [k for k in dict.fromkeys(_split_json_keys(r)[0]) if k not in keys]


def _note_keys(b: dict, sl: dict | None, r: dict | None = None, now_age: int | None = None) -> list:
    """試算に併記する理由のキー（買えない・在庫確認が古い・買取 1 店のみ）。判定は camera_routes.conditional_notes だけ。"""
    keys = list(conditional_notes(b, sl or None, now_age_days=now_age))
    return keys + [k for k in dict.fromkeys(_split_json_keys(r)[1]) if k not in keys]


def _blocked_keys(b: dict, sl: dict | None, r: dict | None = None, now_age: int | None = None) -> list:
    """互換: 隠す理由 + 注記する理由（camera_routes.conditional_blockers と同じ並び）。"""
    return _hide_keys(b, sl, r, now_age) + _note_keys(b, sl, r, now_age)


HIDE_TEXT = {"BUY_STALE": "買値の確認日が古い", "BUY_CARRIED": "買値は前回データの引き継ぎのため参考値",
             "SELL_STALE": "売値の確認日が古い（引き継ぎ・期限切れ・不明）", "SELL_CARRIED": "売値の確認日が古い（引き継ぎ・期限切れ・不明）",
             "SELL_OUTLIER_REVIEW": "買取の最高が他店より極端に高く、外れ値の確認待ち"}
HIDE_CAUSE = {"BUY_STALE": "鮮度切れ", "SELL_STALE": "鮮度切れ", "BUY_CARRIED": "引き継ぎ", "SELL_CARRIED": "引き継ぎ", "SELL_OUTLIER_REVIEW": "外れ値確認待ち"}


def _hide_texts(b: dict, sl: dict | None, r: dict | None = None, now_age: int | None = None) -> list:
    """試算を隠す理由の文。実際の状態で言い分ける（売値・買値が新しいのに『古い』と書かない）。"""
    return list(dict.fromkeys(HIDE_TEXT[k] for k in _hide_keys(b, sl, r, now_age) if k in HIDE_TEXT))


def _blocked_reasons(b: dict, sl: dict | None, r: dict | None = None, now_age: int | None = None) -> list:
    """互換: 隠す理由の文。"""
    return _hide_texts(b, sl, r, now_age)


def _hides_conditional(r: dict, b: dict, sl: dict, now_age: int | None = None) -> bool:
    """条件付きの試算（金額・ROI）を隠すか。隠す理由があるときだけ True。買えないだけでは隠さない。"""
    return bool(sl) and any(isinstance(c, dict) for c in (r.get("conditional") or [])) and bool(_hide_keys(b, sl, r, now_age))


BASIS = {"STAMPED_WARRANTY": "保証書に店舗印ありの価格（完品より減額）"}
BASIS_SHORT = {"STAMPED_WARRANTY": "店舗印ありの価格"}


def _basis(s) -> str:
    """売値の基準の注記（店で買った新品を売る前提の価格など）。"""
    return BASIS.get((s or {}).get("basis"), "")


def _why_sell(s: dict) -> str:
    """「なぜこの売値か」。買取か成約中央値か、その根拠。"""
    if not s:
        return "—"
    ev = s.get("evidence") or {}
    if s.get("price_type") == "SOLD_MEDIAN":
        return f"成約中央値（{ev.get('sample_count')}件・期間 {ev.get('period')}・{COND.get(s.get('condition'), s.get('condition'))}）"
    upd = s.get("source_updated_at") or "更新日不明"
    note = f"・{_basis(s)}" if _basis(s) else ""
    return (f"買取価格（{COND.get(s.get('condition'), '')}・{s.get('source')}{note}・店の更新 {upd}・"
            f"比較できた買取 {ev.get('shops', 1)} 店）")


def _row_stale(r: dict, now: datetime, buy_days: int = 2, sell_days: int = 7) -> bool:
    """行ごとの古さ。仕入れ（在庫）は buy_days 日、売値は sell_days 日を超えたら、BUY を出さない。未来の日付も古い扱い。"""
    out = []
    for x, lim in ((r.get("buy") or {}, buy_days), (r.get("sell") or {}, sell_days)):
        d = parse_dt(x.get("checked_at")) if x.get("checked_at") else None
        if d is None or d > now + timedelta(days=1) or (now - d).days > lim:
            out.append(True)
    return bool(out)


def _row_date_bad(r: dict, now: datetime) -> bool:
    """買値・売値の確認日が読めない／未来のとき True（条件付きの試算を出さない。経過日数では判定できない）。"""
    for x in (r.get("buy") or {}, r.get("sell") or {}):
        d = parse_dt(x.get("checked_at")) if x.get("checked_at") else None
        if d is None or d.astimezone(JST).date() > now.astimezone(JST).date():     # HOME の _is_future と同じ: now（JST の日付）より後は未来 = UNKNOWN
            return True
    return False


ROUTE_SHORT = {"A": "正規店→買取", "B": "正規店→二次流通", "C": "二次流通→買取", "D": "二次流通→二次流通"}


def _route_short(r: dict) -> str:
    return ROUTE_SHORT.get(r.get("route_type"), str(r.get("route_type") or "—"))


def _route_html(r: dict) -> str:
    """ルート名。矢印の前後で自然に折り返し、語の途中（買／取）では折らない。"""
    return f'<span class="rt">{"→<wbr>".join(_e(x) for x in _route_short(r).split("→"))}</span>'


_CAMERA_CSS = (
    "main{max-width:1240px}.rt{white-space:nowrap}"
    "@media (max-width:639px){.dcard .hero .m--route{grid-column:1/-1}.dcard .hero .m--route b{font-size:1rem}"
    ".dcard .why{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}"
    ".dcard .cond{margin:.5rem 0;font-size:.88rem}.dcard .cond div{overflow-wrap:anywhere;word-break:break-word;margin:.15rem 0}"
    ".dcard .cond .cond-t{min-width:0;margin:.3rem 0}.dcard .cond .cond-t .num{white-space:normal}"
    ".dcard .cond .cond-ul{margin:.3rem 0 0 1.1rem;padding:0}.dcard .cond .cond-ul li{margin:.1rem 0;overflow-wrap:anywhere}"
    + _FB_CSS
)


def _roi(v) -> str:
    """ROI の表示。値は変えず、負の符号だけ金額と同じ U+2212 にそろえる。"""
    return "—" if v is None else f"{v}%".replace("-", "−")


def _badge(label: str, tone: str) -> str:
    return f'<span class="sbadge sbadge--{_e(tone)}">{_e(label)}</span>'


def _decision_badge(r: dict, stale: bool, registered: bool = True, fx=None) -> str:
    """判断（BUY/WATCH/WAIT/SKIP）の新語バッジ。購入候補=緑（調査が古い・未登録なら緑にしない）。利益の色とは別軸。
    購入候補は、表示時に在庫・価格の鮮度を確認できたときだけ出す（fx あり）。"""
    d = r.get("decision")
    if d == "BUY":
        if stale:
            return _badge("調査が古い（参考）", "off")
        if not registered:
            return _badge("参考（未登録）", "wait")
        return _gate(fx, "act", r.get("buy") or {}, r.get("sell"), _badge("購入候補", "buy"), _badge("調査が古い（参考）", "off"))
    if d in ("WATCH", "WAIT"):
        return _badge("様子見", "wait")
    return _badge("見送り", "off")


def _is_go(r: dict, registered: bool = True, stale: bool = False) -> bool:
    """緑にしてよいのは購入候補（登録済み・判断が BUY・調査が古くない）だけ。様子見・確認待ち・未登録・古い調査は中立色。"""
    return bool(registered) and not stale and r.get("decision") == "BUY"


def _profit_badge(r: dict, registered: bool = True, stale: bool = False, fx=None) -> str:
    """利益の状態（黒字/赤字）。判断とは別に出す。赤字は net_profit が負のときだけ。黒字は購入候補のときだけ緑、それ以外は中立（灰）。
    価格に基づく表示なので、表示時に価格の鮮度を確認できたときだけ出す（fx あり）。"""
    net = r.get("net_profit")
    if r.get("profit_status") == "PROFITABLE" and (net or 0) > 0:
        if not registered:
            h = _badge("黒字（参考）", "off")
        else:
            h = _badge("黒字", "profit") if _is_go(r, registered, stale) else _badge("黒字", "off")
    elif net is not None and net < 0:
        h = _badge("赤字", "loss")
    else:
        h = _badge("利益なし", "off") if net is not None else ""
    return _gate(fx, "pf", r.get("buy") or {}, r.get("sell"), h, _badge("価格再確認待ち", "off"))


def _stock_html(stock) -> str:
    """買える状態。終了・休止・在庫なしは灰、抽選・予約は注意色のバッジ。購入できる・不明は文字だけ（緑にしない）。"""
    label = STOCK.get(stock, stock)
    tone = STOCK_TONE.get(stock)
    return _badge(label, tone) if tone else _e(label)


def _buy_state(r: dict, b: dict, sl: dict | None, badge: bool = True, now_age: int | None = None, fx=None) -> str:
    """買値の「買える状態」の表示。
    - 試算を隠す理由（鮮度切れ・引き継ぎ・外れ値確認待ち）があるのに stock=AVAILABLE → 『購入可否は判断できません』（隠す理由の関数と同じ判定）。
    - 在庫の確認だけが古い → 『購入できる』と言わず、再確認が必要と書く（購入可否の断定を避ける）。
    - 『購入できる』は、隠す理由も古い在庫確認も無いときだけ。さらに表示時に在庫・価格の鮮度を確認できたときだけ出す（fx あり）。
    - 抽選終了・在庫なし等の実状態（買えない系の注記だけ）は、従来どおりその状態のバッジを出す。"""
    stock = b.get("stock")
    if stock == "AVAILABLE":
        hide = _hide_texts(b, sl, r, now_age)
        if hide:
            txt = "・".join(hide) + "のため購入可否は判断できません"
            return _badge(txt, "off") if badge else _e(txt)
        if "BUY_STOCK_OLD" in _note_keys(b, sl, r, now_age):
            txt = "在庫の確認が古い（購入可否は再確認が必要）"
            return _badge(txt, "off") if badge else _e(txt)
        base = _stock_html(stock) if badge else _e(STOCK.get(stock, stock))
        return _gate(fx, "act", b, sl, base, _badge("再確認待ち", "off") if badge else "再確認待ち")
    return _stock_html(stock) if badge else _e(STOCK.get(stock, stock))


COND_ROW = {"COMPLETE_NO_STAMP": "店舗印なし（条件付き試算）"}
_DEFINITE_STOCK = ("BUY_STOCK_UNKNOWN", "BUY_STOCK_OLD")


def _note_items(notes: list) -> list:
    """条件付き試算に必ず併記する項目（1 項目 1 行で表示する）。現在購入できない（実状態）／店舗印なしの場合に限る／買取価格は購入前に再確認が必要／購入推奨ではありません／買取 1 店のみ（該当時）。"""
    parts = []
    states = []
    for k in notes:
        if k == "BUY_STOCK_OLD":
            states.append("在庫の確認が古い")
        elif k == "BUY_STOCK_UNKNOWN":
            states.append("在庫不明")
        elif k.startswith("BUY_STOCK_"):
            st = k[len("BUY_STOCK_"):]
            states.append(STOCK.get(st, st))
    if states:
        definite = any(k.startswith("BUY_STOCK_") and k not in _DEFINITE_STOCK for k in notes)
        parts.append("現在購入できない（実状態: " + "／".join(dict.fromkeys(states)) + "）" if definite
                     else "現在購入できない、または買えるかどうか未確認（実状態: " + "／".join(dict.fromkeys(states)) + "）")
    parts += ["店舗印なしの場合に限る", "買取価格は購入前に再確認が必要"]
    if "SINGLE_BUYBACK_SHOP" in notes:
        parts.append("買取は 1 店のみ（他店との比較なし）")
    parts.append("購入推奨ではありません")
    return parts


def _note_line(notes: list) -> str:
    """条件付き試算に必ず併記する項目を 1 行にしたもの（互換用。画面は _note_items を箇条書きで出す）。"""
    return "／".join(_note_items(notes))


def _money_cls(v) -> str:
    return "pos" if (v or 0) > 0 else "neg" if (v or 0) < 0 else ""


def _cond_cls(v, notes: list) -> str:
    """条件付き試算の損益の文字色。緑（.pos）は『買える状態（注記に BUY_STOCK_* が無い）』のプラスだけ。購入できない（抽選終了・在庫なし・在庫不明等）は中立色。"""
    if (v or 0) < 0:
        return "neg"
    if (v or 0) > 0 and not any(str(k).startswith("BUY_STOCK_") for k in notes):
        return "pos"
    return ""


def _conditional_html(r: dict, b: dict, sl: dict, now_age: int | None = None, fx=None) -> str:
    """安全側（店舗印あり）の買取と、条件付き（店舗印なし）の試算を分けて見せる。
    根拠のある試算は『現在購入できない』だけでは隠さず、金額・ROI を『条件付き試算』として出し、実状態と注意を同じ欄に併記する。
    鮮度切れ・引き継ぎ・外れ値確認待ち・費用不明の試算は金額を出さない（隠すときは過去の参考価格を取得日つきで残す）。
    条件付き試算は表示専用: 購入推奨ではない。プラスの損益は文字色（.pos/.neg）だけで、バッジは中立・注意色（緑にしない）。"""
    cond = [c for c in (r.get("conditional") or []) if isinstance(c, dict)]
    if not cond or not sl:
        return ""
    hide_keys = _hide_keys(b, sl, r, now_age)
    hide = _hide_texts(b, sl, r, now_age)
    notes = _note_keys(b, sl, r, now_age)
    net, roi = r.get("net_profit"), r.get("roi_pct")
    safe_cls = "neg" if (net or 0) < 0 else ""
    lines = []
    if hide_keys:
        causes = "・".join(dict.fromkeys(HIDE_CAUSE[k] for k in hide_keys if k in HIDE_CAUSE)) or "確認不足"
        prices = (f'買取 {_yen(sl.get("price"))}（店舗印あり・{_md(sl.get("checked_at"))} 確認）'
                  + "".join(f'、店舗印なしの買取 {_yen(c.get("sell_price"))}' for c in cond)
                  + f'・買値 {_yen(b.get("price"))}（{_md(b.get("checked_at"))} 確認）')
        lines.append(f'<div class="mut">{_badge("参考値", "off")} {_e("・".join(hide))}。{_e(HIDDEN_COND_REASON)}</div>')
        lines.append(f'<div>過去の参考: {prices}。試算は{_e(causes)}のため非表示</div>')
        lines.append(f'<div><b>安全側（保証書に店舗印あり）</b>: 買取 {_yen(sl.get("price"))}（{_md(sl.get("checked_at"))} 確認） → 利益 '
                     + _gate(fx, "pf", b, sl, f'<span class="{safe_cls}">{_signed(net) if net is not None else "未計算"}</span>（ROI {_e(_roi(roi))}）', STUB_PF)
                     + '。この価格で判断しています</div>')
    else:
        safe_profit = f'<b class="{safe_cls}">{_signed(net) if net is not None else "未計算"}</b>'
        rows = ['<tr><th scope="row">店舗印あり（判断の基準）</th>'
                f'<td class="num">{_yen(sl.get("price"))}<div class="mut">（{_md(sl.get("checked_at"))} 確認）</div></td><td class="num">基準</td>'
                f'<td class="num">{_gate(fx, "pf", b, sl, safe_profit, STUB_PF) if net is not None else safe_profit}</td>'
                f'<td class="num">{_gate(fx, "pf", b, sl, _e(_roi(roi)), STUB_PF) if roi is not None else "—"}</td></tr>']
        for c in cond:
            cn, cr_ = c.get("net_profit"), c.get("roi_pct")
            diff = (c.get("sell_price") or 0) - (sl.get("price") or 0)
            mc = _cond_cls(cn, notes)
            if cn is None:
                pc, rc = "未計算（購入送料が不明）", "—"
            else:
                pc = _gate(fx, "cd", b, sl, f'<b class="{mc}">{_signed(cn)}</b>', STUB_PF)
                rc = _gate(fx, "cd", b, sl, f'<span class="{mc}">{_e(_roi(cr_))}</span>', STUB_PF)
            # 買取価格・価格差も条件付き試算の一部。期限（売値 executable_days）を過ぎたら live ごと隠し、取得日つきの過去の参考だけ残す
            ref = (f'<span class="mut">過去の参考: 店舗印なしの買取 {_yen(c.get("sell_price"))}（{_md(sl.get("checked_at"))} 確認）。'
                   '期限切れのため試算は非表示</span>')
            price_td = _gate(fx, "cd", b, sl, _yen(c.get("sell_price")), ref)
            diff_td = _gate(fx, "cd", b, sl, _signed(diff), "—")
            rows.append(f'<tr><th scope="row">{_e(COND_ROW.get(c.get("key"), "店舗印なし（条件付き試算）"))} {_badge("条件付き試算", "wait")}</th>'
                        f'<td class="num">{price_td}</td><td class="num">{diff_td}</td>'
                        f'<td class="num">{pc}</td><td class="num">{rc}</td></tr>')
        lines.append('<table class="cond-t"><thead><tr><th>買取条件</th><th>買取価格</th><th>安全側との価格差</th><th>利益</th><th>ROI</th></tr></thead>'
                     f'<tbody>{"".join(rows)}</tbody></table>')
    items = "".join(f"<li>{_e(t)}</li>" for t in _note_items(notes))
    lines.append(f'<div class="mut cond-must"><ul class="cond-ul">{items}<li>必要条件: {_e(cond[0].get("requires"))}</li></ul></div>')
    now_stock = (_badge("確認が古い／鮮度不明のため購入可否は判断できません", "off") if (hide_keys and b.get("stock") == "AVAILABLE")
                 else _buy_state(r, b, sl, True, now_age, fx))
    lines.append(f'<div class="mut">現在の購入可否: {now_stock}／確認日: 買値 {_md(b.get("checked_at"))}・買取 {_md(sl.get("checked_at"))}'
                 f'（店の更新 {_md(sl.get("source_updated_at")) if sl.get("source_updated_at") else "不明"}）／過去の参考価格: 買値 {_yen(b.get("price"))}・買取 {_yen(sl.get("price"))}（取得日時点）</div>')
    return f'<div class="note cond" aria-label="売値の条件別">{"".join(lines)}</div>'


def _reasons_html(rs, hide_conditional: bool, b: dict, sl: dict | None, fx=None) -> str:
    """判断の理由（HTML）。『店舗印なしの場合だけ黒字』は条件付き試算と同じ鮮度の確認を通ったときだけ出す。"""
    out = []
    for k in rs or []:
        if k == "conditional_profit_only":
            out.append(_e(HIDDEN_COND_REASON) if hide_conditional else _gate(fx, "cd", b, sl, _e(REASON[k]), STUB_EXPIRED))
        else:
            out.append(_e(REASON.get(k, k)))
    return "、".join(out) or "—"


def _card(p: dict, r: dict, stale: bool, now_age: int | None = None, fx=None) -> str:
    """判断カード（商品・買値・売値・利益/ROI・ルート・判断）。表の詳細をたたんで持つ。ルートは A〜D の記号でなく語で出す。"""
    b, sl = r["buy"], r["sell"]
    if stale and now_age is None:
        now_age = STALE_SENTINEL                          # 古い扱いなのに経過日数が無い（調査日不明）→ 条件欄・購入可否も古い扱いに一本化
    reg = bool(p.get("registered"))
    net = r.get("net_profit")
    net_cls = "pos" if (net or 0) > 0 and _is_go(r, reg, stale) else "neg" if (net or 0) < 0 else ""        # 緑は購入候補だけ。様子見・未登録・古い調査の黒字は中立色
    ref = "" if reg else ' <span class="chip chip--ref">未登録・参考</span>'
    status = _buy_state(r, b, sl, now_age=now_age, fx=fx)
    profit = _gate(fx, "pf", b, sl, _signed(net), STUB_PF) if net is not None else "未計算"
    roi = _gate(fx, "pf", b, sl, _e(_roi(r.get("roi_pct"))), STUB_PF) if r.get("roi_pct") is not None else "—"
    return (f'<article class="dcard{" dcard--off" if r.get("decision") != "BUY" or stale else ""}">'
            f'<header><h3>{_e(p["product"])}{ref}</h3><div class="badges">{_decision_badge(r, stale, reg, fx)}{_profit_badge(r, reg, stale, fx)}</div></header>'
            f'<div class="hero"><div class="m"><span>買値</span><b>{_yen(b["price"])}</b><em>{_e(b["source"])}（{_md(b.get("checked_at"))} 確認）</em></div>'
            f'<div class="m"><span>売値</span><b>{_yen(sl["price"]) if sl else "—"}</b><em>{_e(sl["source"]) if sl else ""}（{_e(PTYPE.get(sl["price_type"], sl["price_type"])) if sl else ""}{("・" + _e(_basis(sl))) if _basis(sl) else ""}・{_md(sl.get("checked_at")) if sl else "—"} 確認）</em></div>'
            f'<div class="m"><span>利益</span><b class="{net_cls}">{profit}</b></div>'
            f'<div class="m"><span>ROI</span><b>{roi}</b></div>'
            f'<div class="m m--route"><span>買い方→売り方</span><b>{_route_html(r)}</b></div>'
            f'<div class="m"><span>買える状態</span><b>{status}</b></div></div>'
            f'{_conditional_html(r, b, sl, now_age, fx)}'
            f'<div class="mut why">判断の理由: {_reasons_html(r.get("reasons"), _hides_conditional(r, b, sl, now_age), b, sl, fx)}</div>'
            f'<details><summary>買う場所・売る場所・確認日</summary>'
            f'<div>買う場所: {_link(b.get("url"), b["source"])}（{_e(PTYPE.get(b["price_type"], b["price_type"]))}・{_e(COND.get(b["condition"], b["condition"]))}）</div>'
            f'<div>売る場所: {_link(sl.get("url"), sl["source"]) if sl else "—"}</div>'
            f'<div class="mut">確認日 {_md(b.get("checked_at"))}／信頼度 <span title="confidence: {_e(r.get("confidence"))}">{_e(CONF_JA.get(r.get("confidence"), r.get("confidence")))}</span>'
            f'／内部参照: ルート {_e(r["route_type"])}</div></details></article>')


def _row(p: dict, r: dict, stale: bool, now_age: int | None = None, fx=None) -> str:
    """詳細表の 1 行（8 列。旧表記の判断語はこの表に残す）。"""
    b, s = r["buy"], r["sell"]
    if stale and now_age is None:
        now_age = STALE_SENTINEL
    dec_html = ('調査が古い（参考）' if (stale and r["decision"] == "BUY") else
                f'<span title="{_e(DECISION.get(r["decision"], r["decision"]))}">{_e(DECISION_JA.get(r["decision"], r["decision"]))}</span>')
    if r["decision"] == "BUY" and not stale:
        dec_html = _gate(fx, "act", b, s, dec_html, "調査が古い（参考）")          # BUY の語（title も）は、表示時に鮮度を確認できたときだけ出す
    net = _gate(fx, "pf", b, s, _signed(r["net_profit"]), STUB_PF) if r["net_profit"] is not None else "未計算"
    roi = _gate(fx, "pf", b, s, _e(_roi(r["roi_pct"])), STUB_PF) if r["roi_pct"] is not None else "—"
    cls = "ok" if r["decision"] == "BUY" and not stale else ""
    net_cls = "pos" if (r["net_profit"] or 0) > 0 and _is_go(r, bool(p.get("registered")), stale) else "neg" if (r["net_profit"] or 0) < 0 else ""
    c_ = r.get("costs") or {}
    cost = _yen(sum(int(c_.get(k) or 0) for k in ("purchase_shipping", "outbound_shipping", "selling_fee", "other"))) if c_ else "—"
    carried = "（買取は引き継ぎ・古い確認）" if (s and s.get("carried")) or b.get("carried") else ""
    return (f'<tr class="{cls}"><th scope="row" data-label="商品"><div class="v">{_e(p["product"])}{"" if p.get("registered") else " <span class=mut>（未登録・参考）</span>"}</div></th>'
            f'<td data-label="買う場所・買値"><div class="v">{_link(b.get("url"), b["source"])} <b>{_yen(b["price"])}</b><br>'
            f'<span class="mut">{_e(PTYPE.get(b["price_type"], b["price_type"]))}・{_e(COND.get(b["condition"], b["condition"]))}・{_buy_state(r, b, s, badge=False, now_age=now_age, fx=fx)}</span></div></td>'
            f'<td data-label="売る場所・売値"><div class="v">{_link(s.get("url"), s["source"]) if s else "—"} <b>{_yen(s["price"]) if s else "—"}</b><br>'
            f'<span class="mut">{_e(PTYPE.get(s["price_type"], s["price_type"])) if s else "—"}{("・" + _e(_basis(s))) if _basis(s) else ""}</span></div></td>'
            f'<td class="num" data-label="費用"><div class="v">{cost}</div></td><td class="num" data-label="純利益"><div class="v {net_cls}">{net}</div></td>'
            f'<td class="num" data-label="ROI"><div class="v">{roi}</div></td>'
            f'<td data-label="ルート"><div class="v">{_route_html(r)}<br><span class="mut" title="Route {_e(r["route_type"])}">ルート {_e(r["route_type"])}</span></div></td>'
            f'<td data-label="判断"><div class="v"><b>{dec_html}</b><br><span class="mut">{_reasons_html(r.get("reasons"), _hides_conditional(r, b, s, now_age), b, s, fx)}</span><br>'
            f'<span class="mut">確認日 {_md(b.get("checked_at"))}{carried}／信頼度 <span title="confidence: {_e(r.get("confidence"))}">{_e(CONF_JA.get(r.get("confidence"), r.get("confidence")))}</span></span></div></td></tr>')


def _detail(p: dict, r: dict, common_why: frozenset = frozenset(), fx=None) -> str:
    c = r["costs"] or {}
    why = _why_sell(r["sell"])
    why_t = "共通の根拠" if why in common_why else why
    calc = (f'売値 {_yen(r["sell"]["price"])}（{_e(why_t)}）− 仕入れ {_yen(r["buy"]["price"])} − 購入送料 {_yen(c.get("purchase_shipping"))}'
            f' − 発送など {_yen(c.get("outbound_shipping"))} − 販売手数料 {_yen(c.get("selling_fee"))}'
            f'{"（" + str(round(100 * c["selling_fee_rate"])) + "%・" + _e(FEE_STATUS.get(r.get("fee_status"), r.get("fee_status"))) + "）" if c.get("selling_fee_rate") else "（買取は手数料なし）"}'
            f' − その他 {_yen(c.get("other"))} = 純利益 {_signed(r["net_profit"])}')
    return (f'<li><b>{_e(p["product"])} / {_e(_route_short(r))}</b>: '
            f'{_gate(fx, "pf", r["buy"], r["sell"], calc, "価格再確認待ちのため、計算の内訳は非表示です")}</li>')


def _secondary(p: dict) -> str:
    sec = p.get("secondary") or {}
    if not sec.get("listing") and not sec.get("sold") and not sec.get("listing_foreign"):
        return ""
    lf = "".join(f'<tr><th scope="row">{_e(v["market"])}（{_e(COND.get(v["family"], v["family"]))}）</th><td class="num">{_e(v["currency"])} {v["low"]:,.2f}</td>'
                 f'<td class="num">{_e(v["currency"])} {v["high"]:,.2f}</td><td class="num">{v["n"]}</td><td>{"円換算あり" if v.get("fx_status") == "CONFIRMED" else "為替が未確認のため円換算なし"}</td></tr>'
                 for v in (sec.get("listing_foreign") or {}).values())
    ls = "".join(f'<tr><th scope="row">{_e(COND.get(k, k))}</th><td class="num">{_yen(v["low"])}</td><td class="num">{_yen(v["high"])}</td>'
                 f'<td class="num">{v["n"]}</td><td>{_e(v["low_source"])}</td></tr>' for k, v in (sec.get("listing") or {}).items())
    sd = "".join(f'<tr><th scope="row">{_e(v["market"])}（{_e(COND.get(v["family"], v["family"]))}）</th><td class="num">{_yen(v["low"])}</td>'
                 f'<td class="num">{_yen(v["high"])}</td><td class="num">{_yen(v["median"])}</td><td class="num">{v["sample_count"]}</td>'
                 f'<td>{_e(v["period_start"])}〜{_e(v["period_end"])}</td><td>{"売値に使える" if v["eligible"] else "件数不足・売値にしない"}</td></tr>'
                 for v in (sec.get("sold") or {}).values())
    return (f'<section class="sku"><h3>{_e(p["product"])} — 二次流通</h3>'
            + (f'<div class="tw"><table><thead><tr><th>出品中（状態）</th><th title="Listing Low">出品の最安</th><th title="Listing High">出品の最高</th><th>件数</th><th>最安の出品元</th></tr></thead>'
               f'<tbody>{ls}</tbody></table></div><div class="mut">出品中の価格は売れた価格ではありません。出品の最高値は売値に使いません。</div>' if ls else "")
            + (f'<div class="tw"><table><thead><tr><th>海外の出品中（市場・状態）</th><th title="Listing Low">出品の最安（原通貨）</th><th title="Listing High">出品の最高（原通貨）</th><th>件数</th><th>為替</th></tr></thead>'
               f'<tbody>{lf}</tbody></table></div><div class="mut">海外の出品は希望価格で、売れた価格ではありません。送料・関税が不明のため、仕入れの利益計算には使いません。</div>' if lf else "")
            + (f'<div class="tw"><table><thead><tr><th>成約（市場・状態）</th><th title="SOLD Low">成約の最安</th><th title="SOLD High">成約の最高</th><th title="SOLD Median">成約の中央値</th><th title="SOLD Samples">成約の件数</th><th>期間</th><th>扱い</th></tr></thead>'
               f'<tbody>{sd}</tbody></table></div>' if sd else "")
            + "</section>")


def _live(l: dict, now: datetime) -> str:
    end = parse_dt(l.get("application_end")) if l.get("application_end") else None
    if end is None:
        return "応募期限を確認できません"
    return "終了" if end < now else "受付中・予定"


def _vgate(fb, group: str, routes: list, kinds: tuple, inner: str, stub: str, tag: str = "span") -> str:
    """結論バー・件数の鮮度の包み。まとめた件数・名前は、対象ルートのうち最も古い確認日で期限を決める（1 つでも期限切れなら出さない）。"""
    if fb is None or not routes or not inner:
        return inner

    def oldest(side: str):
        return min(((r.get(side) or {}).get("checked_at") for r in routes), key=lambda d: rf.date_obs(d))
    deps = ([(oldest("buy"), "stock")] if "stock" in kinds else []) + [(oldest("buy"), "price"), (oldest("sell"), "price")]
    return fb.wrap(inner, group, deps, tag) + fb.stale(group, stub, tag)


def _verdict(picks: list, fb=None) -> str:
    """最上部の結論バー（2 行に圧縮）。今日買えるもの（購入候補）と黒字の件数・商品名。値は既存のルートの再表示だけ。
    黒字の件数に数えるのは、登録済みで調査が古くないルートだけ。未登録・古い調査は「参考」として別に数える（緑にしない）。
    緑は購入候補（登録済み・実行可能）だけ。様子見の黒字は中立色。
    fb あり: 件数・名前は、表示時に在庫・価格の鮮度を確認できたときだけ出す（期限切れ後は「確認待ち」。件数だけ残さない）。"""
    buy = [(p, r) for p, r, st in picks if r["decision"] == "BUY" and not st and p.get("registered")]
    plus = [(p, r) for p, r, st in picks if (r.get("net_profit") or 0) > 0 and p.get("registered") and not st]
    ref_n = sum(1 for p, r, st in picks if (r.get("net_profit") or 0) > 0 and not (p.get("registered") and not st))
    buy_rs, plus_rs = [r for _p, r in buy], [r for _p, r in plus]

    def line(p, r):
        stock = STOCK.get((r.get("buy") or {}).get("stock"), "")
        return f'{_e(p["product"])}（{_signed(r["net_profit"])}・{_e(stock)}）'
    if buy:
        head = _vgate(fb, "cam-v-buy", buy_rs, ("stock", "price"), f'<span class="sbadge sbadge--buy">今日買えるもの {len(buy)} 件</span>',
                      '<span class="sbadge sbadge--off">今日買えるもの: 確認待ち</span>')
        who = _vgate(fb, "cam-v-buy", buy_rs, ("stock", "price"), "、".join(line(p, r) for p, r in buy[:2]), "再確認待ち")
    else:
        head = '<span class="sbadge sbadge--off">今日すぐ買えるもの 0 件</span>'
        who = "買ってよいと言えるルートはありません。"
    green = bool(buy) and bool(plus)
    ph = f'<span class="sbadge sbadge--{"profit" if green else "off"}">黒字 {len(plus)} 件</span>'
    if plus:
        pw = "、".join(line(p, r) for p, r in plus[:2]) + (f" ほか {len(plus) - 2} 件" if len(plus) > 2 else "")
        if not buy:
            pw += "（様子見）"
    else:
        pw = "黒字になるルートは確認できません。"
    if ref_n:
        pw += f"（参考 {ref_n} 件は除く）"
    if plus:
        ph = _vgate(fb, "cam-v-plus", plus_rs, ("price",), ph, '<span class="sbadge sbadge--off">利益の件数: 確認待ち</span>')
        # 件数・黒字の判定は価格（192h）だけで足りるが、名前の行は「…・購入できる」（在庫）も書くので、在庫（72h）と価格の入れ子 live で包む
        pw = _vgate(fb, "cam-v-plus-who", plus_rs, ("stock", "price"), pw, "再確認待ち")
    return (f'<section class="verdict" aria-label="今日の結論"><p class="vline">{head}<span>{who}</span></p>'
            f'<p class="vline">{ph}<span>{pw}</span></p></section>')


_TABLE_RE = re.compile(r"<table(?P<attrs>[^>]*)>(?P<body>.*?)</table>", re.S)
_ROW_RE = re.compile(r"<tr(?P<ra>[^>]*)>(?P<cells>.*?)</tr>", re.S)
_CELL_RE = re.compile(r"(<t[dh])(?P<ca>[^>]*)>(?P<inner>.*?)(</t[dh]>)", re.S)


def _stack_tables(html: str) -> str:
    """まだカード化していない表を、スマホ幅で 1 行 1 カードに積む表（nu-table--stack）にする。
    見出し（thead の th）をセルの data-label にし、中身を div.v で包む。結合セル（colspan）の行は触らない。"""
    def one(m):
        if "nu-table--stack" in m.group("attrs") or "data-label" in m.group("body"):
            return m.group(0)
        head = re.search(r"<thead>(.*?)</thead>", m.group("body"), re.S)
        if not head:
            return m.group(0)
        labels = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", head.group(1), re.S)]
        tb = re.search(r"<tbody>(.*?)</tbody>", m.group("body"), re.S)
        if not tb:
            return m.group(0)

        def row(rm):
            if "colspan" in rm.group("cells"):
                return rm.group(0)
            i = [0]

            def cell(cm):
                lab = labels[i[0]] if i[0] < len(labels) else ""
                i[0] += 1
                inner = cm.group("inner") if cm.group(1) == "<th" and "<" not in cm.group("inner") else f'<div class="v">{cm.group("inner")}</div>'
                return f'{cm.group(1)}{cm.group("ca")} data-label="{_e(lab)}">{inner}{cm.group(4)}'
            return f'<tr{rm.group("ra")}>' + _CELL_RE.sub(cell, rm.group("cells")) + "</tr>"
        new_tb = _ROW_RE.sub(row, tb.group(1))
        body = m.group("body").replace(tb.group(0), "<tbody>" + new_tb + "</tbody>")
        attrs = m.group("attrs")
        attrs = (attrs.replace('class="', 'class="nu-table--stack ', 1) if 'class="' in attrs else attrs + ' class="nu-table--stack"')
        return f"<table{attrs}>{body}</table>"
    return _TABLE_RE.sub(one, html)


def render(market: dict, *, now: datetime | None = None, cfg: dict | None = None) -> str:
    now = now or datetime.now(JST)
    fb = _FB(cfg)                                            # 在庫 72h・価格 192h は config/camera_routes.yaml の freshness から
    rd = market.get("research_date")
    try:
        d_ = (now.date() - datetime.strptime(str(rd), "%Y-%m-%d").date()).days
        stale = d_ > 2 or d_ < 0
        age_now = STALE_SENTINEL if d_ < 0 else d_
    except (TypeError, ValueError):
        stale = True
        age_now = STALE_SENTINEL
    prods = market.get("products") or []
    calc_rows, details, nocalc, cards, picks = [], [], [], [], []
    for p in prods:
        calc = [r for r in p["routes"] if r["profit_status"] != "NOT_CALCULATED"]
        for r in sorted(calc, key=lambda r: -(r["net_profit"] or 0)):
            st_ = stale or _row_stale(r, now)
            row_age = STALE_SENTINEL if _row_date_bad(r, now) else age_now      # 日付を読めない・未来の行だけ最古扱い。それ以外は表示時点の経過日数（買値・売値の価格は executable_days、在庫は stock_days で別々に判定）
            fx = (fb, f"c{len(calc_rows)}")                   # 行・カードごとの鮮度グループ（-act / -pf / -cd を後ろに付ける）
            calc_rows.append(_row(p, r, st_, row_age, fx))
            cards.append((0 if (r["net_profit"] or 0) > 0 else 1 if r["decision"] in ("WAIT", "WATCH") else 2, len(cards), _card(p, r, st_, row_age, fx)))
            picks.append((p, r, st_))
            details.append((p, r, fx))
        if not calc:
            best = next((r for r in p["routes"] if r["route_type"] == "A" and r.get("buy")), None) or next((r for r in p["routes"] if r.get("buy")), None)
            why = sorted({x for r in p["routes"] for x in r.get("reasons") or []})
            if any(o.get("price") and not o.get("reasons") for o in p["observations"]) or best:
                nocalc.append((p, _reasons(why)))
    why_cnt: dict = {}
    for _p, _r, _fx in details:                              # 同じ売値の根拠が 2 ルート以上で並ぶなら 1 回にまとめる
        _w = _why_sell(_r["sell"])
        why_cnt[_w] = why_cnt.get(_w, 0) + 1
    common_why = frozenset(w for w, n in why_cnt.items() if n >= 2 and w != "—")
    why_note = ("<p class=\"mut\">共通の根拠: " + "／".join(_e(w) for w in sorted(common_why)) + "</p>") if common_why else ""
    details = [_detail(p, r, common_why, fx) for p, r, fx in details]
    rs_cnt: dict = {}
    for _p, _t in nocalc:                                    # 計算できなかった理由も、同じ文が 2 機種以上なら 1 回にまとめる
        rs_cnt[_t] = rs_cnt.get(_t, 0) + 1
    common_rs = frozenset(t for t, n in rs_cnt.items() if n >= 2 and t != "—")
    rs_note = ('<p class="mut">共通の理由: ' + "／".join(_e(t) for t in sorted(common_rs, key=lambda t: -rs_cnt[t])) + "</p>") if common_rs else ""
    nocalc = [f'<tr><th scope="row">{_e(p["product"])}{"" if p.get("registered") else " <span class=mut>（未登録・参考）</span>"}</th>'
              f'<td>{_buy_summary(p, fb, f"nc{i}")}</td><td>{_e(_sell_summary(p))}</td><td>{"上記の共通の理由" if t in common_rs else _e(t)}</td></tr>'
              for i, (p, t) in enumerate(nocalc)]
    summ = market.get("summary") or {}
    rt = summ.get("routes") or {}
    fd = summ.get("found") or {}
    buy_rs = [r for p in prods for r in p["routes"] if r["decision"] == "BUY" and not (stale or _row_stale(r, now))]
    buy_n = len(buy_rs)
    buy_n_html = _vgate(fb, "cam-v-n", buy_rs, ("stock", "price"), f"{buy_n} 件", "確認待ち") if buy_n else f"{buy_n} 件"
    empty = ('<div class="note">計算できる利益ルートは 0 件です。確認できた価格だけで計算し、架空の商品や推測の価格で埋めていません。'
             '下の「計算できなかった機種と理由」を見てください。判断カードは、価格を確認できた商品が出たときに表示されます。</div>') if not calc_rows else ""
    cards = [c for _, _, c in sorted(cards, key=lambda x: (x[0], x[1]))]          # 黒字・様子見を先頭、赤字・見送りを後ろ（同じ商品内の利益順は維持）
    verdict = _verdict(picks, fb)
    src = _source_rows(market.get("source_results") or [])
    lots = "".join(
        f'<li><b>{_link(l.get("official_url"), l.get("product"))}</b> — {_e(l.get("retailer"))}／応募 {_e((l.get("application_start") or "")[:10])}〜{_e((l.get("application_end") or "")[:10])}'
        f'／{_e(_live(l, now))}／根拠: {_e(l.get("evidence"))}</li>' for l in market.get("lotteries") or []) or "<li>公式ページで確認できた抽選はありません</li>"
    hc = (market.get("hidden_counts") or {}).get("discovered_products_unverified", 0)
    html = f"""<!doctype html>
<html lang="ja" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>カメラ せどり判断 | プレ値速報</title><meta name="robots" content="index,follow"><style>{legacy_css()}{_CSS}{_CAMERA_CSS}</style></head>
<body>{site_nav("camera")}<main>
<p><a class="back" href="./">← プレ値速報へ戻る</a></p>
<h1>カメラ せどり判断</h1>
{verdict}
<p class="mut">調査日 {_md(rd)}（週 1 回の調査）</p>
{age_banner(rd, now)}
{empty}
<h2>判断カード</h2>
{"".join(cards) or '<p class="mut">判断できる商品はありません。</p>'}
<details class="note"><summary><b>この調査について</b>（確認できた価格だけで計算します）</summary><p>カードは黒字・様子見が先、赤字・見送りは後に並べています。購入・売却の前に各公式ページで最新の情報を確認してください。</p><p>{_plain(market.get("note"))}</p>
<p class="mut">調査データの生成 {_e(market.get("generated_at"))}／このページの状態は {_e(now.strftime("%Y-%m-%d %H:%M"))} 時点の判定です</p></details>
<div class="grid"><div class="kv"><span>調べた機種</span><b>{_e(summ.get("products_checked"))}</b></div>
<div class="kv"><span>買取価格を確認</span><b>{_e(fd.get("buyback"))} 件</b></div>
<div class="kv"><span>利益を計算できたルート</span><b>{_e(rt.get("confirmed"))} / {_e(rt.get("total"))}</b></div>
<div class="kv"><span>購入候補のルート</span><b>{buy_n_html}</b></div></div>
<h2>判断一覧（買う場所 → 売る場所）</h2>
<details class="spec"><summary>判断一覧の表を開く（カードと同じ内容を表で見る）</summary>
<div class="tw"><table class="nu-table--stack"><thead><tr><th>商品</th><th>買う場所・買値</th><th>売る場所・売値</th><th>費用</th><th>純利益</th><th>ROI</th><th>ルート</th><th>判断</th></tr></thead>
<tbody>{"".join(calc_rows) or '<tr><td colspan="8">計算できたルートはありません</td></tr>'}</tbody></table></div></details>
<div class="mut">利益が出ていても、買ってよいとは限りません（抽選・在庫・ROI・比較できる買取の数も条件です）。</div>
<details class="spec"><summary>買い方→売り方の4種類（正規店→買取など）</summary><div class="mut">A=正規店→買取（正規店・メーカーで買い、買取店へ売る）／B=正規店→二次流通（成約中央値で売る）／C=二次流通→買取（二次流通の最安で買い、買取店へ売る）／D=二次流通→二次流通（成約中央値で売る）。</div></details>
<h2>なぜこの売値か（計算の内訳）</h2>{why_note}<ul>{"".join(details) or "<li>計算できたルートはありません</li>"}</ul>
<h2>計算できなかった機種と理由</h2>
{rs_note}
<details class="spec"><summary>計算できなかった機種の表を開く（{len(nocalc)}件）</summary><div class="tw"><table><thead><tr><th>商品</th><th>確認できた買う側</th><th>確認できた売る側</th><th>計算できなかった理由</th></tr></thead><tbody>{"".join(nocalc) or '<tr><td colspan="4">なし</td></tr>'}</tbody></table></div></details>
{_kinds(summ, market)}
{_markets(market)}
<h2>二次流通（出品と成約は別物。最高の出品価格を売れる価格にしません）</h2>{"".join(_secondary(p) for p in prods) or "<p>確認できた二次流通の価格はありません（フリマ・オークションは検索結果を取得せず、成約は件数 3 以上・期間・個別の根拠が揃うものだけを使います）。</p>"}
<h2>抽選・予約（公式ページで確認できたもの）</h2><ul>{lots}</ul>
<h2>取得元の結果（読めた・読めなかった）</h2>
<details class="spec"><summary>取得元の表を開く（読めた・読めなかった）</summary><div class="tw"><table><thead><tr><th>取得元</th><th>種類</th><th>読めたブランド</th><th>読めなかったブランドと理由</th></tr></thead><tbody>{src}</tbody></table></div></details>
<ul><li>未確認の新商品 {_e(hc)} 件は、確認できるまで公開していません</li></ul>
<p class="mut">週次の調査で、価格・在庫・抽選の状況は変わっている場合があります。購入・売却の前に必ず各公式ページで最新の情報を確認してください。</p>
</main><script>{rf.JS_FRESHNESS}</script></body></html>"""
    return _stack_tables(html)


def _buy_summary(p: dict, fb=None, gid: str = "nc") -> str:
    """確認できた買う側（HTML。値はエスケープ済み）。『購入できる』は、表示時に在庫・価格の鮮度を確認できたときだけ出す（fb あり）。"""
    xs = []
    for j, o in enumerate(p["observations"]):
        if not (o["kind"] in ("official", "retail") and o.get("price") and not o["reasons"]):
            continue
        label = _e(STOCK.get(o.get("stock"), "在庫不明"))
        if fb is not None and o.get("stock") == "AVAILABLE":
            g = f"{gid}-{j}"
            label = (fb.wrap(label, g, [(o.get("checked_at"), "stock"), (o.get("checked_at"), "price")]) + fb.stale(g, "在庫の再確認待ち"))
        xs.append(f'{_e(o["source"])} {_yen(o["price"])}（{label}）{_confirmed(o.get("checked_at"))}')
    return "、".join(xs) or "確認できていない"


def _confirmed(checked_at) -> str:
    """価格に併記する確認日（タグを含まない文字列。_sell_summary は呼び出し側でエスケープされるため HTML を返さない）。確認日が無い・読めないものは『確認日不明』。"""
    raw = str(checked_at or "").strip()
    if not raw or not re.search(r"\d{4}-\d{1,2}-\d{1,2}", raw):
        return "（確認日不明）"
    return f"（{re.sub(r'<[^>]+>', '', _md(raw))} 確認）"


def _sell_summary(p: dict) -> str:
    xs = [f'{o["source"]} {_yen(o["price"])}（{COND.get(o["condition"], "")}{"・" + BASIS_SHORT[o["basis"]] if o.get("basis") in BASIS_SHORT else ""}）' + _confirmed(o.get("checked_at")) for o in p["observations"]
          if o["kind"] == "buyback" and o.get("price") and not o["reasons"] and o["freshness"] == "FRESH"]
    return "、".join(xs[:3]) + ("…" if len(xs) > 3 else "") or "確認できていない"


def _source_rows(results: list) -> str:
    """取得元ごと（店・種類）に、読めたブランドと読めなかったブランド（理由つき）をまとめる。"""
    g: dict = {}
    for v in results:
        g.setdefault((v["shop"], v["role"]), []).append(v)
    out = []
    for (shop, role), vs in sorted(g.items()):
        okr = ("FOUND", "NO_EVENT_FOUND", "CONFIRMED_NO_CURRENT_EVENT", "NOT_LISTED")       # 成功の許可リスト（それ以外は読めなかった）
        ok = [x["brand"] for x in vs if str(x["result"]).upper() in okr]
        ng = [x for x in vs if str(x["result"]).upper() not in okr]
        bad = "；".join(f"{x['brand']}: {(x.get('reason') or '-')[:40]}" for x in ng[:4])
        out.append(f'<tr><th scope="row">{_e(shop)}</th><td>{"買取" if role == "buyback" else "販売・公式"}</td>'
                   f'<td>{_e("、".join(ok)) or "—"}</td><td>{_e(bad) or "—"}</td></tr>')
    return "".join(out)
