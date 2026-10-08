"""今すぐ行動の通知のテストの共通の部品（Phase 19・20）。

判定は Phase 18 の正本（actionability.evaluate）の結果を、診断（opportunity_diagnostics）と同じ形にして使う。
run() は1回の実行（observe → prepare → send）を outbox の上で行い、Phase 19 の報告の形の件数を返す。
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from types import SimpleNamespace

from src.market import actionability as act
from src.market import opportunity_diagnostics as diag
from src.notifiers import adapters as ad
from src.notifiers import outbox as ob
from src.tcg.models import JST

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=JST)
SONY = "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"
RICOH = "https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001567&cat=002010"


def _view(pid, a, *, net=54870, roi=0.396, name=None):
    return SimpleNamespace(product_id=pid, product_name=name or pid, net_profit=net, roi=roi, action=a,
                           actionable=a.actionable)


def _diag(*views, prev=None):
    """診断の「今すぐ行動」（opportunity_diagnostics._actionability_summary）をそのまま作る。"""
    s = SimpleNamespace(eligible=list(views))
    acts = [{"product_id": v.product_id} for v in views if v.actionable]
    return {"actionability": diag._actionability_summary(s, acts, prev)}


def ps5(stock="IN_STOCK", checked=NOW - timedelta(minutes=30), url=SONY, now=NOW, profitable=True):
    return _view("prod_ps5_pro", act.evaluate(profitable=profitable, identity_ok=True, stock=stock,
                                              stock_checked_at=checked, buy_url=url, now=now),
                 name="PlayStation 5 Pro")


def lottery_event(start, end, *, status="active", checked=NOW - timedelta(hours=1), form=RICOH, **kw):
    ev = {"product_id": "prod_gr4_hdf", "product_code": "S0001567", "sale_method": "抽選販売", "status": status,
          "entry_start_at": start.isoformat(), "entry_end_at": end.isoformat() if end else "",
          "checked_at": checked.isoformat(), "entry_form_url": form}
    ev.update(kw)
    return ev


def gr4(event, now=NOW):
    return _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="LOTTERY", stock_checked_at=None,
                                              sale_method="抽選販売", event=event, now=now),
                 net=16200, roi=0.073, name="RICOH GR IV HDF")


def stock_gr4(now=NOW):
    return _view("prod_gr4_hdf", act.evaluate(profitable=True, identity_ok=True, stock="IN_STOCK",
                                              stock_checked_at=now - timedelta(minutes=10), buy_url=RICOH, now=now))


OPEN = lottery_event(NOW - timedelta(days=1), NOW + timedelta(days=2))
CLOSED = lottery_event(datetime(2026, 9, 25, 12, tzinfo=JST), datetime(2026, 9, 28, 12, tzinfo=JST), status="closed")


class SendFail(Exception):
    """偽の配信先の失敗（status: HTTP の状態。"connect" / "read" は通信の失敗）。"""

    def __init__(self, status=None, headers=None):
        super().__init__(str(status))
        self.status, self.headers = status, headers or {}


class FixtureAdapter(ad.ProviderAdapter):
    """テスト用の配信先（通信しない）。sender(record, idempotency_key) を呼ぶ。"""

    name = "fixture"

    def __init__(self, sender):
        def transport(payload, key):
            try:
                body = sender(payload, key)
            except SendFail as e:
                if e.status in ("connect", "read"):
                    raise ad.TransportError(e.status) from None
                return e.status, e.headers, {}
            return 200, {}, body if isinstance(body, dict) else {"id": f"fx-{key[-6:]}"}
        super().__init__(transport)

    def build_payload(self, record):
        return {"content": record.get("message") or ""}

    def delivery_id(self, status, headers, body):
        return str((body or {}).get("id") or "") if isinstance(body, dict) else ""


_ATTEMPTS = itertools.count(1)


def as_store(ledger):
    """None → None（基準日）、{} → 空の台帳、Phase 19 の台帳（商品の辞書）→ 今の形、今の形 → そのまま。"""
    if ledger is None:
        return None
    if isinstance(ledger, dict) and ledger.get("schema") == ob.SCHEMA:
        return ledger
    return ob.migrate({"products": dict(ledger)}) or ob.empty_store()


def run(d, ledger, now=NOW, *, dry_run=True, sender=None, dispatch_now=None, channels=None):
    """1回の実行。(報告, store) を返す。sender を渡すと本番の方式（偽の配信先1つ）で送る。"""
    store = as_store(ledger)
    baseline = store is None
    store = store or ob.empty_store()
    mode = ob.MODE_DRY if dry_run else ob.MODE_LIVE
    adapters = {"fixture": FixtureAdapter(sender)} if sender else {}
    chans = channels or (["fixture"] if sender or not dry_run else None)
    res = ob.cycle(store, d, now=now, mode=mode, baseline=baseline, attempt_id=f"t{next(_ATTEMPTS)}",
                   adapters=adapters, dispatch_now=dispatch_now, channels=chans)
    o, p, s = res["observe"], res["prepare"], res["send"]
    cands = []
    for nid in o["new_outbox"]:
        r = store["records"][nid]
        cands.append({"notification_id": nid, "product_id": r["product_id"], "product": r["product"],
                      "checked_at": r["checked_at"], "availability": r["availability_kind"],
                      "status": ob.an.TITLES.get(r["availability_kind"], ""), "transition": r["state_transition"],
                      "net_profit": r["net_profit"], "roi": r["roi"], "cta_url": r["action_url"],
                      "cta_label": r["cta_label"], "deadline": r["deadline"], "event_id": r["event_id"],
                      "dedupe_key": r["idempotency_key"], "message": r["message"], "channels": list(r["channels"]),
                      "dispatch_status": r["status"], "dry_run": dry_run, "confirmed": r["confirmed"],
                      "until_ms": r["until_ms"], "reasons": r["reasons"]})
    rep = {"is_baseline": baseline, "notification_candidates": o["notification_candidates"],
           "dedupe_suppressed": o["dedupe_suppressed"], "baseline_recorded": o["baseline_recorded"],
           "dispatch_planned": p["planned"], "dispatch_blocked": p["expired"] + p["cancelled"],
           "dispatch_expired": p["expired"], "dispatch_cancelled": p["cancelled"],
           "dispatch_not_configured": p["not_configured"], "dispatch_unknown": p["unknown"] + s.get("unknown", 0),
           "dispatch_sent": s.get("delivered", 0), "dispatch_failed": s.get("retryable", 0) + s.get("final", 0),
           "candidates": cands, "counts": res["counts"]}
    return rep, store


def seq(*diags, ledger=None):
    """続けて実行し、各回の報告を返す（最初の台帳は空 = 基準日ではない）。"""
    st = {} if ledger is None else ledger
    reps = []
    for d in diags:
        rep, st = run(d, st)
        reps.append(rep)
    return reps, st
