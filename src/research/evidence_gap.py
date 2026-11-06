"""証拠不足の原因の分類と価格の種類（Coverage Wave 7c-1）。

- **公式の価格が確認できない原因**（`official_gap_cause`）: 作業キューの「VERIFY_OFFICIAL_PRICE」が何を意味するかを、原因ごとに分ける。
  公式がその商品を今は売っていない（SALE_ENDED）なら、公式の価格は存在しないので、運営者が公式を確認しても何も変わらない
  （仕入れ値は小売の価格で確かめる）。取得元が実装されていない・遮断されている・確認が古い・設定値だけ、などは原因が違うので次の行動も違う。
  **原因は決まった規則で決める**（推測しない。判断に使う情報が無ければ UNKNOWN_CAUSE）。個別の商品は非公開で、公開してよいのは原因ごとの件数だけ。
- **価格の種類**（`price_type_of`）: 仕入れ値の証拠（`retail_lookup.price_evidence` の結果）を REGULAR / SALE / COUPON / MEMBERSHIP / CONDITIONAL / UNKNOWN に分ける。
  確定の仕入れ値に使ってよいのは、**条件なしで全員が再現できる現金の価格**（REGULAR と、条件なしの即時値引き SALE）だけ。
  ポイント・キャッシュバックは現金から引かず、参考（reference_types）として別に残す。クーポン・会員限定・キャンペーン・数量限定は条件つき（確定に使わない）。

このモジュールは確定・通知・通信の部品を import しない（分類だけ。確定の判定は既存の関門が決める）。
"""
from __future__ import annotations

# ── 公式の価格が確認できない原因 ────────────────────────────────────────────────
SALE_ENDED = "SALE_ENDED"                          # 公式がその商品を今は販売していない（販売終了・後継機に交代）。公式の仕入れ価格は存在しない
SOURCE_NOT_IMPLEMENTED = "SOURCE_NOT_IMPLEMENTED"  # 公式の確認の取得元（URL・取得器）が登録されていない
SOURCE_BLOCKED = "SOURCE_BLOCKED"                  # 公式の取得元が遮断・到達不能（回避しない。人が公式ページで確認する）
IDENTITY_NOT_MATCHED = "IDENTITY_NOT_MATCHED"      # 公式のページの商品が、この商品と一致しない（型番・容量・版が違う）
PRICE_NOT_FOUND = "PRICE_NOT_FOUND"                # 公式の取得元はあるが、価格を読めていない
VERIFICATION_STALE = "VERIFICATION_STALE"          # 確認済みの価格はあるが、確認が古い（再確認が必要）
CONFIGURED_PRICE_ONLY = "CONFIGURED_PRICE_ONLY"    # 設定値の価格だけで、公式での確認日が無い
PAGE_CHANGED = "PAGE_CHANGED"                      # 公式の再確認でページは取得できたが型番・価格を読めなかった（ページの構造が変わった可能性。取得器の見直し・人の確認）
PRICE_CHANGED = "PRICE_CHANGED"                    # 公式の再確認で、型番は一致したが価格が記録と違う（人が確かめて記録を更新する）
RECHECK_MATCHED = "RECHECK_MATCHED"                # 公式の再確認で、型番・価格が記録と一致した（自動では確認日を更新しない方針なので、人が確かめて記録を更新する。公式の確認のやり直しではない）
UNKNOWN_CAUSE = "UNKNOWN_CAUSE"
GAP_CAUSES = (SALE_ENDED, SOURCE_NOT_IMPLEMENTED, SOURCE_BLOCKED, IDENTITY_NOT_MATCHED, PRICE_NOT_FOUND, PAGE_CHANGED, PRICE_CHANGED, RECHECK_MATCHED,
              VERIFICATION_STALE, CONFIGURED_PRICE_ONLY, UNKNOWN_CAUSE)

# 公式の再確認（`scripts/recheck_official.py`）の失敗の理由（`collectors.polite` の語彙。ここでは文字列の一致だけで、その部品には依存しない。
# 語彙が増えたときに取りこぼさないよう、テストが polite の集合との整合を確かめる）
_BLOCKED_REASONS = frozenset({"http_403", "http_401", "site_blocked", "rate_limited_429", "robots_disallowed", "robots_unreachable",
                              "blocked_cloud_ip", "cloudflare_blocked", "access_denied", "html_scraping_disabled"})   # 遮断・規約上の拒否（回避しない）
