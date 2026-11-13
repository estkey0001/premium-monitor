"""週次リサーチ（Web 調査）の結果を Premium Monitor へ取り込む（暫定運用。24 時間の自動化の前の週 1 回の経路）。

流れ: 調査の JSON（`.private/research/weekly/<日付>/`。git 管理外）→ 検証 → 一次情報で確認できたものと候補に振り分け →
公開データへ取り込み（既存の取り込み口: TCG は data/tcg_verified_lotteries.csv）。AI の調査結果は DISCOVERED で、
取り込めるのは決定論的な検証を通ったものだけ。

- **一次情報の証拠**: メーカー・店舗の公式ドメイン（`manual.OFFICIAL_DOMAINS` / `STORE_PRIMARY_DOMAINS`。運営者の証拠つき）の
  ページで確認したものだけ。集約サイト・運営者を確認できないサイトは UNVERIFIED（`candidates.json`＝非公開に置く）。
  同じ非公式ページを別の AI が読み直しても検証にならない（整合性の確認）。
- **状態は AI の申告を使わない**: 日時から決定論的に出す（応募期限を過ぎたものは取り込まない）。日付だけで時刻が無い締切は
  その日の 23:59 とみなし、注記に残す。
- **ソースごとの結果の意味**: FOUND / CONFIRMED_NO_CURRENT_EVENT（一覧ページを見て検索もした上で現在の対象が無いと確認）/
  NO_EVENT_FOUND（今回の範囲では見つからなかった。「存在しない」ではない）/ BLOCKED / FAILED / NOT_RESEARCHED。
  トップページを見ただけの「無し」は NO_EVENT_FOUND に落とす。
- **網羅度（coverage）**: 必須ソースのうち調べられた割合。必須ソースの大半が FAILED / BLOCKED なのに成功にしない
  （RESEARCH_INCOMPLETE）。
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.tcg.lottery import manual as M
from src.tcg.lottery.schema import LT_LOTTERY, LT_PREORDER
from src.tcg.models import TCG_TYPES, parse_dt

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---- ソースごとの結果の意味 ----
FOUND = "FOUND"
CONFIRMED_NO_CURRENT_EVENT = "CONFIRMED_NO_CURRENT_EVENT"
NO_EVENT_FOUND = "NO_EVENT_FOUND"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
NOT_RESEARCHED = "NOT_RESEARCHED"
SOURCE_STATES = (FOUND, CONFIRMED_NO_CURRENT_EVENT, NO_EVENT_FOUND, BLOCKED, FAILED, NOT_RESEARCHED)
RESEARCHED_STATES = frozenset({FOUND, CONFIRMED_NO_CURRENT_EVENT, NO_EVENT_FOUND})   # 取得して読めた
SUCCESS_MIN_COVERAGE = 0.8

# TCG の必須ソース（キー, 表示名, 名前に含まれる語）。同じキーの複数の行は、いちばん強い結果を採る
TCG_REQUIRED_SOURCES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("pokemon_official", "ポケモンカード公式", ("pokemon-card.com",)),
    ("onepiece_official", "ONE PIECE カードゲーム公式", ("onepiece-cardgame.com",)),
    ("pokemon_center", "ポケモンセンターオンライン", ("ポケモンセンター",)),
    ("premium_bandai", "プレミアムバンダイ", ("プレミアムバンダイ", "p-bandai")),
    ("geo", "GEO", ("GEO",)),
    ("tsutaya", "TSUTAYA", ("TSUTAYA",)),
    ("aeon", "イオン", ("イオン",)),
    ("toysrus", "トイザらス", ("トイザらス",)),
    ("biccamera", "ビックカメラ", ("ビックカメラ",)),
    ("yodobashi", "ヨドバシ", ("ヨドバシ",)),
    ("joshin", "Joshin", ("Joshin", "ジョーシン")),
    ("edion", "エディオン", ("エディオン",)),
    ("yamada", "ヤマダ", ("ヤマダ",)),
    ("sevennet", "セブンネット", ("セブンネット",)),
    ("amazon", "Amazon", ("Amazon",)),
    ("rakuten", "楽天系公式販売店", ("楽天",)),
    ("card_shops", "主要カードショップ", ("カードラボ", "晴れる屋", "ホビーステーション")),
)
_RANK = {FOUND: 5, CONFIRMED_NO_CURRENT_EVENT: 4, NO_EVENT_FOUND: 3, BLOCKED: 2, FAILED: 1, NOT_RESEARCHED: 0}


def normalize_source_result(entry: dict) -> str:
    """調査の 1 ソースの結果を、意味の定まった状態へ直す。

    「無し」の申告（NO_CURRENT_EVENT / CHECKED など）は、`evidence`（一覧ページを見た・検索を行った）が無ければ
    NO_EVENT_FOUND に落とす。トップページを見ただけで「現在イベント無し」と確認したことにしない。
    """
    raw = str((entry or {}).get("result") or "").strip().upper()
    if raw in (FOUND, BLOCKED, FAILED, NOT_RESEARCHED):
        return raw
    if raw in ("NO_CURRENT_EVENT", CONFIRMED_NO_CURRENT_EVENT, NO_EVENT_FOUND, "CHECKED"):
        ev = (entry or {}).get("evidence")
        confirmed = (
            raw in ("NO_CURRENT_EVENT", CONFIRMED_NO_CURRENT_EVENT)
            and isinstance(ev, dict) and bool(ev.get("event_list_pages")) and _int(ev.get("searches")) is not None
        )
        return CONFIRMED_NO_CURRENT_EVENT if confirmed else NO_EVENT_FOUND
    return FAILED if raw else NOT_RESEARCHED


def coverage(source_results: list[dict], required=TCG_REQUIRED_SOURCES) -> dict:
    """必須ソースの網羅度。必須ソースに結果が無ければ NOT_RESEARCHED。"""
    best: dict[str, str] = {}
    for e in source_results or []:
        name = str(e.get("source") or "")
        state = normalize_source_result(e)
        for key, _label, words in required:
            if any(w in name for w in words) and _RANK[state] > _RANK.get(best.get(key, NOT_RESEARCHED), 0):
                best[key] = state
    per = {key: best.get(key, NOT_RESEARCHED) for key, _l, _w in required}
    counts = {s: sum(1 for v in per.values() if v == s) for s in SOURCE_STATES}
    total = len(per)
    researched = sum(counts[s] for s in RESEARCHED_STATES)
    pct = round(100.0 * researched / total, 2) if total else 0.0
    return {
        "required_sources": total, "per_source": per, "counts": counts,
        "researched": researched, "coverage_pct": pct,
        "confirmed_scope_pct": round(100.0 * (counts[FOUND] + counts[CONFIRMED_NO_CURRENT_EVENT]) / total, 2) if total else 0.0,
        "verdict": "RESEARCH_SUCCESS" if total and researched / total >= SUCCESS_MIN_COVERAGE else "RESEARCH_INCOMPLETE",
        "note": "NO_EVENT_FOUND は『今回の範囲では見つからなかった』で、『イベントが存在しない』ではない（recall の評価で混同しない）",
    }


# ---- TCG のイベントの検証と取り込み ----
RETAILER_KEYS = {
    "カードラボ": "CARD_LABO", "エディオン": "EDION", "EDION": "EDION", "麦わらストア": "MUGIWARA_STORE",
    "ポケモンセンターオンライン": "POKEMON_CENTER_ONLINE", "ホビーステーション": "HOBBY_STATION",
    "福福トレカ": "FUKUFUKU_TOREKA", "三洋堂書店": "SANYODO", "駿河屋": "SURUGAYA",
}
_ISO = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?")
_URL = re.compile(r"https?://[^\s、，（）()「」]+")


def _first_url(text) -> str:
    m = _URL.search(str(text or ""))
    return m.group(0).rstrip(".,;") if m else ""


def _to_iso(value, *, end: bool) -> tuple[Optional[str], bool]:
    """調査の日時の文字列 → ISO 8601（JST）。日付だけなら始点 00:00・終点 23:59（時刻を推測した印を返す）。"""
    m = _ISO.search(str(value or ""))
    if not m:
        return None, False
    day, hm = m.group(1), m.group(2)
    assumed = hm is None
    hm = hm or ("23:59" if end else "00:00")
    return f"{day}T{hm}:00+09:00", assumed


def _host_of(url: str) -> str:
    """URL のホスト名（小文字）。http(s) だけ。通信しない（研究モジュールは取得・送信の部品を import しない規則）。"""
    m = re.match(r"https?://(?:[^/@?#]*@)?([^/:?#]+)", str(url or "").strip(), re.I)
    return m.group(1).lower() if m else ""


def _maker_hosts() -> set:
    """メーカーの公式ドメイン（既存の登録簿 official_price_validator.OFFICIAL_DOMAINS。カメラ・ゲーム等）。"""
    try:
        from src.market.official_price_validator import OFFICIAL_DOMAINS as D
        return {d for v in D.values() for d in v}
    except Exception:  # noqa: BLE001
        return set()


def primary_evidence(url: str) -> Optional[str]:
    """一次情報の根拠の種類（メーカー・店舗の公式ドメイン。ホスト名で判定し、URL の部分一致は使わない）。無ければ None。"""
    host = _host_of(url)
    if any(host == d or host.endswith("." + d) for d in ("amazon.co.jp", "rakuten.co.jp")):
        return None                                          # 出品者が多数のマーケットプレイスは、任意の店のページが一次情報にならない
    if M.is_official_url(url) or (host and any(host == d or host.endswith("." + d) for d in _maker_hosts())):
        return "official_domain"
    if M.is_store_primary_url(url):
        return "store_primary_domain"
    return None


def classify_event(ev: dict, now: datetime) -> dict:
    """調査の 1 件を、一次情報で確認できたもの（VERIFIED）か候補（UNVERIFIED / ENDED / INCOMPLETE）に振り分ける。

    AI の申告（classification / status / confidence）は使わない。根拠の URL の運営者・日時から決める。
    """
    reasons: list[str] = []
    # 根拠は「そのデータを読んだページ」（source_url）が一次情報であること。official_url（公式のトップ・一覧を添えただけのことが多い）や
    # 調査の VERIFIED の申告で救済しない（AI の申告は下げる方向にだけ使う）。
    url = _first_url(ev.get("source_url"))
    evidence = primary_evidence(url) if url else None
    if not evidence:
        reasons.append("no_primary_evidence")      # 集約サイト・運営者を確認できないサイト・検索の要約だけ
    # 調査の申告は「下げる」方向にだけ使う（調査自身が UNVERIFIED / STALE / DUPLICATE とした行は取り込まない）
    if str(ev.get("classification") or "").upper() in ("UNVERIFIED", "STALE", "DUPLICATE"):
        reasons.append("research_marked_" + str(ev.get("classification")).lower())
    tcg = str(ev.get("tcg") or "").upper()
    if tcg not in TCG_TYPES:
        reasons.append("not_tcg_target")
    product = str(ev.get("product_name") or "").strip()
    retailer_name = str(ev.get("retailer") or "").strip()
    key = next((v for k, v in RETAILER_KEYS.items() if k in retailer_name), "")
    if not product:
        reasons.append("missing_product")
    if not key:
        reasons.append("retailer_unmapped")
    start, s_assumed = _to_iso(ev.get("application_start"), end=False)
    end, e_assumed = _to_iso(ev.get("application_end"), end=True)
    if not start or not end:
        reasons.append("missing_application_dates")
    kind = str(ev.get("kind") or "")
    if kind.startswith("LOTTERY"):
        etype = LT_LOTTERY
    elif kind in ("PREORDER_OPEN", "RESERVATION_OPEN"):
        etype = LT_PREORDER
    else:
        etype = None
        reasons.append("event_type_unsupported")
    purchase_end, p_assumed = _to_iso(ev.get("purchase_end"), end=True)
    winner, w_assumed = _to_iso(ev.get("winner_announcement"), end=False)
    purchase_start, ps_assumed = _to_iso(ev.get("purchase_start"), end=False)
    ends = [parse_dt(d) for d in (end, purchase_end) if d and parse_dt(d)]
    if ends and max(ends) < now:
        reasons.append("ended")                      # 応募も購入期間も過ぎた（現在のイベントではない）
    decision = "VERIFIED" if not reasons else (
        "ENDED" if reasons == ["ended"] else
        "UNVERIFIED" if ("no_primary_evidence" in reasons or any(r.startswith("research_marked_") for r in reasons)) else "INCOMPLETE")
    return {
        "decision": decision, "reasons": reasons, "evidence_kind": evidence, "evidence_url": url or None,
        "retailer_key": key, "event_type": etype, "tcg": tcg,
        "application_start": start, "application_end": end, "winner_announcement_at": winner,
        "purchase_start": purchase_start, "purchase_end": purchase_end,
        "time_assumed": [n for n, f in (("application_start", s_assumed), ("application_end", e_assumed), ("winner_announcement", w_assumed and winner),
                                         ("purchase_start", ps_assumed and purchase_start), ("purchase_end", p_assumed)) if f],
    }


def _norm_text(s: str) -> str:
    return re.sub(r"[\s　「」『』（）()]", "", str(s or "")).lower()


def _norm_url(u: str) -> str:
    return str(u or "").strip().lower().rstrip("/")


def _existing_keys(csv_path: Path) -> set:
    keys = set()
    if csv_path.exists():
        for r in csv.DictReader(csv_path.open(encoding="utf-8", newline="")):
            keys.add((_norm_url(r.get("source_url")), (r.get("application_end") or "")[:10]))
    return keys


def csv_row_for(ev: dict, c: dict, *, now: datetime) -> dict:
    """検証済みの 1 件 → data/tcg_verified_lotteries.csv の行（人の確認は未了 = human_confirmed=false）。"""
    price = ev.get("retail_price")
    price = str(int(price)) if isinstance(price, (int, float)) and not isinstance(price, bool) else ""
    note = [f"一次情報: {c['evidence_kind']}（{c['evidence_url']}）の内容を週次リサーチで転記。人の確認は未了。"]
    if c["time_assumed"]:
        note.append("ページに時刻の記載が無い項目（" + "・".join(c["time_assumed"]) + "）は、開始 00:00・終了 23:59 とみなした。")
    row = {k: "" for k in M.CSV_COLUMNS}
    row.update(
        tcg=c["tcg"], product=str(ev["product_name"]).strip(), retailer=c["retailer_key"],
        retailer_name=str(ev.get("retailer") or "").split("（")[0].strip(), event_type=c["event_type"],
        store_specific="true" if ev.get("store_name") else "false", store_name=str(ev.get("store_name") or ""),
        application_start=c["application_start"], application_end=c["application_end"],
        winner_announcement_at=c["winner_announcement_at"] or "", purchase_start=c["purchase_start"] or "",
        purchase_end=c["purchase_end"] or "", retail_price=price,
        eligibility=str(ev.get("eligibility") or ev.get("requirements") or "")[:400],
        human_confirmed="false", source_url=c["evidence_url"], verified_at=now.isoformat(timespec="seconds"),
        verified_by="claude-code（週次リサーチ。AI が一次情報のページを読んで転記。人の確認は未了）",
        notes=" ".join(note),
    )
    return row


def covered_urls(lotteries: Optional[dict]) -> set:
    """既存の自動収集（exports/tcg/lotteries.json）が既にサイトに載せている根拠の URL。
    同じイベントを手動の CSV に重ねると、店舗名・商品名の表記の違いで統合されず重複して表示される。"""
    out = set()
    for it in (lotteries or {}).get("items") or []:
        for u in [it.get("source_url")] + list(it.get("source_urls") or []):
            if u:
                out.add(_norm_url(u))
    return out


def collector_retailers(lotteries: Optional[dict]) -> set:
    """既存の自動収集が取得元として扱っている小売のキー（その小売の告知は、収集が次の実行で拾う。手動の CSV に重ねない）。"""
    return {str(it.get("retailer") or "").upper() for it in (lotteries or {}).get("items") or [] if it.get("retailer")}


# TCG の候補の最終の区分
VERIFIED_C, UNVERIFIED_C, DUPLICATE_EXISTING, STALE_C, FAILED_VERIFICATION = (
    "VERIFIED", "UNVERIFIED", "DUPLICATE_EXISTING", "STALE", "FAILED_VERIFICATION")
FINAL_CLASSES = (VERIFIED_C, UNVERIFIED_C, DUPLICATE_EXISTING, STALE_C, FAILED_VERIFICATION)


def load_verifications(research_dir: Path) -> list[dict]:
    """第 2 段の裏取り（店自身の公式ページを開いた結果）。tcg_verify_*.json を、tcg_to_verify.json の番号で調査の行に結び付ける。"""
    mapping = {}
    mp = research_dir / "tcg_to_verify.json"
    if mp.exists():
        for m in json.loads(mp.read_text(encoding="utf-8")):
            mapping[m["n"]] = (m["retailer"], m["product"])
    out = []
    for f in sorted(research_dir.glob("tcg_verify_*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        rows = d if isinstance(d, list) else (d.get("events") or d.get("results") or [])
        for v in rows:
            if isinstance(v, dict) and v.get("n") in mapping:
                out.append(dict(v, _retailer=mapping[v["n"]][0], _product=mapping[v["n"]][1]))
    return out


_TOKEN_RE = re.compile(r"[ァ-ヶー]{4,}|[一-龥]{3,}|[A-Za-z]{2,}-?\d{2,3}|\d{2}th")
# シリーズ名・一般名詞（別商品でも共通する語。これだけの一致では同じ商品とみなさない）
_GENERIC_WORDS = ("カードゲーム", "ポケモン", "ワンピース", "パック", "デッキ", "ブースター", "スペシャル", "セット", "スタート", "エクストラ",
                  "拡張", "販売", "抽選", "予約", "カード", "ボックス")


def _same_product(a, b) -> bool:
    """調査の商品名とページの商品名が同じ商品らしいか。シリーズ名・一般名詞を除いた固有の語（弾の名前・型番）が 1 つ以上重なること。"""
    def specific(t):
        return {w for w in _TOKEN_RE.findall(str(t or "")) if not any(g in w for g in _GENERIC_WORDS)}
    return bool(specific(a) & specific(b))


def _price_of(text) -> Optional[int]:
    m = re.search(r"([\d,]{3,})\s*円", str(text or ""))
    return int(m.group(1).replace(",", "")) if m else None


def _effective_event(ev: dict, ver: dict) -> dict:
    """裏取りで店自身のページから読んだ事実で、調査の行の日程・商品・価格を置き換える（AI の日付を使わない）。"""
    pf = ver.get("page_facts") or {}
    e = dict(ev)
    url = ver.get("primary_page_url") or ""
    e.update(source_url=url, official_url=url, classification="VERIFIED")
    e["product_name"] = pf.get("product") or ev.get("product_name")
    for k in ("application_start", "application_end", "winner_announcement", "purchase_start", "purchase_end"):
        e[k] = pf.get(k)
    e["retail_price"] = _price_of(pf.get("price"))
    e["eligibility"] = pf.get("eligibility") or ev.get("eligibility")
    return e


def finalize_tcg(research: dict, verifications: list[dict], *, now: datetime, covered: set, collectors: set) -> list[dict]:
    """全候補を VERIFIED / UNVERIFIED / DUPLICATE_EXISTING / STALE / FAILED_VERIFICATION に整理する。

    1. 既存の自動収集が同じ URL を載せている → DUPLICATE_EXISTING（新規 CSV へ重ねない）
    2. 応募も購入期間も過ぎた → STALE（古い情報を現在のイベントにしない）
    3. 店自身のページでの裏取りがある: 一次情報（運営者の証拠つきのドメイン）で商品・日程を確認できた → VERIFIED。
       できなかった（開けない・告知が無い・運営者の証拠なし）→ FAILED_VERIFICATION
    4. 裏取りの無い行: 根拠のページが一次情報で、日程が揃うなら VERIFIED、集約サイトだけなら UNVERIFIED
    取り込み先が既存の収集の取得元（カードラボ・麦わらストアなど）の小売なら DUPLICATE_EXISTING（収集が拾う）。
    """
    groups: dict = {}
    for v in verifications:
        groups.setdefault((v["_retailer"], v["_product"]), []).append(v)
    by_key = {k: vs[0] for k, vs in groups.items()}
    conflicting = {k for k, vs in groups.items() if len({x.get("verdict") for x in vs}) > 1}
    out = []
    for ev in research.get("events") or []:
        ver = by_key.get((ev.get("retailer"), ev.get("product_name")))
        urls = {_norm_url(_first_url(ev.get(k))) for k in ("official_url", "source_url")}
        if ver and ver.get("primary_page_url"):
            urls.add(_norm_url(ver["primary_page_url"]))
        if ver and (ev.get("retailer"), ev.get("product_name")) in conflicting:
            ver = dict(ver, verdict="CONFLICT", page_fetch_status="CONFLICT")
        item = {"event": ev, "verification": ver, "effective": ev, "reasons": []}
        if any(u and u in covered for u in urls):
            item.update(final_class=DUPLICATE_EXISTING, reasons=["already_on_site_by_url"])
            out.append(item)
            continue
        eff = ev
        if ver:
            if ver.get("verdict") != "PRIMARY_VERIFIED":
                st = str(ver.get("page_fetch_status") or "").upper()
                item.update(final_class=FAILED_VERIFICATION,
                            reasons=["page_opened_but_not_confirmable" if st == "OK" else (st.lower() or "unverified")])
                out.append(item)
                continue
            eff = _effective_event(ev, ver)
            if not _same_product(ev.get("product_name"), eff.get("product_name")):
                item.update(final_class=FAILED_VERIFICATION, reasons=["product_mismatch"])
                out.append(item)
                continue
            op = (ver.get("operator_evidence") or {})
            if not (op.get("operator_name") and primary_evidence(eff["source_url"])):
                item.update(final_class=FAILED_VERIFICATION, reasons=["operator_evidence_missing_or_domain_not_registered"])
                out.append(item)
                continue
        c = classify_event(eff, now)
        item.update(effective=eff, classification=c)
        if c["decision"] == "ENDED":
            item.update(final_class=STALE_C, reasons=["ended"])
        elif c["decision"] == "VERIFIED" and c["retailer_key"] in collectors:
            item.update(final_class=DUPLICATE_EXISTING, reasons=["collector_covers_source"])
        elif c["decision"] == "VERIFIED":
            item.update(final_class=VERIFIED_C)
        else:
            item.update(final_class=UNVERIFIED_C, reasons=c["reasons"])
        out.append(item)
    return out


def import_tcg(research: dict, *, now: datetime, csv_path: Path = M.MANUAL_CSV, apply: bool = False,
               covered: Optional[set] = None, verifications: Optional[list] = None, collectors: Optional[set] = None) -> dict:
    """TCG の調査結果を 5 区分に整理し、新規に一次情報で確認できたものだけ CSV へ追記する（dry-run が既定）。"""
    seen = _existing_keys(csv_path)
    items = finalize_tcg(research, verifications or [], now=now, covered=covered or set(), collectors=collectors or set())
    verified, candidates, skipped_dup, already = [], [], 0, []
    new_rows: list[dict] = []
    counts = {k: 0 for k in FINAL_CLASSES}
    for it in items:
        ev, fc = it["event"], it["final_class"]
        counts[fc] += 1
        base = {"product_name": ev.get("product_name"), "retailer": ev.get("retailer"), "final_class": fc, "reasons": it["reasons"],
                "official_url": ev.get("official_url"), "source_url": ev.get("source_url"), "application_end": ev.get("application_end")}
        if fc == VERIFIED_C:
            row = csv_row_for(it["effective"], it["classification"], now=now)
            k = (_norm_url(row["source_url"]), row["application_end"][:10])
            if k in seen:
                skipped_dup += 1
                counts[fc] -= 1
                counts[DUPLICATE_EXISTING] += 1
                continue
            seen.add(k)
            new_rows.append(row)
            verified.append({"product": row["product"], "retailer": row["retailer"], "store": row["store_name"], "evidence": row["source_url"]})
        elif fc == DUPLICATE_EXISTING:
            already.append(base)
        else:
            candidates.append(base)
    if apply and new_rows:
        raw = csv_path.read_bytes() if csv_path.exists() else b""
        nl = b"\r\n" if b"\r\n" in raw else b"\n"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=M.CSV_COLUMNS, lineterminator="\n")
        for r in new_rows:
            w.writerow(r)
        with open(csv_path, "ab") as f:
            if raw and not raw.endswith(nl):
                f.write(nl)
            f.write(buf.getvalue().replace("\n", nl.decode()).encode("utf-8"))
    return {"verified": verified, "already_covered": already, "candidates": candidates, "duplicates_skipped": skipped_dup,
            "counts": counts, "applied": bool(apply and new_rows)}


# ---- iPhone の買取の比較（複数店舗・SKU ごと） ----
# 比較専用の公開データ（exports/iphone_buyback/iphone_buyback_comparison.json）を作る。利益エンジン・買取店マスタ（BUYBACK_SHOPS。
# 買取の変化の検知・通知に使われる）には入れない。正本に登録された商品（Duo 256GB）だけ identity=REGISTERED、
# 他は DISCOVERED（部品番号・正本登録待ち）の参考。BUY / ACTIONABLE とは言わない。
#
# 価格の扱い（掲載の最高値を捨てない）:
#  - highest_listed: 掲載の最高値（条件が新品未開封の行の中の最高。色減額の有無・鮮度に関わらず表示・保存する）
#  - highest_executable: 掲載の最高値が十分に確認できたときだけ。確認できる = 取得できた店・SKU と条件が完全に一致・
#    色減額が分かる・ページの更新日が FRESH（または UNKNOWN_FRESHNESS を許す設定）・外れ値でない（または人が確認済み）
#  - 外れ値（2 位より outlier.rate を超えて高い）: OUTLIER_REVIEW。最高値は表示・保存するが利益計算に使わず、
#    次点を「最高の実行可能価格」とは呼ばない（次点での計算は参考として別の名前で出す）
IPHONE_TARGET_MODELS = ("iPhone Duo", "iPhone 18 Pro Max", "iPhone 18 Pro")        # 長い名前を先に（18 Pro が Pro Max に一致しないように）
IPHONE_CAPACITIES = ("256GB", "512GB", "1TB", "2TB")
REGISTERED_IPHONE = {"iPhone Duo 256GB": "prod_iphoneduo_256"}
APPLE_BUY_URL = "https://www.apple.com/jp/shop/buy-iphone"
CONFIG_PATH = PROJECT_ROOT / "config" / "iphone_buyback.yaml"
DEFAULT_CONFIG = {
    "outlier": {"rate": 0.03, "reviewed": []},
    "freshness": {"default": {"fresh_days": 1}, "sources": {}, "unknown_freshness_executable": True},
    "surge": {"yen": 5000},
}
CONDITIONS = ("UNOPENED", "OPENED_NEW", "USED")
FRESH, STALE, UNKNOWN_FRESHNESS = "FRESH", "STALE", "UNKNOWN_FRESHNESS"
SHOP_KEYS = (
    ("ルデヤ", "rudeya"), ("モバイル一番", "mobile_ichiban"), ("買取商店", "kaitori_shouten"), ("森森", "morimori"),
    ("FS買取", "fs_kaitori"), ("クイック", "quick"), ("アキモバ", "akimoba"), ("楽園", "rakuen"), ("HONOKA", "honoka"),
    ("Twinkle", "twinkle"), ("トゥインクル", "twinkle"), ("1丁目", "itchome"), ("一丁目", "itchome"), ("携帯空間", "keitai_space"),
    ("BestBuy", "bestbuy"), ("アメモバ", "amemoba"), ("イオシス", "iosys"), ("じゃんぱら", "janpara"), ("浜北", "hamakita"),
    ("スマスピ", "smaspi"), ("サクモバ", "sakumoba"), ("大黒屋", "daikokuya"), ("ダイワン", "dwan"), ("パステック", "pastec"),
    ("リンクス", "linx"),
)
_SKU_RE = re.compile(r"(iPhone Duo|iPhone 18 Pro Max|iPhone 18 Pro)\s*(256GB|512GB|1TB|2TB)")
_DATE_RE = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})")


def load_config(path: Path = CONFIG_PATH) -> dict:
    """しきい値の設定（config/iphone_buyback.yaml）。読めない・足りない項目は既定値。"""
    import copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    try:
        import yaml
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        raw = {}
    except Exception:  # noqa: BLE001 — 壊れた設定で週次の取り込み全体を止めない
        raw = {}
    for k, v in raw.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
    return cfg


def _int(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v) if v > 0 else None
    if isinstance(v, str) and re.fullmatch(r"[\d,]+", v.strip()):
        n = int(v.replace(",", ""))
        return n if n > 0 else None
    return None


def shop_key(name: str) -> str:
    for word, key in SHOP_KEYS:
        if word in str(name):
            return key
    return "shop_" + re.sub(r"\W+", "", str(name))[:20].lower()


_UPDATED_RE = re.compile(r"更新日?時?[^\d]{0,14}(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})")
_PAGE_RE = re.compile(r"ページ(?:記載|表示|自身)[^\d]{0,14}(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})")
_LEAD_TIME_RE = re.compile(r"^\s*(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\s+\d{1,2}:\d{2}[^()（）]*[（(][^)）]*ページ(?:表示|記載|自身)")
_NO_DATE_RE = re.compile(r"記載なし|記載が(?:ない|なかっ)|更新なし|不明")


def page_updated_on(checked_at: str) -> Optional[str]:
    """ページ自身の更新日（YYYY-MM-DD）。取得日（checked_at の先頭の日付）は使わない。

    「更新」「ページ記載」「ページ表示」の語の後ろ（14 字以内）に日付があるときだけ採る。先頭の「日付 時刻（ページ表示の時点）」も採る
    （ページが時刻まで表示している）。「記載なし」「更新なし」「不明」の語が 1 つでもあれば、日付があっても None
    （更新日の記載なし = UNKNOWN_FRESHNESS。関連記事の日付などを更新日にしない）。
    """
    t = str(checked_at or "")
    if _NO_DATE_RE.search(t):
        return None
    m = _UPDATED_RE.search(t) or _PAGE_RE.search(t) or _LEAD_TIME_RE.search(t)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _age_days(updated_on: Optional[str], research_date: str) -> Optional[int]:
    if not updated_on:
        return None
    return (datetime.strptime(research_date, "%Y-%m-%d") - datetime.strptime(updated_on, "%Y-%m-%d")).days


def freshness_of(key: str, updated_on: Optional[str], research_date: str, cfg: dict) -> tuple[str, Optional[int]]:
    """鮮度（FRESH / STALE / UNKNOWN_FRESHNESS）。しきい値は設定（店ごとに上書きできる）。更新日が無ければ UNKNOWN_FRESHNESS。"""
    age = _age_days(updated_on, research_date)
    if age is None or age < 0:
        return UNKNOWN_FRESHNESS, None                       # 更新日が無い・調査日より未来の日付は、鮮度を言わない
    src = (cfg["freshness"].get("sources") or {}).get(key) or {}
    days = int(src.get("fresh_days") or (cfg["freshness"].get("default") or {}).get("fresh_days") or 1)
    return (FRESH if age <= days else STALE), age


def _fetch_status(raw: dict) -> str:
    st = str(raw.get("fetch_status") or "").strip().upper()
    return next((x for x in ("ACTIVE", "NO_PRICE", "BLOCKED", "FAILED") if st.startswith(x)), "ACTIVE" if st.startswith("STALE") else "FAILED")


def _row_prices(item: dict) -> tuple[Optional[int], Optional[int], Optional[int], str]:
    """(base, best, executable, basis)。executable は色指定の無い SKU で確実に受け取れる価格（減額が最大の色の価格）。

    basis: uniform（色で価格が変わらない）/ worst_color（色別の減額を反映した最低）/ colors_unverified（色別の減額が
    不明。base は上限であって実行可能価格ではない）/ range_only（範囲だけ）。
    """
    base = _int(item.get("base_price"))
    ep = item.get("executable_price")
    best = _int(item.get("executable_price_no_reduction")) or _int(item.get("executable_price_no_deduction"))
    worst = _int(item.get("executable_price_worst_color")) or _int(item.get("executable_price_max_deduction"))
    if isinstance(ep, dict):
        best = best or _int(ep.get("no_reduction") or ep.get("no_deduction_color"))
        worst = worst or _int(ep.get("max_reduction_color") or ep.get("max_deduction_color") or ep.get("worst_color"))
    elif _int(ep):
        best = best or _int(ep)
    best = best or base
    if base is None and best is None:
        return None, None, None, "range_only"
    if worst is not None and best is not None and worst > best:
        return base, best, None, "colors_unverified"         # 減額後が掲載より高いのは不整合（実行可能価格にしない）
    if worst is not None:
        return base, best, worst, "uniform" if worst == best else "worst_color"
    colors = item.get("color_adjustments")
    if colors in ({}, [], None) and "color_adjustments" in item and not isinstance(ep, dict):
        return base, best, best, "uniform"
    return base, best, None, "colors_unverified"


def _condition(value) -> Optional[str]:
    u = str(value or "").strip().upper()
    m = re.match(r"(UNOPENED|OPENED_NEW|USED)(?![A-Z_0-9])", u)      # 完全な語で一致（UNOPENED_X のような接尾辞や OPENED との前方一致で混ぜない）
    return m.group(1) if m else None


def normalize_iphone_shops(raw_shops: list, research_date: str, cfg: Optional[dict] = None) -> list[dict]:
    cfg = cfg or load_config()
    out = []
    for raw in raw_shops:
        if not isinstance(raw, dict) or not raw.get("shop_name"):
            continue
        name = str(raw["shop_name"]).strip()
        key = shop_key(name)
        status = _fetch_status(raw)
        updated = page_updated_on(raw.get("checked_at"))
        fresh, age = freshness_of(key, updated, research_date, cfg)
        text = json.dumps(raw, ensure_ascii=False)
        indicative = "相場の最大価格" in text or "最大価格。実際は" in text           # 確定価格でない（目安の最大）
        rows = []
        for item in (raw.get("skus") or raw.get("prices") or []):
            if not isinstance(item, dict):
                continue
            m = _SKU_RE.search(str(item.get("sku") or f"{item.get('model', '')} {item.get('storage') or item.get('capacity') or ''}"))
            if not m:
                continue
            common = raw.get("common") if isinstance(raw.get("common"), dict) else {}
            cond = _condition(item.get("condition") or common.get("condition"))
            if cond is None:
                continue                                     # 条件が不明な行は混ぜない
            if "range_new" in item or "range" in item:
                base, best, executable, basis = None, None, None, "range_only"      # 版・色の対応が取れない範囲は価格にしない
            else:
                base, best, executable, basis = _row_prices(item)
            if indicative and basis in ("uniform", "worst_color", "colors_unverified"):
                basis = "indicative"                         # 目安の最大。確定価格でない（掲載の最高値にも数えない）
                executable, best = None, None
            ca = item.get("color_adjustments")
            rows.append({
                "sku": f"{m.group(1)} {m.group(2)}", "condition": cond, "base_price": base, "best_price": best,
                "executable_price": executable, "basis": basis,
                "color_adjustments": ca if isinstance(ca, dict) else {},
                "carrier_or_region": str(item.get("carrier_or_region") or common.get("carrier_or_region") or "")[:80],
                "campaign": str(item.get("campaign") or "")[:120] or None,
                "conditions": str(item.get("conditions") or "")[:160] or None,
            })
        out.append({
            "shop": name[:40], "key": key, "status": status,
            "official_url": raw.get("official_url") if str(raw.get("official_url") or "").startswith("http") else None,
            "price_page_url": _first_url(raw.get("price_page_url")) or None,
            "checked_at": str(raw.get("checked_at") or "")[:120],
            "updated_on": updated, "age_days": age, "freshness": fresh,
            "discovered": bool(raw.get("discovered")), "reason": str(raw.get("reason") or raw.get("fetch_status_note") or "")[:120],
            "rows": rows,
        })
    return out


def _executable_candidate(shop: dict, row: dict, cfg: dict) -> bool:
    """利益計算の候補にできる行か（取得できた店・新品未開封・色減額が分かる・鮮度が STALE でない）。"""
    if shop["status"] != "ACTIVE" or row["condition"] != "UNOPENED":
        return False
    if row.get("campaign"):
        return False                                         # キャンペーンの記載がある行は、価格が通常価格か確認できない（別欄のボーナスと混ぜない）
    if not isinstance(row["executable_price"], int) or row["basis"] not in ("uniform", "worst_color"):
        return False
    if shop["freshness"] == STALE:
        return False
    return shop["freshness"] == FRESH or bool(cfg["freshness"].get("unknown_freshness_executable", True))


def _listed(shop: dict, row: dict) -> Optional[int]:
    """掲載の最高値（色減額の有無・鮮度に関わらない）。取得できた店の新品未開封の行だけ。範囲・目安は価格にしない。"""
    if shop["status"] != "ACTIVE" or row["condition"] != "UNOPENED" or row["basis"] in ("range_only", "indicative"):
        return None
    return row["best_price"] if isinstance(row["best_price"], int) else None


def _reviewed(cfg: dict, sku: str, key: str, price: int, research_date: str) -> bool:
    for r in (cfg["outlier"].get("reviewed") or []):
        if isinstance(r, dict) and r.get("sku") == sku and r.get("shop_key") == key and r.get("price") == price \
                and str(r.get("reviewed_on") or "") <= research_date and r.get("reviewed_on") == research_date:
            return True
    return False


def build_iphone_comparison(raw_shops: list, apple_prices: dict, *, research_date: str, now: datetime, cfg: Optional[dict] = None) -> dict:
    from src.market import official_shipping, profit_formula
    cfg = cfg or load_config()
    rate = float(cfg["outlier"].get("rate") or 0.03)
    shops = normalize_iphone_shops(raw_shops, research_date, cfg)
    skus = []
    for model in IPHONE_TARGET_MODELS:
        for cap in IPHONE_CAPACITIES:
            sku = f"{model} {cap}"
            apple = _int((apple_prices.get(model) or {}).get(cap))
            if apple is None:
                continue
            rows = []
            for sh in shops:
                for r in sh["rows"]:
                    if r["sku"] == sku:
                        rows.append(dict(r, shop=sh["shop"], key=sh["key"], shop_status=sh["status"], freshness=sh["freshness"],
                                         price_page_url=sh["price_page_url"], checked_at=sh["checked_at"], updated_on=sh["updated_on"],
                                         age_days=sh["age_days"], listed_price=_listed(sh, r),
                                         eligible=_executable_candidate(sh, r, cfg)))
            per_shop: dict = {}
            for r in rows:                                   # 同じ店・同じ SKU の複数行（キャンペーン・版の違い・重複）は 1 店として数え、保守的に最低の価格を採る
                if r["eligible"] and (r["key"] not in per_shop or r["executable_price"] < per_shop[r["key"]]["executable_price"]):
                    per_shop[r["key"]] = r
            for r in rows:
                if r["eligible"] and per_shop[r["key"]] is not r:
                    r["eligible"] = False                    # 同じ店の他の行（高い方）は採用しない（保守的に最低を 1 行だけ採る）
                    r["duplicate_row"] = True
            elig = sorted(per_shop.values(), key=lambda r: -r["executable_price"])
            listed = sorted([r for r in rows if r["listed_price"]], key=lambda r: -r["listed_price"])
            priced_shops = {r["key"] for r in listed if r["condition"] == "UNOPENED"}
            fresh_shops = {r["key"] for r in listed if r["freshness"] == FRESH}
            top = elig[0] if elig else None
            # 外れ値: 実行可能な最高値が 2 位より rate を超えて高い（最高値は捨てない。利益計算に使わず確認待ちにする）
            if not top:
                outlier = "NO_DATA"
            elif len(elig) < 2:
                outlier = "SINGLE_SOURCE"
            elif top["executable_price"] > elig[1]["executable_price"] * (1 + rate):
                outlier = "REVIEWED" if _reviewed(cfg, sku, top["key"], top["executable_price"], research_date) else "OUTLIER_REVIEW"
            else:
                outlier = "NONE"
            confirmed = bool(top) and outlier in ("NONE", "REVIEWED")
            fee = official_shipping.purchase_shipping(REGISTERED_IPHONE.get(sku) or "prod_unregistered", APPLE_BUY_URL, apple)["fee"]
            costs = None if fee is None else profit_formula.fixed_costs() + int(fee)
            net = (top["executable_price"] - apple - costs) if (confirmed and costs is not None) else None
            ref_net = None
            if outlier == "OUTLIER_REVIEW" and costs is not None and len(elig) > 1:
                ref_net = {"shop": elig[1]["shop"], "price": elig[1]["executable_price"],
                           "net_profit": elig[1]["executable_price"] - apple - costs,
                           "note": "次点の価格での参考計算。最高の実行可能価格ではない（最高値は確認待ち）"}
            hl = listed[0] if listed else None
            skus.append({
                "sku": sku, "apple_price": apple, "apple_url": APPLE_BUY_URL,
                "identity": "REGISTERED" if sku in REGISTERED_IPHONE else "DISCOVERED",
                "identity_note": "正本に登録済み（部品番号つき）" if sku in REGISTERED_IPHONE else "参考: 部品番号が公式ページに無く、正本に未登録。利益の判定（BUY）には使わない",
                "rows": sorted(rows, key=lambda r: (not r["eligible"], -(r["listed_price"] or 0))),
                "source_count": len(priced_shops), "fresh_source_count": len(fresh_shops), "eligible_shops": len(elig),
                "outlier_status": outlier,
                "highest_listed": {"shop": hl["shop"], "price": hl["listed_price"], "freshness": hl["freshness"], "executable": hl["eligible"]} if hl else None,
                "highest_executable": {"shop": top["shop"], "price": top["executable_price"]} if (top and confirmed) else None,
                "highest_unconfirmed": {"shop": top["shop"], "price": top["executable_price"], "status": outlier} if (top and not confirmed) else None,
                "second": {"shop": elig[1]["shop"], "price": elig[1]["executable_price"]} if len(elig) > 1 else None,
                "third": {"shop": elig[2]["shop"], "price": elig[2]["executable_price"]} if len(elig) > 2 else None,
                "costs": costs, "net_profit": net, "roi_pct": round(100.0 * net / apple, 2) if net is not None else None,
                "reference_net_at_second": ref_net,
                "best_route": (f"Apple → {top['shop']}" if (confirmed and net is not None and net > 0 and sku in REGISTERED_IPHONE) else None),
                "reference_route": (f"Apple → {top['shop']}" if (confirmed and net is not None and net > 0 and sku not in REGISTERED_IPHONE) else None),
            })
    counts = {k: sum(1 for s in shops if s["status"] == k) for k in ("ACTIVE", "NO_PRICE", "BLOCKED", "FAILED")}
    for f in (FRESH, STALE, UNKNOWN_FRESHNESS):
        counts[f] = sum(1 for s in shops if s["status"] == "ACTIVE" and s["freshness"] == f)
    return {
        "schema": 2, "type": "IPHONE_BUYBACK_COMPARISON", "research_date": research_date,
        "generated_at": now.isoformat(timespec="seconds"),
        "note": "週次の Web 調査（AI）の結果。価格は各店の公開ページの掲載価格で、買取の確定ではない（事前申込・検品・減額がある）。"
                "「掲載の最高値」はそのまま表示・保存する。「最高の実行可能価格」は、新品未開封・色減額が分かる・更新が STALE でない・"
                "外れ値でない（または確認済み）ときだけ。外れ値は OUTLIER_REVIEW として利益計算に使わない。"
                "identity が DISCOVERED の SKU は参考（正本に未登録）で、BUY の判定ではない。",
        "thresholds": {"outlier_rate": rate, "fresh_days_default": (cfg["freshness"].get("default") or {}).get("fresh_days", 1),
                       "unknown_freshness_executable": bool(cfg["freshness"].get("unknown_freshness_executable", True))},
        "counts": counts, "shops_researched": len(shops),
        "shops": [{k: v for k, v in s.items() if k != "rows"} | {"rows_count": len(s["rows"])} for s in shops],
        "skus": skus,
    }


def diff_snapshots(prev_rows: list, curr_rows: list, *, surge_yen: int = 5000) -> list:
    """前回との比較: 最高買取店の変更・買取価格の急騰・赤字 → 黒字。rows は {sku, key, shop, price, net}。"""
    events = []
    pm = {(r["sku"], r["key"]): r for r in prev_rows}

    def best(rows, sku):
        c = [r for r in rows if r["sku"] == sku]
        return max(c, key=lambda r: r["price"]) if c else None
    for sku in sorted({r["sku"] for r in curr_rows}):
        b0, b1 = best(prev_rows, sku), best(curr_rows, sku)
        if b0 and b1 and b0["key"] != b1["key"] and b0["price"] != b1["price"]:
            events.append({"type": "BEST_SHOP_CHANGE", "sku": sku, "from": b0["shop"], "to": b1["shop"], "price": b1["price"]})
        if b0 and b1 and (b0.get("net") or 0) <= 0 < (b1.get("net") or 0):
            events.append({"type": "LOSS_TO_PROFIT", "sku": sku, "shop": b1["shop"], "net": b1["net"]})
    for r in curr_rows:
        p = pm.get((r["sku"], r["key"]))
        if p and r["price"] - p["price"] >= surge_yen:
            events.append({"type": "BUYBACK_SURGE", "sku": r["sku"], "shop": r["shop"], "from": p["price"], "to": r["price"]})
    return events


def snapshot_rows(comp: dict) -> list:
    out = []
    for s in comp["skus"]:
        top = (s["highest_executable"] or {}).get("price")
        unconf = s.get("highest_unconfirmed") or {}
        for r in s["rows"]:
            if s["outlier_status"] == "SINGLE_SOURCE":
                continue                                     # 比較できない（確認待ちの価格を変動の根拠にしない）
            if unconf and r["shop"] == unconf.get("shop") and r["executable_price"] == unconf.get("price"):
                continue                                     # 外れ値（OUTLIER_REVIEW）の価格は変動として出さない
            if r["eligible"] and not r.get("duplicate_row"):
                out.append({"sku": s["sku"], "key": r["key"], "shop": r["shop"], "price": r["executable_price"],
                            "net": s["net_profit"] if top == r["executable_price"] else None})
    return out


def update_history(comp: dict, history_path: Path, *, keep: int = 26, surge_yen: int = 5000) -> dict:
    hist = {"schema": 1, "snapshots": []}
    if history_path.exists():
        try:
            hist = json.loads(history_path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    snaps = [x for x in hist.get("snapshots", []) if x.get("date") != comp["research_date"]]    # 同じ日の再実行で二重にしない
    prev = snaps[-1]["rows"] if snaps else []
    cur = snapshot_rows(comp)
    comp["events"] = diff_snapshots(prev, cur, surge_yen=surge_yen) if prev else []
    comp["events_note"] = "前回の週次の調査との比較" if prev else "初回の調査のため比較なし"
    snaps.append({"date": comp["research_date"], "rows": cur})
    hist["snapshots"] = snaps[-keep:]
    return hist


def import_iphone(research_dir: Path, *, now: datetime, out_dir: Path, apply: bool = False, cfg: Optional[dict] = None) -> Optional[dict]:
    apple_file = research_dir / "research_iphone.json"
    shop_files = sorted(research_dir.glob("iphone_exp_*.json"))
    if not apple_file.exists() or not shop_files:
        return None
    cfg = cfg or load_config()
    apple = json.loads(apple_file.read_text(encoding="utf-8")).get("apple_official", {}).get("prices_jpy", {})
    raw_shops: list = []
    for f in shop_files:
        d = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("shops"), list):
            d = d["shops"]
        raw_shops += d if isinstance(d, list) else [v for v in d.values() if isinstance(v, dict)]
    research_date = research_dir.name if re.fullmatch(r"\d{4}-\d{2}-\d{2}", research_dir.name) else now.strftime("%Y-%m-%d")
    comp = build_iphone_comparison(raw_shops, apple, research_date=research_date, now=now, cfg=cfg)
    hist = update_history(comp, out_dir / "iphone_buyback_history.json", surge_yen=int(cfg["surge"].get("yen") or 5000))
    if apply:
        out_dir.mkdir(parents=True, exist_ok=True)
        from src.utils.atomic_write import write_json_atomic
        write_json_atomic(out_dir / "iphone_buyback_comparison.json", comp)
        write_json_atomic(out_dir / "iphone_buyback_history.json", hist)
    return comp


# ---- カメラ（週次の調査の要約。利益商品を無理に作らない） ----
# 抽選に当たらないと仕入れられないルートは LOTTERY_DEPENDENT（即時の BUY にしない）。在庫が無いものは OUT_OF_STOCK。
# 二次流通は出品（LISTING）と成約（SOLD）を分け、SOLD の中央値と期間が確認できないときは期待売値を作らない。
# 純利益の数字は、確認できない項目（購入送料・買取の条件）があるので「参考の推定」としてだけ出し、確定のルートにしない。
def _camera_status(route: dict) -> str:
    buy = route.get("buy") or {}
    text = str(buy.get("where", "")) + str(buy.get("stock", ""))
    if "抽選" in text:
        return "LOTTERY_DEPENDENT"
    if "SOLD OUT" in text.upper() or "在庫なし" in text or "購入不可" in text:
        return "OUT_OF_STOCK"
    return "UNCONFIRMED"


def _sell_candidate(x: dict, research_date: str = "") -> dict:
    where = str(x.get("where") or "")[:120]
    note = str(x.get("note") or "")
    unnamed = "店名非公開" in where or "店名なし" in where or "査定サイト" in where
    unverified = str(x.get("classification") or "").upper() == "UNVERIFIED" or "検索結果の要約" in where or "BLOCKED" in where
    age = x.get("age_days")
    m = _DATE_RE.search(where) if research_date else None
    if age is None and m:
        try:
            age = (datetime.strptime(research_date, "%Y-%m-%d") - datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
        except ValueError:
            age = None
    old = isinstance(age, (int, float)) and age > 7
    text = where + note
    not_new = any(w in text for w in ("美品", "中古", "新品ではない", "新品同様")) or "新品" not in text
    reasons = [r for r, f in (("店名が分からない", unnamed), ("原本を確認していない", unverified), ("価格が古い", old),
                              ("価格の新しさを確認できない", age is None),
                              ("新品の条件を確認できない（状態が違う可能性）", not_new), ("範囲・相場で単一の価格でない", x.get("price") is None)) if f]
    return {"where": where, "price": _int(x.get("price")), "range": x.get("range"), "age_days": age,
            "executable_candidate": not reasons, "reasons": reasons}


def build_camera_summary(rc: dict, *, research_date: str, now: datetime) -> dict:
    """カメラの週次の要約（公開データ）。公開するのは、確認できた売却先・メーカーの公式ページの抽選・集計だけ。

    原本を確認していない価格・集約サイトの価格・未確認の新商品の名前は公開しない（件数だけ。個別の候補は .private/ の調査に残る）。
    抽選の「受付中・終了」は保存せず、ページを作るたびに現在の日時と応募期限から決める（週次の JSON に古い状態を焼き込まない）。
    """
    from src.market import profit_formula
    routes = [r for r in rc.get("price_routes") or [] if isinstance(r, dict)]
    fixed = profit_formula.fixed_costs()
    products, hidden_sell = [], 0
    for r in routes:
        if not r.get("buy"):
            continue
        buy = r["buy"]
        st = _camera_status(r)
        buy_price = _int(buy.get("price"))
        article_price = any(w in str(buy.get("price_note") or "") for w in ("記事", "未裏取り"))
        if article_price:
            buy_price = None                                 # 公式ページで確認できない（記事の）仕入れ価格は公開しない・利益計算に使わない
        cands_all = [_sell_candidate(x, research_date) for x in r.get("sell") or [] if isinstance(x, dict)]
        cands = [c for c in cands_all if "原本を確認していない" not in c["reasons"]]
        hidden_sell += len(cands_all) - len(cands)
        usable = [c for c in cands if c["executable_candidate"] and c["price"]]
        ref_net = [{"where": c["where"], "sell": c["price"], "net_before_purchase_shipping": c["price"] - buy_price - fixed,
                    "roi_pct": round(100.0 * (c["price"] - buy_price - fixed) / buy_price, 1)} for c in usable] if buy_price else []
        note = ("売却先として使える（店名・日付・新品の条件が確認できた）価格が無く、利益の見込みは判断できません。" if not usable
                else "確認できた売却先での参考の純利益です（購入送料・買取の条件が未確認のため、確定のルートではありません）。")
        if st == "LOTTERY_DEPENDENT":
            note += " 抽選に当たらなければ仕入れられません。"
        if st == "OUT_OF_STOCK":
            note += " 公式は在庫がなく、今は購入できません。"
        products.append({
            "product": str(r.get("product") or "")[:80], "status": st,
            "buy": {"where": str(buy.get("where") or "")[:100], "price": buy_price, "availability": str(buy.get("stock") or "")[:80],
                    "price_note": ("仕入れ価格は公式ページに金額が無い（記事の値は確認できないため公開しない）" if article_price
                                   else (str(buy.get("price_note") or "")[:120] or None))},
            "sell_candidates": cands, "reference_net": ref_net,
            "reference_label": "INFERENCE（購入送料・買取の条件が未確認の参考値。確定のルートではない）",
            "immediate_buy": False, "note": note,
        })
    secondary = []
    for r in routes:
        sold = r.get("sold_new") or (r.get("secondary") or {}).get("sold_new_silver")
        if not sold:
            continue
        listing = r.get("listing_new") or {"note": (r.get("secondary") or {}).get("listing_new")}
        secondary.append({
            "product": str(r.get("product") or "")[:80],
            "listing": {"low": _int(listing.get("low")), "high": _int(listing.get("high")), "n": listing.get("n"), "note": listing.get("note")},
            "sold": {"low": _int(sold.get("low")), "high": _int(sold.get("high")), "median": _int(sold.get("median")),
                     "n": sold.get("n"), "period": str(sold.get("period") or "")[:60]},
            "expected_sell_price": None,
            "evidence": "二次流通サイトの掲載を要約経由で読んだ値（期間・手数料・状態は未確認）",
            "expected_sell_price_reason": "SOLD の中央値・期間が確認できない（出品の最高値・成約の最高値を売れる価格として使わない）",
        })
    discovered = sum(1 for i in list(rc.get("items") or []) + routes if i.get("kind") == "NEW_PRODUCT"
                     and str(i.get("classification") or "").upper() == "UNVERIFIED")
    lotteries, hidden_lot = [], 0
    for i in rc.get("items") or []:
        if not str(i.get("kind") or "").startswith("LOTTERY"):
            continue
        url = _first_url(i.get("source_url")) or _first_url(i.get("official_url"))
        if not (url and primary_evidence(url)):
            hidden_lot += 1                                    # 一次情報で確認できない抽選は公開しない
            continue
        lotteries.append({"product": str(i.get("product_name") or "")[:100], "retailer": str(i.get("retailer") or "")[:60],
                          "application_start": _to_iso(i.get("application_start"), end=False)[0],
                          "application_end": _to_iso(i.get("application_end"), end=True)[0],
                          "winner_announcement": str(i.get("winner_announcement") or "")[:40] or None,
                          "official_url": url, "evidence": "メーカーまたは店舗の公式ページ"})
    return {"schema": 2, "type": "CAMERA_WEEKLY_RESEARCH", "research_date": research_date, "generated_at": now.isoformat(timespec="seconds"),
            "note": "週次の Web 調査（AI）の結果。利益商品を無理に作らない。抽選に当たらないと仕入れられないものは LOTTERY_DEPENDENT で、即時の BUY ではない。",
            "products": products, "secondary_market": secondary, "lotteries": lotteries,
            "hidden_counts": {"unverified_sell_candidates": hidden_sell, "unverified_lotteries": hidden_lot, "discovered_products_unverified": discovered}}


def import_camera(research_dir: Path, *, now: datetime, out_dir: Path, apply: bool = False) -> Optional[dict]:
    f = research_dir / "research_camera.json"
    if not f.exists():
        return None
    research_date = research_dir.name if re.fullmatch(r"\d{4}-\d{2}-\d{2}", research_dir.name) else now.strftime("%Y-%m-%d")
    summary = build_camera_summary(json.loads(f.read_text(encoding="utf-8")), research_date=research_date, now=now)
    if apply:
        out_dir.mkdir(parents=True, exist_ok=True)
        from src.utils.atomic_write import write_json_atomic
        write_json_atomic(out_dir / "camera_research_weekly.json", summary)
    return summary


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="週次リサーチの結果の取り込み（既定は dry-run）")
    ap.add_argument("--dir", required=True, help="調査の JSON のフォルダ（.private/research/weekly/<日付>/）")
    ap.add_argument("--apply", action="store_true", help="公開データへ書き込む（既定は書かない）")
    a = ap.parse_args(argv)
    d = Path(a.dir)
    now = datetime.now(JST)
    out: dict = {"ran_at": now.isoformat(timespec="seconds"), "apply": a.apply}
    tcg_path = d / "research_tcg.json"
    if tcg_path.exists():
        research = json.loads(tcg_path.read_text(encoding="utf-8"))
        try:
            lot = json.loads((PROJECT_ROOT / "exports" / "tcg" / "lotteries.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            lot = None
        out["tcg"] = import_tcg(research, now=now, apply=a.apply, covered=covered_urls(lot),
                                verifications=load_verifications(d), collectors=collector_retailers(lot))
        out["tcg_coverage"] = coverage(research.get("source_results") or [])
    comp = import_iphone(d, now=now, out_dir=PROJECT_ROOT / "exports" / "iphone_buyback", apply=a.apply)
    if comp:
        out["iphone"] = {"shops_researched": comp["shops_researched"], "counts": comp["counts"], "applied": a.apply,
                         "skus": [{k: s[k] for k in ("sku", "identity", "source_count", "fresh_source_count", "outlier_status", "highest_listed", "highest_executable", "net_profit", "roi_pct")} for s in comp["skus"]],
                         "events": comp["events"]}
    cam = import_camera(d, now=now, out_dir=PROJECT_ROOT / "exports" / "camera_research", apply=a.apply)
    if cam:
        out["camera"] = {"products": [{"product": p["product"], "status": p["status"], "immediate_buy": p["immediate_buy"]} for p in cam["products"]],
                         "secondary": len(cam["secondary_market"]), "lotteries": len(cam["lotteries"]), "hidden": cam["hidden_counts"], "applied": a.apply}
    (d / "import_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk in ("verdict", "coverage_pct", "applied", "duplicates_skipped")}) for k, v in out.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
