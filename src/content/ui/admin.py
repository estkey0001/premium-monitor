"""運営者向けの画面（UI Phase 9）。旧UIにしかなかった運営の情報を新UIの別ページに移す。

URL: ?page=admin&section=overview|sources|data-quality|ai|capital|execution|notifications|system

- **読むだけ**（取得の再実行・価格の編集・通知の再送などの操作は無い。押しても何も起きないボタンも置かない）
- **ログイン・権限の仕組みは無い**（静的なページ。公開ページの中にある）。画面にもそう書く
- 秘密の値（API キー・トークン・Webhook の URL・環境変数の値）は出さない。生成物の JSON からは
  表示する項目だけを明示して読む（丸ごとは出さない）
- 判定（利益・ROI・照合・鮮度・確定ルート）はやり直さない。既存の判定（opportunity.record_route_ok など）を通すだけ
- 試行（attempt）・成功（success）・観測（observed）・生成（generated）の時刻を混ぜない
"""

from __future__ import annotations

import re
from datetime import datetime

from src.content.ui import components as c
from src.content.ui import opportunity as opp
from src.content.ui import product_page
from src.content.ui.components import esc
from src.content.ui.navigation import page_href
from src.tcg.models import JST, parse_dt

SECTIONS = (("overview", "概要"), ("sources", "取得元"), ("data-quality", "データ品質"), ("ai", "AI 候補"),
            ("capital", "資金配分"), ("execution", "実行履歴"), ("notifications", "通知"), ("system", "システム"))
OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
STATUS_TEXT = {OK: "正常", WARN: "要確認", FAIL: "失敗", INFO: "情報"}
STATUS_TONE = {OK: "success", WARN: "warning", FAIL: "danger", INFO: "neutral"}

# 利益商品の候補を外した理由（opportunity_diagnostics の分類）→ 運営向けの言葉
DIAG_LABELS = {"no_buy_price": "仕入れ価格が無い", "unverified_buy_price": "定価が未確認（確認日なし・古い）",
               "no_sell_price": "売却価格が無い", "invalid_identity": "商品の照合が未完了",
               "stale_buyback": "買取価格が古い（14日超）", "unknown_type": "価格の種別が不明（下取りのみ等）",
               "no_sold_period": "成約の期間が不明", "insufficient_sold_samples": "成約の件数が不足",
               "missing_costs": "費用（購入送料など）が不明", "no_profit": "利益が出ない", "other": "その他"}
TCG_LABELS = {"HEALTHY": ("正常", OK), "OK_NO_EVENTS": ("正常（該当なし）", OK), "DEGRADED": ("要確認", WARN),
              "BLOCKED": ("アクセス拒否（人の確認が必要）", WARN), "FAILED": ("取得失敗", FAIL)}
LOT_SOURCE_TONE = {"ACTIVE_LOTTERY": OK, "NO_ACTIVE_LOTTERY": OK, "SOURCE_BLOCKED": WARN,
                   "SOURCE_UNREACHABLE": FAIL, "SOURCE_NOT_MONITORED": INFO}
API_CONFIGURED = {"configured": "設定済み", "not_configured": "未設定"}
API_STATUS = {"disabled_kill_switch": "無効（停止スイッチ）", "dry_run": "試験実行のみ", "enabled": "有効",
              "active": "有効", "disabled": "無効"}
USER_NOTICE_LABELS = {"NEW_MAIN": "利益ルートの成立", "WATCH_TO_BUY": "買い時の条件に到達", "PRICE_DROP": "仕入れ価格の値下がり",
                      "PRICE_RISE": "仕入れ価格の値上がり", "ROI_UP": "利益率の上昇", "ROI_DOWN": "利益率の低下"}
SYSTEM_NOTICE_LABELS = {"HEALTH_ALERT": "データ品質の低下", "DATA_RECOVERED": "データ品質の回復"}
EXEC_STATUSES = ("OPEN", "SUCCESS", "FAILED", "CANCELLED", "INVALIDATED")
# 取得失敗の理由（CLAUDE.md の「失敗理由の意味」）→ 運営向けの言葉（コードは小さく併記）
FAIL_REASON_LABELS = {"price_not_found": "ページは取れたが価格が無い", "product_not_listed": "サイトに掲載なし",
                      "rate_limited_429": "アクセス制限（429）", "site_blocked": "bot 対策でブロック",
                      "service_unavailable": "サーバー障害", "not_supported": "オンライン見積もり非対応",
                      "timeout": "時間切れ", "http_403": "アクセス拒否（403）", "http_404": "ページが無い（404）",
                      "robots_disallowed": "robots.txt で禁止（取得しない）",
                      "robots_unreachable": "robots.txt に到達できない（一時的な障害の可能性。取得しない）",
                      "html_scraping_disabled": "公式 API だけで取得（HTML は取らない）"}
# 価格を利益ルートの計算から外した理由（profit_routes の rejection_top5）
PRICE_REJECT_LABELS = {"stale_over_14d": "14日より古い", "price_zero": "0円（取得失敗）",
                       "accessory_or_wrong_product": "付属品・別の商品", "sold_label_without_evidence": "成約の根拠が無い",
                       "duplicate_price_collision": "同じ価格の重複", "condition_not_new": "新品・未開封でない"}
# 旧表示の取得の警告バー（_collector_warn_bar_html）と同じ分類・同じ順序。段階 → (表示, 状態)
WARN_LEVELS = {"strong": ("強い警告（価格の精度に問題）", FAIL), "moves": ("注意（前回から大きく変動した価格）", WARN),
               "rejected": ("情報（誤りと判断して隔離した価格だけ）", INFO), "soft": ("注意（必須の店の取得失敗が多い）", WARN),
               "info": ("情報（任意の店の取得失敗だけ）", INFO), "none": ("警告なし", OK)}
BIG_CHANGE_PCT = 20                                       # 「大きな変動」（収集の price_change_over_20pct と同じ基準）
EXEC_LABELS = {"OPEN": "進行中", "SUCCESS": "成功", "FAILED": "失敗", "CANCELLED": "見送り", "INVALIDATED": "無効（履歴）"}


# ── 共通 ───────────────────────────────────────────────────────────────

def _yen(v) -> str:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return "—"
    return f"{n:,}円" if n == 0 else f"¥{n:,}"            # 0 は「0円」（取得失敗の ¥0 と見分ける）


def _pct(v, *, ratio: bool = True) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{f * 100:.1f}%" if ratio else f"{f:.1f}%"


def _when(iso) -> str:
    """時刻（絶対時刻だけ。生成・試行・成功・観測・通知のどれかは見出しで分け、「確認」などの言葉を付けない）。
    閲覧時の「N分前確認」への書き換え（data-nu-time）はしない。無ければ「記録なし」。"""
    s = str(iso or "").strip()
    if not s:
        return '<span class="nu-osub">記録なし</span>'
    d = parse_dt(s.replace(" JST", "+09:00").replace(" ", "T", 1))
    if d is None:
        return f'<span class="nu-time">{esc(s[:16])}</span>'
    return f'<time class="nu-time" datetime="{esc(d.isoformat())}">{d.astimezone(JST).strftime("%m/%d %H:%M")}</time>'


def _age_days(iso, now: datetime) -> float | None:
    s = str(iso or "").strip()
    d = parse_dt(s.replace(" JST", "+09:00").replace(" ", "T", 1)) if s else None
    return (now - d).total_seconds() / 86400 if d else None


def _badge(status: str, text: str = "") -> str:
    return (f'<span class="nu-badge nu-tone-{STATUS_TONE.get(status, "neutral")}" data-nu-ad-status="{esc(status)}">'
            f'{esc(text or STATUS_TEXT.get(status, ""))}</span>')


_TERMS = (("参考0→main昇格", "参考ルートから確定ルートへの昇格は 0件"), ("main昇格", "確定ルートへの昇格"),
          ("main ルート", "確定ルート"), ("mainルート", "確定ルート"), ("sell候補", "売却の候補"), ("buy候補", "仕入れの候補"),
          ("stale率", "古い価格の割合"), ("stale化", "古くなる"), ("stale", "古い価格"), ("sold", "成約"))


def _safe_text(s) -> str:
    """生成物の文の表示（取得失敗の ¥0 と紛れる「¥0」を「0円」と書く。内部の言葉を言い換える。秘密の値の形は伏せる）。"""
    t = str(s or "")
    t = re.sub(r"[+＋]?¥0(?![0-9,])", "0円", t)
    t = re.sub(r"0円(?=\d+件)", "0円（取得失敗）", t)            # 「0円5件の解消」→「0円（取得失敗）5件の解消」
    t = re.sub(r"(?i)\bhealth タブ", "運営の管理画面の「取得元」", t)
    for a, b in _TERMS:
        t = t.replace(a, b)
    t = re.sub(r"(?i)(appid|token|secret|key|password)=\S+", r"\1=（非表示）", t)
    return t


def _reason(code) -> str:
    """失敗理由のコード → 言葉（運営者が調べられるようにコードも小さく残す）。"""
    s = str(code or "").strip()
    if not s or s == "—":
        return "—"
    lbl = FAIL_REASON_LABELS.get(s)
    return f'{esc(lbl)} <span class="nu-osub">{esc(s)}</span>' if lbl else esc(s)


def collector_warn(collector: dict, optional: set, threshold: int) -> dict:
    """旧表示の取得の警告バー（daily_lp_generator._collector_warn_bar_html）と同じ分類で、段階と件数を返す。
    隔離した価格（rejected）は公開していないので「精度に問題」とは数えない。強い警告は HARD_REJECT_REASONS だけ。"""
    from src.market.price_quality import HARD_REJECT_REASONS as hard
    col = collector or {}
    sus = [x for x in col.get("suspicious_prices") or [] if isinstance(x, dict)]
    rejected = len({(x.get("product_alias"), x.get("shop")) for x in sus if x.get("action") == "rejected"})
    hard_n = sum(1 for x in sus if x.get("action") != "rejected" and x.get("reason") in hard)
    moves = len({(x.get("product_alias"), x.get("shop")) for x in sus
                 if x.get("action") != "rejected" and x.get("reason") not in hard})
    low = int(((col.get("summary") or {}).get("low_confidence_count")) or 0)
    req_failed = sum(int(r.get("failed") or 0) for r in col.get("shop_detail") or []
                     if isinstance(r, dict) and r.get("shop_id") not in optional)
    opt_failed = sum(int(r.get("failed") or 0) for r in col.get("shop_detail") or []
                     if isinstance(r, dict) and r.get("shop_id") in optional)
    if hard_n or low:
        level = "strong"
    elif moves:
        level = "moves"
    elif rejected:
        level = "rejected"
    elif req_failed >= threshold:
        level = "soft"
    elif opt_failed >= threshold:
        level = "info"
    else:
        level = "none"
    text, status = WARN_LEVELS[level]
    return {"level": level, "text": text, "status": status, "suspicious": hard_n, "low_confidence": low,
            "moves": moves, "rejected": rejected, "required_failed": req_failed, "optional_failed": opt_failed,
            "threshold": threshold}