_UNREACHABLE_REASONS = frozenset({"timeout", "connection_error", "ssl_error", "service_unavailable",
                                  "http_500", "http_502", "http_503", "http_504"})                                   # 到達できなかった（一時的な障害を含む。人が確認する）
_PAGE_REASONS = frozenset({"http_404", "http_410", "moved", "empty_html", "price_not_found", "no_data", "html_failed"})  # ページは見えたが読めない・移動した
# 価格の証拠の区分（`market.price_evidence`。ここでは文字列の一致だけ見て、その部品には依存しない）
_EV_STALE, _EV_CONFIGURED, _EV_UNKNOWN = "STALE", "CONFIGURED_REFERENCE", "UNKNOWN"
_EV_VERIFIED = frozenset({"VERIFIED_CURRENT", "VERIFIED_DATED"})


def official_gap_cause(*, evidence, meta, official_not_sold: bool = False, source_blocked: bool = False) -> str:
    """公式の価格が確認済みでない原因（1 つ）。判断の順序は固定:
    販売終了 → 同一性が未決（どの版か決まっていない）→ 取得元が未登録（URL が無い）→ 商品の同一性が確認できない → 確認済み（不足ではない）→ 遮断・到達不能 → ページの変更（価格を読めない）→
    価格が記録と違う → 再確認で一致（記録の更新待ち）→ 確認が古い → 設定値だけ → 価格を読めていない → 不明。

    入力（meta のフラグ）は `official_signals` が公式の再確認の記録と登録簿の判断から作る:
    `official_not_sold`（取得元の設定の販売終了）・`registry_sale_ended`（公式の登録簿の販売終了 = DISCONTINUED）・
    `recheck_sale_ended`（再確認でページに販売終了の表示）。**後の 2 つは原因の分類だけ**に使い、候補の買い側の経路（`official_not_sold` が決める）は変えない・
    `identity_undecided`（どの版かが決まっていない = 判断待ち・型番も JAN も無い）・`identity_mismatch`（型番・JAN の登録はあるが公式の証拠が無い・食い違う）・
    `source_blocked`（再確認が遮断・到達不能）・
    `recheck_failed`（再確認でページを取得したが型番・価格を読めなかった）・`price_changed`（再確認で価格が記録と違う）・
    `recheck_matched`（再確認で型番・価格が記録と一致）。
    URL が空なら、確認の根拠のページが無いので evidence に関わらず取得元が未登録（ただし再確認の記録に URL があれば `gap_url` として分類にだけ使う）。
    """
    meta = meta if isinstance(meta, dict) else {}
    ev = str(evidence or _EV_UNKNOWN)
    # 取得元が登録されているか: 取得元の設定の URL、または再確認の記録の URL（分類専用の gap_url。候補の買い側の URL・送料には使わない）
    has_url = bool(str(meta.get("url") or "").strip()) or bool(str(meta.get("gap_url") or "").strip())
    if official_not_sold or meta.get("official_not_sold") or meta.get("recheck_sale_ended") or meta.get("registry_sale_ended"):
        return SALE_ENDED
    if meta.get("identity_undecided"):
        return IDENTITY_NOT_MATCHED                   # どの版かが決まっていない商品は、公式ページを登録しても確認できない（同一性が先）
    if not has_url:
        return SOURCE_NOT_IMPLEMENTED
    if meta.get("identity_mismatch"):
        return IDENTITY_NOT_MATCHED
    if ev in _EV_VERIFIED:
        return UNKNOWN_CAUSE                          # 確認済みなら不足ではない（遮断・ページの変更より先に判定）
    if source_blocked or meta.get("source_blocked"):
        return SOURCE_BLOCKED
    if meta.get("recheck_failed"):
        return PAGE_CHANGED
    if meta.get("price_changed"):
        return PRICE_CHANGED
    if meta.get("recheck_matched"):
        return RECHECK_MATCHED                        # 新しい再確認で一致している。「確認が古い・設定値だけ」ではなく、記録の更新待ち
    if ev == _EV_STALE:
        return VERIFICATION_STALE
    if ev == _EV_CONFIGURED:
        return CONFIGURED_PRICE_ONLY
    if ev == _EV_UNKNOWN:
        return PRICE_NOT_FOUND
    return UNKNOWN_CAUSE


