"""二次流通（フリマ・オークション）の取得可否の管理と、公式 API アダプターの受け皿。

方針（新しい仕組みは作らない。camera_routes / camera_refresh の入口を広げるだけ）:
- 市場ごとに AVAILABLE / PARTIAL / BLOCKED / FAILED / NOT_SUPPORTED を持つ。取得できなかった市場は「未取得」で、
  「出品なし・成約なし」とは書かない（listing_rows / sold_rows は未取得なら None。0 は「取れたが 0 件」だけ）。
- 検索結果のスクレイピングはしない（config/secondary_markets.yaml の policy）。データは (1) 公式 API のアダプター、
  (2) 調査員が個別の根拠 URL つきで読んだ行（research_camera_*.json）だけから入る。どちらも既存の行の検査を通る。
- 資格情報は環境変数の名前だけを設定に持ち、値は読んでも出力・保存しない。未登録は NOT_CONFIGURED（安全に BLOCKED）。
- アダプターは register_adapter() で後から差し込める。登録が無い間は、キーがあっても adapter_not_implemented の BLOCKED。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from src.research import camera_routes as cr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "secondary_markets.yaml"

AVAILABLE, PARTIAL, BLOCKED, FAILED, NOT_SUPPORTED = "AVAILABLE", "PARTIAL", "BLOCKED", "FAILED", "NOT_SUPPORTED"
STATUSES = (AVAILABLE, PARTIAL, BLOCKED, FAILED, NOT_SUPPORTED)
NOT_CONFIGURED, CONFIGURED, NOT_REQUIRED = "NOT_CONFIGURED", "CONFIGURED", "NOT_REQUIRED"
_NO_DATA = (BLOCKED, FAILED, NOT_SUPPORTED)                     # 取得できていない（0 件ではなく未取得）

# アダプター: (market_id, env) -> list[dict]（research_camera_*.json の行と同じ形）。例外・None は FAILED
_ADAPTERS: dict[str, Callable] = {}


def register_adapter(market_id: str, fn: Callable) -> None:
    _ADAPTERS[market_id] = fn


def clear_adapters() -> None:
    _ADAPTERS.clear()


def load_config() -> dict:
    import yaml
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def _has(env, names) -> bool:
    return bool(names) and all(str((env or {}).get(n) or "").strip() for n in names)


def credential_state(spec: dict, env=None) -> str:
    """資格情報の状態だけを返す（値は返さない）。API が無い市場は NOT_REQUIRED。"""
    env = os.environ if env is None else env
    api = spec.get("official_api") or {}
    if not api.get("exists"):
        return NOT_REQUIRED
    return CONFIGURED if _has(env, api.get("credential_env") or []) else NOT_CONFIGURED


def _enabled(spec: dict, env) -> bool:
    var = (spec.get("official_api") or {}).get("enable_var")
    return bool(var) and str((env or {}).get(var) or "").lower() == "true"


def market_status(market_id: str, spec: dict, env=None, *, rows: Optional[dict] = None, adapter_error: Optional[str] = None,
                  adapters_ran: Optional[set] = None) -> dict:
    """1 市場の取得状態。rows = {"listing": n, "sold": n}（行が実際に採用できた件数）。"""
    env = os.environ if env is None else env
    cred = credential_state(spec, env)
    status, reason = spec.get("status", BLOCKED), spec.get("reason", "unknown")
    la, sa = spec.get("listing_access", BLOCKED), spec.get("sold_access", BLOCKED)
    api = spec.get("official_api") or {}
    if api.get("exists"):
        if cred == NOT_CONFIGURED:
            status, reason, la, sa = BLOCKED, "official_api_not_configured", BLOCKED, BLOCKED
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
    return {"market": market_id, "label": spec.get("label"), "priority": spec.get("priority"), "status": status, "reason": reason,
            "listing_access": la, "sold_access": sa, "credentials": cred, "api_error": adapter_error, "checked_on": spec.get("checked_on"),
            "official_api": api.get("name"), "evidence": spec.get("evidence"),
            # 未取得は None（0 件と区別する）
            "listing_rows": int(nl or 0) if got_listing else None, "sold_rows": int(ns or 0) if got_sold else None}


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
                  adapters_ran: Optional[set] = None) -> list[dict]:
    """全市場の取得状態＋手数料の状態。優先順位順。"""
    cfg = cfg or load_config()
    counts = count_rows(market)
    out = []
    for mid, spec in sorted((cfg.get("markets") or {}).items(), key=lambda kv: kv[1].get("priority", 99)):
        st = market_status(mid, spec, env, rows=counts.get(mid), adapter_error=(adapter_errors or {}).get(mid), adapters_ran=adapters_ran)
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
    """登録済みのアダプターを呼ぶ（キーが設定・有効のときだけ）。返り値: (行, {market: エラー理由}, 実際に呼んだ市場)。
    アダプターは失敗を例外で知らせる契約（失敗時に [] を返すと「取れたが 0 件」になる）。取得時刻 checked_at は行に必ず付けること。"""
    env = os.environ if env is None else env
    cfg = load_config()
    rows, errs, ran = [], {}, set()
    for mid, spec in (cfg.get("markets") or {}).items():
        if mid not in _ADAPTERS or credential_state(spec, env) != CONFIGURED or not _enabled(spec, env):
            continue
        ran.add(mid)
        try:
            got = _ADAPTERS[mid](mid, env)
            if not isinstance(got, list):
                raise TypeError("adapter must return list")
            rows.extend(r for r in got if isinstance(r, dict))
        except Exception as e:  # noqa: BLE001 - 失敗は FAILED として記録（空として扱わない）
            errs[mid] = f"adapter_error:{type(e).__name__}"
    return rows, errs, ran