def _table(heads: list[str], rows: list[list[str]], *, caption: str) -> str:
    if not rows:
        return ""
    th = "".join(f'<th scope="col">{esc(h)}</th>' for h in heads)
    trs = "".join("<tr>" + "".join(
        (f'<th scope="row" data-label="{esc(heads[i])}">{cell}</th>' if i == 0
         else f'<td data-label="{esc(heads[i])}">{cell}</td>') for i, cell in enumerate(r)) + "</tr>" for r in rows)
    return (f'<table class="nu-ad-table"><caption class="nu-sr">{esc(caption)}</caption>'
            f'<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>')


def _box(title: str, body: str, *, sub: str = "", hid: str = "") -> str:
    h = f' id="{esc(hid)}"' if hid else ""
    return (f'<section class="nu-ad-box"><h2 class="nu-ad-h"{h}>{esc(title)}</h2>'
            + (f'<p class="nu-osub">{esc(sub)}</p>' if sub else "") + body + "</section>")


def _empty(text: str) -> str:
    return f'<p class="nu-ad-empty">{esc(text)}</p>'


def _generated(label: str, iso) -> str:
    return f'<p class="nu-ad-gen">{esc(label)}の生成 {_when(iso)}</p>'


# ── 取得元（買取店・TCG・抽選・API） ────────────────────────────────────────

def _shop_name(shop_id: str) -> str:
    try:
        from src.models.buyback_price import BUYBACK_SHOPS
    except Exception:                                       # noqa: BLE001
        return shop_id
    return (BUYBACK_SHOPS.get(f"src_{shop_id}") or BUYBACK_SHOPS.get(shop_id) or {}).get("name") or shop_id


def build_shops(collector: dict, dq_report: dict, optional: set, now: datetime) -> list[dict]:
    """買取店ごとの取得状況（試行・成功・観測を分ける。登録されているだけでは「取得できている」と言わない）。"""
    consecutive = {str(r.get("shop_id")): r.get("consecutive_failures")
                   for r in (dq_report or {}).get("consecutive_failed_shops") or [] if isinstance(r, dict)}
    out = []
    for r in (collector or {}).get("shop_detail") or []:
        if not isinstance(r, dict):
            continue
        sid = str(r.get("shop_id") or "")
        ok, failed = int(r.get("ok") or 0), int(r.get("failed") or 0)
        age = _age_days(r.get("last_observed_at"), now)
        fresh = "unknown" if age is None else ("fresh" if age <= 1.5 else "stale")
        if ok > 0 and fresh == "fresh":
            status, text = OK, "正常"
        elif ok > 0:
            status, text = WARN, "成功したが観測が古い"
        elif sid in optional:
            status, text = INFO, "任意の店（取得できなくても公開に影響しない）"
        elif r.get("blocked_count") or r.get("rate_429_count"):
            status, text = WARN, "アクセス制限"
        else:
            status, text = FAIL, "取得失敗"
        out.append({"id": sid, "name": _shop_name(sid), "status": status, "text": text, "ok": ok, "failed": failed,
                    "total": int(r.get("total") or 0), "reason": str(r.get("top_reason") or ""),
                    "attempt": r.get("last_attempt_at"), "success": r.get("last_success_at"),
                    "observed": r.get("last_observed_at"), "fresh": fresh,
                    "consecutive": consecutive.get(sid), "optional": sid in optional})
    order = {FAIL: 0, WARN: 1, INFO: 2, OK: 3}
    return sorted(out, key=lambda s: (order[s["status"]], s["name"]))


def build_data_coverage(diag: dict | None, tcg_report: dict | None) -> dict:
    """データの網羅（定価・在庫・買取・TCG）の件数（Phase 14）。判定はやり直さず、診断と TCG の報告の値をそのまま数える。

    報告の形が壊れていても（辞書・リストでない値）落とさず、数えられない項目は0にする。
    """
    D = lambda x: x if isinstance(x, dict) else {}       # noqa: E731
    L = lambda x: [e for e in x if isinstance(e, dict)] if isinstance(x, list) else []  # noqa: E731

    def num(d, k):
        try:
            return int(d.get(k) or 0)
        except (TypeError, ValueError):
            return 0
    diag, tcg = D(diag), D(tcg_report)
    retail = D(D(diag.get("retail_prices")).get("summary"))
    stock = D(D(diag.get("stock")).get("states"))
    bb = D(diag.get("buyback"))
    lots = L(tcg.get("lotteries"))
    evs = L(tcg.get("events")) + lots
    # 種類ごとに1回だけ数える（抽選情報には予約・購入権も入るので、抽選は LOTTERY・PURCHASE_RIGHT だけ）。
    # 予約の再開（キャンセル分）は予約、再販は明示の再入荷（店頭・EC）だけ。AVAILABLE_NOW は状態なので数えない
    kinds = {k: sum(1 for e in evs if str(e.get("event_type") or "").upper() in names)
             for k, names in (("preorder", ("PREORDER", "RESERVATION_REOPEN")), ("first_come", ("FIRST_COME",)),
                              ("restock", ("RESTOCK", "ONLINE_RESTOCK")))}
    lottery_n = sum(1 for e in lots if str(e.get("event_type") or "LOTTERY").upper() in ("LOTTERY", "PURCHASE_RIGHT"))
    return {"retail": {k: num(retail, k) for k in ("verified", "reference", "sale_ended", "stale", "unknown")},
            "stock": {k: num(stock, k) for k in ("IN_STOCK", "OUT_OF_STOCK", "UNKNOWN", "LOTTERY",
                                                 "RESERVATION", "PREORDER")},
            "buyback": {k: num(bb, k) for k in ("usable_products", "fresh_rows", "stale_rows", "failed_rows")},
            # 今すぐ行動できるか（Phase 18。src/market/actionability の結果を数えたもの。診断に無ければ空）
            "actionability": ({k: num(D(diag.get("actionability")), k) for k in (
                "confirmed_profitable", "actionable", "blocked_by_stock", "blocked_by_closed_lottery",
                "blocked_by_stale_availability", "blocked_by_unknown_schedule", "blocked_by_sale_ended",
                "blocked_by_missing_url")} if isinstance(diag.get("actionability"), dict) else {}),
            "actionability_products": [r for r in (D(diag.get("actionability")).get("products") or [])
                                       if isinstance(r, dict)],
            # 診断に camera が無い（Phase 17 より前）ときは空にして、行を出さない（0件と区別する。レビュー L1）
            "camera": ({k: num(D(diag.get("camera")), k) for k in ("products", "fresh_new", "stale_new", "used_reference",
                                                                  "confirmed_sells", "profitable", "actionable")}
                       if isinstance(diag.get("camera"), dict) else {}),
            "tcg": {"lotteries": lottery_n, **kinds}}


def _recheck_results() -> list[dict]:
    """公式の再確認の最新の結果（exports/official_recheck/latest.json。無ければ空）。"""
    import json
    from pathlib import Path
    try:
        d = json.loads((Path(__file__).resolve().parents[3] / "exports" / "official_recheck" / "latest.json")
                       .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in d.get("results") or [] if isinstance(r, dict)]


def build_identity(details: dict | None) -> dict:
    """商品の同一性の監査（Phase 15）。判定は official_registry.identity_state（型番・JAN と公式の証拠）をそのまま使う。"""
    from src.market import official_registry as reg
    prods = [{"id": getattr(v, "product_id", ""), "name": getattr(v, "product_name", ""),
              "model_number": getattr(v, "model", ""), "jan_code": getattr(v, "jan", "")}
             for v in (details or {}).values()]
    out = reg.identity_audit(prods)
    # 公式直販価格の判定（Phase 16。official_direct_gate の結果をそのまま出す。判定し直さない）
    out["official_direct"] = reg.official_direct_audit(prods, recheck=_recheck_results()) if prods else []
    return out


def build_tcg(tcg_report: dict) -> list[dict]:
    out = []
    for s in (tcg_report or {}).get("source_health") or []:
        if not isinstance(s, dict):
            continue
        text, status = TCG_LABELS.get(str(s.get("status") or ""), ("要確認", WARN))
        out.append({"name": str(s.get("source_name") or s.get("source") or ""), "status": status, "text": text,
                    "reason": str(s.get("status_reason") or ""), "checked": s.get("last_checked"),
                    "success": s.get("last_success"), "events": s.get("events_found"),
                    "errors": int(s.get("errors") or 0)})
    return out


def build_lottery_sources(tcg_report: dict) -> list[dict]:
    out = []
    for s in (tcg_report or {}).get("lottery_sources") or []:
        if not isinstance(s, dict):
            continue
        state = str(s.get("state") or "")
        label = str(s.get("state_label") or state)
        if state == "SOURCE_BLOCKED":
            label = "アクセス拒否（人の確認が必要。回避はしない）"
        out.append({"name": str(s.get("retailer") or s.get("source_id") or ""), "priority": str(s.get("priority") or ""),
                    "status": LOT_SOURCE_TONE.get(state, WARN), "text": label,
                    "implemented": bool(s.get("adapter")), "checked": s.get("last_checked") or s.get("checked_at"),
                    "url": c.safe_href(str(s.get("official_url") or ""))})
    order = {FAIL: 0, WARN: 1, INFO: 2, OK: 3}
    return sorted(out, key=lambda s: (order[s["status"]], s["priority"], s["name"]))


def build_api(api: dict) -> list[dict]:
    """API の状態（設定済みか・状態・停止スイッチ・最後の成功だけ。キーの値は持たない）。"""
    out = []
    for name, d in ((api or {}).get("per_api") or {}).items():
        if not isinstance(d, dict):
            continue
        configured = str(d.get("configured") or "")
        st = str(d.get("status") or "")
        status = OK if (configured == "configured" and d.get("healthy")) else (INFO if configured != "configured" else WARN)
        out.append({"name": {"ebay": "eBay", "rakuten": "楽天", "yahoo": "Yahoo!ショッピング"}.get(name, name),
                    "configured": API_CONFIGURED.get(configured, "不明"), "state": API_STATUS.get(st, st or "不明"),
                    "kill_switch": "停止中" if d.get("kill_switch_off") else "動作可",
                    "success": d.get("last_success"), "status": status})
    return out


# ── データ品質 ───────────────────────────────────────────────────────────

