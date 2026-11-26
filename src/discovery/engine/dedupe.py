"""既存の情報との重複（G8）。URL の正規化は src/tcg/lottery/pipeline.normalize_url。

既存として見るもの:
- exports/tcg/lotteries.json の items（自動収集の抽選・日程つき）と announcements（日程の無い告知）
- data/tcg_verified_lotteries.csv（人が確認した抽選）の source_url / entry_url
- exports/discovery/event_candidates.json のエンジン以外の候補の official_url（既存の発見と二重にしない）
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENGINE_ORIGIN = "discovery_engine"


def _norm(u: str) -> str:
    from src.tcg.lottery.pipeline import normalize_url
    return normalize_url(u or "")


class ExistingIndex:
    def __init__(self):
        self.by_url: dict[str, str] = {}             # 正規化 URL → 何と重複するか（lottery:<id> / csv / candidate:<id>）

    def add(self, url: str, ref: str) -> None:
        k = _norm(url)
        if k and k not in self.by_url:
            self.by_url[k] = ref

    def find(self, url: str) -> Optional[str]:
        return self.by_url.get(_norm(url))


def build_index(*, lotteries_path: Optional[Path] = None, manual_csv: Optional[Path] = None,
                event_store: Optional[dict] = None) -> ExistingIndex:
    idx = ExistingIndex()
    lp = Path(lotteries_path) if lotteries_path else PROJECT_ROOT / "exports" / "tcg" / "lotteries.json"
    try:
        lots = json.loads(lp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lots = {}
    for it in (lots or {}).get("items") or []:
        if isinstance(it, dict):
            for u in [it.get("source_url"), it.get("entry_url")] + list(it.get("source_urls") or []):
                if u:
                    idx.add(u, f"lottery:{it.get('lottery_id') or ''}")
    for an in (lots or {}).get("announcements") or []:
        if isinstance(an, dict) and an.get("source_url"):
            idx.add(an["source_url"], "announcement")
    cp = Path(manual_csv) if manual_csv else PROJECT_ROOT / "data" / "tcg_verified_lotteries.csv"
    try:
        with cp.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                for k in ("source_url", "entry_url"):
                    if row.get(k):
                        idx.add(row[k], "manual_csv")
    except OSError:
        pass
    for cid, rec in ((event_store or {}).get("candidates") or {}).items():
        if isinstance(rec, dict) and rec.get("origin") != ENGINE_ORIGIN and rec.get("official_url"):
            idx.add(rec["official_url"], f"candidate:{cid}")
    return idx
