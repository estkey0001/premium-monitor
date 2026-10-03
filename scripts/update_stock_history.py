"""在庫の状態の履歴を更新する（在庫再開。UI Phase 4）。

前回の exports/stock_history/latest.json を読み、今回の実行で取得に成功した在庫の観測だけを反映して書き戻す。
- 公式商品: products の official_stock_status と official_stock_observed_at（在庫の根拠があった取得の時刻。
  価格の時刻とは別）。在庫の表示が取れなかった商品（時刻が空）は観測にしない
- TCG: exports/tcg/latest.json の events のうち、在庫の根拠があるものだけ
  - 在庫あり: 入荷・在庫復活の報告（IN_STOCK_EVENT_TYPES: 再入荷・EC 在庫復活・突発販売・コンビニ入荷）か、
    在庫の明示（sold_out=False / box_available=True）があり、今買える（AVAILABLE_NOW・古くない）もの
  - 予約キャンセル分・予約再開（RESERVATION_REOPEN）は在庫ありにせず、予約受付（RESERVATION）として記録する
  - 在庫切れ: SOLD_OUT か sold_out=True
  - 時刻は報告・告知の時刻（reported_at / published_at。時刻つきのものだけ）。取得した時刻（observed_at）は使わない
    （根拠が変わらないのに確認時刻が毎回進まないように）。発売日を過ぎただけの販売告知は在庫の根拠にしない
  （発売予定・抽選・予約は抽選・予約のページで扱う）

取得に失敗した商品・店は観測に入れないので、前回の状態と確認時刻はそのまま残る（新しく見せない）。

  python scripts/update_stock_history.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.market import stock_history as sh  # noqa: E402
from src.market import stock_state as ss  # noqa: E402
from src.tcg.models import JST  # noqa: E402

DB_PATH = ROOT / "data" / "premium_monitor.db"
TCG_PATH = ROOT / "exports" / "tcg" / "latest.json"
OUT_PATH = ROOT / "exports" / "stock_history" / "latest.json"


def official_observations(con) -> list[dict]:
    """公式商品の在庫の観測（在庫の根拠があったものだけ）。"""
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
    if "official_stock_observed_at" not in cols:
        return []
    urls = {}
    for r in con.execute("SELECT product_id, source_id, target_url FROM product_source_config "
                         "WHERE target_url IS NOT NULL AND target_url != ''"):
        urls[(r["product_id"], r["source_id"])] = r["target_url"]
    try:
        names = {r["id"]: r["name"] for r in con.execute("SELECT id, name FROM sources")}
    except sqlite3.Error:
        names = {}
    out = []
    for p in con.execute("SELECT * FROM products WHERE is_active = 1"):
        at = p["official_stock_observed_at"] or ""
        status = p["official_stock_status"] or ""
        if not at or not status:
            continue
        src = p["official_price_source"] or ""
        state = ss.LOTTERY if p["is_lottery"] else ss.stock_state(status)
        out.append({
            "key": f"official:{p['id']}:{src}", "product_id": p["id"], "product_name": p["name"],
            "category": p["genre"] or "", "store": names.get(src, src), "event_type": "",
            # 公式ストアの在庫表示（collector）と、人が公式ページで確認した在庫（VERIFIED_URLS）は、DB では区別できない
            # ので同じ種類として扱う（鮮度の期限はどちらも3時間）
            "source_type": "official_store", "state": state, "observed_at": at,
            "price": p["official_price"], "price_observed_at": p["official_price_updated_at"] or "",
            "url": urls.get((p["id"], src), ""), "source_url": urls.get((p["id"], src), ""),
        })
    return out


def _timed(v) -> str:
    """時刻つきの日時だけ（日付だけの値に時刻を足さない）。"""
    s = str(v or "").strip()
    return s if len(s) >= 16 and s[10] in "T " else ""


# 在庫ありの根拠になる TCG の報告の種類（許可するものだけを並べる。予約・抽選・発売告知は入れない）
IN_STOCK_EVENT_TYPES = ("RESTOCK", "ONLINE_RESTOCK", "GUERRILLA_SALE", "CONVENIENCE_STORE")
RESERVATION_EVENT_TYPES = ("RESERVATION_REOPEN",)
# 在庫の明示（sold_out=False / box_available=True）があっても在庫ありにしない種類（予約・抽選）
NEVER_IN_STOCK_EVENT_TYPES = ("PREORDER", "LOTTERY", "RESERVATION_REOPEN")


def tcg_observations(report: dict) -> list[dict]:
    """TCG の在庫の観測（在庫の根拠と報告時刻があるものだけ）。"""
    out = []
    for e in (report or {}).get("events") or []:
        if not isinstance(e, dict):
            continue
        status = e.get("status")
        if status == "SOLD_OUT" or e.get("sold_out") is True:
            state, at = ss.OUT_OF_STOCK, _timed(e.get("reported_at")) or _timed(e.get("published_at"))
        elif e.get("event_type") in RESERVATION_EVENT_TYPES and status == "AVAILABLE_NOW" and not e.get("stale"):
            # 予約の再開は在庫ありではない（予約受付として記録する）
            state, at = ss.RESERVATION, _timed(e.get("reported_at"))
        elif (status == "AVAILABLE_NOW" and not e.get("stale")
              and (e.get("event_type") in IN_STOCK_EVENT_TYPES
                   or (e.get("event_type") not in NEVER_IN_STOCK_EVENT_TYPES
                       and (e.get("sold_out") is False or e.get("box_available") is True)))):
            state, at = ss.IN_STOCK, _timed(e.get("reported_at"))
        else:
            continue
        name = str(e.get("product_name") or "")
        store = str(e.get("store") or "")
        if not name or not at:
            continue
        limit = e.get("purchase_limit") or (f"1人{e['packs_per_customer']}パックまで" if e.get("packs_per_customer") else "")
        out.append({
            "key": f"tcg:{store}:{e.get('product_type') or ''}:{name}", "product_id": str(e.get("product_id") or ""),
            "product_name": name, "category": "tcg", "store": store, "source_type": "tcg_event",
            "event_type": str(e.get("event_type") or ""), "variant": str(e.get("shrink_status") or e.get("product_type") or ""),
            "state": state, "observed_at": at,
            "price": e.get("price") if e.get("retail_price_basis") == "product_unit" else None,
            "price_observed_at": at if e.get("retail_price_basis") == "product_unit" else "",
            "url": e.get("canonical_url") or "", "source_url": e.get("source_url") or "",
            "purchase_limit": str(limit or ""),
        })
    return out


def main() -> int:
    now = datetime.now(tz=JST)
    history = sh.load(OUT_PATH)
    obs: list[dict] = []
    if DB_PATH.exists():
        con = sqlite3.connect(str(DB_PATH))
        try:
            obs += official_observations(con)
        finally:
            con.close()
    if TCG_PATH.exists():
        try:
            obs += tcg_observations(json.loads(TCG_PATH.read_text(encoding="utf-8")))
        except ValueError:
            pass
    before = len(history.get("events") or [])
    sh.apply(history, obs, now=now)
    sh.save(OUT_PATH, history)
    states: dict[str, int] = {}
    for e in history["entries"].values():
        states[e.get("state", "")] = states.get(e.get("state", ""), 0) + 1
    print(f"[update_stock_history] 観測 {len(obs)} 件 / 記録 {len(history['entries'])} 件 / "
          f"新しい遷移 {len(history['events']) - before} 件 / 状態 {states}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