def build_dq(catalog, details: dict, diagnostics: dict, health: dict, collector: dict) -> dict:
    """利益商品の候補を外した理由（理由ごとの商品つき）と、データの品質の指標。判定はやり直さない。"""
    from src.market import opportunity_diagnostics as od
    from src.content.ui import product_detail as pd
    s = getattr(catalog, "opportunity_set", None)
    groups: dict[str, list] = {}
    # 理由は候補の診断（opportunity_diagnostics。判定 opportunity.eligibility の結果を分類したもの）の候補ごとの記録。
    # 無ければ（古い生成物）新UIの判定の外した候補から作る。判定そのものはやり直さない
    names = {pid: v.product_name for pid, v in details.items()}
    views = {v.product_id: v for v in (list(s.ineligible) if s else [])}
    cands = (diagnostics or {}).get("candidates")
    if isinstance(cands, list):
        for cnd in cands:
            if not isinstance(cnd, dict):
                continue
            pid = str(cnd.get("product_id") or "")
            v = views.get(pid)
            groups.setdefault(str(cnd.get("primary") or "other"), []).append({
                "pid": pid, "name": names.get(pid) or (v.product_name if v else pid), "linked": pid in details,
                "reasons": [DIAG_LABELS.get(r, r) for r in cnd.get("reasons") or []][:4],
                "detail": list(dict.fromkeys(pd.REASON_LABELS.get(r, r) for r in (v.reasons if v else ())))[:3],
                "source": (v.sell_source if v else "") or "", "route": str(cnd.get("route_type") or "")})
    else:
        for v in (list(s.ineligible) if s else []):
            cat = od._reason(v.reasons[0], v) if v.reasons else "other"
            groups.setdefault(cat, []).append({
                "pid": v.product_id, "name": v.product_name, "linked": v.product_id in details,
                "reasons": [], "detail": list(dict.fromkeys(pd.REASON_LABELS.get(r, r) for r in v.reasons))[:4],
                "source": v.sell_source or "", "route": ""})
    hq = (health or {}).get("data_quality") or {}
    an = (health or {}).get("anomalies") or {}
    return {"groups": sorted(groups.items(), key=lambda kv: -len(kv[1])),
            "excluded": (diagnostics or {}).get("exclusion_reasons") or {},
            "candidates": (diagnostics or {}).get("candidate_count"), "eligible": (diagnostics or {}).get("eligible_count"),
            "stale_rate": hq.get("stale_rate"), "zero_rate": hq.get("zero_rate"), "item_url_rate": hq.get("item_url_rate"),
            "usable": hq.get("usable_obs"), "total_obs": hq.get("total_obs"),
            "anomalies": {k: list(an.get(k) or []) for k in ("critical", "warning", "info")},
            "changes_big": sum(1 for x in (collector or {}).get("price_changes") or []
                               if isinstance(x, dict) and abs(float(x.get("change_pct") or 0)) >= BIG_CHANGE_PCT),
            "changes": len((collector or {}).get("price_changes") or []),
            "fetch_failed": len((collector or {}).get("fetch_failed") or []),
            "generated": (diagnostics or {}).get("generated_at")}


# ── AI・資金配分・実行・通知（今の確定ルートと照合する。古い生成物は「前回の生成」） ─────────────────

def _is_older(a, b) -> bool:
    da = parse_dt(str(a or "").replace(" JST", "+09:00").replace(" ", "T", 1))
    db = parse_dt(str(b or "").replace(" JST", "+09:00").replace(" ", "T", 1))
    return bool(da and db and da < db)


def build_ai(ai: dict, keys: dict, routes_generated) -> dict:
    allops = [o for o in (ai or {}).get("todays_opportunities") or [] if isinstance(o, dict)]
    ops = [o for o in allops if opp.record_route_ok(o, keys)]
    # 今の確定ルートと照合できない候補の「今日やること」（商品名・商品 ID を含む行）は出さない（当時の値を復活させない）
    gone = {str(x) for o in allops if o not in ops for x in (o.get("product"), o.get("product_id")) if x}
    kept = {str(x) for o in ops for x in (o.get("product"), o.get("product_id")) if x}

    def _mentions_gone(t: str) -> bool:
        # 外した商品の名前を含む行。ただし、その名前を含む別の（残した）商品の行は残す（GR IV と GR IV HDF など）
        return any(g in t and not any(g in k and k != g and k in t for k in kept) for g in gone)
    tasks = [str(t) for t in (ai or {}).get("today_tasks") or [] if not _mentions_gone(str(t))]
    return {"ops": ops, "dropped": len(allops) - len(ops),
            "tasks": tasks[:10],
            "generated": (ai or {}).get("generated_at"), "previous": _is_older((ai or {}).get("generated_at"), routes_generated),
            "health_note": str((ai or {}).get("health_note") or "")}


def build_capital(allocation: dict, keys: dict, routes_generated=None) -> list[dict]:
    plans = []
    gen = (allocation or {}).get("generated_at")
    prev = _is_older(gen, routes_generated)
    for budget, p in ((allocation or {}).get("plans") or {}).items():
        if not isinstance(p, dict):
            continue
        allocs = [a for a in p.get("allocations") or [] if isinstance(a, dict) and opp.record_route_ok(a, keys)]
        waiting = [w for w in p.get("waiting") or [] if isinstance(w, dict) and opp.record_route_ok(w, keys)]
        dropped = (len(p.get("allocations") or []) - len(allocs)) + (len(p.get("waiting") or []) - len(waiting))
        plans.append({"budget": p.get("budget") or budget, "allocs": allocs, "waiting": waiting, "dropped": dropped,
                      "generated": gen, "previous": prev,
                      # 外した行があるときは、生成物の合計（外した行を含む）を出さない（計算し直さない）
                      "totals": None if dropped else {k: p.get(k) for k in (
                          "allocated", "cash", "expected_profit", "expected_roi", "avg_risk_score",
                          "diversification_score", "max_concentration")}})
    return plans


def _is_sample(rec: dict) -> bool:
    return str(rec.get("note") or "").startswith("sample")


def build_execution(execution: dict, history: dict, keys: dict) -> dict:
    recs = [r for r in (history or {}).get("executions") or [] if isinstance(r, dict)]
    real = [r for r in recs if not _is_sample(r)]
    counts = {s: sum(1 for r in real if r.get("status") == s) for s in EXEC_STATUSES}
    closed_real = counts["SUCCESS"] + counts["FAILED"]
    rows = sorted(real, key=lambda r: str(r.get("date") or ""), reverse=True)[:30]
    for r in rows:
        r["_alive"] = r.get("status") != "OPEN" or opp.record_route_alive(r, keys)
    ex = execution or {}
    return {"counts": counts, "samples": len(recs) - len(real), "closed_real": closed_real, "rows": rows,
            "insights": [str(x) for x in ex.get("insights_top10") or []][:10],
            "coef": ex.get("learning_coefficients") if isinstance(ex.get("learning_coefficients"), dict) else {},
            "pred": ex.get("prediction_accuracy") if isinstance(ex.get("prediction_accuracy"), dict) else {},
            "notif": ex.get("notification_accuracy") if isinstance(ex.get("notification_accuracy"), dict) else {},
            "invalidated_total": ex.get("invalidated_count"), "sample_total": ex.get("sample_excluded_count"),
            "rate": (execution or {}).get("execution_success_rate") if closed_real else None,
            "accuracy": (execution or {}).get("prediction_accuracy") if closed_real else None,
            "generated": (execution or {}).get("generated_at")}


def _notice_text(msg) -> str:
    """通知の文。過去の通知の「落札」（実際は出品の価格）を、今の呼び方（出品中）に読み替える（price_types.relabel_legacy）。"""
    from src.market import price_types as pt
    return _safe_text(pt.relabel_legacy(msg or "")).replace("\n", " / ")


def build_notifications(events: list | None, keys: dict, latest: dict) -> dict:
    seen, user, system, other = set(), [], [], []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        k = (e.get("type"), e.get("product_id"), e.get("created_at"))
        if k in seen:                                          # 同じ通知は1回だけ（生成側の抑制とは別に表示で重ねない）
            continue
        seen.add(k)
        typ = str(e.get("type") or "")
        if typ in USER_NOTICE_LABELS:
            alive = bool(e.get("route_checked") is True
                         and opp.record_route_ok({"route_id": e.get("route_id"), "kind": "main"}, keys))
            user.append({"label": USER_NOTICE_LABELS[typ], "pid": str(e.get("product_id") or ""),
                         "product": str((e.get("data") or {}).get("product") or e.get("product_id") or ""),
                         "at": e.get("created_at"), "alive": alive,
                         # 今は確定ルートでない通知は、当時の金額を出さない（無効になったルートの値を復活させない）
                         "message": _notice_text(e.get("message")) if alive else ""})
        elif typ in SYSTEM_NOTICE_LABELS:
            system.append({"label": SYSTEM_NOTICE_LABELS[typ], "at": e.get("created_at"),
                           "message": _notice_text(e.get("message"))})
        else:
            other.append({"label": typ or "不明", "at": e.get("created_at")})
    return {"user": user, "system": system, "other": other,
            "channels": [str(x) for x in (latest or {}).get("channels") or []],
            "delivery": {str(k): str(v) for k, v in ((latest or {}).get("delivery_status") or {}).items()},
            "suppressed": (latest or {}).get("suppressed_count")}


def build_actionable_notices(rep: dict | None) -> dict:
    """今すぐ行動できるようになった商品の通知（Phase 19。src/notifiers/actionable の今回の生成の結果を数えて出すだけ）。
    重複の抑制の識別子・配信先の URL・トークンは出さない。"""
    r = rep if isinstance(rep, dict) else {}
    keys = ("notification_candidates", "dedupe_suppressed", "baseline_recorded", "dispatch_planned", "dispatch_sent",
            "dispatch_failed", "dispatch_blocked")
    return {"available": bool(r), "dry_run": r.get("dry_run") is not False, "baseline": bool(r.get("is_baseline")),
            "at": r.get("generated_at") or "", **{k: int(r.get(k) or 0) for k in keys},
            "items": [{"product": str(c.get("product") or c.get("product_id") or ""), "status": str(c.get("status") or ""),
                       "transition": str(c.get("transition") or ""), "dispatch": str(c.get("dispatch_status") or "")}
                      for c in (r.get("candidates") or []) if isinstance(c, dict)][:20]}


def check_text(full: str, tail: int = 4000) -> str:
    """CI のチェックの出力（数万字）から、渡す部分だけを取り出す。実行日時はヘッダ（先頭）、件数は末尾にあるので、
    先頭の実行日時の行と末尾だけ（途中の項目の一覧は渡さない）。"""
    t = str(full or "")
    m = re.search(r"^\s*実行日時:.*$", t, re.M)
    return ((m.group(0).strip() + "\n") if m else "") + t[-tail:]


def current_health(health: dict | None, profit_routes: dict | None, now: datetime) -> dict:
    """健康度の報告のうち、利益ルート由来の値（検証済みのルートの件数・最大利益・新しく確定になったルート・
    eBay を設定したときの見込み）を、今の利益ルートで判定を通ったものから数え直す（旧UIの Health タブと同じ扱い）。
    報告が古いまま残っても、無効になったルートの利益を出さない。健康度の点数そのものは報告の値のまま。"""
    h = dict(health or {})
    mains = opp.confirmed_routes((profit_routes or {}).get("main_routes"), now)
    refs = opp.reference_routes((profit_routes or {}).get("reference_routes"), now)
    main_pids = {r.get("product_id") for r in mains}
    an = dict(h.get("anomalies") or {})
    info = [x for x in (an.get("info") or []) if not str(x).startswith("検証済み利益ルート")]
    if mains:
        info.insert(0, f"検証済み利益ルート {len(mains)}件 / 最大 +¥{max(r.get('net_profit') or 0 for r in mains):,}")
    an["info"] = info
    h["anomalies"] = an
    dv = dict(h.get("diff_vs_prev") or {})
    if dv.get("available"):
        dv["new_main"] = [x for x in (dv.get("new_main") or []) if x in main_pids]
        for k, n in (("main_route_count", len(mains)), ("reference_route_count", len(refs))):
            if isinstance(dv.get(k), dict):
                dv[k] = dict(dv[k], cur=n)
        h["diff_vs_prev"] = dv
    pot = sum(r.get("net_profit") or 0 for r in refs)
    h["improvements_top10"] = [
        (dict(i, effect=f"+¥{pot:,}（参考{len(refs)}→main昇格）") if isinstance(i, dict)
         and i.get("action") == "EBAY_APP_ID 設定" else i) for i in (h.get("improvements_top10") or [])]
    return h


