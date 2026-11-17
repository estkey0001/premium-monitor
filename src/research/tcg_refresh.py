# -*- coding: utf-8 -*-
"""TCG（ポケモンカード・ONE PIECE カード）の週次の更新を 1 コマンドで行う。

    python -m src.research.tcg_refresh                # dry-run（何も書かない。内容を表示するだけ）
    python -m src.research.tcg_refresh --apply        # 検証に通ったときだけ書く
    python -m src.research.tcg_refresh --dir <調査フォルダ> [--skip-recheck]

流れ（既存の部品を組み合わせる。作り直さない）:
  A 既存の自動収集（exports/tcg/lotteries.json。定時の CI が更新する）の状態を読む
  B 公式サイト・C 公式 SNS・D 集約サイトの調査結果（調査フォルダの research_tcg*.json。AI の調査は DISCOVERED まで）
  → 取得元ごとの結果の意味（FOUND / NO_EVENT_FOUND / CONFIRMED_NO_CURRENT_EVENT / BLOCKED / FAILED）
  → 一次情報での確認（weekly_import.finalize_tcg。商品・運営者・種別・応募期間）→ 重複排除 → 状態の再計算
  → 既存の公開イベントの再確認（polite 取得・日付を書き換えない）→ 週次の履歴・変化イベント・通知の dry-run。

守ること:
- 状態（OPEN など）は保存した値を使わず、必ず今の日時から `compute_lottery_status` で作り直す。AI の申告の状態は使わない。
- 集約サイト・検索の要約だけでは VERIFIED にしない（DISCOVERED のまま。非公開）。公開は一次情報で確認できたものだけ。
- 取得できなかった取得元を「イベント無し」にしない（BLOCKED / FAILED）。トップページだけは NO_EVENT_FOUND まで。
- 再確認は `verified_at` や `observed_at` を書き換えない（日付だけ新しくしない）。結果は週次の履歴に残す。
- 通知は送らない（検出の記録だけ）。本体の通知・outbox には接続しない。
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src.research import weekly_import as wi
from src.tcg.lottery import manual as M
from src.tcg.lottery import schema as S

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEEKLY_ROOT = PROJECT_ROOT / ".private" / "research" / "weekly"
EXPORT_DIR = PROJECT_ROOT / "exports" / "tcg"
HISTORY_FILE = "weekly_history.json"
CANDIDATE_FILE = "tcg_candidates.json"
HISTORY_KEEP = 26
BRANDS = ("POKEMON", "ONE_PIECE")
CHECK_MAX_AGE_DAYS = 8            # これより古い確認日の調査行は、現在の情報として扱わない
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# 公開側の状態（compute_lottery_status）のうち、「今、動ける」もの
LIVE_STATUSES = (S.L_OPEN, S.L_ENDING_SOON, S.L_UPCOMING)
# 状態の変化 → イベント名（既存の語彙で足りない分だけ、この週次の変化に限って使う）
CLOSED_STATES = frozenset({S.L_CLOSED, S.L_RESULT_PENDING, S.L_ENDED})

# 種別 → 既存の取り込み口（data/tcg_verified_lotteries.csv）で扱える種別。扱えない種別は候補のまま（公開しない）
PUBLISHABLE_KINDS = ("LOTTERY_OPEN", "LOTTERY_ENDING", "LOTTERY_UPCOMING", "PREORDER_OPEN", "RESERVATION_OPEN")


# ---- 商品の同一性 ----
_BRACKETS = re.compile(r"[\s　「」『』（）()【】\[\]・〜~、,.:：!！?？\"'“”‘’/／\-－―ー]")
_LINES = (  # 商品の種類（別の種類を同じ商品にしない）
    ("starter", ("スターターデッキ", "スタートデッキ", "スタートセット")),
    ("deck", ("構築済みデッキ", "デッキセット", "デッキビルド", "スペシャルデッキ")),
    ("cardset", ("カードセット", "コレクション")),
    ("extra", ("エクストラブースター",)),
    ("booster", ("ブースターパック",)),
    ("highclass", ("ハイクラスパック",)),
    ("special", ("スペシャルBOX", "スペシャルボックス")),
    ("expansion", ("拡張パック", "強化拡張パック")),
)
_BOX = re.compile(r"(?<![a-z])(1?box|ボックス|カートン|carton|20パック|30パック|1ボックス)", re.I)


def normalize_product(name: str) -> str:
    """商品名の比較用の形（全角半角・空白・括弧・記号を除く。小文字）。"""
    t = unicodedata.normalize("NFKC", str(name or ""))
    return _BRACKETS.sub("", t).lower()


def product_line(name: str) -> Optional[str]:
    t = unicodedata.normalize("NFKC", str(name or ""))
    for key, words in _LINES:
        if any(w in t for w in words):
            return key
    return None


def is_box(name: str) -> Optional[bool]:
    """BOX（箱）と明記されていれば True。パック単位と明記されていれば False。書かれていなければ None。"""
    t = unicodedata.normalize("NFKC", str(name or ""))
    if _BOX.search(t):
        return True
    if re.search(r"(?<!\d)(1|3|5)パック|パック単位|バラ(パック)?", t):
        return False
    return None


_EXTRA_TOKEN = re.compile(r"[A-Za-z]{2,3}-?\d{2}[A-Za-z]?(?![0-9])|[A-Za-z]{6,}|[一-龥]{1,3}の[一-龥]{1,3}")
_VOL = re.compile(r"vol\.?\s*(\d+)", re.I)
_ASCII_STOP = {"piece", "booster", "pokemon", "card", "game", "pack", "mega", "ONE".lower(), "ver", "version", "carton"}


def _ascii_words(name: str) -> set:
    """英語の語（4 文字以上）・巻数・型番。両方の名前に英語の語があるのに、片方が他方を含まなければ別商品。"""
    t = unicodedata.normalize("NFKC", str(name or ""))
    out = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", t)} - _ASCII_STOP
    out |= {"vol" + n for n in _VOL.findall(t)}
    out |= {w.lower().replace("-", "") for w in re.findall(r"\b[A-Za-z]{2,3}-?\d{2}[A-Za-z]?(?![0-9])", t)}
    return out
_EXTRA_STOP = {"piece", "booster", "pokemon", "celebration"}   # シリーズ名・一般語（これだけでは同じ商品にしない）。CELEBRATION は 30th と組で見る


def _specific(name: str) -> set:
    t = unicodedata.normalize("NFKC", str(name or ""))
    out = {w for w in wi._TOKEN_RE.findall(t) if not any(g in w for g in wi._GENERIC_WORDS)}
    for w in _EXTRA_TOKEN.findall(t):             # 型番（EB-05・OP-18）・英語の弾名（Heroines）・「神の支配」のような語
        k = w.lower().replace("-", "")
        if k not in _EXTRA_STOP:
            out.add(k)
    return {x.lower() if x.isascii() else x for x in out}


def same_product(a: str, b: str) -> bool:
    """同じ商品か。弾の名前・型番が重なり、商品の種類（拡張パック / カードセット等）と BOX・パックの別が食い違わないこと。
    シリーズ名・部分一致・曖昧な別名だけでは同一にしない。"""
    if normalize_product(a) and normalize_product(a) == normalize_product(b):
        return True
    if not (_specific(a) & _specific(b)):
        return False
    la, lb = product_line(a), product_line(b)
    if la and lb and la != lb:
        return False
    ba, bb = is_box(a), is_box(b)
    if ba is not None and bb is not None and ba != bb:
        return False
    xa, xb = _ascii_words(a), _ascii_words(b)
    if xa and xb and not (xa <= xb or xb <= xa):       # Terastal Festa と Terastal Charge・Vol1 と Vol2・30th Celebration と 30th Anniversary
        return False
    return True


def _day(value) -> str:
    m = _DATE.search(str(value or ""))
    return m.group(0) if m else ""


def _store_norm(ev: dict) -> str:
    return normalize_product(ev.get("store_name") or "")


def _etype(ev: dict) -> str:
    k = str(ev.get("event_type") or ev.get("kind") or "")
    if k.startswith("LOTTERY") or k in ("PURCHASE_RIGHT",):
        return "LOTTERY"
    if k in ("PREORDER_OPEN", "RESERVATION_OPEN", "PREORDER"):
        return "PREORDER"
    return k


def same_event(a: dict, b: dict) -> bool:
    """同じイベントか: 商品・小売（と店舗）・種別・応募の終わりの日。根拠の URL が同じでも同じ。"""
    ua, ub = wi._norm_url(a.get("source_url")), wi._norm_url(b.get("source_url"))
    if ua and ua == ub and _day(a.get("application_end") or a.get("application_end_date")) == _day(b.get("application_end") or b.get("application_end_date")):
        return True
    if str(a.get("tcg") or "").upper() != str(b.get("tcg") or "").upper():
        return False
    if str(a.get("retailer") or "").upper() != str(b.get("retailer") or "").upper():
        return False
    if _store_norm(a) != _store_norm(b):
        return False
    if _etype(a) != _etype(b):
        return False
    ea = _day(a.get("application_end") or a.get("application_end_date"))
    eb = _day(b.get("application_end") or b.get("application_end_date"))
    if not ea or ea != eb:
        return False
    return same_product(a.get("product_name"), b.get("product_name"))


# ---- 状態（今の日時から作り直す） ----
def _split(value) -> tuple[Optional[str], Optional[str]]:
    """日時の文字列 → (時刻つき ISO, 日付だけ)。時刻の記載が無ければ日付だけ（時刻を推測しない）。"""
    raw = str(value or "")
    tz = re.search(r"(Z|[+-]\d{2}:?\d{2})\s*$", raw)
    if tz and tz.group(1) not in ("+09:00", "+0900"):          # JST 以外の時刻は JST に直す（読めなければ使わない）
        try:
            dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00").replace(" ", "T", 1)).astimezone(JST)
            return dt.strftime("%Y-%m-%dT%H:%M:00+09:00"), None
        except ValueError:
            return None, None
    m = wi._ISO.search(raw)
    if not m:
        return None, None
    if m.group(2):
        return f"{m.group(1)}T{m.group(2)}:00+09:00", None
    return None, m.group(1)


def status_event(ev: dict) -> dict:
    """候補・調査行の日程 → compute_lottery_status が読む形（時刻つきは *_at、日付だけは *_date）。"""
    out: dict = {}
    for src_key, at_key, date_key in (
        ("application_start", "application_start", "application_start_date"),
        ("application_end", "application_end", "application_end_date"),
        ("winner_announcement", "winner_announcement_at", "winner_announcement_date"),
        ("purchase_start", "purchase_start", "purchase_start_date"),
        ("purchase_end", "purchase_end", "purchase_end_date"),
    ):
        raw = ev.get(src_key) if src_key in ev else ev.get(at_key)
        at, day = _split(raw)
        if at is None and day is None:
            raw2 = ev.get(date_key)
            at, day = _split(raw2)
        out[at_key], out[date_key] = at, day
    return out


def derive_status(ev: dict, now: datetime) -> str:
    return S.compute_lottery_status(status_event(ev), now)


# ---- 調査結果の読み込み ----
def load_research(research_dir: Path) -> tuple[dict, list[dict], list[str]]:
    """調査フォルダの research_tcg*.json（A・B・C の分担分）を 1 つにまとめる。(research, verifications, files)。
    イベントの中の verification（運営者自身の公式ページを開いた結果）は、既存の裏取りと同じ形に直す。"""
    sources: list[dict] = []
    events: list[dict] = []
    gaps: list[str] = []
    files: list[str] = []
    for f in sorted(research_dir.glob("research_tcg*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        files.append(f.name)
        sources += [dict(s, _file=f.name) for s in d.get("source_results") or [] if isinstance(s, dict)]
        events += [dict(e, _file=f.name) for e in d.get("events") or [] if isinstance(e, dict)]
        gaps += [str(x) for x in d.get("not_investigated") or []]
    verifications = wi.load_verifications(research_dir)
    for ev in events:
        v = ev.get("verification")
        if isinstance(v, dict) and v.get("primary_page_url"):
            verifications.append(dict(v, _retailer=ev.get("retailer"), _product=ev.get("product_name")))
    return {"source_results": sources, "events": events, "not_investigated": gaps}, verifications, files


def _check_date(ev: dict) -> Optional[str]:
    return _day(ev.get("checked_at"))


def stale_check_reason(ev: dict, research_date: str) -> Optional[str]:
    """調査行の確認日が、調査日より新しい・古すぎる行は現在の情報として扱わない。"""
    d = _check_date(ev)
    if not d:
        return "checked_at_missing"
    try:
        c = datetime.strptime(d, "%Y-%m-%d")
        r = datetime.strptime(research_date, "%Y-%m-%d")
    except ValueError:
        return "checked_at_unreadable"
    if c > r:
        return "checked_at_in_future"
    if (r - c).days > CHECK_MAX_AGE_DAYS:
        return "checked_at_too_old"
    return None


# ---- 候補（Step 6 の項目） ----
VERIFIED, DISCOVERED, DUPLICATE, EXPIRED = "VERIFIED", "DISCOVERED", "DUPLICATE", "EXPIRED"


def candidate_record(item: dict, now: datetime, *, research_date: str, existing: list[dict]) -> dict:
    """調査の 1 行 → 候補の記録。未登録の商品でも DISCOVERED にできる（正本への登録を前提にしない）。"""
    ev = item["event"]
    eff = item.get("effective") or ev
    fc = item["final_class"]
    reasons = list(item.get("reasons") or [])
    stale = stale_check_reason(ev, research_date)
    if stale:
        reasons.append(stale)
    if fc == wi.VERIFIED_C and not stale:
        vstatus = VERIFIED
    elif fc == wi.DUPLICATE_EXISTING:
        vstatus = DUPLICATE
    elif fc == wi.STALE_C:
        vstatus = EXPIRED
    else:
        vstatus = DISCOVERED
    status = derive_status(eff, now)
    ver = item.get("verification") or {}
    if vstatus == VERIFIED and (ver.get("verdict") != "PRIMARY_VERIFIED" or str(ver.get("page_fetch_status") or "").upper() != "OK"):
        vstatus = DISCOVERED                                            # 運営者自身のページ本文での確認が無い行は公開しない（AI の日付のままにしない）
        reasons.append("no_page_level_verification")
    if vstatus == VERIFIED and status in (S.L_ENDED, S.L_UNKNOWN, S.L_CLOSED):
        vstatus = EXPIRED if status in (S.L_ENDED, S.L_CLOSED) else DISCOVERED       # 日程が読めなければ公開しない
        reasons.append("status_" + status.lower())
    kind = str(ev.get("kind") or "")
    if vstatus == VERIFIED and kind not in PUBLISHABLE_KINDS:
        vstatus = DISCOVERED
        reasons.append("event_type_not_publishable")
    c = item.get("classification") or {}
    probe = {"tcg": str(ev.get("tcg") or "").upper(), "retailer": _retailer_key(ev.get("retailer")), "store_name": ev.get("store_name"),
             "event_type": kind, "application_end": eff.get("application_end"), "product_name": eff.get("product_name") or ev.get("product_name"),
             "source_url": eff.get("source_url") or ev.get("source_url")}
    dup_of = next((e.get("lottery_id") or e.get("source_url") for e in existing if same_event(probe, e)), None)
    if vstatus == VERIFIED and dup_of:
        vstatus = DUPLICATE
        reasons.append("same_event_already_public")
    return {
        "tcg": str(ev.get("tcg") or "").upper(),
        "product_name_raw": ev.get("product_name"),
        "normalized_product_name": normalize_product(eff.get("product_name") or ev.get("product_name")),
        "retailer": ev.get("retailer"), "store": ev.get("store_name"), "region": "JP",
        "event_type": kind, "application_start": eff.get("application_start"), "application_end": eff.get("application_end"),
        "winner_announcement": eff.get("winner_announcement"), "purchase_start": eff.get("purchase_start"),
        "purchase_end": eff.get("purchase_end"), "release_date": ev.get("release_date"), "retail_price": eff.get("retail_price"),
        "eligibility": eff.get("eligibility") or ev.get("eligibility"), "requirements": ev.get("requirements"),
        "source_url": eff.get("source_url") or ev.get("source_url"), "source_type": ev.get("source_type"),
        "discovered_at": f"{research_date} JST", "checked_at": ev.get("checked_at"),
        "verification_status": vstatus, "confidence": ev.get("confidence"),
        "derived_status": status, "reasons": sorted(set(reasons)),
        "evidence_kind": c.get("evidence_kind"), "duplicate_of": dup_of,
    }


# ---- 取得元ごとの結果 ----
def _keys_of(entry: dict) -> list[str]:
    return [key for key, _l, words in wi.TCG_REQUIRED_SOURCES if any(w in str(entry.get("source") or "") for w in words)]


def resolve_conflicts(source_results: list[dict]) -> tuple[list[dict], list[dict]]:
    """同じ取得元で「読めた（NO_EVENT_FOUND / CONFIRMED_NO_CURRENT_EVENT）」と「BLOCKED / FAILED」が食い違うとき、悪い側を採る。
    （別の URL が読めただけで、遮断された本体を「イベント無し」にしない。FOUND は実際にイベントを読んだ証拠なので残す。）"""
    by_key: dict[str, list[dict]] = {}
    for e in source_results:
        for k in _keys_of(e):
            by_key.setdefault(k, []).append(e)
    drop: set = set()
    conflicts = []
    for k, es in by_key.items():
        states = [wi.normalize_source_result(e) for e in es]
        if wi.FOUND in states or not any(s in wi.UNREACHABLE_STATES for s in states):
            continue
        weak = [id(e) for e, s in zip(es, states) if s in (wi.NO_EVENT_FOUND, wi.CONFIRMED_NO_CURRENT_EVENT)]
        if weak:
            drop |= set(weak)
            conflicts.append({"key": k, "dropped_results": len(weak), "kept": sorted({s for s in states if s in wi.UNREACHABLE_STATES})})
    kept = []
    for e in source_results:
        if id(e) in drop:
            continue
        if wi.normalize_source_result(e) in wi.UNREACHABLE_STATES:
            mates = [x for k in _keys_of(e) for x in by_key.get(k, []) if id(x) in drop]
            if mates and not wi._documented_gap(e):
                m = mates[0]
                e = dict(e)
                e["reason"] = str(e.get("reason") or "").strip() or "自動収集が遮断・到達不能と判定"
                e["alternative_source"] = str(e.get("alternative_source") or "").strip() or str(m.get("source") or "")[:120]
                e["alternative_finding"] = str(e.get("alternative_finding") or "").strip() or (
                    f"別の経路では {wi.normalize_source_result(m)}（{str(m.get('reason') or '本文を確認')[:150]}）。遮断された本体は読めていない")
        kept.append(e)
    return kept, conflicts


def source_report(source_results: list[dict]) -> dict:
    """17 の必須ソースの結果。RAW（本文を読めた）と ACCOUNTED（結果を理由つきで分類できた）を分ける。"""
    source_results, conflicts = resolve_conflicts(source_results)
    cov = wi.coverage(source_results)
    per = cov["per_source"]
    c = cov["counts"]
    return {
        "sources_total": cov["required_sources"],
        "sources_checked": sum(1 for v in per.values() if v != wi.NOT_RESEARCHED),
        "sources_found": c[wi.FOUND],
        "sources_no_event_found": c[wi.NO_EVENT_FOUND],
        "sources_confirmed_no_current_event": c[wi.CONFIRMED_NO_CURRENT_EVENT],
        "sources_blocked": c[wi.BLOCKED],
        "sources_failed": c[wi.FAILED],
        "sources_not_researched": c[wi.NOT_RESEARCHED],
        "raw_read_coverage_pct": cov["coverage_pct"], "accounted_coverage_pct": cov["accounted_pct"],
        "per_source": per, "gaps": cov["gaps"], "verdict": cov["verdict"], "conflicts": conflicts,
    }


# ---- A: 既存の決定論的な収集（定時の CI）の結果を、取得元の結果に直す ----
def collector_source_results(path: Path = EXPORT_DIR / "lottery_sources.json", *, research_date: str = "") -> list[dict]:
    """自動収集が最近（CHECK_MAX_AGE_DAYS 日以内）に実際に読んだ取得元だけを、調査の結果と同じ形にする。
    監視していない取得元（SOURCE_NOT_MONITORED）・確認日が古い取得元・確認日時が読めない取得元は含めない（読んでいないものを読んだことにしない）。
    HEALTHY かつ受付中あり → FOUND。読めたが受付中が無い → NO_EVENT_FOUND（一覧を読んだだけで「イベントが無い」とは確定しない）。"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for s in d.get("sources") or []:
        if not isinstance(s, dict) or s.get("state") == "SOURCE_NOT_MONITORED":
            continue
        checked = _day(s.get("last_checked"))
        if not checked or not research_date:
            continue
        try:
            age = (datetime.strptime(research_date, "%Y-%m-%d") - datetime.strptime(checked, "%Y-%m-%d")).days
        except ValueError:
            continue
        if age < 0 or age > CHECK_MAX_AGE_DAYS:
            continue
        health, state = str(s.get("health") or ""), str(s.get("state") or "")
        # 遮断・到達不能を先に判定する（health が OK_NO_EVENTS でも、本体が遮断なら読めていない = BLOCKED。遮断を「イベント無し」にしない）
        if s.get("blocked") or health == "BLOCKED" or state == "SOURCE_BLOCKED":
            res = "BLOCKED"
        elif health == "FAILED" or state == "SOURCE_UNREACHABLE" or s.get("unreachable"):
            res = "FAILED"
        elif health == "HEALTHY" and (s.get("active_lotteries") or 0) > 0:
            res = "FOUND"
        elif health in ("HEALTHY", "OK_NO_EVENTS") and s.get("last_success"):
            res = "NO_EVENT_FOUND"
        else:
            continue
        if not s.get("adapter") and res not in ("BLOCKED", "FAILED"):
            continue                         # 読む部品が無い取得元の「イベント無し」は採らない。遮断・到達不能の証拠だけ採る
        urls = " ".join(str(s.get(k) or "") for k in ("official_url", "news_url", "lottery_url"))
        out.append({"source": f"{s.get('retailer')}（自動収集 {s.get('source_id')}） {urls}", "result": res,
                    "url": s.get("news_url") or s.get("official_url"), "checked_at": str(s.get("last_checked") or "")[:19] + " JST",
                    "reason": str(s.get("error") or "")[:300], "_collector": True})
    return out