def official_signals(recheck_doc, products, now, identity_state, *, verified_urls=None, max_age_hours: float = 36.0) -> dict:
    """公式の価格が確認できない原因の入力（商品 ID → フラグ）を、実際の記録から作る。通信しない・推測しない。

    - 公式の再確認の記録（`exports/official_recheck/latest.json` の results。`scripts/recheck_official.py` の状態）。観測の時刻が新しいもの
      （max_age_hours 以内・1 時間を超える未来でない）だけ。古い記録・読めない時刻は使わない（古い遮断を今日のものにしない）:
        blocked → source_blocked／failed で、理由が遮断・到達不能（`_BLOCKED_REASONS` / `_UNREACHABLE_REASONS`）→ source_blocked／
        failed で、ページ側の理由（404・移動・空のページ・価格を読めない）や未知の理由・理由なし → recheck_failed（遮断とは断定しない）／
        sale_ended → recheck_sale_ended（原因の分類だけ）／changed → price_changed／unchanged → recheck_matched（型番・価格が一致。記録の更新待ち）
    - 再確認の記録にある URL と、公式の登録簿の確認済み URL（`verified_urls`: 商品 ID → {"url": …}）（https・ホストあり・認証情報なし・印字可能。時刻に関わらず）→ `gap_url`（**分類専用**。取得元の設定（DB）に URL が無くても根拠のページがあることを
      示す。候補の買い側の URL・送料の判定には使わない）
    - 公式の登録簿の同一性（`identity_state(product)`）: NEEDS_USER_DECISION / AMBIGUOUS → identity_undecided（どの版かが決まっていない）／
      PARTIAL_IDENTITY → identity_mismatch（型番・JAN の登録はあるが公式の証拠が無い）／DISCONTINUED → registry_sale_ended（販売終了。分類専用）。
      IDENTITY_CONFIRMED は不足ではない
    現在時刻がタイムゾーンなしなら JST とみなす（比べられない値で落とさない）。
    """
    from datetime import datetime, timedelta, timezone
    out: dict = {}
    if getattr(now, "tzinfo", None) is None:
        now = now.replace(tzinfo=timezone(timedelta(hours=9)))

    def _flag(pid, key, value=True):
        if pid:
            out.setdefault(str(pid), {})[key] = value

    doc = recheck_doc if isinstance(recheck_doc, dict) else {}
    results = doc.get("results")
    for r in (results if isinstance(results, (list, tuple)) else []):         # リストでなければ空（登録簿の旗は残す）
        if not isinstance(r, dict):
            continue
        pid = r.get("product_id") if isinstance(r.get("product_id"), str) else None
        url = str(r.get("url") or "").strip()
        if pid and _https_url_ok(url):
            _flag(pid, "gap_url", url)
        st, why = str(r.get("status") or ""), str(r.get("reason") or "").strip()
        if st == "failed":
            # 遮断・到達できなかった → source_blocked（人が公式ページで確認。回避しない）。ページは見えたが読めない・移動 → recheck_failed。
            # 理由が未知・空なら、遮断とは断定せず recheck_failed（ページ側の問題として人が確認する）
            failed_key = "source_blocked" if (why in _BLOCKED_REASONS or why in _UNREACHABLE_REASONS) else "recheck_failed"
        else:
            failed_key = None
        key = {"blocked": "source_blocked", "failed": failed_key, "sale_ended": "recheck_sale_ended", "changed": "price_changed",
               "unchanged": "recheck_matched"}.get(st)
        if key is None:
            continue
        try:
            at = datetime.fromisoformat(str(r.get("observed_at") or "").replace(" JST", ""))
            if at.tzinfo is None:
                at = at.replace(tzinfo=now.tzinfo)
            age = now - at
        except (ValueError, TypeError, OverflowError):
            continue
        if age < timedelta(hours=-1) or age > timedelta(hours=max_age_hours):
            continue
        _flag(pid, key)
    for pid, rec in (verified_urls.items() if isinstance(verified_urls, dict) else []):
        u = str(rec.get("url") or "").strip() if isinstance(rec, dict) else ""
        if isinstance(pid, str) and _https_url_ok(u):
            out.setdefault(pid, {}).setdefault("gap_url", u)                  # 再確認の記録の URL を優先し、無ければ登録簿の確認済み URL
    for p in products or []:
        if not isinstance(p, dict):
            continue
        try:
            state = identity_state(p)[0]
        except Exception:  # noqa: BLE001 - 判断できない商品は旗を立てない（推測しない）
            continue
        if state in ("AMBIGUOUS", "NEEDS_USER_DECISION"):
            _flag(p.get("id") or p.get("product_id"), "identity_undecided")
        elif state == "PARTIAL_IDENTITY":
            _flag(p.get("id") or p.get("product_id"), "identity_mismatch")
        elif state == "DISCONTINUED":
            _flag(p.get("id") or p.get("product_id"), "registry_sale_ended")
    return out


_HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-.")


def _https_url_ok(url: str) -> bool:
    """根拠のページの URL として補ってよいか: https（スキームは大文字も可）・ホストあり（ASCII の英数字とハイフンとドットだけ）・認証情報（@）なし・ポートは 1〜65535・
    空白・制御文字・不可視文字なし（パスやクエリの日本語など印字可能な文字は可）。
    パーサーの import を増やさず、手書きで検証する（この部品は他の部品・通信に依存しない）。"""
    if (not isinstance(url, str) or url[:8].lower() != "https://" or not url.isprintable() or any(ch.isspace() or ch == "\\" for ch in url)):
        return False                                  # 印字可能な文字だけ（不可視文字・DEL・方向制御を通さない）。ホストは下で ASCII に限る（IDN は punycode で）
    authority = url[len("https://"):].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if not authority:
        return False                                  # 認証情報（@）はホストの許可文字に無いので、下のホストの検査で拒否される
    host, _sep, port = authority.partition(":")
    host = host[:-1] if host.endswith(".") and not host.endswith("..") else host          # 末尾のドット（完全修飾名）は 1 つだけ許す
    labels = host.split(".")
    if not (bool(host) and set(host) <= _HOST_CHARS and len(labels) >= 2 and all(lb and not lb.startswith("-") and not lb.endswith("-") for lb in labels)):
        return False
    if all(lb.isdigit() or lb.lower().startswith("0x") for lb in labels) or labels[-1].isdigit():
        return False                                  # IP リテラル風（数字だけ・0x 表記）のホストは根拠のページにしない
    return not _sep or (port.isascii() and port.isdigit() and len(port) <= 5 and 1 <= int(port) <= 65535)


SIGNAL_KEYS = frozenset({"gap_url", "source_blocked", "recheck_failed", "recheck_sale_ended", "registry_sale_ended", "price_changed", "recheck_matched",
                         "identity_undecided", "identity_mismatch"})        # 分類専用の旗（official_signals が作るもの）


def merge_signals(meta_by_pid: dict, signals: dict) -> dict:
    """`official_signals` の旗を、商品 ID → official_meta に流し込む（メタを書き換えて返す）。
    **`meta["url"]` には触らない**（`gap_url` は分類専用の別キー。候補の買い側の URL・送料の判定に影響させない）。"""
    for pid, flags in (signals or {}).items():
        m = meta_by_pid.get(pid)
        if not isinstance(m, dict):
            m = meta_by_pid[pid] = {}
        for k, v in flags.items():
            if k in SIGNAL_KEYS:                             # 許可した旗だけ（url・official_not_sold など買い側の経路・URL を決めるキーは書かない）
                m[k] = v
    return meta_by_pid


def gap_counts(rows) -> dict:
    """原因ごとの件数（公開してよい。商品・ID は出さない）。キーは決まった一覧だけ・0 も出す。"""
    out = {c: 0 for c in GAP_CAUSES}
    for r in rows or []:
        c = r.get("official_gap") if isinstance(r, dict) else None
        if isinstance(c, str) and c in out:
            out[c] += 1
    return out