def _check_summary(text: str) -> dict:
    """前回の CI のチェックの結果（このページの生成より前に実行したもの）と、その実行日時。"""
    m = re.search(r"Errors:\s*(\d+)(?:\s*\|\s*Warnings:\s*(\d+)\s*\|\s*OK:\s*(\d+))?", text or "")
    at = re.search(r"実行日時:\s*(\S+)", text or "")
    if not m:
        return {"text": "記録なし", "at": ""}
    return {"text": f"エラー {m.group(1)}" + (f"・警告 {m.group(2)}・OK {m.group(3)}" if m.group(2) else ""),
            "at": at.group(1) if at else ""}


# ── 全体 ─────────────────────────────────────────────────────────────────

def build(data: dict | None, *, catalog, details: dict, profit_routes: dict | None, tcg_report: dict | None,
          now: datetime, lp_generated: str = "") -> dict:
    d = data or {}
    # 健康度の報告の利益ルート由来の値は、今の利益ルートで数え直す（古い報告で無効なルートの利益を出さない）
    d = dict(d, health=current_health(d.get("health"), profit_routes, now)) if d.get("health") else d
    keys = opp.current_route_keys(profit_routes, now)
    shops = build_shops(d.get("collector"), d.get("dq_report"), set(d.get("optional_shops") or ()), now)
    tcg = build_tcg(tcg_report)
    lot_sources = build_lottery_sources(tcg_report)
    api = build_api(d.get("api"))
    dq = build_dq(catalog, details, d.get("diagnostics"), d.get("health"), d.get("collector"))
    ai = build_ai(d.get("ai"), keys, (profit_routes or {}).get("generated_at"))
    capital = build_capital(d.get("allocation"), keys, (profit_routes or {}).get("generated_at"))
    execution = build_execution(d.get("execution"), d.get("execution_history"), keys)
    notices = build_notifications(d.get("notifications"), keys, d.get("notifications_latest"))
    s = getattr(catalog, "opportunity_set", None)
    restock = [r for r in getattr(catalog, "restock_views", []) or [] if r.available(now)]
    from src.content.ui import runtime as rt
    lot_open = sum(1 for lv in getattr(catalog, "lottery_views", []) or [] if lv.vm
                   and rt.derive_runtime_state(lv.vm, now).get("status") in rt.OPEN_STATUSES)
    hs = (d.get("health") or {}).get("health_score") or {}
    req_fail = [x for x in shops if x["status"] == FAIL]
    warn = collector_warn(d.get("collector"), set(d.get("optional_shops") or ()), int(d.get("warn_threshold") or 5))
    overview = {
        "products": len(details), "opportunities": len(s.eligible) if s else 0,
        # 利益ルート（せどりルートの計算。確定の利益商品とは別の計算）。今も出せるものだけ数える
        "routes_main": len(keys.get("main") or ()), "reference": len(keys.get("reference") or ()), "lotteries": lot_open,
        "restock": len(restock), "health": hs.get("total"),
        "shops_ok": sum(1 for x in shops if x["status"] == OK), "shops_fail": len(req_fail),
        "shops_warn": sum(1 for x in shops if x["status"] == WARN),
        "tcg_ok": sum(1 for x in tcg if x["status"] == OK), "tcg_warn": sum(1 for x in tcg if x["status"] != OK),
        "api_configured": sum(1 for x in api if x["configured"] == "設定済み"), "api_total": len(api),
        "dq_excluded": sum(len(v) for _k, v in dq["groups"]), "critical": len(dq["anomalies"]["critical"]),
        "lp_generated": lp_generated, "page_generated": now.isoformat(), "warn": warn,
        "deploy": _check_summary(d.get("deploy_check") or ""),
        "prelaunch": _check_summary(d.get("prelaunch_check") or ""),
    }
    resale = [{"name": {"ebay": "eBay", "amazon": "Amazon", "mercari": "メルカリ", "yahoo": "ヤフオク", "rakuten": "楽天",
                        "rakuma_direct": "ラクマ"}.get(k, k), "label": str(p.get("label_jp") or p.get("status") or "不明"),
               "status": OK if str(p.get("status") or "").startswith("ok") else (INFO if p.get("status") == "no_data" else WARN)}
              for k, p in ((d.get("resale_status") or {}).get("platforms") or {}).items() if isinstance(p, dict)]
    flea = [{"name": {"mercari": "メルカリ", "yahoo": "ヤフオク", "rakuma": "ラクマ"}.get(k, k),
             "products": len((f or {}).get("products") or {}),
             "recent": sum(1 for x in ((f or {}).get("products") or {}).values()
                           if isinstance(x, dict) and (x.get("count_recent") or 0) > 0),
             "generated": (f or {}).get("generated_at")} for k, f in (d.get("flea_sold") or {}).items()]
    zdiag = {pid: z for pid, z in ((profit_routes or {}).get("zero_route_diagnostics") or {}).items() if isinstance(z, dict)}
    zero = [{"pid": pid, "name": str(z.get("product_name") or pid), "reason": str(z.get("main_blocked_reason") or "—"),
             "buy": z.get("buy_candidates"), "sell": z.get("sell_candidates"), "stale": z.get("stale_excluded"),
             # 観測した最安の仕入れ・最高の売却（価格の観測。利益ではない）。照合が済んでいないものは「参考・照合未了」
             "min_buy": z.get("min_usable_buy"), "min_buy_src": str(z.get("min_usable_buy_source") or ""),
             "min_buy_ok": bool(z.get("min_usable_buy_identity_verified")),
             "max_sell": z.get("max_usable_sell"), "max_sell_src": str(z.get("max_usable_sell_source") or ""),
             "max_sell_ok": bool(z.get("max_usable_sell_identity_verified")),
             "needed": [str(x) for x in z.get("needed") or []][:3], "linked": pid in details}
            for pid, z in zdiag.items()]
    from collections import Counter
    rej = Counter()
    for z in zdiag.values():
        for pair in z.get("rejection_top5") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                rej[str(pair[0])] += int(pair[1] or 0)
    zero_totals = {"buy": sum(int(z.get("buy_candidates") or 0) for z in zdiag.values()),
                   "sell": sum(int(z.get("sell_candidates") or 0) for z in zdiag.values()),
                   "stale": sum(int(z.get("stale_excluded") or 0) for z in zdiag.values()),
                   "overseas_stale": sum(int(z.get("overseas_stale") or 0) for z in zdiag.values()),
                   "top5": rej.most_common(5)} if zdiag else None
    missing = [m for m in (profit_routes or {}).get("missing_data_priority") or [] if isinstance(m, dict)]
    return {"overview": overview, "shops": shops, "tcg": tcg, "lot_sources": lot_sources,
            "resale": resale, "flea": flea, "zero_routes": zero, "zero_totals": zero_totals, "missing": missing,
            "camera": (d.get("camera_status") or {}).get("summary") or {},
            # 自動取得できたカメラの買取価格のうち、中古の「新品同様」の段の価格の件数（状態を明示する。Phase 12）
            "camera_used": sum(1 for r in ((d.get("camera_status") or {}).get("detail") or [])
                               if isinstance(r, dict) and r.get("status") == "OK"
                               and "新品同様" in str(r.get("matched_item") or "")),
            "camera_generated": (d.get("camera_status") or {}).get("generated_at"),
            "data_coverage": build_data_coverage(d.get("diagnostics"), tcg_report),
            "identity": build_identity(details),
            "min_sold": d.get("min_sold_samples"),
            "resale_collected": (d.get("resale_status") or {}).get("collected_at"),
            "lot_coverage": (tcg_report or {}).get("lottery_coverage") or {}, "api": api,
            "api_dry_run": (d.get("api") or {}).get("dry_run"), "api_generated": (d.get("api") or {}).get("generated_at"),
            "dq": dq, "ai": ai, "capital": capital, "execution": execution, "notices": notices,
            "act_notices": build_actionable_notices(d.get("actionable_notifications")),
            "health": d.get("health") or {}, "coverage": d.get("coverage") or {},
            "collector_generated": (d.get("collector") or {}).get("generated_at"),
            "dq_report": d.get("dq_report") or {}, "now": now}


# ── 描画 ─────────────────────────────────────────────────────────────────

def _ov_card(label: str, value: str, status: str, sub: str = "", href: str = "") -> str:
    badge = _badge(status, "低い" if (status == FAIL and label == "システムの健康度") else "")
    inner = (f'<span class="nu-ad-ov__label">{esc(label)}</span><span class="nu-ad-ov__val">{esc(value)}</span>'
             f'{badge}' + (f'<span class="nu-osub">{esc(sub)}</span>' if sub else ""))
    if href:
        return f'<li><a class="nu-ad-ov nu-ad-ov--{status}" href="{esc(href)}">{inner}</a></li>'
    return f'<li><div class="nu-ad-ov nu-ad-ov--{status}">{inner}</div></li>'


def _warn_value(w: dict) -> str:
    return {"strong": f'疑わしい価格 {w["suspicious"]}件・低信頼度 {w["low_confidence"]}件',
            "moves": f'前回から大きく変動 {w["moves"]}件', "rejected": f'誤りとして隔離 {w["rejected"]}件',
            "soft": f'必須の店の取得失敗 {w["required_failed"]}件', "info": f'任意の店の取得失敗 {w["optional_failed"]}件',
            "none": "なし"}[w["level"]]


def _sec_href(key: str) -> str:
    return f'{page_href("admin")}&section={key}'


def _overview(v: dict) -> str:
    o = v["overview"]
    hs = o["health"]
    cards = [
        _ov_card("確定の利益商品", f'{o["opportunities"]}件', OK if o["opportunities"] else INFO,
                 f'利益商品の一覧に出ている件数（定価と買取の案件＋確定のせどりルート）。せどりルートは確定 '
                 f'{o["routes_main"]}件・参考 {o["reference"]}件', page_href("opportunities")),
        _ov_card("抽選・予約の受付中（生成時点）", f'{o["lotteries"]}件', INFO, "閲覧時の状態は抽選の一覧で確認",
                 page_href("lottery")),
        _ov_card("在庫再開（購入可能・生成時点）", f'{o["restock"]}件', INFO, "", page_href("restock")),
        _ov_card("監視している商品", f'{o["products"]}件', INFO, "", page_href("search")),
        _ov_card("買取店の取得", f'正常 {o["shops_ok"]}・失敗 {o["shops_fail"]}',
                 FAIL if o["shops_fail"] else (WARN if o["shops_warn"] else OK),
                 f'要確認 {o["shops_warn"]}（任意の店は除く）', _sec_href("sources")),
        _ov_card("取得の警告", _warn_value(o["warn"]), o["warn"]["status"], "旧表示の警告バーと同じ分類",
                 _sec_href("sources")),
        _ov_card("TCG の取得元", f'正常 {o["tcg_ok"]}・要確認 {o["tcg_warn"]}', WARN if o["tcg_warn"] else OK,
                 "", _sec_href("sources")),
        _ov_card("データ品質", f'候補から外した {o["dq_excluded"]}件', WARN if o["critical"] else INFO,
                 f'重大な異常 {o["critical"]}件', _sec_href("data-quality")),
        _ov_card("システムの健康度", f"{hs} / 100" if hs is not None else "記録なし",
                 OK if (hs or 0) >= 80 else (WARN if (hs or 0) >= 40 else FAIL),
                 "80 以上で正常・40 未満は低い（内訳は「システム」）", _sec_href("system")),
        _ov_card("外部 API", f'設定済み {o["api_configured"]} / {o["api_total"]}',
                 INFO if not o["api_configured"] else OK, "未設定は HTML の取得・手入力で補う", _sec_href("system")),
    ]
    return (f'<ul class="nu-ad-ov-grid" role="list">{"".join(cards)}</ul>'
            + _box("生成と公開前チェック",
                   '<dl class="nu-ad-dl">'
                   f'<dt>このページの生成</dt><dd>{_when(o["page_generated"])}</dd>'
                   f'<dt>情報の確認（ページ上部の時刻と同じ）</dt><dd>{esc(o["lp_generated"] or "記録なし")}</dd>'
                   + "".join(
                       f'<dt>前回の CI の{lbl}</dt><dd>{esc(c["text"])}<span class="nu-osub">'
                       + (f'実行 {_when(c["at"])}' if c["at"] else "実行の日時は記録なし")
                       + '・このページの生成より前に実行した結果（今の公開のチェックではない）</span></dd>'
                       for lbl, c in (("公開前チェック（deploy-check）", o["deploy"]),
                                      ("本番前チェック（prelaunch）", o["prelaunch"]))) +
                   '<dt>CI の結果</dt><dd>GitHub Actions の Daily LP Update で確認（このページでは見られない）</dd></dl>',
                   sub="取得に成功した時刻・観測した時刻は「取得元」で分けて出す"))


