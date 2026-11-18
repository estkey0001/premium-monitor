"""二次流通（フリマ・オークション）の取得可否の管理と、公式 API アダプターの受け皿。

方針（新しい仕組みは作らない。camera_routes / camera_refresh の入口を広げるだけ）:
- 市場ごとに AVAILABLE / PARTIAL / BLOCKED / FAILED / NOT_SUPPORTED を持つ。取得できなかった市場は「未取得」で、
  「出品なし・成約なし」とは書かない（listing_rows / sold_rows は未取得なら None。0 は「取れたが 0 件」だけ）。
- 検索結果のスクレイピングはしない（config/secondary_markets.yaml の policy）。データは (1) 公式 API のアダプター、
  (2) 調査員が個別の根拠 URL つきで読んだ行（research_camera_*.json）だけから入る。どちらも既存の行の検査を通る。
- 資格情報は環境変数の名前だけを設定に持ち、値は読んでも出力・保存しない。未登録は NOT_CONFIGURED（安全に BLOCKED）。
- アダプターは register_adapter() で差し込む（標準は eBay。register_default_adapters）。登録が無い市場は、キーがあっても adapter_not_implemented の BLOCKED。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from src.research import camera_routes as cr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "secondary_markets.yaml"

AVAILABLE, PARTIAL, BLOCKED, FAILED, NOT_SUPPORTED = "AVAILABLE", "PARTIAL", "BLOCKED", "FAILED", "NOT_SUPPORTED"
NOT_CONFIGURED, CONFIGURED, NOT_REQUIRED = "NOT_CONFIGURED", "CONFIGURED", "NOT_REQUIRED"
PENDING_APPROVAL = "PENDING_APPROVAL"                           # 利用許可の審査待ち（資格情報は有効。成約など）
STATUSES = (AVAILABLE, PARTIAL, BLOCKED, FAILED, NOT_SUPPORTED, NOT_CONFIGURED, PENDING_APPROVAL)
_NO_DATA = (BLOCKED, FAILED, NOT_SUPPORTED, NOT_CONFIGURED, PENDING_APPROVAL)   # 取得できていない（0 件ではなく未取得）

# アダプター: (market_id, env) -> list[dict]（research_camera_*.json の行と同じ形）。例外・None は FAILED
_ADAPTERS: dict[str, Callable] = {}


def register_adapter(market_id: str, fn: Callable) -> None:
    _ADAPTERS[market_id] = fn


def clear_adapters() -> None:
    _ADAPTERS.clear()


def load_config() -> dict:
    import yaml
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _has(env, names, alias=None) -> bool:
    """名前がすべて設定されているか。alias = {名前: [別名...]} があれば、別名のどれかで足りる（値は読むだけで返さない）。"""
    alias = alias or {}
    return bool(names) and all(any(str((env or {}).get(k) or "").strip() for k in [n, *(alias.get(n) or [])]) for n in names)


def credential_state(spec: dict, env=None) -> str:
    """資格情報の状態だけを返す（値は返さない）。API が無い市場は NOT_REQUIRED。"""
    env = os.environ if env is None else env
    api = spec.get("official_api") or {}
    if not api.get("exists"):
        return NOT_REQUIRED
    return CONFIGURED if _has(env, api.get("credential_env") or [], api.get("credential_alias")) else NOT_CONFIGURED


def _enabled(spec: dict, env) -> bool:
    var = (spec.get("official_api") or {}).get("enable_var")
    return bool(var) and str((env or {}).get(var) or "").lower() == "true"


def market_status(market_id: str, spec: dict, env=None, *, rows: Optional[dict] = None, adapter_error: Optional[str] = None,
                  adapters_ran: Optional[set] = None, detail=None) -> dict:
    """1 市場の取得状態。rows = {"listing": n, "sold": n}（行が実際に採用できた件数）。"""
    env = os.environ if env is None else env
    cred = credential_state(spec, env)
    status, reason = spec.get("status", BLOCKED), spec.get("reason", "unknown")
    la, sa = spec.get("listing_access", BLOCKED), spec.get("sold_access", BLOCKED)
    api = spec.get("official_api") or {}
    if api.get("exists") and detail is not None:                # アダプターが自分で状態を判断して返した（資格情報・承認・dry-run・取得結果）
        status, reason, la, sa = detail.status, detail.reason, detail.listing_access, detail.sold_access
        if detail.status == FAILED:
            adapter_error = detail.reason
        st_ = detail.stats or {}
        rows = {"listing": st_.get("listing_matched") if la in (AVAILABLE, PARTIAL) else None,        # 同一性・状態を通った件数（為替未確認でも数える）
                "sold": st_.get("sold_matched") if sa in (AVAILABLE, PARTIAL) else None}
    elif api.get("exists"):
        if cred == NOT_CONFIGURED:
            status, reason, la, sa = NOT_CONFIGURED, "official_api_not_configured", NOT_CONFIGURED, NOT_CONFIGURED
        elif not _enabled(spec, env):
            status, reason, la, sa = BLOCKED, "official_api_not_enabled", BLOCKED, BLOCKED
        elif adapter_error:
            status, reason, la, sa = FAILED, adapter_error, FAILED, FAILED
        elif market_id not in _ADAPTERS:
            status, reason, la, sa = BLOCKED, "adapter_not_implemented", BLOCKED, BLOCKED
        elif market_id not in (adapters_ran or set()):          # 登録だけでは取得扱いにしない（実際に呼んだ週だけ）
            status, reason, la, sa = BLOCKED, "adapter_not_run", BLOCKED, BLOCKED
        else:
            sold_ok = all(str(env.get(n) or "").lower() == "true" for n in (api.get("sold_requires") or [])) and bool(api.get("sold_requires"))
            status, reason, la, sa = PARTIAL, "api_listing_only" if not sold_ok else "api_ok", AVAILABLE, (AVAILABLE if sold_ok else BLOCKED)
            if sold_ok:
                status = AVAILABLE
    nl = (rows or {}).get("listing")
    ns = (rows or {}).get("sold")
    if (nl or ns) and status in _NO_DATA:                       # 調査員が個別の根拠 URL で読んだ行がある（検索結果の取得ではない）
        status, reason = PARTIAL, "rows_from_research_file"
        la = AVAILABLE if nl else la
        sa = AVAILABLE if ns else sa
    got_listing = la in (AVAILABLE, PARTIAL)
    got_sold = sa in (AVAILABLE, PARTIAL)
    out = {"market": market_id, "label": spec.get("label"), "priority": spec.get("priority"), "status": status, "reason": reason,
            "listing_access": la, "sold_access": sa, "credentials": cred, "api_error": adapter_error, "checked_on": spec.get("checked_on"),
            "official_api": api.get("name"), "evidence": spec.get("evidence"),
            # 未取得は None（0 件と区別する）
            "listing_rows": int(nl or 0) if got_listing else None, "sold_rows": int(ns or 0) if got_sold else None}
    if detail is not None:                                       # 件数・状態だけ（秘密の値・自由記述を入れない）
        out["adapter"] = {"attempted_at": detail.checked_at, **_public_stats(detail.stats)}      # 試行した時刻（取得に成功した観測の時刻ではない）
    return out


_STAT_KEYS = ("requests", "items_found", "items_matched", "listing_matched", "sold_matched", "rejected_identity", "rejected_condition",
              "rejected_no_price_or_url", "rejected_not_fixed_price", "budget_exhausted", "truncated", "listing_error", "sold_error", "sold_reason")


def _public_stats(st: dict) -> dict:
    """公開してよい統計だけ（許可リスト。数値・真偽・短い英字の理由のみ）。"""
    import re
    out = {}
    for k in _STAT_KEYS:
        v = (st or {}).get(k)
        if isinstance(v, bool) or isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"[a-z0-9_]{1,40}", v)):
            out[k] = v
    ap = (st or {}).get("approval") or {}
    out["approval"] = {"insights_approved": bool(ap.get("insights_approved")), "sold_license_confirmed": bool(ap.get("sold_license_confirmed"))}
    out["fx"] = {str(c)[:3]: {"status": str(f.get("status"))[:12], "checked_at": str(f.get("checked_at") or "")[:10] or None}
                 for c, f in ((st or {}).get("fx") or {}).items() if isinstance(f, dict)}
    return out


def count_rows(market: dict) -> dict:
    """build_market の出力から、市場ごとに「採用できた」listing / sold の件数（URL ホストから市場を決める）。"""
    n: dict = {}
    for p in market.get("products", []):
        for o in p["observations"]:
            if o["kind"] not in ("listing", "sold") or o["reasons"] or not o.get("price"):
                continue
            k = cr.market_from_url(o.get("url")) if hasattr(cr, "market_from_url") else None
            if not k:
                continue
            n.setdefault(k, {"listing": 0, "sold": 0})[o["kind"]] += 1
    return n


def market_report(market: dict, cfg: Optional[dict] = None, env=None, *, fees: Optional[dict] = None, adapter_errors: Optional[dict] = None,
                  adapters_ran: Optional[set] = None, adapter_details: Optional[dict] = None) -> list[dict]:
    """全市場の取得状態＋手数料の状態。優先順位順。"""
    cfg = cfg or load_config()
    counts = count_rows(market)
    out = []
    for mid, spec in sorted((cfg.get("markets") or {}).items(), key=lambda kv: kv[1].get("priority", 99)):
        st = market_status(mid, spec, env, rows=counts.get(mid), adapter_error=(adapter_errors or {}).get(mid), adapters_ran=adapters_ran,
                           detail=(adapter_details or {}).get(mid))
        f = (fees or {}).get(mid) or {}
        st["fee_status"] = cr.fee_status(f)
        st["fee_rate"] = f.get("rate") if st["fee_status"] != cr.FEE_UNKNOWN else None
        out.append(st)
    return out


def blocked_treated_as_empty(report: list[dict]) -> int:
    """品質: 取得できていない市場が「0 件」と書かれていたら数える（0 でなければならない）。"""
    return sum(1 for m in report if m["status"] in _NO_DATA and (m["listing_rows"] is not None or m["sold_rows"] is not None))


def retail_api_states(cfg: Optional[dict] = None, env=None) -> list[dict]:
    """楽天・Yahoo!ショッピング API の受け皿の状態（資格情報の有無だけ。値は出さない）。"""
    cfg = cfg or load_config()
    env = os.environ if env is None else env
    out = []
    for k, v in (cfg.get("retail_apis") or {}).items():
        has = _has(env, v.get("credential_env") or [])
        en = str(env.get(v.get("enable_var") or "") or "").lower() == "true"
        out.append({"api": k, "label": v.get("label"), "status": (NOT_CONFIGURED if not has else (BLOCKED if not en else BLOCKED)),
                    "reason": "NOT_CONFIGURED" if not has else ("not_enabled" if not en else "adapter_not_implemented"), "scope": v.get("scope")})
    return out


def run_adapters(env=None) -> tuple[list[dict], dict, set]:
    """後方互換: (行, {market: エラー理由}, 実際に呼んだ市場)。詳細は run_adapters_full。"""
    rows, errs, ran, _ = run_adapters_full(env)
    return rows, errs, ran


def run_adapters_full(env=None) -> tuple[list[dict], dict, set, dict]:
    """登録済みのアダプターを呼ぶ。返り値: (行, {market: エラー理由}, 実際に呼んだ市場, {market: AdapterResult})。
    - 従来型のアダプター（list を返す）は、資格情報あり・有効化のときだけ呼ぶ。失敗は例外で知らせる契約（[] は「取れたが 0 件」）。
    - self_gated = True のアダプター（eBay）は常に呼ぶ。資格情報・有効化・dry-run の判断はアダプター自身が行い、
      欠けていれば通信 0 で NOT_CONFIGURED / BLOCKED の AdapterResult を返す。AdapterResult.records は機種レコード（listing / sold）。"""
    env = os.environ if env is None else env
    cfg = load_config()
    rows, errs, ran, details = [], {}, set(), {}
    for mid, spec in (cfg.get("markets") or {}).items():
        fn = _ADAPTERS.get(mid)
        if fn is None:
            continue
        gated = bool(getattr(fn, "self_gated", False))
        if not gated and (credential_state(spec, env) != CONFIGURED or not _enabled(spec, env)):
            continue
        ran.add(mid)
        try:
            got = fn(mid, env)
            if hasattr(got, "records") and hasattr(got, "status"):
                details[mid] = got
                rows.extend(r for r in got.records if isinstance(r, dict))
                if got.status == FAILED:
                    errs[mid] = got.reason
            elif isinstance(got, list):
                rows.extend(r for r in got if isinstance(r, dict))
            else:
                raise TypeError("adapter must return list or AdapterResult")
        except Exception as e:  # noqa: BLE001 - 失敗は FAILED として記録（空として扱わない）
            errs[mid] = f"adapter_error:{type(e).__name__}"
    return rows, errs, ran, details


def _ebay_fetch(market_id: str, env):
    """eBay のアダプター。import は呼ぶときに行う（ebay_adapter が先に import されても循環しない）。"""
    from src.research import ebay_adapter
    return ebay_adapter.fetch(market_id, env)


_ebay_fetch.self_gated = True          # 資格情報・有効化・dry-run の判断はアダプター自身（欠けていれば通信 0 の AdapterResult）


def register_default_adapters() -> None:
    """標準のアダプター（eBay）を登録する。登録しても、資格情報・有効化・dry-run が欠けていれば通信 0（NOT_CONFIGURED / BLOCKED）。"""
    register_adapter("ebay", _ebay_fetch)


register_default_adapters()