# ---- 既存の公開イベントの再確認 ----
def _mentions_date(text: str, iso: str) -> bool:
    m = _DATE.search(iso or "")
    if not m:
        return False
    y, mo, d = (int(x) for x in m.group(0).split("-"))
    t = unicodedata.normalize("NFKC", text)
    pats = (f"{y}-{mo:02d}-{d:02d}", f"{y}/{mo}/{d}", f"{y}/{mo:02d}/{d:02d}", f"{y}年{mo}月{d}日", f"{mo}/{d}", f"{mo}月{d}日", f"{mo:02d}/{d:02d}")
    # 数字の途中で一致させない（11/2 が 11/21 に、1月5日 が 11月5日 に一致しない）
    return any(re.search(r"(?<![0-9/月年])" + re.escape(p) + r"(?![0-9])", t) for p in pats)


def _csv_status_event(r: dict) -> dict:
    return {"application_start": r.get("application_start"), "application_end": r.get("application_end"),
            "winner_announcement": r.get("winner_announcement_at"), "purchase_start": r.get("purchase_start"), "purchase_end": r.get("purchase_end")}


def csv_events(rows: list[dict]) -> list[dict]:
    """手動 CSV の既存行 → 重複判定の形（lotteries.json に取り込まれる前でも、既存行と同じイベントを二重にしない）。"""
    return [{"lottery_id": "csv:" + str(r.get("source_url") or ""), "tcg": str(r.get("tcg") or "").upper(),
             "retailer": str(r.get("retailer") or "").upper(), "store_name": r.get("store_name"), "event_type": r.get("event_type") or "LOTTERY",
             "application_end": r.get("application_end"), "product_name": r.get("product"), "source_url": r.get("source_url")} for r in rows]


