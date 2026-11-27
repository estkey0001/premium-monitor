"""iPhone 買取比較ページ（docs/iphone-buyback.html）の描画。

入力は exports/iphone_buyback/iphone_buyback_comparison.json（src/research/weekly_import.py が作る週次の調査結果）。
- 買取店ごとの価格を一覧にする（最高値だけにして他店を捨てない）。条件（新品未開封）・色減額・更新日時・状態を出す。
- identity が DISCOVERED の SKU は「参考」と書く（正本に未登録。BUY・確認済みとは書かない）。
- 調査は週 1 回。掲載価格で、買取の確定ではない。ページに調査日を出し、古い調査を現在の価格のように見せない。
- すべての文字は HTML エスケープ。リンクは http(s) だけ。
"""
from __future__ import annotations

import html as _html
import re
from datetime import date, datetime, timedelta, timezone

from src.content import iphone_hub_model as H
from src.content.ui.shared_css import legacy_css, site_nav
from src.tcg import runtime_freshness as rf

_JST = timezone(timedelta(hours=9))

BASIS_LABEL = {
    "uniform": "色で変わらない", "worst_color": "減額が最大の色の価格", "colors_unverified": "色減額 未確認（上限）",
    "indicative": "目安の最大（確定でない）", "range_only": "範囲だけ（価格にしない）",
}
STATUS_LABEL = {"ACTIVE": "取得できた", "NO_PRICE": "価格が見つからない", "BLOCKED": "取得を拒否された", "FAILED": "取得できなかった",
                "STALE": "更新が古い"}
COND_LABEL = {"UNOPENED": "新品未開封", "OPENED_NEW": "開封済み新品・未使用品", "USED": "中古"}


# ── ページ表示時の鮮度（TCG と同じ共通の JS_FRESHNESS / data-fb-*）──
# 期間の唯一の定義は config/iphone_buyback.yaml の freshness.page_buy_days / apple_availability_days。ここに数値を書かない。
# 読めない・無い・不正（負・bool・数値以外・小数）は None（設定不明 = 常に「再確認待ち」にする側 = fail-closed）。0 は正当な設定値（当日 24:00 まで）。
_FRESH_CFG: dict = {}


def _load_cfg() -> dict:
    if not _FRESH_CFG:
        from src.research import weekly_import as _wi
        _FRESH_CFG.update(_wi.load_config())
    return _FRESH_CFG