def _sources(v: dict) -> str:
    rows = [[f'{esc(s["name"])}<span class="nu-osub">{"任意" if s["optional"] else "必須"}</span>',
             _badge(s["status"], s["text"]),
             f'{s["ok"]} / {s["total"]}（失敗 {s["failed"]}）',
             _reason(s["reason"]), _when(s["attempt"]), _when(s["success"]),
             f'{_when(s["observed"])}<span class="nu-osub">{ {"fresh": "新しい", "stale": "古い", "unknown": "不明"}[s["fresh"]] }</span>',
             esc(str(s["consecutive"])) if s["consecutive"] is not None else "—"] for s in v["shops"]]
    shops = _table(["買取店", "状態", "成功 / 試行", "主な失敗理由", "最後に試した", "最後に成功", "最後の観測", "連続失敗（回）"],
                   rows, caption="買取店の取得状況") or _empty("買取店の取得の記録はありません。")
    tcg = _table(["取得元", "状態", "理由", "最後に確認", "最後に成功", "採用件数", "エラー"],
                 [[esc(t["name"]), _badge(t["status"], t["text"]), esc(t["reason"] or "—"), _when(t["checked"]),
                   _when(t["success"]), esc(str(t["events"] if t["events"] is not None else "—")), str(t["errors"])]
                  for t in v["tcg"]], caption="TCG の取得元") or _empty("TCG の取得元の記録はありません。")
    lc = v["lot_coverage"]
    lots = _table(["抽選の監視元", "優先度", "状態", "解析の実装", "公式"],
                  [[esc(s["name"]), esc(s["priority"] or "—"), _badge(s["status"], s["text"]),
                    "あり" if s["implemented"] else "未実装",
                    (f'<a href="{esc(s["url"])}" target="_blank" rel="noopener noreferrer">公式<span class="nu-sr">（外部サイト）</span></a>'
                     if s["url"].startswith("https://") else "—")] for s in v["lot_sources"]],
                  caption="抽選の監視元") or _empty("抽選の監視元の記録はありません。")
    cov = (f'<p class="nu-osub">登録 {lc.get("configured_sources", "—")}・解析あり {lc.get("implemented_collectors", "—")}・'
           f'正常 {lc.get("healthy_sources", "—")}・アクセス拒否 {lc.get("blocked_sources", "—")}・'
           f'接続できない {lc.get("unreachable_sources", "—")}・未実装 {lc.get("not_implemented_sources", "—")}</p>'
           if lc else "")
    w = v["overview"]["warn"]
    warn = _box("取得の警告（旧表示の警告バーと同じ分類）",
                f'<p>{_badge(w["status"], w["text"])}</p><dl class="nu-ad-dl">'
                f'<dt>疑わしい価格（誤りの可能性が高いもの・公開中）</dt><dd>{w["suspicious"]}件</dd>'
                f'<dt>低信頼度の価格</dt><dd>{w["low_confidence"]}件</dd>'
                f'<dt>前回から大きく変動した価格（誤りとは限らない）</dt><dd>{w["moves"]}件</dd>'
                f'<dt>誤りと判断して隔離した価格（公開していない）</dt><dd>{w["rejected"]}件</dd>'
                f'<dt>取得失敗（必須の店 / 任意の店）</dt><dd>{w["required_failed"]}件 / {w["optional_failed"]}件'
                f'<span class="nu-osub">{w["threshold"]}件以上で警告</span></dd></dl>',
                sub="強い警告 → 大きな変動 → 隔離だけ → 必須の店の失敗 → 任意の店の失敗 の順に1つだけ出す")
    return (warn + _box("買取店", shops + _generated("取得レポート", v["collector_generated"]),
                 sub="「試した」「成功した」「観測した（価格を得た）」は別の時刻。登録されているだけでは取得できているとは言わない")
            + _box("再販・フリマの取得", (_table(["取得元", "状態"], [[esc(r["name"]), _badge(r["status"], r["label"])]
                                                      for r in v["resale"]], caption="再販・フリマの取得元")
                                               or _empty("再販の取得の記録はありません。"))
                   + (_table(["フリマの成約（手入力）", "商品", "最近の成約がある商品", "生成"],
                             [[esc(f["name"]), f'{f["products"]}件', f'{f["recent"]}件', _when(f["generated"])]
                              for f in v["flea"]], caption="フリマの成約") or "")
                   + _generated("再販の取得状況", v["resale_collected"]),
                   sub="フリマの成約は規約に沿って人が確認したものだけ（自動で取得しない）")
            + _box("TCG（商品・入荷）", tcg)
            + _box("抽選の監視元", cov + lots,
                   sub="アクセス拒否の取得元は、bot 対策を回避せず、公式ページを人が確認して補う"))


def _dq(v: dict) -> str:
    dq = v["dq"]
    groups = []
    for cat, items in dq["groups"]:
        lis = "".join(
            f'<li><span>{(product_page.link(it["pid"], it["name"]) if it["linked"] else esc(it["name"]))}</span>'
            f'<span class="nu-osub">{esc("・".join(it["reasons"] + it["detail"]))}'
            f'{("・売却先 " + esc(it["source"])) if it["source"] else ""}</span></li>'
            for it in items[:40])
        groups.append(f'<details class="nu-ad-dq"><summary><b>{esc(DIAG_LABELS.get(cat, cat))}</b> '
                      f'<span class="nu-ad-count">{len(items)}件</span></summary><ul class="nu-ad-list">{lis}</ul></details>')
    an = dq["anomalies"]
    anomalies = "".join(f'<li>{_badge(st, lbl)} {esc(_safe_text(x))}</li>'
                        for key, st, lbl in (("critical", FAIL, "重大"), ("warning", WARN, "注意"), ("info", INFO, "情報"))
                        for x in an.get(key) or [])
    metrics = ('<dl class="nu-ad-dl">'
               f'<dt>価格の観測（使えるもの / すべて）</dt><dd>{esc(str(dq["usable"] or "—"))} / {esc(str(dq["total_obs"] or "—"))}</dd>'
               f'<dt>古い価格の割合</dt><dd>{_pct(dq["stale_rate"])}</dd>'
               f'<dt>0円（取得失敗）の割合</dt><dd>{_pct(dq["zero_rate"])}</dd>'
               f'<dt>商品ページ単位の URL の割合</dt><dd>{_pct(dq["item_url_rate"])}</dd>'
               f'<dt>前回からの価格の変動（収集時）</dt><dd>{BIG_CHANGE_PCT}% 以上 {dq["changes_big"]}件・'
               f'それ未満 {dq["changes"] - dq["changes_big"]}件</dd>'
               '<dt>疑わしい価格・低信頼度</dt><dd>「取得元」の取得の警告を参照</dd>'
               f'<dt>取得失敗の記録</dt><dd>{dq["fetch_failed"]}件</dd></dl>')
    zt = v["zero_totals"]
    ztot = ((f'<p class="nu-ad-note">仕入れの候補 {zt["buy"]}件・売却の候補 {zt["sell"]}件・古くて外した価格 {zt["stale"]}件'
             f'（うち海外の成約 {zt["overseas_stale"]}件）</p>'
             + ('<p class="nu-osub">価格を計算から外した理由（上位5）: '
                + "・".join(f'{esc(PRICE_REJECT_LABELS.get(k, k))} {n}件' for k, n in zt["top5"]) + "</p>"
                if zt["top5"] else "")) if zt else "")
    return (_box("利益商品の候補から外した理由（商品ごと）",
                 ("".join(groups) or _empty("候補から外した商品はありません。"))
                 + _generated("候補の診断", dq["generated"]),
                 sub=f'候補 {dq["candidates"] if dq["candidates"] is not None else "—"}件のうち確定 '
                     f'{dq["eligible"] if dq["eligible"] is not None else "—"}件。理由は判定（opportunity.py）の結果をそのまま分類したもの。'
                     '商品名から商品詳細へ')
            + _box("せどりルートが成立しない理由（理由ごと）", ztot + (_zero_groups(v["zero_routes"]) or _empty("記録はありません。"))
                   + (('<h3 class="nu-ad-h3">次に取得すべきデータ（優先度順）</h3><ul class="nu-ad-list">'
                       + "".join(f'<li><b>{esc(str(m.get("rank", "")))}. {esc(_safe_text(m.get("label")))}</b>'
                                 f'<span class="nu-osub">対象の商品 {esc(str(m.get("product_count", "—")))}件・'
                                 f'優先度 {esc({"high": "高", "medium": "中", "low": "低"}.get(str(m.get("priority")), str(m.get("priority") or "—")))}'
                                 '</span></li>'
                                 for m in v["missing"]) + "</ul>") if v["missing"] else ""),
                   sub="利益ルート（profit_routes）の診断より。見込みの利益は確定ではないので金額は出さない。"
                       "最安・最高は価格の観測（利益ではない）")
            + _box("異常の一覧", f'<ul class="nu-ad-list">{anomalies}</ul>' if anomalies else _empty("異常の記録はありません。"),
                   sub="システムの健康度の報告（audit_health）より")
            + _box("データの指標", metrics))


def _zero_groups(zero: list) -> str:
    groups: dict[str, list] = {}
    for z in zero:
        groups.setdefault(_safe_text(z["reason"]), []).append(z)
    out = []
    for reason, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lis = "".join(
            f'<li><span>{(product_page.link(z["pid"], z["name"]) if z["linked"] else esc(z["name"]))}</span>'
            f'<span class="nu-osub">仕入れの候補 {z["buy"] if z["buy"] is not None else "—"}・売却の候補 '
            f'{z["sell"] if z["sell"] is not None else "—"}・古くて外した {z["stale"] if z["stale"] is not None else "—"}'
            + "".join(f'・{lbl} {esc(src)} {_yen(val)}' + ("" if ok else "（参考・照合未了）")
                      for lbl, src, val, ok in (("最安の仕入れ", z["min_buy_src"], z["min_buy"], z["min_buy_ok"]),
                                                ("最高の売却", z["max_sell_src"], z["max_sell"], z["max_sell_ok"])) if val)
            + (f'・あと必要: {esc(_safe_text("・".join(z["needed"])))}' if z["needed"] else "") + "</span></li>" for z in items)
        out.append(f'<details class="nu-ad-dq"><summary><b>{esc(reason)}</b> <span class="nu-ad-count">{len(items)}件</span>'
                   f'</summary><ul class="nu-ad-list">{lis}</ul></details>')
    return "".join(out)