def public_rows(csv_path: Path = M.MANUAL_CSV) -> list[dict]:
    if not csv_path.exists():
        return []
    return list(csv.DictReader(csv_path.open(encoding="utf-8", newline="")))


def recheck_public(rows: list[dict], fetch: Callable[[str], tuple], now: datetime) -> list[dict]:
    """既存の公開イベント（手動確認の行）の根拠ページをもう一度読み、商品名と応募の終わりの日が今もあるかを確かめる。
    結果は RECONFIRMED / PAGE_CHANGED / FETCH_FAILED。CSV の日付は書き換えない（日付だけ新しくしない）。"""
    out = []
    for r in rows:
        if derive_status(_csv_status_event(r), now) in (S.L_ENDED,):        # 終わった行は毎週取り直さない
            continue
        url = (r.get("source_url") or "").strip()
        base = {"retailer": r.get("retailer"), "product": r.get("product"), "source_url": url,
                "application_end": r.get("application_end"), "checked_at": now.isoformat(timespec="seconds")}
        if not url:
            out.append(dict(base, result="FETCH_FAILED", reason="no_url"))
            continue
        try:
            html, err = fetch(url)
        except Exception as e:  # noqa: BLE001
            html, err = None, type(e).__name__
        if not html:
            out.append(dict(base, result="FETCH_FAILED", reason=err or "fetch_failed"))
            continue
        text = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", html))
        text = unicodedata.normalize("NFKC", text)
        toks = {x for x in _specific(r.get("product")) if x}
        hit = {x for x in toks if x in text.lower() or x in text}
        product_ok = len(hit) >= min(2, len(toks)) and bool(hit)
        date_ok = _mentions_date(text, r.get("application_end") or "")
        res = "RECONFIRMED" if (product_ok and date_ok) else "PAGE_CHANGED"
        out.append(dict(base, result=res, reason="" if res == "RECONFIRMED" else
                        ("product_not_found" if not product_ok else "application_end_not_found")))
    return out