def _norm_days(v) -> int | None:
    """正の整数または整数値の float（0 を含む）だけ受け付ける。bool・負数・非整数・数値以外は None（設定不明）。HOME・Camera と同じ規則。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return v if isinstance(v, int) and v >= 0 else None


def _days(key: str) -> int | None:
    try:
        return _norm_days((_load_cfg().get("freshness") or {}).get(key))
    except Exception:  # noqa: BLE001 — 設定が読めない = 設定不明（fail-closed）
        return None


def _is_stale_days(days, key: str = "page_buy_days") -> bool:
    """経過日数 days が設定の上限を超えた（または日数・設定が不明）か。設定不明は常に古い扱い。"""
    lim = _days(key)
    return days is None or lim is None or days > lim


def _buy_hours() -> float:
    """買取価格: 確認日は日付だけ（00:00 JST 起点）なので、暦日の差 N 日以内 = N 日目の終わりまで（days_to_hours。age_banner の「N 日以内」と同じ数え方）。"""
    d = _days("page_buy_days")
    return float("nan") if d is None else rf.days_to_hours(d)       # 設定不明は nan（JS は UNKNOWN_FRESHNESS = 出さない）


def _apple_hours() -> float:
    """Apple の購入可否: checked_at は時刻つきの ISO（実際の確認時刻）なので、日付の丸めをせず 日数 × 24 時間（days_to_hours は使わない）。"""
    d = _days("apple_availability_days")
    return float("nan") if d is None else float(d * 24)


def _safe_cfg() -> dict:
    """設定が読めない・不正なときは空設定（属性の max は nan = JS が UNKNOWN にして出さない側）。ページ生成は落とさない（Camera・HOME と同じ）。"""
    try:
        c = _load_cfg()
        return c if isinstance(c, dict) else {}
    except Exception:  # noqa: BLE001 — 設定不明 = fail-closed
        return {}


def _buy_attrs(date_str) -> str:
    return rf.attrs(rf.date_obs(date_str), _safe_cfg(), max_hours=_buy_hours())


def _apple_attrs(checked_at) -> str:
    return rf.attrs(checked_at, _safe_cfg(), max_hours=_apple_hours())


def _mmdd(d) -> str:
    m = _DATE_RE.search(str(d or ""))
    return f"{int(m.group(2)):02d}/{int(m.group(3)):02d}" if m else "不明"


def _lv(tag: str, inner: str, g: str, attrs: str, cls: str = "") -> str:
    """鮮度が FRESH のときだけ見せる要素。最初は hidden（JS が確認できたときだけ出す = JS が動かなければ出さない）。"""
    c = f' class="{cls}"' if cls else ""
    return f'<{tag}{c} data-fb-live data-fb-group="{g}" {attrs} hidden>{inner}</{tag}>'


def _st(tag: str, inner: str, g: str, cls: str = "") -> str:
    """同じ group の live が FRESH でないときに見せる「再確認待ち」（最初は表示）。"""
    c = f' class="{cls}"' if cls else ""
    return f'<{tag}{c} data-fb-stale data-fb-group="{g}">{inner}</{tag}>'


def _lvn(tag: str, inner: str, g: str, attr_list: list, cls: str = "") -> str:
    """複数の観測（買取価格 + Apple 購入可否）に依存する要素は、観測ごとに入れ子の live で包む。"""
    out = _lv(tag, inner, g, attr_list[-1], cls)
    for a in reversed(attr_list[:-1]):
        out = _lv(tag, out, g, a)
    return out


class _Fx:
    """1 回の描画で使う鮮度の文脈（調査日と group id の採番）。"""

    def __init__(self, research_date=None):
        self.rd = research_date
        self._ids: dict = {}
        self._n = 0

    def sid(self, s: dict) -> str:
        return "s%d" % self._ids.setdefault(s.get("sku"), len(self._ids) + 1)

    def nid(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def buy_date(self, s: dict):
        """最高の実行可能買取の価格の確認日（その行の updated_on）。行が見つからなければ調査日。どちらも無ければ None（UNKNOWN = 出さない）。"""
        hx = s.get("highest_executable") or {}
        for r in s.get("rows") or []:
            if r.get("eligible") and r.get("shop") == hx.get("shop") and r.get("executable_price") == hx.get("price") and r.get("updated_on"):
                return r["updated_on"]
        return self.rd

    def buy(self, s: dict) -> tuple:
        d = self.buy_date(s)
        return _buy_attrs(d), d

    def apple(self, s: dict) -> str:
        return _apple_attrs((s.get("apple_availability") or {}).get("checked_at"))


def _hide_when_stale_css() -> str:
    return "[data-fb-live][hidden],[data-fb-stale][hidden]{display:none!important}"


def age_banner(research_date, now) -> str:
    """調査日から日数がたったら警告する（週次の調査。古い調査を現在の価格のように見せない）。"""
    try:
        days = (now.date() - datetime.strptime(str(research_date), "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        return '<div class="note">調査日を確認できません。</div>'
    if not _is_stale_days(days):
        return ""
    return (f'<div class="note"><b>調査から {days} 日たっています。</b>価格・在庫・抽選の状況は変わっている可能性が高いです。'
            f'次の週次の調査まで、公式ページで必ず最新の情報を確認してください。</div>')


def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _yen(v) -> str:
    return "—" if v is None else f"¥{int(v):,}"


def _signed(v) -> str:
    if v is None:
        return "—"
    return ("+" if v > 0 else "−" if v < 0 else "") + f"¥{abs(int(v)):,}"


_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _md(v, now: datetime | None = None) -> str:
    """日付の短い表示（11/18）。1 年以上前なら年を付ける（2025/11/18）。原値は title に残す。日付が無ければ「不明」、読めなければそのまま（エスケープ済み）。"""
    raw = str(v or "")
    if not raw.strip():
        return "不明"
    m = _DATE_RE.search(raw)
    if not m:
        return _e(raw)
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    label = f"{mo:02d}/{d:02d}"
    try:
        if ((now or datetime.now(_JST)).date() - date(y, mo, d)).days >= 365:
            label = f"{y}/{mo:02d}/{d:02d}"
    except ValueError:
        pass
    return f'<span title="{_e(raw)}">{label}</span>'


_PLAIN = {"UNKNOWN_FRESHNESS": "更新日の記載なし", "OUTLIER_REVIEW": "外れ値の確認待ち", "SINGLE_SOURCE": "比較できる店が1つだけ",
          "DISCOVERED": "未登録", "INFERENCE": "推測", "FRESH": "更新が新しい", "STALE": "更新が古い", "WATCH": "様子見（要確認）",
          "WAIT": "様子見", "BUY": "購入候補", "PASS": "見送り", "NOT_CALCULATED": "未計算"}
_PLAIN_RE = re.compile(r"(?<![A-Za-z_])(" + "|".join(sorted(_PLAIN, key=len, reverse=True)) + r")(?![A-Za-z_])")


_DUP_RE = re.compile(r"([一-龥ぁ-んァ-ヶー]{2,})[（(]\1[）)]")


def _plain(text) -> str:
    """本文に出る内部の識別子を平易な日本語にする（エスケープ済みを返す）。原文は詳細側・title に残す。
    「更新が古い（STALE）」が「更新が古い（更新が古い）」にならないよう、同じ語の重複は 1 つにする。"""
    t = "" if text is None else str(text)
    t = t.replace("正本に未登録", "監視対象に未登録").replace("正本", "監視対象")
    return _e(_DUP_RE.sub(r"\1", _PLAIN_RE.sub(lambda m: _PLAIN[m.group(1)], t)))


def _man(v) -> str:
    return f"{v / 10000:.1f}万"


UNC_PLAIN = {"SINGLE_SOURCE": "比較できる店が1つだけ", "OUTLIER_REVIEW": "他店より極端に高く確認待ち", "NO_DATA": "比較できる価格なし"}


def _link(url, label, plain: bool = False) -> str:
    u = str(url or "")
    lab = _plain(label) if plain else _e(label)
    return f'<a href="{_e(u)}" target="_blank" rel="noopener nofollow">{lab}</a>' if u.startswith(("http://", "https://")) else lab


def _colors(row: dict) -> str:
    ca = row.get("color_adjustments") or {}
    if row.get("basis") == "colors_unverified":
        return "未確認"
    if not ca:
        return "なし（掲載なし）"
    return "、".join(f"{_e(k)} {_e(v)}" for k, v in list(ca.items())[:4])


AV_LABEL = {"BUYABLE": "購入できる（Apple で確認）", "UNAVAILABLE": "今は購入できない", "UNKNOWN": "購入可否 未確認"}
PROFIT_LABEL = {"PROFITABLE": "計算上の黒字（PROFITABLE）", "LOSS": "赤字（LOSS）", "NO_DATA": "確定できる価格なし（NO_DATA）",
                "REFERENCE_PROFIT": "REFERENCE_PROFIT（参考の黒字・未登録）"}
OPP_LABEL = {"BUY": "BUY（週次の判定）", "WATCH": "WATCH（様子見・要確認）", "WAIT": "WAIT（待ち）", "PASS": "PASS（見送り）"}
EVENT_LABEL = {"BEST_SHOP_CHANGE": "最高買取店の変更", "LOSS_TO_PROFIT": "赤字 → 黒字", "PROFIT_TO_LOSS": "黒字 → 赤字",
               "BUYBACK_SURGE": "買取価格の上昇", "PRICE_DROP": "買取価格の下落",
               "WAIT_TO_BUY": "判定が BUY に昇格", "BUY_TO_WAIT": "判定が BUY から降格"}
FRESH_LABEL = {"FRESH": "FRESH（更新が新しい）", "STALE": "STALE（更新が古い）", "UNKNOWN_FRESHNESS": "更新日の記載なし"}
OUTLIER_LABEL = {"NONE": "外れ値なし", "OUTLIER_REVIEW": "最高値が他店より大きく高い・確認待ち（OUTLIER_REVIEW）",
                 "REVIEWED": "外れ値を確認済み", "SINGLE_SOURCE": "比較できる店が1つだけ（確認待ち）", "NO_DATA": "比較できる価格なし"}


OPP_BADGE = {"BUY": ("購入候補", "buy"), "WATCH": ("様子見", "wait"), "WAIT": ("様子見", "wait"), "PASS": ("見送り", "off")}
PROFIT_BADGE = {"PROFITABLE": ("黒字", "profit"), "LOSS": ("赤字", "loss"), "NO_DATA": ("データ無し", "off"),
                "REFERENCE_PROFIT": ("参考の黒字", "off")}
FRESH_SHORT = {"FRESH": ("更新が新しい", "info"), "STALE": ("更新が古い", "off"), "UNKNOWN_FRESHNESS": ("更新日なし", "off")}


def _badge(label: str, tone: str) -> str:
    return f'<span class="sbadge sbadge--{_e(tone)}">{_e(label)}</span>'


def opp_badge(status, ref: bool = False) -> str:
    """判定（週次）の新語バッジ。購入候補=緑。参考（未登録）は緑にしない。値は opportunity_status の再表示だけ。"""
    label, tone = OPP_BADGE.get(str(status or "").upper(), ("判定なし", "off"))
    if (ref or _PAGE_STALE) and tone == "buy":                    # 参考・調査が古いときは緑にしない（文言は変えない）
        tone = "wait"
    return _badge(label, tone)


_PAGE_STALE = False        # render() が調査日から決める（7 日超）。古い調査では購入候補の見た目（緑）を出さない


def _is_go(s: dict, ref: bool = False) -> bool:
    """緑にしてよいのは購入候補（正本に登録済み・実行可能な買取あり・判定が BUY）だけ。様子見・確認待ち・参考・古い調査は中立色。"""
    return (not _PAGE_STALE) and (not ref) and bool(s.get("highest_executable")) and str(s.get("opportunity_status") or "").upper() == "BUY"


def _cell(label: str, inner: str, cls: str = "") -> str:
    return f'<td data-label="{_e(label)}"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}><div class="v">{inner}</div></td>'


def _row_html(r: dict, rank: int | None = None, top_price: int | None = None, fx: "_Fx | None" = None) -> str:
    fx = fx or _Fx()
    g = fx.nid("r")
    ra = _buy_attrs(r.get("updated_on"))                       # 行の観測時刻 = その行のページ更新日（生成時刻ではない）
    ref_d = _mmdd(r.get("updated_on"))
    notes = []
    if r.get("shop_status") != "ACTIVE":
        notes.append(STATUS_LABEL.get(r.get("shop_status"), ""))
    if r.get("condition") != "UNOPENED":
        notes.append("別の状態（利益計算に使わない）")
    if r.get("freshness") == "STALE":
        notes.append("STALE（更新が古く、利益計算の主要価格に使わない。休業日などで更新が無いだけの場合もあり、誤価格とは限らない）")
    if r.get("freshness") == "UNKNOWN_FRESHNESS":
        notes.append("更新日の記載なし（掲載価格として表示するだけで、利益計算に使わない）")
    if r.get("basis") in BASIS_LABEL and r["basis"] not in ("uniform", "worst_color"):
        notes.append(BASIS_LABEL[r["basis"]])
    price = r.get("executable_price")
    listed = r.get("listed_price")
    shown = _yen(price) if price is not None else (_yen(listed) + "（掲載・上限）" if listed else "—")
    extra = f'<div class="mut">{_e(r["campaign"])}（期間限定・通常価格に含めない）</div>' if r.get("campaign") else ""
    weak = (not r.get("eligible")) or r.get("freshness") in ("STALE", "UNKNOWN_FRESHNESS")
    cls = ("ng is-stale" if weak else "ok") + (" top" if rank == 1 else "")
    age = ""                                               # 日数は調査日基準で固定され、今日の経過と食い違う（誤読）ため出さない。取得日だけ表示する
    diff = "—"
    if rank == 1:
        diff = "基準（1 位）"
    elif rank and isinstance(price, int) and isinstance(top_price, int):
        diff = _signed(price - top_price)                      # 表示だけの引き算（1 位との差）
    fl, ft = FRESH_SHORT.get(r.get("freshness"), ("", "off"))
    if r.get("freshness") == "FRESH" and fl:                    # 「更新が新しい」は、ページを開いた時点でも新しいときだけ（生成時の FRESH を鵜呑みにしない）
        badge = _lv("span", _badge(fl, ft), g, ra) + _st("span", _badge(f"価格の再確認待ち（取得 {ref_d}）", "off"), g)
    else:
        badge = _badge(fl, ft) if fl else ""
    fresh = badge + f'<div class="mut">{_md(r.get("updated_on")) if r.get("updated_on") else "更新日の記載なし"}{_e(age)}</div>'
    treat = _e("、".join(n for n in notes if n)) or ("利益計算の候補" if r.get("eligible") else "利益計算に使わない（同じ店の他の行・キャンペーンなど）")
    if r.get("eligible") and not any(notes):
        treat = (_lv("span", "利益計算の候補", g + "t", ra) + _st("span", f"価格の再確認待ち（取得 {ref_d} の参考価格・利益計算に使わない）", g + "t"))
    fresh_lab = _e(FRESH_LABEL.get(r.get("freshness"), ""))
    if r.get("freshness") == "FRESH":
        fresh_lab = _lv("span", fresh_lab, g + "f", ra) + _st("span", "再確認待ち", g + "f")
    rk = "—"
    if rank:
        rk = (_lv("span", f"{rank} 位", g + "k", ra, "rk1" if rank == 1 else "") + _st("span", "参考", g + "k"))
    detail = (f'<details><summary>条件・色減額・扱い</summary><div class="mut">条件: {_e(COND_LABEL.get(r.get("condition"), r.get("condition")))}'
              f'／色減額: {_colors(r)}</div><div class="mut">鮮度: {fresh_lab}</div>'
              f'<div>{treat}</div>{extra}</details>')
    return (f'<tr class="{cls}">{_cell("順位", rk, "num")}'
            f'<th scope="row" data-label="買取店"><div class="v">{_link(r.get("price_page_url"), r.get("shop"), True)}</div></th>'
            f'{_cell("買取価格", shown, "num")}{_cell("差額（1位比）", diff, "num")}{_cell("鮮度", fresh)}'
            f'{_cell("確認日時", _md(str(r.get("checked_at"))[:60]) if r.get("checked_at") else "記載なし")}{_cell("詳細", detail)}</tr>')


def _hero_html(s: dict, ref: bool, fx: "_Fx | None" = None, loc: str = "h") -> str:
    """SKU 先頭の指標（Apple 価格／最高買取／純利益／ROI／判定）。既存値の再表示だけ。
    最高買取・純利益・ROI・黒字バッジ・購入候補は、価格の確認日から page_buy_days を超えたら（購入候補は Apple 購入可否が apple_availability_days を超えても）
    ページ表示時に隠し、取得日つきの参考表示に切り替える（data-fb-live / data-fb-stale）。"""
    fx = fx or _Fx()
    g = f"{fx.sid(s)}-{loc}"
    hx, unc = s.get("highest_executable"), s.get("highest_unconfirmed")
    net = s.get("net_profit") if hx else None
    ba, bd = fx.buy(s) if hx else ("", None)
    md = _mmdd(bd)
    if hx:
        best = (f'<b data-fb-live data-fb-group="{g}b" {ba} hidden>{_yen(hx["price"])}</b><em data-fb-live data-fb-group="{g}b" {ba} hidden>{_e(hx["shop"])}</em>'
                f'<b data-fb-stale data-fb-group="{g}b" class="warn">再確認待ち</b>'
                f'<em data-fb-stale data-fb-group="{g}b">取得 {md} の参考価格 {_e(hx["shop"])} {_yen(hx["price"])}</em>')
    elif unc:
        best = f'<b class="warn">確認待ち</b><em>最高値 {_e(unc["shop"])} {_yen(unc["price"])}（<span title="{_e(unc["status"])}">{_e(UNC_PLAIN.get(unc["status"], "確認待ち"))}</span>）</em>'
    else:
        best = '<b>—</b><em>比較できる価格なし</em>'
    go = _is_go(s, ref)
    net_cls = "pos" if (net or 0) > 0 and go else "neg" if (net or 0) < 0 else ""        # 緑は購入候補だけ。様子見・参考の黒字は中立色
    pl, pt = PROFIT_BADGE.get(s.get("profit_status"), ("", "off"))
    if pt == "profit" and not go:
        pt = "off"
    roi = ("%.1f%%" % s["roi_pct"]).replace("-", "−") if hx and s.get("roi_pct") is not None else "—"
    ref_chip = ""                                                  # 「参考」はカード見出しの 1 回だけ（hero では繰り返さない）
    if hx:
        net_h = (f'<b data-fb-live data-fb-group="{g}n" {ba} hidden class="{net_cls}">{_signed(net)}</b>'
                 f'<b data-fb-stale data-fb-group="{g}n" class="warn">再確認待ち</b>')
        pl_h = (_lv("span", _badge(pl, pt), g + "n", ba, "") + "") if pl else ""
        roi_h = (f'<b data-fb-live data-fb-group="{g}r" {ba} hidden>{_e(roi)}</b><b data-fb-stale data-fb-group="{g}r">—</b>')
    else:
        net_h, pl_h, roi_h = f'<b class="{net_cls}">{_signed(net)}</b>', (_badge(pl, pt) if pl else ""), f'<b>{_e(roi)}</b>'
    opp = opp_badge(s.get("opportunity_status"), ref)
    if str(s.get("opportunity_status") or "").upper() == "BUY":      # 購入候補は、買取価格と Apple 購入可否の両方が新しいときだけ
        opp = _lvn("span", opp, g + "d", [fx.buy(s)[0], fx.apple(s)]) + _st("span", _badge(f"価格の再確認待ち（取得 {md if hx else _mmdd(fx.rd)}）", "wait"), g + "d")
    return ('<div class="hero">'
            f'<div class="m"><span>Apple 価格</span><b>{_yen(s["apple_price"])}</b></div>'
            f'<div class="m"><span title="最高の実行可能買取">最高買取</span>{best}</div>'
            f'<div class="m"><span>純利益{"（参考）" if ref else ""}</span>{net_h}{pl_h}</div>'
            f'<div class="m"><span>ROI</span>{roi_h}</div>'
            f'<div class="m"><span>判定（週次）</span>{opp}{ref_chip}</div></div>')


def _sku_html(s: dict, extra_html: str = "", prev_html: str = "", fx: "_Fx | None" = None) -> str:
    fx = fx or _Fx()
    sid = fx.sid(s)
    ref = s.get("identity") != "REGISTERED"
    badge = (f'<span class="chip chip--ref" title="参考・正本に未登録">{REF_LONG_TEXT}</span>' if ref
             else '<span class="chip chip--ok" title="正本に登録済み">監視対象に登録済み</span>')
    hl, hx, unc = s.get("highest_listed"), s.get("highest_executable"), s.get("highest_unconfirmed")
    sec, thi = s.get("second"), s.get("third")

    hxs = s.get("highest_executable")
    ba, bd = fx.buy(s) if hxs else (_buy_attrs(fx.rd), fx.rd)
    md = _mmdd(bd)

    def one(label, x, extra="", gate=False, k=""):
        if x and gate:                                         # 実行可能な 2・3 位の売り先と価格は、最高買取と同じ鮮度で表示する
            g = f"{sid}-{k}"
            return (f'<div class="kv" data-fb-live data-fb-group="{g}" {ba} hidden><span>{label}</span><b>{_e(x["shop"])}</b><em>{_yen(x["price"])}{extra}</em></div>'
                    f'<div class="kv" data-fb-stale data-fb-group="{g}"><span>{label}</span><b>再確認待ち</b><em>取得 {md} の参考価格 {_e(x["shop"])} {_yen(x["price"])}</em></div>')
        return f'<div class="kv"><span>{label}</span><b>{_e(x["shop"]) if x else "—"}</b><em>{_yen(x["price"]) if x else ""}{extra}</em></div>'
    out = s.get("outlier_status") or "NO_DATA"
    av = s.get("apple_availability") or {}
    listed_note = ""
    if hl:
        listed_note = f' ／ {_e(FRESH_LABEL.get(hl.get("freshness"), ""))}／{"利益計算に使う価格" if hl.get("executable") else "利益計算に使わない"}'
        if hl.get("freshness") == "FRESH" or hl.get("executable"):     # 「FRESH」「利益計算に使う価格」は、表示時点でも新しいときだけ
            listed_note = (_lv("span", listed_note, sid + "-hl", ba) + _st("span", f' ／ 取得 {md} の掲載価格（再確認待ち・利益計算に使わない）', sid + "-hl"))
    ref_net = s.get("reference_net_at_second")
    ref_html = (_lv("div", f'参考: 次点（{_e(ref_net["shop"])} {_yen(ref_net["price"])}）で計算すると純利益 {_signed(ref_net["net_profit"])}。'
                    f'次点は最高の実行可能価格ではありません。', sid + "-rn", ba, "mut")
                + _st("div", "次点で計算した参考の純利益は、価格の再確認待ちのため出していません。", sid + "-rn", "mut") if ref_net else "")
    route = (_lv("div", f'最大利益ルート: {_e(s["best_route"])}', sid + "-rt", ba, "route") + _st("div", f"最大利益ルート: 価格の再確認待ち（取得 {md}）", sid + "-rt", "route") if s.get("best_route")
             else _lv("div", f'参考の最大ルート（監視対象に未登録のため確定ではない）: {_e(s["reference_route"])}', sid + "-rt", ba, "route")
             + _st("div", f"参考の最大ルート: 価格の再確認待ち（取得 {md}）", sid + "-rt", "route") if s.get("reference_route")
             else '<div class="route mut">利益が出るルートは確認できません</div>')
    ranks = H.rank_rows(s)
    top = max((r["executable_price"] for r in s.get("rows") or [] if ranks.get(id(r)) == 1), default=None)
    rows = "".join(_row_html(r, ranks.get(id(r)), top, fx) for r in s.get("rows") or [])
    fresh_rows = [r.get("updated_on") for r in s.get("rows") or [] if r.get("freshness") == "FRESH"]
    n_fresh = s.get("fresh_source_count", 0)
    if isinstance(n_fresh, int) and n_fresh > 0:               # 件数は、いちばん古い FRESH の行が期限を超えたら成り立たない（数値を隠して確認待ちにする）
        old = min((d for d in fresh_rows if d), default=None) if all(fresh_rows) else None
        fresh_em = (_lv("em", f"うち更新が新しい {_e(n_fresh)} 店", sid + "-fc", _buy_attrs(old or (fx.rd if not fresh_rows else None)))
                    + _st("em", "更新が新しい店の数: 価格の再確認待ち", sid + "-fc"))
    else:
        fresh_em = f'<em>うち更新が新しい {_e(n_fresh)} 店</em>'
    av_b = _e(AV_LABEL.get(av.get("status"), AV_LABEL["UNKNOWN"]))
    if av.get("status") == "BUYABLE":                          # 「購入できる」は、Apple 購入可否の確認が新しいときだけ
        av_b = _lv("span", av_b, sid + "-av", _apple_attrs(av.get("checked_at"))) + _st("span", "購入可否 再確認待ち", sid + "-av")
    pst = _e(PROFIT_LABEL.get(s.get("profit_status"), "—"))
    if hxs:
        pst = _lv("span", pst, sid + "-ps", ba) + _st("span", "再確認待ち", sid + "-ps")
    ost = _e(OPP_LABEL.get(s.get("opportunity_status"), "—"))
    orn = _e(s.get("opportunity_reason") or "")
    if str(s.get("opportunity_status") or "").upper() == "BUY":
        ost = _lvn("span", ost, sid + "-os", [ba, fx.apple(s)]) + _st("span", "再確認待ち", sid + "-os")
        orn = _lvn("span", orn, sid + "-or", [ba, fx.apple(s)])
    return (f'<section class="sku"><h3>{_e(s["sku"])} {badge}</h3>{_hero_html(s, ref, fx)}'
            f'<details class="spec"><summary>詳細（店数・購入可否・外れ値・諸経費）</summary>'
            f'<div class="grid">{one("掲載の最高値", hl, listed_note)}{one("実行可能 2位", sec, gate=True, k="2")}{one("実行可能 3位", thi, gate=True, k="3")}'
            f'<div class="kv"><span>買取店の数</span><b>{_e(s.get("source_count", 0))} 店</b>{fresh_em}</div>'
            f'<div class="kv"><span>Apple の購入可否</span><b>{av_b}</b>'
            f'<em>確認: {_e(av.get("checked_at") or "なし")}</em></div>'
            f'<div class="kv kv--s"><span>利益の状態</span><b>{pst}</b></div>'
            f'<div class="kv kv--s"><span>判定（週次・BUY とは別）</span><b>{ost}</b>'
            f'<em>{orn}</em></div>'
            f'<div class="kv"><span>外れ値の判定</span><b>{_e(OUTLIER_LABEL.get(out, out))}</b></div>'
            f'{prev_html}'
            f'<div class="kv kv--s"><span>諸経費（純利益・ROI は上の数値）</span><b>{_yen(s.get("costs"))}</b></div></div></details>'
            f'{route}'
            f'<details class="spec"><summary>履歴・参考・補足</summary>'
            f'{ref_html}<div class="mut">{_plain(s.get("identity_note"))}</div>{extra_html}</details>'
            f'<details><summary>買取店ごとの価格（{len(s.get("rows") or [])} 行）</summary>'
            f'<div class="tw"><table class="nu-table--stack cmp"><thead><tr><th>順位</th><th>買取店</th><th class="num">買取価格</th><th class="num">差額（1位比）</th><th>鮮度</th><th>確認日時</th><th>条件・扱い</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div></details></section>')


CSS = """
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans",sans-serif}
main{max-width:1240px;margin:0 auto;padding:12px 16px 16px}main>p:first-child{margin:0}main>p:first-child+h1{margin-top:.2rem}a{color:var(--link)}h1{font-size:1.35rem;margin:.2rem 0}h2{font-size:1.1rem;margin:1.6rem 0 .6rem}h3{font-size:1.02rem;margin:0 0 .6rem}
.mut{color:var(--mut);font-size:.85rem}.note{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:.8rem 0}
.sum{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:.8rem 0}.sum div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px}.sum b{display:block;font-size:1.25rem}
.sku{border:1px solid var(--line);border-radius:12px;padding:12px;margin:12px 0;background:var(--bg)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.kv{background:var(--card);border-radius:8px;padding:8px 10px;display:flex;flex-direction:column}.kv span{color:var(--mut);font-size:.78rem}.kv b{font-size:1.05rem;overflow-wrap:anywhere}.kv em{font-style:normal;color:var(--mut);font-size:.82rem;overflow-wrap:anywhere}
.pos{color:var(--ok)}.neg{color:var(--ng)}.chip{white-space:nowrap;font-size:.75rem;padding:2px 8px;border-radius:99px;border:1px solid var(--line);vertical-align:middle;font-weight:600}.chip--ref{color:var(--ref);white-space:normal}.nw{white-space:nowrap}.rt{word-break:keep-all;overflow-wrap:normal}.chip--ok{color:var(--ok)}
.kv--s b{font-size:.85rem;font-weight:600}.route{margin:.6rem 0 .2rem;font-weight:700}details{margin-top:.6rem}summary{cursor:pointer;color:var(--link)}.tw{overflow-x:auto;margin-top:.5rem}
table{border-collapse:collapse;width:100%;min-width:700px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;font-size:.85rem;vertical-align:top}th[scope=row]{font-weight:600}.num{text-align:right;white-space:nowrap}tr.ng td,tr.ng th{color:var(--mut)}
ul{padding-left:1.1rem}
.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px;margin:.2rem 0 .6rem}
.hero .m{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 10px;display:flex;flex-direction:column;gap:2px}
.hero .m>span{color:var(--mut);font-size:.75rem}.hero .m>b{font-size:1.3rem;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;line-height:1.3}
.hero .m>em{font-style:normal;color:var(--mut);font-size:.78rem;overflow-wrap:anywhere}.hero .m>.sbadge{align-self:flex-start;margin-top:2px}
.badges{display:flex;flex-wrap:wrap;gap:6px;align-items:center}.warn{color:var(--ref);font-weight:600}
tr.is-stale td,tr.is-stale th{color:var(--mut);background:var(--card)}tr.is-stale .num{opacity:.65}.rk1{background:var(--tone-success-bg);border-radius:6px;padding:0 6px}
.dcard{border:1px solid var(--line);border-radius:12px;padding:12px;margin:10px 0;background:var(--bg)}
.dcard header{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px 10px;align-items:center;margin-bottom:.4rem}.dcard h3{margin:0}
.dcard--off{background:var(--card)}
.verdict{border:2px solid var(--line);border-radius:12px;padding:10px 12px;margin:.6rem 0 1rem;background:var(--bg)}.verdict p{margin:.3rem 0 .6rem}.verdict p:last-child{margin-bottom:0}
.v{display:block}.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.back{display:inline-flex;align-items:center;min-height:44px}
.today{border:2px solid var(--line);border-radius:12px;padding:12px;margin:.6rem 0 1rem;background:var(--bg)}.today h2{margin:0 0 .3rem}.today .lead{margin:.2rem 0 .6rem;font-size:1.02rem}
.prevbig{display:flex;flex-direction:column;gap:2px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:.4rem 0}
.prevbig>span{color:var(--mut);font-size:.8rem}.prevbig>b{font-size:1.5rem;font-variant-numeric:tabular-nums}.prevbig>em{font-style:normal;color:var(--mut);font-size:.8rem}
table.cmp{min-width:0}table.cmp td,table.cmp th{overflow-wrap:anywhere}table.cmp summary{white-space:nowrap}details.nodata-skus{margin:.6rem 0}
details.hub-note>summary{padding:4px 0}.nd-list{list-style:none;padding:0;margin:.4rem 0}.nd-list li{padding:6px 0;border-top:1px solid var(--line);font-size:.85rem}.nd-list details{margin:0}table.cand{min-width:0}table.cand th,table.cand td{padding:4px 6px}
a.back,.tw a,.v a,main li a,.note a,.dcard a,.sku a,main td a,main li a{display:inline-flex;align-items:center;min-height:44px}
.dcard .badges .sbadge{white-space:normal}.verdict .vline{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;margin:.2rem 0}.verdict .vline:last-child{margin-bottom:0}.verdict{padding:8px 12px;margin:.4rem 0 .6rem}
@media (max-width:639px){summary{padding:10px 0}.nu-table--stack .v{text-align:right;min-width:0}.nu-table--stack .tw{overflow:visible}
.dcard{padding:10px;margin:8px 0}.dcard .hero,.sku .hero{grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:.2rem 0 .4rem}.dcard .hero .m,.sku .hero .m{padding:6px 8px}.dcard .hero .m>b{font-size:1rem}.dcard .hero .m>span,.sku .hero .m>span{font-size:.75rem}.sku{padding:10px}.sku .hero .m{gap:1px;padding:5px 6px}.sku .hero .m>b{font-size:.92rem;line-height:1.25;overflow-wrap:normal}.sku .hero .m>em{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:.75rem;line-height:1.3}.sku details.spec{margin:.2rem 0}.sku summary{padding:8px 0}}
"""


HUB_CSS = """
.hub-note{border-left:4px solid var(--ref)}.ans{margin:.4rem 0 1rem}.ans h3{margin:.2rem 0}.q{font-weight:700}
.ans .head{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:.4rem 0}
.wait{color:var(--ref);font-weight:600}.nodata{color:var(--mut)}
details.model{border:1px solid var(--line);border-radius:12px;padding:6px 12px;margin:12px 0}details.model>summary{font-weight:700;font-size:1.05rem;padding:4px 0}
.mini{min-width:0}.mini th,.mini td{font-size:.8rem;padding:4px 6px}.hist{margin-top:.6rem}.hist h4{margin:.4rem 0 .2rem;font-size:.9rem}
.sig li{margin:.2rem 0}.concl-note{margin:.3rem 0}
@media (min-width:640px){table.mini.concl{min-width:640px}table.mini.concl td.num{white-space:normal}table.mini.concl th,table.mini.concl td{overflow-wrap:break-word;word-break:normal}
table.mini.concl thead th:nth-child(1){min-width:7.5em}table.mini.concl thead th:nth-child(2){min-width:9em}table.mini.concl thead th:nth-child(3){min-width:7em}
table.mini.concl thead th:nth-child(4){min-width:8em}table.mini.concl thead th:nth-child(5){min-width:9em}}
.spark{display:block;max-width:100%;height:auto;color:var(--mut);margin:.2rem 0}details.spec{margin:.5rem 0}details.spec>summary{font-size:.85rem}
"""


REF_CHIP = ' <span class="chip chip--ref">参考</span>'
REF_LONG_TEXT = "参考（まだ監視対象に登録していない機種）"
REF_CHIP_LONG = f' <span class="chip chip--ref" title="参考・正本に未登録">{REF_LONG_TEXT}</span>'


def _fmt_age_date(v) -> str:
    return _e(v) if v else "データ無し"


def _answer_cells(a: dict, cmp_: dict, common: frozenset = frozenset(), s: "dict | None" = None, fx: "_Fx | None" = None) -> str:
    """5 つの問いのうち、容量ごとに答えられる 4 つ（どの店・利益・前回比・判断）。出せないものは理由つきで「確認待ち」「データ無し」。
    common に入る理由の文は、見出し側に 1 回だけ出すので行には書かない。"""
    def why(t) -> str:
        return f'<div class="mut">{_plain(t)}</div>' if t and t not in common else ""
    go = (not _PAGE_STALE) and (not a["reference"]) and bool(a["sell_shop"]) and str(a["decision"] or "").upper() == "BUY"
    fx = fx or _Fx()
    g = f"{fx.sid(s)}-c" if s else fx.nid("c")
    ba, bd = fx.buy(s) if s else ("", None)
    md = _mmdd(bd)
    if a["sell_shop"]:
        sell = f'<b>{_e(a["sell_shop"])}</b> {_yen(a["sell_price"])}'
        sell = (_lv("span", sell, g + "s", ba) + _st("span", f'<span class="wait">再確認待ち</span><div class="mut">取得 {md} の参考価格 {_e(a["sell_shop"])} {_yen(a["sell_price"])}</div>', g + "s"))
    else:
        sell = f'<span class="wait">確認待ち</span>{why(a["sell_reason"])}'
    if a["net"] is not None:
        cls = "pos" if a["net"] > 0 and go else "neg" if a["net"] < 0 else ""
        roi = f'（ROI {a["roi"]:.1f}%）' if a.get("roi") is not None else ""
        net = f'<b class="{cls}">{_signed(a["net"])}</b>{_e(roi)}'
        if a["sell_shop"]:
            net = _lv("span", net, g + "n", ba) + _st("span", '<span class="wait">再確認待ち</span>', g + "n")
    else:
        net = f'<span class="nodata">データ無し</span>{why(a["net_reason"])}'
    if cmp_["status"] == "OK":
        prev = (f'{_signed(cmp_["delta"])}<div class="mut">{_md(cmp_["prev_date"])} の同じ {cmp_["common"]} 店の最高 {_yen(cmp_["prev_best"])}'
                f' → {_yen(cmp_["cur_best"])}</div>')
    else:
        prev = f'<span class="nodata">データ無し</span>{why(cmp_["reason"])}'
    dec_note = f'<div class="mut">{_plain(a["decision_reason"])}</div>' if a.get("decision_reason") and a["decision_reason"] not in common else ""
    ref = a["reference"]
    dec = opp_badge(a["decision"], ref)
    if str(a["decision"] or "").upper() == "BUY":              # 購入候補は買取価格と Apple 購入可否の両方が新しいときだけ（理由の文も同じ）
        ap = fx.apple(s) if s else ""
        dec = _lvn("span", dec + dec_note, g + "d", [ba, ap]) + _st("span", _badge("価格の再確認待ち", "wait"), g + "d")
        dec_note = ""
    return (f'<td data-label="どの店へ売る"><div class="v">{sell}</div></td><td class="num" data-label="利益"><div class="v">{net}</div></td>'
            f'<td data-label="前回比"><div class="v">{prev}</div></td>'
            f'<td data-label="判定（週次）"><div class="v">{dec}{dec_note}</div></td>')


def _conclusion_html(group: dict, tl, fx: "_Fx | None" = None) -> str:
    fx = fx or _Fx()
    skus = group["skus"]
    c = H.model_conclusion(skus)
    if c["status"] in ("PROFIT", "NO_PROFIT", "PROFIT_WATCH"):
        a = c["answer"]
        if c["status"] == "PROFIT_WATCH":
            head = (f'<span class="wait">様子見</span> — 最大は <b>{_e(a["capacity"])}</b>（{_e(a["sell_shop"])}）。'
                    f'週次の判定は {_plain(OPP_BADGE.get(str(a["decision"] or "").upper(), ("—",))[0])} のため「買い」とは案内しません')
        elif c["status"] == "PROFIT":
            head = f'<b>{_e(a["capacity"])}</b> を買い、<b>{_e(a["sell_shop"])}</b> へ売る'     # 金額・利益は下の表の 1 行だけ
            bs = next((x for x in skus if x.get("sku") == a["sku"]), None)
            if bs is not None:                                  # 「買い」は、買取価格と Apple 購入可否の両方が新しいときだけ
                g_h = fx.sid(bs) + "-ch"
                head = (_lvn("span", head, g_h, [fx.buy(bs)[0], fx.apple(bs)])
                        + _st("span", f'<span class="wait">価格の再確認待ち（取得 {_mmdd(fx.buy(bs)[1])}）</span> — 取得時点は <b>{_e(a["capacity"])}</b> → <b>{_e(a["sell_shop"])}</b>。いまの価格とは限りません', g_h))
            if _PAGE_STALE:                                     # 調査が古いときは断定しない（上部「今日のおすすめ」と表記を揃える）
                head = (f'<span class="wait">調査が古い</span> — 調査時点は <b>{_e(a["capacity"])}</b> → <b>{_e(a["sell_shop"])}</b>'
                        f'。いまの価格とは限りません')
        else:
            head = f'黒字になる容量は確認できません（{_plain(c["reason"])}）。最大でも {_e(a["capacity"])}（利益は下の表）'
    else:
        head = f'<span class="wait">確認待ち</span> — {_plain(c["reason"])}'
    ordered = sorted(skus, key=lambda s: (H.info_rank(s), s.get("identity") != "REGISTERED"))                       # 判断材料のある行を先に（同順位内は容量順のまま）
    triples = [(s, H.sku_answer(s), H.prev_compare(tl, s.get("sku"))) for s in ordered]
    cnt: dict = {}
    for _s, a, cm in triples:
        for t in (a["sell_reason"], a["net_reason"], a.get("decision_reason"), cm.get("reason") if cm["status"] != "OK" else None):
            if t:
                cnt[t] = cnt.get(t, 0) + 1
    common = frozenset(t for t, n in cnt.items() if n >= 2)      # 2 行以上で同じ文の理由は 1 回にまとめる
    note = ""
    if common:
        note = ('<p class="mut concl-note">複数の行に共通の理由: '
                + "／".join(_plain(t) for t in sorted(common, key=lambda t: -cnt[t])) + '</p>')
    pend = [(s, a, cm) for s, a, cm in triples if not a["sell_shop"] and a["net"] is None]
    if len(pend) >= 2:                                           # 確認待ち・データ無しの容量は 1 行にまとめる
        triples = [t for t in triples if t not in pend]
        note += (f'<p class="mut concl-note"><span class="wait">確認待ち {len(pend)} 容量</span>（データ無し）: '
                 + "、".join(_e(a["capacity"] or s.get("sku")) for s, a, _cm in pend) + '</p>')
    rows = "".join(
        f'<tr class="{"ng" if a["reference"] else "ok"}"><th scope="row" data-label="容量"><div class="v">{_e(a["capacity"] or a["sku"])}'
        f'{REF_CHIP if a["reference"] else ""}<div class="mut">Apple {_yen(s.get("apple_price"))}</div></div></th>{_answer_cells(a, cm, common, s, fx)}</tr>'
        for s, a, cm in triples)
    if not rows:
        return f'<div class="ans"><div class="head"><span class="q">どの容量を買うか:</span> {head}</div>{note}</div>'
    return (f'<div class="ans"><div class="head"><span class="q">どの容量を買うか:</span> {head}</div>{note}'
            f'<div class="tw"><table class="mini concl nu-table--stack"><thead><tr><th>容量（Apple 価格）</th><th>どの店へ売る（実行可能な最高買取）</th><th>利益</th><th>前回比</th>'
            f'<th>判定（週次）<span class="vh"> 購入候補か様子見か（BUY か WAIT か）</span></th></tr></thead><tbody>{rows}</tbody></table></div></div>')


def _sparkline(lay: dict) -> str:
    """最高買取の推移（SVG・JS なし）。2 点以上で線がつながるときだけ描く。端点に日付と金額、軸に日付と価格帯。店数が変わる日は線を切る。"""
    if lay.get("status") != "OK" or not lay.get("segments"):
        return ""
    lines = "".join('<polyline fill="none" stroke="currentColor" stroke-width="2" points="%s"/>' % " ".join(f"{x},{y}" for x, y in sg)
                    for sg in lay["segments"])
    dots = "".join(f'<circle cx="{d["x"]}" cy="{d["y"]}" r="3.5" fill="currentColor"><title>{_e(d["date"])} {_yen(d["price"])}（{_e(d["shops"])} 店）</title></circle>'
                   for d in lay["dots"])
    first, last = lay["dots"][0], lay["dots"][-1]
    x0, x1, yh, yl, w, h = lay["x0"], lay["x1"], lay["y_hi"], lay["y_lo"], lay["width"], lay["height"]

    def md(d):
        m = _DATE_RE.search(str(d))
        return f"{int(m.group(2)):02d}/{int(m.group(3)):02d}" if m else str(d)
    axes = (f'<line x1="{x0}" y1="{yh}" x2="{x1}" y2="{yh}" stroke="currentColor" stroke-opacity=".25" stroke-dasharray="3 3"/>'
            f'<line x1="{x0}" y1="{yl}" x2="{x1}" y2="{yl}" stroke="currentColor" stroke-opacity=".25"/>'
            f'<text x="{x0 - 6}" y="{yh + 4}" text-anchor="end" font-size="12" fill="currentColor">{_e(_man(lay["hi"]))}</text>'
            f'<text x="{x0 - 6}" y="{yl + 4}" text-anchor="end" font-size="12" fill="currentColor">{_e(_man(lay["lo"]))}</text>'
            f'<text x="{x0}" y="{h - 6}" text-anchor="start" font-size="12" fill="currentColor">{_e(md(first["date"]))}</text>'
            f'<text x="{x1}" y="{h - 6}" text-anchor="end" font-size="12" fill="currentColor">{_e(md(last["date"]))}</text>'
            f'<text x="{first["x"]}" y="{first["y"] - 9}" text-anchor="start" font-size="13" font-weight="700" fill="currentColor">{_e(md(first["date"]))} {_e(_yen(first["price"]))}</text>'
            f'<text x="{last["x"]}" y="{last["y"] - 9}" text-anchor="end" font-size="13" font-weight="700" fill="currentColor">{_e(md(last["date"]))} {_e(_yen(last["price"]))}</text>')
    label = f'最高買取の推移 {first["date"]} {_yen(first["price"])} から {last["date"]} {_yen(last["price"])}'
    return f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" aria-label="{_e(label)}">{axes}{lines}{dots}</svg>'


def _prev_big(cmp_: dict) -> str:
    """点が足りない・線を結べないときの代わり。前回比（prev_compare の値）を大きく出す。"""
    if cmp_["status"] == "OK":
        return (f'<div class="prevbig"><span>前回比（同じ店の組だけ）</span><b>{_signed(cmp_["delta"])}</b>'
                f'<em>{_md(cmp_["prev_date"])} → 今回・共通 {cmp_["common"]} 店の最高 {_yen(cmp_["prev_best"])} → {_yen(cmp_["cur_best"])}</em></div>')
    return f'<div class="prevbig"><span>前回比</span><b class="nodata">データ無し</b><em>{_e(cmp_["reason"])}</em></div>'


def _hist_html(history, tl, s: dict, comp: dict) -> str:
    sku = s.get("sku")
    trend = H.sku_trend(tl, sku)
    if tl is None:
        body = f'<p class="mut nodata">買取の履歴: {H.NO_HISTORY}</p>'
    else:
        shown = [t for t in trend if t["best_price"] is not None]
        if not shown:
            body = '<p class="mut nodata">買取の履歴: この SKU の記録なし（データ無し）</p>'
        else:
            rows = "".join(
                f'<tr><td>{_e(t["date"])}</td><td class="num">{_yen(t["best_price"])}</td><td>{_e(t["best_shop"])}</td>'
                f'<td class="num">{t["shops"]} 店</td><td class="num">{_signed(t["net"]) if t["net"] is not None else "—"}</td></tr>' for t in shown)
            one = '<p class="mut">記録 1 件のみ（推移は比較できない）</p>' if len(shown) == 1 else ""
            chart = _sparkline(H.spark_layout(shown))
            body = (f'{chart or _prev_big(H.prev_compare(tl, sku))}{one}'
                    f'<details><summary>履歴の表（{len(shown)} 件）</summary>'
                    f'<div class="tw"><table class="mini"><thead><tr><th>調査日</th><th>最高買取</th><th>店</th><th>取得店数</th>'
                    f'<th>純利益（最高買取の行）</th></tr></thead><tbody>{rows}</tbody></table></div></details>'
                    f'<p class="mut">取得店数が違う日どうしは同列に比べない（前回比は同じ店の組だけ・線は店数が同じ日どうしだけつなぐ）。実行可能でない価格は含まない。</p>')
    ap = H.apple_trend(history, sku, comp)
    if ap["status"] == "NO_DATA":
        apple = f'Apple 価格の推移: {H.NO_HISTORY}'
    elif ap["status"] == "ONE":
        d, p = ap["points"][0]
        apple = f'Apple 価格の推移: 記録 1 件のみ（{_e(d)} {_yen(p)}）'
    else:
        apple = "Apple 価格の推移: " + _e(" → ".join(f"{d} {_yen(p)}" for d, p in ap["points"]))
    return f'<div class="hist"><h4>履歴</h4>{body}<p class="mut">{apple}</p></div>'


def _signals_html(comp: dict, tl) -> str:
    sg = H.signals(comp, tl)

    def _ev(e):
        move = (f"（{_yen(e['from'])} → {_yen(e['to'])}）" if isinstance(e.get("from"), int) and isinstance(e.get("to"), int)
                else f"（{_e(e.get('from'))} → {_e(e.get('to'))}）" if e.get("from") and e.get("to") else "")
        return f"<li>{_e(EVENT_LABEL.get(e.get('type'), e.get('type')))}: {_e(e.get('sku'))} {_e(e.get('shop') or '')}{move}</li>"
    parts = []
    for g in sg["groups"]:
        parts.append(f'<li><b>{_e(g["date"])}</b><ul>{"".join(_ev(e) for e in g["events"])}</ul></li>')
    if not parts:
        parts.append(f'<li class="mut">検出なし（{_e(comp.get("events_note") or "変動の記録はまだありません")}）</li>')
    note = f'<p class="mut">{_e(sg["history_note"])}</p>' if sg["history_note"] else ""
    return f'<ul class="sig">{"".join(parts)}</ul>{note}'


def _candidates_html(candidates) -> str:
    """新製品・予約情報。モデルごとの 1 つの小さな表（容量・状態・Apple 公式価格）。確認日は同じなら見出しに 1 回だけ。
    発売日・予約日は全件データ無しなので行に繰り返さず 1 回だけ書く。価格が取れていない候補は 1 つの details にまとめる。"""
    groups = H.apple_candidates(candidates)
    if groups is None:
        return '<p class="nodata">データ無し（新製品・予約情報を読めない）</p>'
    out, noprice = [], []
    for g in groups:
        items = [i for i in g["items"] if i["price"] is not None]
        noprice += [(g["model"], i) for i in g["items"] if i["price"] is None]
        if not items:
            continue
        dates = {(i["first_seen"], i["last_seen"]) for i in items}
        if len(dates) == 1:
            f, l = next(iter(dates))
            head_note = f'<p class="mut">初確認 {_fmt_age_date(f)}／最終確認 {_fmt_age_date(l)}</p>'
            seen = lambda i: ""                                                       # noqa: E731
        else:
            head_note = ""
            seen = lambda i: f'<div class="mut">初確認 {_fmt_age_date(i["first_seen"])}／最終確認 {_fmt_age_date(i["last_seen"])}</div>'   # noqa: E731
        rows = "".join(f'<tr><th scope="row">{_e(i["capacity"])}</th><td>{_e(i["status_label"])}{seen(i)}</td><td class="num">{_yen(i["price"])}</td></tr>'
                       for i in items)
        out.append(f'<h3>{_e(g["model"])}</h3>{head_note}<div class="tw"><table class="mini cand"><thead><tr><th>容量</th><th>状態</th>'
                   f'<th class="num">Apple 公式価格</th></tr></thead><tbody>{rows}</tbody></table></div>')
    if noprice:
        li = "".join(f'<li>{_e(m)} {_e(i["capacity"])} — {_e(i["status_label"])}／価格未取得</li>' for m, i in noprice)
        out.append(f'<details class="nodata-skus"><summary>価格未取得の商品（{len(noprice)}件）</summary><ul class="nd-list">{li}</ul></details>')
    return ("".join(out) + '<p class="mut">発売日・予約日: データ無し（Apple 公式ページから取得できていません）。'
            'Apple 公式ページで確認した候補の表示だけです。監視対象の商品には、ここからは登録しません。</p>')


def _today_html(comp: dict, now: datetime | None = None, fx: "_Fx | None" = None) -> str:
    """h1 直下の「今日のおすすめ」。正本に登録済みで、実行可能な買取価格と純利益がある SKU から 1 件。
    購入候補（BUY・購入可）が 1 件でもあればそれを優先し、無ければ純利益が最大の 1 件。
    判定が購入候補でなければ「様子見」と正直に書く（買うとは案内しない）。調査が古いときは、先に鮮度の注意を出す。値は既存データの再表示だけ。"""
    cand = [s for s in comp.get("skus") or [] if s.get("identity") == "REGISTERED" and s.get("highest_executable")
            and isinstance(s.get("net_profit"), int)]
    if not cand:
        return ('<section class="today" aria-labelledby="today-h"><h2 id="today-h">今日のおすすめ</h2>'
                '<p class="lead"><span class="wait">確認待ち</span> — 確定できる買取価格と利益がそろった容量が、今回はありません。'
                '推測の価格・利益は出していません。</p></section>')
    fx = fx or _Fx(comp.get("research_date"))
    best = H.pick_best(cand)
    a = H.sku_answer(best)
    net, roi = best["net_profit"], best.get("roi_pct")
    buy_ok = H.is_buy_candidate(best)
    try:
        days = ((now or datetime.now(_JST)).date() - datetime.strptime(str(comp.get("research_date")), "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        days = None
    stale = _is_stale_days(days)
    stale_t = (f'<span class="wait">調査が古い（{days} 日前）</span> — ' if days is not None else '<span class="wait">調査日を確認できません</span> — ')
    if net > 0 and buy_ok and stale:
        lead = (f'{stale_t}調査時点では <b>{_e(best["sku"])}</b> が購入候補でしたが（売り先 <b>{_e(a["sell_shop"])}</b>）、価格は変わっている可能性が高いため、公式・各店で再確認するまで買うとは案内しません。')
    elif net > 0 and buy_ok:
        lead = (f'<b>{_e(best["sku"])}</b> が購入候補です。<b>{_e(a["sell_shop"])}</b> へ売る想定です（金額は下の数値）。')
        g_l = fx.sid(best) + "-tl"                              # 「購入候補です」は、買取価格と Apple 購入可否の両方が新しいときだけ
        lead = (_lvn("span", lead, g_l, [fx.buy(best)[0], fx.apple(best)])
                + _st("span", f'<span class="wait">価格の再確認待ち（取得 {_mmdd(fx.buy(best)[1])}）</span> — 取得時点では <b>{_e(best["sku"])}</b> が購入候補でしたが（売り先 <b>{_e(a["sell_shop"])}</b>）、'
                      f'価格は変わっている可能性が高いため、公式・各店で再確認するまで買うとは案内しません。', g_l))
    elif net > 0:
        lead = ((stale_t if stale else "") + f'<span class="wait">様子見</span> — いま買ってよいと言える容量はありません。計算上いちばん利益が大きいのは <b>{_e(best["sku"])}</b>'
                f'ですが、買う条件にはまだ届いていません。')
    else:
        lead = ((stale_t if stale else "") + f'<span class="wait">様子見</span> — 黒字になる容量は確認できません。いちばん近いのは <b>{_e(best["sku"])}</b> です。')
    hero = _hero_html(best, False, fx, "t")
    if stale:                                                   # 調査が古いときは、緑にしない（購入候補の見た目を出さない）
        hero = hero.replace("sbadge--buy", "sbadge--wait").replace('class="pos"', 'class=""').replace("sbadge--profit", "sbadge--off")
    return (f'<section class="today" aria-labelledby="today-h"><h2 id="today-h">今日のおすすめ</h2><p class="lead">{lead}</p>'
            f'{hero}'
            f'<p class="mut">調査日 {_md(comp.get("research_date"), now)} の掲載価格での計算です。確定ではありません。</p></section>')


def render(comp: dict, *, now: datetime | None = None, history=None, candidates=None) -> str:
    """描画。調査の古さ（_PAGE_STALE）は描画中だけ有効にし、終わったら必ず戻す（呼び出しをまたいで残さない）。"""
    global _PAGE_STALE
    try:
        return _render(comp, now=now, history=history, candidates=candidates)
    finally:
        _PAGE_STALE = False


def _render(comp: dict, *, now: datetime | None = None, history=None, candidates=None) -> str:
    global _PAGE_STALE
    try:
        _d = ((now or datetime.now(_JST)).date() - datetime.strptime(str(comp.get("research_date")), "%Y-%m-%d").date()).days
    except (TypeError, ValueError):
        _d = None
    _PAGE_STALE = _is_stale_days(_d)
    now = now or datetime.now(_JST)
    fx = _Fx(comp.get("research_date"))
    counts = comp.get("counts") or {}
    tl = H.build_timeline(comp, history)
    groups = H.group_models(comp.get("skus") or [])
    concl, models, nodata_all = [], [], []
    for g in groups:
        concl.append(f'<h3>{_e(g["model"])}{"" if g["primary"] else REF_CHIP_LONG}</h3>'
                     + _conclusion_html(g, tl, fx))
        def _card_of(s):
            return _sku_html(s, extra_html=_hist_html(history, tl, s, comp), prev_html=_prev_kv(H.prev_compare(tl, s.get("sku"))), fx=fx)
        has = [s for s in g["skus"] if s.get("highest_executable") or isinstance(s.get("net_profit"), int)]
        nod = [s for s in g["skus"] if s not in has]
        cards = "".join(_card_of(s) for s in has)
        for s in nod:                                           # 価格の無い容量は縦のカードにせず、最後の 1 つの details にまとめる
            nodata_all.append((g, s, _card_of(s) if s.get("rows") else ""))
        if not has:
            continue
        if g["primary"]:
            models.append(f'<details class="model" open><summary>{_e(g["model"])}（{len(g["skus"])} 容量）</summary>{cards}</details>')
        else:
            models.append(f'<details class="model"><summary>{_e(g["model"])}（{REF_LONG_TEXT}／{len(g["skus"])} 容量・押すと開く）</summary>'
                          f'<p class="mut">監視対象に未登録の参考表示です。買う・売るの判断には使わないでください。</p>{cards}</details>')
    if nodata_all:
        items = "".join(
            (f'<li><details class="nd"><summary>{_e(s["sku"])}{"" if g["primary"] else " <span class=mut>（参考）</span>"} — Apple {_yen(s.get("apple_price"))} ／ 価格未取得'
             f'<span class="mut">（買取店の行 {len(s.get("rows") or [])} 件・押すと開く）</span></summary>{card}</details></li>') if card else
            f'<li class="ndrow">{_e(s["sku"])}{"" if g["primary"] else " <span class=mut>（参考）</span>"} — Apple {_yen(s.get("apple_price"))} ／ 価格未取得</li>'
            for g, s, card in nodata_all)
        models.append(f'<details class="nodata-skus"><summary>価格未取得の商品（{len(nodata_all)}件）</summary>'
                      f'<p class="mut">確認できる買取価格がまだ無い容量です（推測の価格・利益は出していません）。</p><ul class="nd-list">{items}</ul></details>')
    missing = [s for s in comp.get("shops") or [] if s.get("status") != "ACTIVE" or s.get("rows_count", 0) == 0]
    miss_html = "".join(
        f'<li><b>{_link(s.get("price_page_url") or s.get("official_url"), s.get("shop"))}</b> — {_e(STATUS_LABEL.get(s.get("status"), s.get("status")))}'
        f'{("（新規に発見した店）" if s.get("discovered") else "")}<span class="mut"> {_plain(s.get("reason"))}</span></li>' for s in missing)
    fr_dates = [r.get("updated_on") for s_ in comp.get("skus") or [] for r in s_.get("rows") or [] if r.get("freshness") == "FRESH"]
    if counts.get("FRESH", 0):                                  # 「更新が新しい N 店」は、最も古い FRESH の行が期限を超えたら成り立たない
        fresh_tile = (_lv("b", _e(counts.get("FRESH", 0)), "sum-fresh", _buy_attrs(min((d for d in fr_dates if d), default=None) if fr_dates and all(fr_dates) else (comp.get("research_date") if not fr_dates else None)))
                      + _st("b", "確認待ち", "sum-fresh"))
    else:
        fresh_tile = f'<b>{_e(counts.get("FRESH", 0))}</b>'
    return f"""<!doctype html>