def _ai(v: dict) -> str:
    a = v["ai"]
    prev = ('<p class="nu-ad-note">この AI の候補は利益ルートより前に生成されたもの（前回の生成）。'
            '今の確定ルートと照合して残ったものだけを出している。</p>' if a["previous"] else "")
    def _cond(o):
        bc = o.get("buy_conditions") if isinstance(o.get("buy_conditions"), dict) else {}
        return "・".join(_safe_text(bc.get(k)) for k in ("buy", "sell", "roi") if bc.get(k)) or "—"

    def _why(o):
        w = o.get("why")
        return _safe_text("・".join(str(x) for x in w[:2]) if isinstance(w, list) else (w or "—"))
    rows = [[esc(str(o.get("product") or o.get("product_id") or "")),
             esc(f'{o.get("action") or "—"}（{o.get("buy_now") or "—"}）'),
             esc(f'{o.get("opportunity_score") if o.get("opportunity_score") is not None else "—"}・'
                 f'確度 {o.get("confidence") or "—"}'),
             esc(_cond(o)),
             # 参考ルート（確定でない）の金額は出さない（一般のページと同じ扱い。公開の HTML の中にあるため）
             (_yen(o.get("net_profit")) if o.get("kind") == "main" else '<span class="nu-osub">参考ルート（金額は出さない）</span>'),
             esc(f'仕入 {o.get("buy_price_evidence") or "不明"}・売却 {o.get("sell_price_evidence") or "不明"}'),
             esc(_why(o))] for o in a["ops"]]
    tbl = _table(["商品", "判断（BUY・WAIT など）", "スコア・確度", "買う条件", "想定純利益（当時）", "価格の根拠", "理由"],
                 rows, caption="AI の候補")
    tasks = "".join(f"<li>{esc(_safe_text(t))}</li>" for t in a["tasks"])     # 「Health タブ」は _safe_text で読み替える
    dropped = (f'<p class="nu-osub">今の確定ルートと照合できない候補 {a["dropped"]}件は出していない。</p>'
               if a["dropped"] else "")
    return _box("今日の AI の候補", prev + (tbl or _empty("今の AI の候補はありません。")) + dropped
                + (f'<h3 class="nu-ad-h3">今日やること</h3><ul class="nu-ad-list">{tasks}</ul>' if tasks else "")
                + _generated("AI の候補", a["generated"]),
                sub="BUY・WAIT などの判断は生成時のもの。今の確定ルート（route_id）と照合して残ったものだけ")


def _capital(v: dict) -> str:
    out = []
    for p in v["capital"]:
        t = p["totals"]
        head = (f'<dl class="nu-ad-dl"><dt>配分</dt><dd>{_yen(t.get("allocated"))}</dd><dt>現金</dt><dd>{_yen(t.get("cash"))}</dd>'
                f'<dt>期待利益</dt><dd>{_yen(t.get("expected_profit"))}</dd><dt>期待 ROI</dt><dd>{_pct(t.get("expected_roi"))}</dd>'
                f'<dt>リスク</dt><dd>{esc(str(t.get("avg_risk_score") if t.get("avg_risk_score") is not None else "—"))}</dd>'
                f'<dt>分散</dt><dd>{esc(str(t.get("diversification_score") if t.get("diversification_score") is not None else "—"))}</dd></dl>'
                if t else '<p class="nu-ad-note">今の確定ルートと照合できない行を外したため、合計（生成時の値）は出していない。</p>')
        rows = [[esc(str(a.get("product") or a.get("product_id") or "")), esc(str(a.get("units") or "—")),
                 _yen(a.get("total")), _yen(a.get("expected_profit")),
                 esc(f'リスク {a.get("risk_score", "—")}・流動性 {a.get("liquidity_score", "—")}')] for a in p["allocs"]]
        tbl = _table(["商品", "台数", "金額", "期待利益", "リスク・流動性"], rows, caption=f'予算 {_yen(p["budget"])} の配分')
        wait = "".join(f'<li>{esc(str(w.get("product") or w.get("product_id") or ""))}</li>' for w in p["waiting"][:6])
        out.append(f'<details class="nu-ad-dq"{" open" if not out else ""}><summary><b>予算 {_yen(p["budget"])}</b>'
                   f' <span class="nu-ad-count">配分 {len(p["allocs"])}件・待機 {len(p["waiting"])}件</span></summary>'
                   + head + (tbl or _empty("配分はありません（今の確定ルートが無い）。"))
                   + (f'<p class="nu-osub">待機中</p><ul class="nu-ad-list">{wait}</ul>' if wait else "") + "</details>")
    if v["capital"] and all(not p["allocs"] and not p["waiting"] and not p["dropped"] for p in v["capital"]):
        out = [f'<p class="nu-ad-note">どの予算（{esc("・".join(_yen(p["budget"]) for p in v["capital"]))}）も配分・待機は 0件'
               '（今の確定ルートが無い）。</p>']
    first = v["capital"][0] if v["capital"] else {}
    note = ('<p class="nu-ad-note">この資金配分は利益ルートより前に生成されたもの（前回の生成）。金額は生成したときの値で、'
            '今の確定ルートと照合して残った行だけを出している。</p>' if first.get("previous") else "")
    return _box("資金配分", note + ("".join(out) or _empty("資金配分の記録はありません。"))
                + (_generated("資金配分", first.get("generated")) if first else ""),
                sub="配分・待機は、今の確定ルート（route_id）と照合して残ったものだけ")


def _learn(e: dict) -> str:
    coef, pred, notif = e["coef"], e["pred"], e["notif"]
    closed = pred.get("closed_count") or 0
    rows = ('<dl class="nu-ad-dl">'
            f'<dt>集計に入れていない記録</dt><dd>無効 {esc(str(e["invalidated_total"] if e["invalidated_total"] is not None else "—"))}件・'
            f'サンプル {esc(str(e["sample_total"] if e["sample_total"] is not None else "—"))}件</dd>'
            '<dt>予測と実績</dt><dd>' + (f'予測の成功確率 {esc(str(pred.get("predicted_success_prob_avg")))}%・実績 '
                                       f'{_pct(pred.get("realized_success_rate"))}（{closed}件）' if closed
                                       else "—（実績の記録なし）") + '</dd>'
            '<dt>通知の成功</dt><dd>' + (f'{_pct(notif.get("notification_success_rate"))}（通知 {notif.get("total_notifications")}件）'
                                      if notif.get("total_notifications") else "—（通知の記録なし）") + '</dd>'
            f'<dt>補正係数</dt><dd>スコア {esc(str(coef.get("opportunity_score_coeff", "—")))}・成功確率 '
            f'{esc(str(coef.get("success_probability_coeff", "—")))}・リスク {esc(str(coef.get("risk_score_coeff", "—")))}'
            f'（件数 {esc(str(coef.get("sample_size", "—")))}・信頼度 {esc(str(coef.get("confidence") or "—"))}。'
            '利益の判定には使わない）</dd></dl>')
    ins = "".join(f"<li>{esc(_safe_text(x))}</li>" for x in e["insights"])
    return rows + (f'<h3 class="nu-ad-h3">今週学んだこと</h3><ul class="nu-ad-list">{ins}</ul>' if ins else "")


def _execution(v: dict) -> str:
    e = v["execution"]
    cnt = "".join(f'<li><span>{esc(EXEC_LABELS[s])}</span><b>{e["counts"][s]}件</b></li>' for s in EXEC_STATUSES)
    rate = (_pct(e["rate"]) if e["rate"] is not None else "—（実績の記録なし）")
    rows = [[esc(str(r.get("product") or r.get("product_id") or "")), esc(str(r.get("date") or "—")),
             _badge(OK if r.get("status") == "SUCCESS" else FAIL if r.get("status") == "FAILED"
                    else INFO, EXEC_LABELS.get(str(r.get("status")), str(r.get("status") or ""))),
             esc(str(r.get("action") or "—")),
             ('<span class="nu-osub">無効（当時の値は出さない）</span>' if r.get("status") == "INVALIDATED"
              else '<span class="nu-osub">今のルートと照合できない（当時の値は出さない）</span>' if not r["_alive"]
              else _yen(r.get("predicted_net")) + '<span class="nu-osub">当時の予測</span>'),
             (_yen(r.get("realized_profit")) if r.get("realized_profit") is not None else "—"),
             esc(str(r.get("invalidated_reason") or ("—" if r["_alive"] else "今のルートと照合できない")))] for r in e["rows"]]
    memos = {r[-1] for r in rows}
    common = ""
    if len(rows) > 1 and len(memos) == 1 and next(iter(memos)) != "—":
        common = f'<p class="nu-ad-note">すべての記録のメモ: {next(iter(memos))}</p>'
        rows = [r[:-1] for r in rows]
    tbl = common + _table(["商品", "日付", "状態", "判断", "予測", "実績", "メモ"][:len(rows[0]) if rows else 7], rows,
                          caption="実行の記録（新しい順・最大30件）")
    return (_box("実行の件数", f'<ul class="nu-ad-counts" role="list">{cnt}</ul>'
                 f'<p class="nu-osub">成功率 {rate}・サンプルの記録 {e["samples"]}件は数えない</p>'
                 + _generated("実行の集計", e["generated"]),
                 sub="無効（INVALIDATED）は履歴として残し、今の値には使わない")
            + _box("実行の記録", tbl if rows else _empty("実行の記録はありません。"))
            + _box("学んだこと・補正（実行の集計より）", _learn(e)))


_DISPATCH_LABELS = {"dry_run_planned": "配信を計画（dry-run・送っていない）", "sent": "送信済み", "failed": "送信の失敗",
                    "revalidation_failed": "配信の直前の確認で止めた", "not_configured": "送信先が無い（送っていない）"}


def _act_notices(a: dict) -> str:
    """今すぐ行動の通知（dry-run）の件数と候補。"""
    if not a.get("available"):
        return _box("今すぐ行動の通知", _empty("今回の生成の記録がありません。"))
    items = "".join(f'<li><b>{esc(i["status"])}</b>・{esc(i["product"])}<span class="nu-osub">{esc(i["transition"])}・'
                    f'{esc(_DISPATCH_LABELS.get(i["dispatch"], i["dispatch"]))}</span></li>' for i in a["items"])
    dl = "".join(f"<dt>{esc(lbl)}</dt><dd>{a[k]}件</dd>" for k, lbl in (
        ("notification_candidates", "通知の候補（行動できない → できる）"), ("dedupe_suppressed", "同じ状態のため出さなかった"),
        ("baseline_recorded", "前回の状態を見ていないため記録だけ"),
        ("dispatch_planned", "配信の計画（dry-run）"), ("dispatch_sent", "送信"), ("dispatch_failed", "送信の失敗"),
        ("dispatch_blocked", "配信の直前の確認で止めた")))
    mode = "dry-run（外部へは送らない）" if a["dry_run"] else "送信あり"
    return _box("今すぐ行動の通知", f'<dl class="nu-ad-dl"><dt>方式</dt><dd>{esc(mode)}</dd>{dl}</dl>'
                + (f'<ul class="nu-ad-list">{items}</ul>' if items else _empty(
                    "今回、行動できるようになった利益商品はありません" + ("（基準日）。" if a["baseline"] else "。")))
                + _generated("今回", a["at"]),
                sub="確定の利益があり、今すぐ行動できるようになった商品だけ（同じ状態では毎回出さない）。判定は「今すぐ行動」と同じ")