# ---- 公開イベントの一覧と変化 ----
def load_public_events(path: Path = EXPORT_DIR / "lotteries.json") -> list[dict]:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [i for i in d.get("items") or [] if isinstance(i, dict)]


def public_snapshot(events: list[dict], now: datetime) -> list[dict]:
    """公開イベントごとに、今の日時から状態を再計算して記録する（保存済みの状態は使わない）。"""
    out = []
    for e in events:
        out.append({"key": e.get("lottery_id") or "|".join(str(e.get(k) or "") for k in ("tcg", "retailer", "product_name", "application_end")),
                    "tcg": e.get("tcg"), "retailer": e.get("retailer"), "store": e.get("store_name"),
                    "product": e.get("product_name"), "event_type": e.get("event_type"),
                    "application_end": e.get("application_end") or e.get("application_end_date"),
                    "status": derive_status(e, now)})
    return out


def diff_events(prev: Optional[list[dict]], cur: list[dict]) -> list[dict]:
    """前回の週次の記録と今回の公開イベントを比べ、変化を既存の語彙で表す。前回が無ければ NEW_EVENT は出さない（基準が無い）。"""
    if prev is None:
        return []
    before = {p["key"]: p for p in prev}
    out = []
    for c in cur:
        p = before.get(c["key"])
        base = {"key": c["key"], "tcg": c["tcg"], "retailer": c["retailer"], "product": c["product"], "event_type": c["event_type"]}
        if p is None:
            if c["status"] in LIVE_STATUSES:          # 現れた時点で終わっているもの・日程不明のものは「新規」にしない
                out.append(dict(base, type="NEW_EVENT", to=c["status"]))
            continue
        a, b = p["status"], c["status"]
        if a == b:
            continue
        if b == S.L_WINNER_PURCHASE_PERIOD:
            t = "PURCHASE_PERIOD_STARTED"
        elif b == S.L_WINNER_ANNOUNCED:
            t = "WINNER_ANNOUNCED"
        elif a == S.L_UPCOMING and b in (S.L_OPEN, S.L_ENDING_SOON):
            t = "UPCOMING_TO_OPEN"
        elif a == S.L_OPEN and b == S.L_ENDING_SOON:
            t = "OPEN_TO_ENDING"
        elif a in (S.L_OPEN, S.L_ENDING_SOON, S.L_UPCOMING) and b in CLOSED_STATES:
            t = "OPEN_TO_CLOSED"
        else:
            continue
        out.append(dict(base, type=t, **{"from": a, "to": b}))
    return out


