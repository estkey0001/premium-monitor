"""全 canonical product の公式の状態（Wave 7e-1）。

全商品を **必ず 1 回ずつ** 分類し、公開は状態別の件数だけにする（個別の状態は非公開）。
既存の語彙（`evidence_gap.GAP_CAUSES`・`price_evidence` の区分）と互換にする。判断の順序は `official_gap_cause` と同じ。

- 確認済みの状態（VERIFIED_CURRENT / VERIFIED_DATED）の合計は、既存の「公式の確認済み」（`official_verified_coverage.verified`）と一致する。
  期限の考え方（`official_stale_days`）を変えない。この部品は判定を **読むだけ** で、確定・actionable・通知には影響しない
- RECHECK_MATCHED は「確認済みではない（確認が古い・設定値だけ）が、新しい再確認で型番・価格が一致した」商品（記録の更新待ち）。
  確認済みの件数には入れない
- 通信しない。他の部品（確定・通知・取得）に依存しない（`evidence_gap` と同じ）
"""
from __future__ import annotations

from src.research import evidence_gap as eg

VERIFIED_CURRENT = "VERIFIED_CURRENT"
VERIFIED_DATED = "VERIFIED_DATED"
RECHECK_MATCHED = "RECHECK_MATCHED"
SALE_ENDED = "SALE_ENDED"
SOURCE_BLOCKED = "SOURCE_BLOCKED"
SOURCE_NOT_REGISTERED = "SOURCE_NOT_REGISTERED"
IDENTITY_NOT_MATCHED = "IDENTITY_NOT_MATCHED"
PAGE_CHANGED = "PAGE_CHANGED"
PRICE_CHANGED = "PRICE_CHANGED"
STALE = "STALE"
CONFIGURED_REFERENCE = "CONFIGURED_REFERENCE"
UNKNOWN = "UNKNOWN"

# 公開の集計のキー（この順。0 件でも必ず出す）
STATES = (VERIFIED_CURRENT, VERIFIED_DATED, RECHECK_MATCHED, SALE_ENDED, SOURCE_BLOCKED, SOURCE_NOT_REGISTERED,
          IDENTITY_NOT_MATCHED, PAGE_CHANGED, PRICE_CHANGED, STALE, CONFIGURED_REFERENCE, UNKNOWN)
VERIFIED_STATES = frozenset({VERIFIED_CURRENT, VERIFIED_DATED})

# 既存の原因の語彙 → 状態（互換の対応表）
_FROM_GAP = {
    eg.SALE_ENDED: SALE_ENDED,
    eg.SOURCE_NOT_IMPLEMENTED: SOURCE_NOT_REGISTERED,
    eg.SOURCE_BLOCKED: SOURCE_BLOCKED,
    eg.IDENTITY_NOT_MATCHED: IDENTITY_NOT_MATCHED,
    eg.PAGE_CHANGED: PAGE_CHANGED,
    eg.PRICE_CHANGED: PRICE_CHANGED,
    eg.RECHECK_MATCHED: RECHECK_MATCHED,
    eg.VERIFICATION_STALE: STALE,
    eg.CONFIGURED_PRICE_ONLY: CONFIGURED_REFERENCE,
    eg.PRICE_NOT_FOUND: UNKNOWN,
    eg.UNKNOWN_CAUSE: UNKNOWN,
}
_EV_CURRENT, _EV_DATED = "VERIFIED_CURRENT", "VERIFIED_DATED"


def official_state_of(*, evidence, meta) -> str:
    """商品 1 件の公式の状態（12 状態のどれか 1 つ）。壊れた入力は UNKNOWN（例外にしない）。

    **確認済み（evidence が VERIFIED_CURRENT / VERIFIED_DATED）を最初に判定する**。既存の「公式の確認済み」の件数（`price_evidence.PROFIT_ELIGIBLE`
    の商品数）と、確認済みの状態の合計を必ず一致させるため（別の旗で確認済みの数が変わらない）。それ以外は `evidence_gap.official_gap_cause` と
    同じ順序（販売終了 → 同一性が未決 → 取得元が未登録 → 同一性が確認できない → 遮断 → ページの変更 → 価格の変化 → 再確認で一致 →
    確認が古い → 設定値だけ → 不明）。
    """
    if str(evidence or "") in (_EV_CURRENT, _EV_DATED):
        return str(evidence)                                  # 確認済み（不足の原因ではない）
    try:
        cause = eg.official_gap_cause(evidence=evidence, meta=meta)
    except Exception:  # noqa: BLE001 - 分類できない商品は UNKNOWN（推測しない）
        return UNKNOWN
    return _FROM_GAP.get(cause, UNKNOWN)


def classify_products(products, msrp_evidence, official_meta) -> dict:
    """全商品の状態（商品 ID → 状態）。products の各要素の `id` を 1 回ずつ分類する（重複した ID は 1 件として数える）。"""
    out: dict = {}
    ev_map = msrp_evidence if isinstance(msrp_evidence, dict) else {}
    meta_map = official_meta if isinstance(official_meta, dict) else {}
    for p in products or []:
        pid = str((p or {}).get("id") or "") if isinstance(p, dict) else ""
        if not pid or pid in out:
            continue
        out[pid] = official_state_of(evidence=ev_map.get(pid), meta=meta_map.get(pid))
    return out


def state_counts(states: dict, canonical_count: int | None = None) -> dict:
    """状態別の件数（12 状態すべてを 0 件でも出す）。`canonical_count` を渡すと、合計が一致しないとき例外にする（一致を保証する）。"""
    counts = {s: 0 for s in STATES}
    for st in (states or {}).values():
        counts[st if st in counts else UNKNOWN] += 1
    if canonical_count is not None and sum(counts.values()) != int(canonical_count):
        raise ValueError("official state total != canonical product count")
    return counts


def verified_total(counts: dict) -> int:
    """確認済みの状態の合計（既存の official_verified_coverage.verified と一致する）。"""
    return sum(int((counts or {}).get(s) or 0) for s in VERIFIED_STATES)