def _notices(v: dict) -> str:
    n = v["notices"]
    user = "".join(
        f'<li>{_badge(OK if u["alive"] else INFO, "今も有効" if u["alive"] else "当時の通知")} <b>{esc(u["label"])}</b>'
        f'・{esc(u["product"])}<span class="nu-osub">{_when(u["at"])}'
        + (f'・{esc(u["message"])}' if u["message"] else "・今は確定ルートではない（当時の内容は出さない）")
        + "</span></li>" for u in n["user"][:30])
    system = "".join(f'<li><b>{esc(s["label"])}</b><span class="nu-osub">{_when(s["at"])}・'
                     f'{esc(s["message"])}</span></li>' for s in n["system"][:20])
    delivery = "・".join(f"{esc(k)}: {esc(v2)}" for k, v2 in n["delivery"].items()) or "記録なし"
    return (_act_notices(v.get("act_notices") or {})
            + _box("利用者向けの通知", f'<ul class="nu-ad-list">{user}</ul>' if user else _empty("利用者向けの通知はありません。"),
                 sub="同じ通知は1回だけ。今の確定ルートでない通知は、当時の金額を出さない")
            + _box("システムの通知（データ品質）", f'<ul class="nu-ad-list">{system}</ul>' if system
                   else _empty("システムの通知はありません。"))
            + _box("配信", f'<dl class="nu-ad-dl"><dt>配信先</dt><dd>{esc("・".join(n["channels"]) or "記録なし")}</dd>'
                           f'<dt>直近の配信</dt><dd>{delivery}</dd>'
                           f'<dt>抑制した通知</dt><dd>{esc(str(n["suppressed"] if n["suppressed"] is not None else "—"))}件</dd></dl>',
                   sub="配信先の URL・トークンは出さない"))


def _diff(dv: dict) -> str:
    if not dv.get("available"):
        return _empty("前日の記録がありません。")
    rows = []
    for k, lbl, ratio in (("stale_rate", "古い価格の割合", True), ("zero_rate", "0円（取得失敗）の割合", True),
                          ("item_url_rate", "商品ページ単位の URL の割合", True), ("main_route_count", "確定ルート", False),
                          ("reference_route_count", "参考ルート", False)):
        x = dv.get(k) or {}
        f = (lambda y: _pct(y)) if ratio else (lambda y: f"{y}件" if y is not None else "—")
        rows.append([esc(lbl), f(x.get("prev")), f(x.get("cur"))])
    extra = "".join(f"<li>{esc(lbl)}: {esc('・'.join(str(p) for p in dv.get(k) or []) or 'なし')}</li>"
                    for k, lbl in (("new_main", "新しく確定になったルート"), ("lost_main", "確定から外れたルート")))
    return _table(["指標", "前日", "今日"], rows, caption="前日比較") + f'<ul class="nu-ad-list">{extra}</ul>'


def _data_coverage_html(c: dict) -> str:
    r, s, b, g = (c.get(k) or {} for k in ("retail", "stock", "buyback", "tcg"))
    cm = c.get("camera") or {}
    ac = c.get("actionability") or {}
    ap = c.get("actionability_products") or []
    if not (r or s or b or g):
        return _empty("記録なし")
    n = lambda d, k: esc(str(d.get(k, 0)))  # noqa: E731
    return ('<dl class="nu-ad-dl">'
            f'<dt>定価</dt><dd>確認済み {n(r, "verified")}・参考 {n(r, "reference")}（別に数えた公式の販売終了 '
            f'{n(r, "sale_ended")}）</dd>'
            f'<dt>在庫</dt><dd>在庫あり {n(s, "IN_STOCK")}・在庫切れ {n(s, "OUT_OF_STOCK")}・在庫未確認 '
            f'{n(s, "UNKNOWN")}・抽選 {n(s, "LOTTERY")}</dd>'
            f'<dt>買取</dt><dd>使える商品 {n(b, "usable_products")}・新しい {n(b, "fresh_rows")}行・古い '
            f'{n(b, "stale_rows")}行・失敗 {n(b, "failed_rows")}行</dd>'
            f'<dt>TCG</dt><dd>抽選 {n(g, "lotteries")}・予約 {n(g, "preorder")}・先着 {n(g, "first_come")}・'
            f'再販 {n(g, "restock")}</dd>'
            + (f'<dt>カメラの買取</dt><dd>新品の買取 新しい {n(cm, "fresh_new")}行・古い {n(cm, "stale_new")}行・'
               f'中古の参考 {n(cm, "used_reference")}行（新品同様も中古）・確定の売値 {n(cm, "confirmed_sells")}行・'
               f'利益 {n(cm, "profitable")}・今すぐ行動できる {n(cm, "actionable")}</dd>' if cm else "")
            + (f'<dt>今すぐ行動</dt><dd>確定の利益 {n(ac, "confirmed_profitable")}・今すぐ行動できる {n(ac, "actionable")}'
               f'（行動できない: 在庫切れ・未確認 {n(ac, "blocked_by_stock")}・抽選などの受付終了 '
               f'{n(ac, "blocked_by_closed_lottery")}・確認が古い（更新待ち） {n(ac, "blocked_by_stale_availability")}・'
               f'日程不明・受付前 {n(ac, "blocked_by_unknown_schedule")}・販売終了 {n(ac, "blocked_by_sale_ended")}・'
               f'購入ページ不明 {n(ac, "blocked_by_missing_url")}）</dd>' if ac else "")
            + '</dl>'
            + ('<ul class="nu-ad-list">' + "".join(
                f'<li><b>{esc(str(r.get("product") or r.get("product_id") or ""))}</b><span class="nu-osub">'
                f'{esc(str(r.get("label") or ""))}・{"今すぐ行動できる" if r.get("actionable") else "行動できない"}'
                + (f'・締切 {esc(str(r.get("deadline"))[:16].replace("T", " "))}' if r.get("deadline") else "")
                + (f'・{esc(str(r.get("checked_at"))[:16].replace("T", " "))} 確認' if r.get("checked_at") else "")
                + '</span></li>' for r in ap[:50]) + '</ul>' if ap else "")
            + '<p class="nu-osub">在庫ありは、公式などのページで購入できる表示（在庫あり・カートに入れる）を確認した'
            '時刻つきのものだけ（この欄は利益の案件・診断の値。確認から7日を過ぎれば在庫未確認に戻る。'
            '在庫再開・商品詳細の表示、今すぐ行動できるかは確認から3時間で「更新待ち」になる）。</p>')


IDENTITY_LABELS = {"IDENTITY_CONFIRMED": "確認済み（公式ページで型番・JAN を確認）", "PARTIAL_IDENTITY": "一部だけ確認",
                   "AMBIGUOUS": "曖昧（型番も JAN も無い）", "DISCONTINUED": "公式で販売終了",
                   "NEEDS_USER_DECISION": "判断待ち（版が決められない）"}


def _identity_html(idn: dict) -> str:
    cnt, rows = idn.get("counts") or {}, [r for r in idn.get("products") or [] if isinstance(r, dict)]
    if not rows:
        return _empty("記録なし")
    dl = "".join(f'<dt>{esc(label)}</dt><dd>{esc(str(cnt.get(k, 0)))}</dd>' for k, label in IDENTITY_LABELS.items())
    dl += (f'<dt>型番なし / JAN なし</dt><dd>{esc(str(cnt.get("missing_model", 0)))} / '
           f'{esc(str(cnt.get("missing_jan", 0)))}</dd>')
    # 曖昧・判断待ちの商品から商品詳細へたどれるようにする（同一性の監査の理由つき）
    items = "".join(f'<li><b>{esc(r.get("name") or r["product_id"])}</b>'
                    f'<span class="nu-osub">{esc(IDENTITY_LABELS.get(r["state"], r["state"]))}・'
                    f'{esc(_safe_text(r.get("reason") or ""))}</span> {product_page.link(r["product_id"])}</li>'
                    for r in rows if r.get("state") in ("NEEDS_USER_DECISION", "AMBIGUOUS"))
    return (f'<dl class="nu-ad-dl">{dl}</dl>'
            + (f'<h3 class="nu-ad-h3">判断待ち・曖昧な商品</h3><ul class="nu-ad-list">{items}</ul>' if items else "")
            + '<p class="nu-osub">確認済みは、型番か JAN が登録され、その値を公式ページで確かめた証拠があるものだけ'
              '（商品名・価格の一致だけで決めない）。</p>'
            + _official_direct_html(idn.get("official_direct") or []))


OFFICIAL_DIRECT_REASONS = {
    "identity_not_confirmed": "同一性が未確認", "model_not_exact": "型番が一致しない", "model_mismatch": "型番が証拠と違う",
    "jan_not_exact": "JAN が一致しない", "jan_mismatch": "JAN が証拠と違う", "capacity_mismatch": "容量が違う",
    "body_kit_mismatch": "ボディー/キットが違う", "edition_unknown": "版が分からない", "not_official_shop": "公式ストアでない",
    "not_purchase_page": "購入ページでない", "no_current_price": "表示中の価格が無い", "shipping_unknown": "送料が分からない",
    "sale_mode_not_purchasable": "抽選・販売終了など", "stock_semantics_unknown": "在庫の表し方が分からない",
    "no_verified_at": "確認日が無い", "verified_at_in_future": "確認日が未来", "verified_at_mismatch": "確認日が記録と違う",
    "price_kind_not_official_direct": "公式直販価格でない", "no_official_direct_evidence": "証拠が無い",
    "shipping_source_mismatch": "送料の記録が別の店", "recheck_changed": "再確認で価格が変わった（確認待ち）",
    "recheck_sale_ended": "再確認で販売終了", "verified_at_stale": "確認から14日を過ぎた",
}
OFFICIAL_DIRECT_STOCK = {"IN_STOCK": "在庫あり（確認時）", "OUT_OF_STOCK": "在庫なし（確認時）", "UNKNOWN": "在庫未確認"}