def notification_dry_run(events: list[dict], snapshot: list[dict]) -> dict:
    """通知の候補を検出するだけ（外部へは送らない。本体の通知・outbox には接続しない）。"""
    kinds = {"NEW_EVENT": "新規の抽選・予約", "UPCOMING_TO_OPEN": "受付開始", "OPEN_TO_ENDING": "締切間近",
             "WINNER_ANNOUNCED": "当選発表", "PURCHASE_PERIOD_STARTED": "購入期間の開始"}
    items = [dict(e, label=kinds[e["type"]]) for e in events if e["type"] in kinds]
    seen = {i["key"] for i in items}
    for s in snapshot:               # 今、締切間近のもの（変化として出ていなくても検出する）
        if s["status"] == S.L_ENDING_SOON and s["key"] not in seen:
            items.append({"type": "ENDING_SOON_NOW", "label": "締切間近", "key": s["key"], "tcg": s["tcg"], "retailer": s["retailer"],
                          "product": s["product"], "event_type": s["event_type"]})
    return {"mode": "DRY_RUN", "would_notify": len(items), "sent": 0, "items": items,
            "note": "通知は送信しない（検出の記録だけ。本体の通知・outbox には接続しない）"}


def brand_status_counts(snapshot: list[dict]) -> dict:
    out = {b: {"open": 0, "ending_soon": 0, "upcoming": 0} for b in BRANDS}
    for s in snapshot:
        b = str(s.get("tcg") or "").upper()
        if b not in out:
            continue
        st = s["status"]
        if st == S.L_OPEN:
            out[b]["open"] += 1
        elif st == S.L_ENDING_SOON:
            out[b]["ending_soon"] += 1
        elif st == S.L_UPCOMING:
            out[b]["upcoming"] += 1
    return out