<html lang="ja" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>iPhone 買取比較 | プレ値速報</title><meta name="robots" content="index,follow"><style>{legacy_css()}{CSS}{HUB_CSS}{_hide_when_stale_css()}</style></head>
<body>{site_nav("iphone")}<main>
<p><a class="back" href="./">← プレ値速報へ戻る</a></p>
<h1>iPhone 買取比較（新品未開封）</h1>
{_today_html(comp, now, fx)}
<p class="mut">調査日 {_md(comp.get("research_date"), now)}（週1回の Web 調査）／このページの作成 {_e(now.strftime("%Y-%m-%d %H:%M"))}</p>
{age_banner(comp.get("research_date"), now)}
<details class="note hub-note"><summary><b>週次の調査です。確定ではありません。</b>（この調査について）</summary>
<p>価格は調査日の掲載価格で、現在の価格とは限りません。各所に調査日・確認日・鮮度を出しています。</p>
<p class="mut">調査データの生成 {_e(comp.get("generated_at"))}</p><div>{_e(comp.get("note"))}</div></details>
<div class="sum"><div><span class="mut">調べた買取店</span><b>{_e(comp.get("shops_researched"))}</b></div>
<div><span class="mut">価格を取れた店</span><b>{_e(counts.get("ACTIVE", 0))}</b></div>
<div><span class="mut" title="FRESH">更新が新しい</span>{fresh_tile}</div>
<div><span class="mut" title="STALE">更新が古い</span><b>{_e(counts.get("STALE", 0))}</b></div>
<div><span class="mut" title="UNKNOWN_FRESHNESS">更新日の記載なし</span><b>{_e(counts.get("UNKNOWN_FRESHNESS", 0))}</b></div>
<div><span class="mut">価格なし</span><b>{_e(counts.get("NO_PRICE", 0))}</b></div>
<div><span class="mut">取得失敗・拒否</span><b>{_e(counts.get("FAILED", 0) + counts.get("BLOCKED", 0))}</b></div></div>
<h2>今の結論</h2>
<p class="mut">どの容量を買うか／どの店へ売るか／利益／前回比／購入候補か様子見か。答えを出せないものは理由つきで「確認待ち」「データ無し」にしています（推測の価格・利益は出しません）。</p>
{"".join(concl)}
<h2>モデル別・容量別の詳細</h2>
{"".join(models)}
<h2>シグナル（前回からの変動）</h2>
{_signals_html(comp, tl)}
<p class="mut">通知は送信していません（検出の記録だけ）。</p>
<h2>新製品・予約情報</h2>
{_candidates_html(candidates)}
<h2>価格を取れなかった店・価格が部分的な店</h2><details class="nu-more"><summary>店ごとの調査メモ（{len(missing)} 件・押すと開く）</summary><ul>{miss_html}</ul></details>
<p class="mut">この表は週次の調査で、価格が変わっている場合があります。売る前に各店の公式の価格ページで最新の価格・条件（事前申込・検品・減額）を必ず確認してください。取得できない店の回避（認証の突破・過剰なアクセス）は行っていません。</p>
</main><script>{rf.JS_FRESHNESS}</script></body></html>"""


def _prev_kv(cmp_: dict) -> str:
    if cmp_["status"] == "OK":
        return (f'<div class="kv"><span>前回比（同じ店の組だけ）</span><b>{_signed(cmp_["delta"])}</b>'
                f'<em>{_e(cmp_["prev_date"])} の共通 {cmp_["common"]} 店: 最高 {_yen(cmp_["prev_best"])} → {_yen(cmp_["cur_best"])}</em></div>')
    return f'<div class="kv"><span>前回比</span><b class="nodata">データ無し</b><em>{_e(cmp_["reason"])}</em></div>'