def _official_direct_html(rows: list[dict]) -> str:
    """公式直販価格（Phase 16）: 確定の仕入れ値に使えるもの・参考のもの。希望小売価格（定価）ではないことを明記する。"""
    rows = [r for r in rows if isinstance(r, dict)]
    if not rows:
        return ""
    ok = [r for r in rows if r.get("eligible")]

    def _li(r: dict) -> str:
        fee = r.get("shipping_fee")
        why = "・".join(OFFICIAL_DIRECT_REASONS.get(x.split(":")[0], "条件を満たさない") for x in r.get("reasons") or [])
        msrp = "希望小売価格はオープン価格・" if r.get("msrp") == "open_price" else ""
        price = f'¥{int(r["price"]):,}' if isinstance(r.get("price"), int) and r["price"] > 0 else "—"
        return (f'<li><b>{esc(str(r.get("name") or r.get("product_id") or ""))}</b>'
                f'<span class="nu-osub">{esc(str(r.get("shop") or ""))}・公式直販価格 {esc(price)}・{esc(msrp)}'
                f'送料 {esc("—" if fee is None else "無料" if int(fee) == 0 else f"¥{int(fee):,}")}・'
                f'{esc(OFFICIAL_DIRECT_STOCK.get(str(r.get("stock") or ""), "在庫未確認"))}・'
                f'確認 {esc(str(r.get("verified_at") or "—"))}・'
                f'{"確定の仕入れ値に使える" if r.get("eligible") else "参考（" + esc(why or "条件を満たさない") + "）"}'
                f'</span> {product_page.link(str(r.get("product_id") or ""))}</li>')
    return (f'<h3 class="nu-ad-h3">公式直販価格（使える {len(ok)} / 参考 {len(rows) - len(ok)}）</h3>'
            f'<ul class="nu-ad-list">{"".join(_li(r) for r in rows)}</ul>'
            '<p class="nu-osub">公式直販価格は、メーカーの公式ストアが実際に売っている価格で、希望小売価格（定価）ではない'
            '（カメラの希望小売価格はオープン価格のまま）。型番・JAN・容量・ボディー/キット・版・購入ページ・送料・在庫の表し方・'
            '確認日がそろったものだけを確定の仕入れ値に使う。今すぐ行動できる商品に数えるのは、在庫ありの明示があるときだけ。</p>')


def _system(v: dict) -> str:
    h = v["health"]
    hs = h.get("health_score") or {}
    parts = "".join(f"<dt>{esc(lbl)}</dt><dd>{esc(str(hs.get(k, '—')))} / {mx}</dd>" for k, lbl, mx in (
        ("data_quality", "データ品質", 35), ("profit_discovery", "利益の発見", 25), ("source_health", "取得元", 20),
        ("link_quality", "リンク", 10), ("freshness", "鮮度", 10)))
    imp = "".join(f'<li>{"★" * int(i.get("stars") or 0)} {esc(_safe_text(i.get("action")))}'
                  f'<span class="nu-osub">効果 {esc(_safe_text(i.get("effect") or "—"))}・工数 {esc(str(i.get("effort") or "—"))}</span></li>'
                  for i in (h.get("improvements_top10") or []) if isinstance(i, dict))
    api_rows = [[esc(a["name"]), _badge(a["status"], a["configured"]), esc(a["state"]), esc(a["kill_switch"]),
                 _when(a["success"])] for a in v["api"]]
    api = _table(["API", "設定", "状態", "停止スイッチ", "最後の成功"], api_rows, caption="外部 API") or _empty("API の記録はありません。")
    cov = v["coverage"]
    dqr = v["dq_report"].get("collection") or {}
    cmp = v["dq_report"].get("comparison") or {}
    cam = v["camera"]
    cam_used = (f'（うち中古「新品同様」の価格 {esc(str(v.get("camera_used")))}件・確定の売値には使わない）'
                if v.get("camera_used") else "")
    cam_text = ((f'自動取得 {esc(str(cam.get("ok")))} / {esc(str(cam.get("total")))}件{cam_used}' if cam.get("ok") else
                 "手動の確認で補っている（自動取得 0件）") + f'<span class="nu-osub">生成 {_when(v["camera_generated"])}</span>'
                if cam else "記録なし")
    reasons = "".join(f'<li>{_reason(r.get("reason"))}<b>{esc(str(r.get("count")))}件</b></li>'
                      for r in (v["dq_report"].get("failure_reasons") or [])[:6] if isinstance(r, dict))
    return (_box("システムの健康度", f'<p class="nu-ad-big">{esc(str(hs.get("total", "—")))} / 100</p>'
                 f'<dl class="nu-ad-dl">{parts}</dl>' + _generated("健康度の報告", h.get("generated_at")))
            + _box("前日比較", _diff(h.get("diff_vs_prev") or {}))
            + _box("改善の優先順位", f'<ul class="nu-ad-list">{imp}</ul>' if imp else _empty("改善の候補はありません。"))
            + _box("外部 API（設定の有無だけ。キーの値は出さない）",
                   api + f'<p class="nu-osub">試験実行のみ: {"はい" if v["api_dry_run"] else "いいえ"}。'
                         '回路遮断（circuit breaker）の状態は記録されていない。キーは GitHub の Secrets に登録する'
                         '（例: EBAY_APP_ID。値はこのページに出さない）。</p>'
                         '<p class="nu-osub">eBay を設定したときに参考ルートが確定ルートになる条件: API で 14日以内の成約を取得し、'
                         f'同じ商品の成約を {esc(str(v.get("min_sold") or "—"))}件以上・成約日時つきで集計できること'
                         '（今の eBay の取得は1件ごとの成約日時を保存していないので、この条件はまだ満たせない）。</p>'
                         + _generated("API の監査", v["api_generated"]))
            + _box("買取の取得（全体）", f'<dl class="nu-ad-dl"><dt>取得の成功</dt><dd>{esc(str(dqr.get("ok_jobs", "—")))} / '
                   f'{esc(str(dqr.get("total_jobs", "—")))}（{esc(str(dqr.get("success_rate_pct", "—")))}%）</dd>'
                   f'<dt>全部失敗している店</dt><dd>{esc(str(dqr.get("shops_all_failed", "—")))} / {esc(str(dqr.get("total_shops", "—")))}店</dd>'
                   + (f'<dt>前回比</dt><dd>{"+" if (cmp.get("delta_pct") or 0) > 0 else ""}{esc(str(cmp.get("delta_pct")))}pt'
                      f'（{esc(str(cmp.get("trend") or "—"))}・7日平均 {esc(str(cmp.get("moving_avg_7d_pct", "—")))}%）</dd>'
                      if cmp.get("delta_pct") is not None else "")
                   + f'<dt>カメラの買取</dt><dd>{cam_text}</dd></dl>'
                   + (f'<p class="nu-osub">主な失敗理由</p><ul class="nu-ad-counts" role="list">{reasons}</ul>' if reasons else ""))
            + _box("データの網羅（定価・在庫・買取・TCG）", _data_coverage_html(v.get("data_coverage") or {}))
            + _box("商品の同一性（型番・JAN・版）", _identity_html(v.get("identity") or {}))
            + _box("カバー範囲", f'<dl class="nu-ad-dl"><dt>商品数</dt><dd>{esc(str(cov.get("total_products", "—")))}</dd>'
                   f'<dt>カバー率のスコア</dt><dd>{esc(str(cov.get("coverage_score", "—")))}</dd>'
                   + "".join(f'<dt>{esc(str(cc.get("category") or ""))}</dt><dd>{esc(str(cc.get("products", "—")))}商品'
                             f'（確定 {esc(str(cc.get("main", 0)))}・参考 {esc(str(cc.get("reference", 0)))}）</dd>'
                             for cc in (cov.get("current_coverage") or []) if isinstance(cc, dict))
                   + '</dl>'
                   + (('<h3 class="nu-ad-h3">追加の候補のカテゴリ（上位5）</h3><ul class="nu-ad-list">'
                       + "".join(f'<li><b>{esc(str(cc.get("category") or ""))}</b><span class="nu-osub">優先度 '
                                 f'{esc(str(cc.get("priority_score", "—")))}・工数 {esc(str(cc.get("effort") or "—"))}・'
                                 f'{esc(_safe_text(cc.get("note") or ""))}</span></li>'
                                 for cc in (cov.get("category_candidates_ranked") or [])[:5] if isinstance(cc, dict))
                       + "</ul>") if cov.get("category_candidates_ranked") else ""))
            + _box("ほかのページ", '<ul class="nu-ad-list">'
                   '<li><a href="./collector_report.html">取得レポート（詳しい表）</a></li>'
                   '<li><a href="beta/">はじめかた（beta）</a><span class="nu-osub">別ページ。削除の候補</span></li></ul>'))


def render(view: dict | None) -> str:
    v = view or {}
    nav = "".join(f'<a class="nu-ad-tab" href="{esc(_sec_href(k))}" data-nu-ad-tab="{k}">{esc(lbl)}</a>'
                  for k, lbl in SECTIONS)
    panels = {"overview": _overview, "sources": _sources, "data-quality": _dq, "ai": _ai, "capital": _capital,
              "execution": _execution, "notifications": _notices, "system": _system}
    body = "".join(f'<div class="nu-ad-panel" data-nu-ad-panel="{k}"{"" if k == "overview" else " hidden"}>'
                   f'{panels[k](v) if v else _empty("運営の情報がまだ生成されていません。")}</div>'
                   for k, _l in SECTIONS)
    return (
        '<section class="nu-page nu-ad" data-nu-page="admin" aria-labelledby="nu-ad-title" hidden>'
        '<div class="nu-ad-head"><h1 id="nu-ad-title" class="nu-page__title" tabindex="-1">運営の管理画面</h1>'
        '<p class="nu-ad-notice">運営者向けの表示です。<b>ログイン・権限の仕組みは無く</b>、公開ページの中にあります'
        '（静的なページ）。秘密の値は出しません。<b>読むだけ</b>の画面で、ここから設定や取得は変えられません。</p></div>'
        f'<nav class="nu-ad-nav" aria-label="運営者向けの切り替え">{nav}</nav>'
        f'{body}</section>'
    )


def script() -> str:
    """section の切り替えとタイトル（ルーターの表示のあとに nu:render で受ける）。"""
    keys = [k for k, _l in SECTIONS]
    labels = {k: lbl for k, lbl in SECTIONS}
    import json
    return ("<script>(function(){var root=document.getElementById('new-ui-root');if(!root)return;"
            f"var KEYS={json.dumps(keys)},LABELS={json.dumps(labels, ensure_ascii=False)};"
            "root.addEventListener('nu:render',function(e){var sec=root.querySelector('[data-nu-page=\"admin\"]');"
            "if(!sec||sec.hidden)return;var s=new URLSearchParams(location.search).get('section');"
            "if(KEYS.indexOf(s)<0)s='overview';"
            "sec.querySelectorAll('[data-nu-ad-panel]').forEach(function(p){p.hidden=p.getAttribute('data-nu-ad-panel')!==s;});"
            "sec.querySelectorAll('[data-nu-ad-tab]').forEach(function(t){if(t.getAttribute('data-nu-ad-tab')===s)"
            "t.setAttribute('aria-current','page');else t.removeAttribute('aria-current');});"
            "var site=root.getAttribute('data-nu-site')||'';document.title='運営 - '+LABELS[s]+' | '+site;});})();</script>")


def without_admin(html: str) -> str:
    """HTML から運営者向けのページ（<section data-nu-page="admin"> と、それが閉じるまで）を除く（一般のページの検査に使う）。
    入れ子の <section> を数えて対応する </section> まで（後ろのページの印に頼らない。後ろを消しすぎない）。"""
    i = html.find('data-nu-page="admin"')
    if i < 0:
        return html
    i = html.rfind("<section", 0, i)
    depth, pos = 0, i
    for m in re.finditer(r"<section\b|</section>", html[i:]):
        depth += 1 if m.group(0) != "</section>" else -1
        if depth == 0:
            pos = i + m.end()
            return html[:i] + html[pos:]
    return html[:i]                                       # 閉じていなければ後ろを全部除く（一般のページの検査で内部情報を拾わない側）