# ---- 本体 ----
def refresh(research_dir: Path, date: str, *, now: datetime, fetch: Optional[Callable] = None, recheck: bool = True,
            csv_path: Path = M.MANUAL_CSV, public_events: Optional[list[dict]] = None,
            prev_history: Optional[dict] = None, collector_results: Optional[list] = None) -> dict:
    """調査結果を整理し、書き込む内容を作る（ここでは何も書かない）。"""
    research, verifications, files = load_research(research_dir)
    research["source_results"] = research["source_results"] + (collector_results if collector_results is not None
                                                               else collector_source_results(research_date=date))
    pub = public_events if public_events is not None else load_public_events()
    collectors = wi.collector_retailers({"items": pub})
    items = wi.finalize_tcg(research, verifications, now=now, covered=wi.covered_urls({"items": pub}), collectors=collectors)
    existing = list(pub) + csv_events(public_rows(csv_path))
    cands: list[dict] = []
    for it in items:
        rec = candidate_record(it, now, research_date=date, existing=existing)
        cands.append(rec)
        if rec["verification_status"] == VERIFIED:       # 同じ調査の中の重複も、先に出たほうだけを残す
            existing.append(dict(it.get("effective") or it["event"], tcg=rec["tcg"], retailer=_retailer_key(rec["retailer"]),
                                 event_type=rec["event_type"], lottery_id="research:" + rec["normalized_product_name"][:40]))
    # 既存の CSV の取り込み口に流すのは VERIFIED の行だけ
    seen = wi._existing_keys(csv_path)
    new_rows: list[dict] = []
    new_checks: list[str] = []
    for it, rec in zip(items, cands):
        if rec["verification_status"] != VERIFIED:
            continue
        eff = it["effective"]
        row = wi.csv_row_for(eff, it["classification"], now=now)
        checked_day = _check_date(it["event"])
        # 確認日は根拠のページを読んだ日。実行日時を verified_at にしない（ページを読んだ時刻より新しい日時を付けない）
        row["verified_at"] = checked_day
        row["notes"] = row["notes"] + f" 取り込みの実行: {now.isoformat(timespec='seconds')}。"
        k = (wi._norm_url(row["source_url"]), row["application_end"][:10])
        if k in seen:
            rec["verification_status"] = DUPLICATE
            rec["reasons"] = sorted(set(rec["reasons"]) | {"already_in_manual_csv"})
            continue
        seen.add(k)
        new_rows.append(row)
        new_checks.append(checked_day)
    rechecks = recheck_public(public_rows(csv_path), fetch, now) if (recheck and fetch) else []
    snap_pub = public_snapshot(pub, now)
    prev_snaps = (prev_history or {}).get("snapshots") or []
    prev = None
    for s in reversed(prev_snaps):
        if s.get("research_date") != date:
            prev = s.get("public_events")
            break
    events = diff_events(prev, snap_pub)
    src = source_report(research["source_results"])
    by = {k: sum(1 for c in cands if c["verification_status"] == k) for k in (VERIFIED, DISCOVERED, DUPLICATE, EXPIRED)}
    brand_counts = {b: {k: sum(1 for c in cands if c["tcg"] == b and c["verification_status"] == k) for k in (VERIFIED, DISCOVERED, DUPLICATE, EXPIRED)} for b in BRANDS}
    return {"date": date, "now": now, "files": files, "sources": src, "candidates": cands, "new_rows": new_rows, "rechecks": rechecks,
            "public_snapshot": snap_pub, "events": events, "by_status": by, "brand_counts": brand_counts,
            "brand_live": brand_status_counts(snap_pub), "notification": notification_dry_run(events, snap_pub),
            "not_investigated": research["not_investigated"], "items": items, "source_entries": research["source_results"], "new_row_checks": new_checks,
            "csv_events": csv_events(public_rows(csv_path))}