# ── 価格の種類 ───────────────────────────────────────────────────────────────────
REGULAR, SALE, COUPON, MEMBERSHIP, CONDITIONAL, UNKNOWN = "REGULAR", "SALE", "COUPON", "MEMBERSHIP", "CONDITIONAL", "UNKNOWN"
PRICE_TYPES = (REGULAR, SALE, COUPON, MEMBERSHIP, CONDITIONAL, UNKNOWN)
CONFIRMABLE_TYPES = frozenset({REGULAR, SALE})        # 確定の仕入れ値に使ってよい（条件なしで全員が再現できる現金の価格）
POINTS, CASHBACK = "POINTS", "CASHBACK"               # 参考の項目（現金から引かない）
_COND_COUPON, _COND_MEMBER = "COUPON_REQUIRED", "MEMBER_ONLY"


def price_type_of(ev) -> dict:
    """仕入れ値の証拠（`retail_lookup.price_evidence` の結果）の価格の種類。

    {"price_type": 種類, "confirmable": 確定に使ってよいか, "reference_types": [POINTS / CASHBACK（現金から引かない参考）]}。
    優先順: 価格が読めない → UNKNOWN／クーポン → COUPON／会員限定 → MEMBERSHIP／キャンペーン・数量限定 → CONDITIONAL／
    条件なしで即時値引きあり → SALE／それ以外 → REGULAR。ポイント・キャッシュバックは種類を変えない（参考にだけ残す）。
    """
    ev = ev if isinstance(ev, dict) else {}

    def _n(v):
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    refs = [t for t, k in ((POINTS, "points"), (CASHBACK, "cashback")) if _n(ev.get(k)) > 0]
    # price_conditions が無い入力でも、条件の元の項目（クーポン・会員限定・キャンペーン・数量限定）があれば条件つきとして読む（緩くならない）
    raw_conds = ev.get("price_conditions")
    if raw_conds is None or raw_conds == "":
        conds = set()
    elif isinstance(raw_conds, str):
        conds = {raw_conds}
    elif isinstance(raw_conds, (list, tuple, set, frozenset)):
        conds = {c for c in raw_conds if c}
    else:
        conds = {"UNREADABLE"}                               # 条件の値が壊れている（数値・辞書など）。条件なしとは読まず、条件つき（確定に使わない）側に倒す
    if str(ev.get("required_coupon") or "").strip():
        conds = set(conds) | {_COND_COUPON}
    if ev.get("member_only"):
        conds = set(conds) | {_COND_MEMBER}
    if str(ev.get("campaign_conditions") or "").strip() or _n(ev.get("campaign_price")) or ev.get("limited_quantity"):
        conds = set(conds) | {"CAMPAIGN_CONDITIONAL"}
    if not _n(ev.get("listed_price")) and not _n(ev.get("effective_price")):
        ptype = UNKNOWN
    elif "effective_price" in ev and not _n(ev.get("effective_price")):
        ptype = UNKNOWN                                      # 現金の価格が確定できない（値引きが価格以上など）なら、確定に使えない
    elif _COND_COUPON in conds:
        ptype = COUPON
    elif _COND_MEMBER in conds:
        ptype = MEMBERSHIP
    elif conds:
        ptype = CONDITIONAL
    elif _n(ev.get("immediate_discount")) > 0:
        ptype = SALE
    else:
        ptype = REGULAR
    return {"price_type": ptype, "confirmable": ptype in CONFIRMABLE_TYPES, "reference_types": refs}


def price_type_counts(rows) -> dict:
    """価格の種類ごとの件数（公開してよい）。キーは決まった一覧だけ・0 も出す。参考（ポイント・キャッシュバックあり）も別に数える。"""
    out = {t: 0 for t in PRICE_TYPES}
    out["with_points"] = 0
    out["with_cashback"] = 0
    out["rejected_conditional"] = 0                       # 条件つきで確定に使わなかった価格（COUPON / MEMBERSHIP / CONDITIONAL）
    for r in rows or []:
        t = r.get("retail_price_type") if isinstance(r, dict) else None
        if not isinstance(t, str) or t not in PRICE_TYPES:
            continue
        out[t] += 1
        refs = r.get("retail_reference_types") or ()
        out["with_points"] += int(POINTS in refs)
        out["with_cashback"] += int(CASHBACK in refs)
        out["rejected_conditional"] += int(t in (COUPON, MEMBERSHIP, CONDITIONAL))
    return out
