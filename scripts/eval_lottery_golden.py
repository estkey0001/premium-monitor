#!/usr/bin/env python3
"""抽選の収集の品質（再現率・抽出精度・検出遅延）を出す。通信しない・何も書かない（標準出力だけ）。

  python scripts/eval_lottery_golden.py                 # data/golden/lottery_golden.json と exports/tcg の記録
  python scripts/eval_lottery_golden.py --golden PATH

記録 = exports/tcg/lotteries.json の items（応募条件つき）＋ exports/tcg/lottery_history.json（最初に記録した時刻）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.tcg.lottery.evaluation import (  # noqa: E402
    detection_latency, evaluate, evaluate_texts, kpis, load_golden, verifier_class,
)


def _items(path: Path) -> list[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [i for i in (d.get("items") or []) if isinstance(i, dict)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", type=Path, default=None)
    ap.add_argument("--exports", type=Path, default=ROOT / "exports" / "tcg")
    ap.add_argument("--texts", type=Path, default=None,
                    help="公式ページの本文の置き場（非公開。1 行目が URL・2 行目から本文の .txt）。指定すると今の抽出器の精度も測る")
    a = ap.parse_args()
    current = _items(a.exports / "lotteries.json")
    history = _items(a.exports / "lottery_history.json")
    seen = {h.get("lottery_id"): h for h in history}
    # 今の記録に、履歴の最初に記録した時刻を足す。今の記録に無い過去の抽選は履歴の行をそのまま使う（照合の対象を広げる）
    records = [{**seen.get(r.get("lottery_id"), {}), **r} for r in current]
    ids = {r.get("lottery_id") for r in current}
    records += [h for h in history if h.get("lottery_id") not in ids]
    golden = load_golden(a.golden)
    out = {"records": len(records), "history_latency": detection_latency(history),
           "history_latency_excluding_onboarding_day": detection_latency(history, exclude_backlog=True)}
    lot = json.loads((a.exports / "lotteries.json").read_text(encoding="utf-8")) if (a.exports / "lotteries.json").exists() else {}
    out["kpi"] = kpis(current, history, generated_at=str(lot.get("generated_at") or ""))
    if golden:
        # 人が確かめた正解と、AI が確かめた正解（人の確認待ち）は混ぜずに別々に出す
        out["golden_eval"] = {f"{c}:{sp}": evaluate(gs, records)
                              for c in ("human", "ai_unreviewed") for sp in ("tuning", "holdout", "holdout2")
                              for gs in [[g for g in golden if verifier_class(g) == c and g.get("split", "tuning") == sp
                                          or (g.get("kind") == "non_lottery" and verifier_class(g) == c and sp == "tuning")]] if gs}
        if a.texts:
            texts = {}
            for f in sorted(Path(a.texts).glob("*.txt")):
                url, _, body = f.read_text(encoding="utf-8").partition("\n")
                texts[url.strip()] = body
            # 確認者（人 / AI）と、修正に使ったか（tuning / holdout）で分けて出す
            out["extraction_eval"] = {f"{c}:{sp}": evaluate_texts(gs, texts)
                                      for c in ("human", "ai_unreviewed") for sp in ("tuning", "holdout", "holdout2")
                                      for gs in [[g for g in golden if verifier_class(g) == c and g.get("split", "tuning") == sp]] if gs}
    else:
        out["golden_eval"] = None
        out["note"] = "ゴールデンセットが無い（data/golden/lottery_golden.json）。再現率・抽出精度は測れない"
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