def quality_checks(state: dict) -> dict:
    """公開してよいかの品質の数（すべて 0 であること）。出力した行・元の取得結果から数え直す（候補の判定を使い回さない）。"""
    now = state["now"]
    rows = state["new_rows"]
    expired_open = sum(1 for r in rows if derive_status(_csv_status_event(r) | {"winner_announcement": r.get("winner_announcement_at")}, now)
                       in (S.L_ENDED, S.L_UNKNOWN, S.L_CLOSED))
    # 新規の行ごとに、根拠が一次情報のドメインで、人の確認を名乗らず、運営者自身のページでの確認（PRIMARY_VERIFIED）に由来するか
    verified_items = [it for it, c in zip(state["items"], state["candidates"]) if c["verification_status"] == VERIFIED]
    unverified_as_verified = sum(1 for r in rows if str(r.get("human_confirmed")).lower() == "true" or not wi.primary_evidence(r.get("source_url") or ""))
    unverified_as_verified += sum(1 for it in verified_items if (it.get("verification") or {}).get("verdict") != "PRIMARY_VERIFIED")
    pool = [{"tcg": s["tcg"], "retailer": s["retailer"], "store_name": s["store"], "event_type": s["event_type"],
             "application_end": s["application_end"], "product_name": s["product"], "source_url": ""} for s in state["public_snapshot"]]
    # 手動 CSV の行は、公開済みの一覧に既に載っていれば同じ記録（二重ではない）。まだ載っていない行だけを加える
    pool += [c for c in state.get("csv_events") or [] if not any(same_event(c, p) for p in pool)]
    pool += [{"tcg": r["tcg"], "retailer": r["retailer"], "store_name": r["store_name"], "event_type": r["event_type"],
              "application_end": r["application_end"], "product_name": r["product"], "source_url": r["source_url"]} for r in rows]
    dups = sum(1 for i in range(len(pool)) for j in range(i + 1, len(pool)) if same_event(pool[i], pool[j]))
    wrong_identity = sum(1 for it in verified_items if it.get("verification") and
                         not same_product(it["event"].get("product_name"), (it.get("effective") or {}).get("product_name")))
    # verified_at は根拠のページを読んだ日と同じであること（実行日時・未来の日時にしない）
    checks = state.get("new_row_checks") or []
    fake_checked = sum(1 for r, d in zip(rows, checks) if not d or _day(r.get("verified_at")) != d)
    fake_checked += sum(1 for r in state["rechecks"] if r["result"] == "RECONFIRMED" and not r.get("checked_at"))
    # 読めた（FOUND / NO_EVENT_FOUND / CONFIRMED）と報告した取得元に、読めた根拠の行が 1 つもない・自動収集が遮断の理由を持つ
    failure_as_no_event = 0
    for key, _l, words in wi.TCG_REQUIRED_SOURCES:
        final = state["sources"]["per_source"].get(key)
        if final not in wi.RESEARCHED_STATES:
            continue
        mine = [s for s in state.get("source_entries") or [] if any(w in str(s.get("source") or "") for w in words)]
        read = [s for s in mine if wi.normalize_source_result(s) in wi.RESEARCHED_STATES]
        if not read or all(s.get("_collector") and (s.get("reason") or "").strip() for s in read):
            failure_as_no_event += 1
    return {"expired_shown_open": expired_open, "unverified_shown_verified": unverified_as_verified, "duplicate_event": dups,
            "wrong_product_identity": wrong_identity, "fake_checked_at": fake_checked, "source_failure_treated_no_event": failure_as_no_event}


def validate(state: dict) -> list[str]:
    """書き込む前の検証。1 つでもあれば書かない。"""
    problems: list[str] = []
    if not state["files"]:
        problems.append("調査ファイル（research_tcg*.json）が無い")
    if state["sources"]["sources_checked"] == 0:
        problems.append("結果が分かった取得元が 0 件")
    for r in state["new_rows"]:
        ev, err = M._row_to_event(r)
        if err or ev is None:
            problems.append(f"取り込み行が読めない: {r.get('product')} ({err})")
        elif str(r.get("human_confirmed")).lower() == "true":
            problems.append(f"AI が人の確認を名乗っている: {r.get('product')}")
        elif not (wi.primary_evidence(r.get("source_url") or "")):
            problems.append(f"一次情報でない根拠: {r.get('product')}")
    keys = [(wi._norm_url(r["source_url"]), r["application_end"][:10]) for r in state["new_rows"]]
    if len(keys) != len(set(keys)):
        problems.append("新規の行どうしで重複がある")
    for c in state["candidates"]:
        if c["verification_status"] == VERIFIED and c["derived_status"] in (S.L_ENDED, S.L_UNKNOWN):
            problems.append(f"期限切れ・日程不明が VERIFIED: {c['product_name_raw']}")
    for k, v in quality_checks(state).items():
        if v:
            problems.append(f"品質: {k} = {v}（0 でなければ書かない）")
    return problems


def _retailer_key(name) -> str:
    n = str(name or "")
    return next((v for k, v in wi.RETAILER_KEYS.items() if k in n), n.upper())


def history_snapshot(state: dict) -> dict:
    s = state["sources"]
    return {
        "research_date": state["date"], "generated_at": state["now"].isoformat(timespec="seconds"),
        "source_results": s["per_source"],
        "coverage": {k: s[k] for k in ("sources_total", "sources_checked", "sources_found", "sources_no_event_found",
                                       "sources_confirmed_no_current_event", "sources_blocked", "sources_failed",
                                       "raw_read_coverage_pct", "accounted_coverage_pct")},
        "counts": {"discovered": len(state["candidates"]), "verified_new": len(state["new_rows"]),
                   "unverified": state["by_status"][DISCOVERED], "duplicate": state["by_status"][DUPLICATE],
                   "expired": state["by_status"][EXPIRED], "status_changed": len(state["events"])},
        "by_brand": state["brand_counts"], "live_by_brand": state["brand_live"],
        "public_events": state["public_snapshot"], "events": state["events"],
        "rechecks": [{k: r[k] for k in ("retailer", "product", "result", "reason", "checked_at")} for r in state["rechecks"]],
        "notification_dry_run": {k: state["notification"][k] for k in ("mode", "would_notify", "sent")},
        "quality": quality_checks(state),
    }


def merge_history(old: Optional[dict], snap: dict) -> dict:
    """同じ日の再実行は上書き。直近 HISTORY_KEEP 件だけ残す。"""
    snaps = [s for s in ((old or {}).get("snapshots") or []) if s.get("research_date") != snap["research_date"]]
    snaps.append(snap)
    snaps.sort(key=lambda s: s["research_date"])
    return {"schema": "tcg_weekly_history_v1", "snapshots": snaps[-HISTORY_KEEP:]}


def write_all(state: dict, research_dir: Path, *, export_dir: Path = EXPORT_DIR, csv_path: Path = M.MANUAL_CSV) -> list[str]:
    """検証に通ったときだけ呼ぶ。新規の VERIFIED の行を CSV の末尾に追記し、週次の履歴と非公開の候補を書く。"""
    from src.utils.atomic_write import write_json_atomic
    written: list[str] = []
    rows = state["new_rows"]
    if rows:
        import io
        raw = csv_path.read_bytes() if csv_path.exists() else b""
        nl = b"\r\n" if b"\r\n" in raw else b"\n"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=M.CSV_COLUMNS, lineterminator="\n")
        for r in rows:
            w.writerow(r)
        with open(csv_path, "ab") as f:
            if raw and not raw.endswith(nl):
                f.write(nl)
            f.write(buf.getvalue().replace("\n", nl.decode()).encode("utf-8"))
        written.append(str(csv_path.relative_to(PROJECT_ROOT)) if csv_path.is_absolute() and PROJECT_ROOT in csv_path.parents else csv_path.name)
    hp = export_dir / HISTORY_FILE
    try:
        old = json.loads(hp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    export_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(hp, merge_history(old, history_snapshot(state)))
    written.append("exports/tcg/" + HISTORY_FILE)
    # 未確認の候補は非公開（.private 配下）にだけ書く。--dir が .private の外なら、既定の場所へ書く
    cdir = research_dir if ".private" in research_dir.resolve().parts else WEEKLY_ROOT / state["date"]
    cdir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(cdir / CANDIDATE_FILE, {"research_date": state["date"], "candidates": state["candidates"]})
    return written


def summarize(state: dict, *, apply: bool, written: Optional[list[str]], problems: list[str]) -> dict:
    s = state["sources"]
    rc = state["rechecks"]
    return {
        "mode": "APPLY" if apply else "DRY_RUN", "research_date": state["date"], "research_files": state["files"],
        "sources_total": s["sources_total"], "sources_checked": s["sources_checked"], "sources_found": s["sources_found"],
        "sources_no_event_found": s["sources_no_event_found"], "sources_confirmed_no_current_event": s["sources_confirmed_no_current_event"],
        "sources_blocked": s["sources_blocked"], "sources_failed": s["sources_failed"], "sources_not_researched": s["sources_not_researched"],
        "raw_read_coverage_pct": s["raw_read_coverage_pct"], "accounted_coverage_pct": s["accounted_coverage_pct"],
        "per_source": s["per_source"],
        "candidates_discovered": len(state["candidates"]), "verified_new": len(state["new_rows"]),
        "existing_duplicates": state["by_status"][DUPLICATE], "unverified": state["by_status"][DISCOVERED],
        "expired": state["by_status"][EXPIRED], "status_changed": len(state["events"]),
        "by_brand": state["brand_counts"], "live_by_brand": state["brand_live"],
        "rechecks": {"total": len(rc), "reconfirmed": sum(1 for r in rc if r["result"] == "RECONFIRMED"),
                     "page_changed": sum(1 for r in rc if r["result"] == "PAGE_CHANGED"),
                     "fetch_failed": sum(1 for r in rc if r["result"] == "FETCH_FAILED")},
        "events": state["events"], "notification_dry_run": {k: state["notification"][k] for k in ("mode", "would_notify", "sent")},
        "public_files_affected": written if apply else ["(dry-run: 書かない) data/tcg_verified_lotteries.csv", "(dry-run: 書かない) exports/tcg/" + HISTORY_FILE],
        "quality": quality_checks(state), "validation_problems": problems,
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="TCG の週次の更新。既定は dry-run（何も書かない）")
    ap.add_argument("--apply", action="store_true", help="検証に通ったときだけ、CSV・週次の履歴・非公開の候補へ書き込む")
    ap.add_argument("--dir", help="調査フォルダ（既定: .private/research/weekly/<今日>）")
    ap.add_argument("--skip-recheck", action="store_true", help="既存の公開イベントの再確認（polite 取得）を省く")
    a = ap.parse_args(argv)
    now = datetime.now(JST)
    date = now.strftime("%Y-%m-%d")
    target = Path(a.dir) if a.dir else WEEKLY_ROOT / date
    if _DATE.fullmatch(target.name):
        date = target.name
    fetch = None
    if not a.skip_recheck:
        from scripts.recheck_official import _fetch as fetch  # noqa: PLC0415（polite 取得。robots・間隔・正直な UA）
    try:
        hist = json.loads((EXPORT_DIR / HISTORY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hist = None
    state = refresh(target, date, now=now, fetch=fetch, recheck=not a.skip_recheck, prev_history=hist)
    problems = validate(state)
    written = write_all(state, target) if (a.apply and not problems) else None
    out = summarize(state, apply=a.apply, written=written, problems=problems)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=list))
    if problems:
        return 1
    s = state["sources"]
    return 0 if not (s["sources_blocked"] or s["sources_failed"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
