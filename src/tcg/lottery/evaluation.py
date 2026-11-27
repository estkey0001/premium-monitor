# -*- coding: utf-8 -*-
"""抽選の収集の品質を測る（ゴールデンセットに対する再現率・抽出精度と、履歴からの検出遅延）。

ゴールデンセット（既定 data/golden/lottery_golden.json。人が公式ページで確かめた過去の実在の抽選）:

    {"schema": 1, "items": [{
        "golden_id": "g-001", "retailer": "CARD_LABO", "source_url": "https://...",   # 公式の告知 URL（照合の第一キー）
        "product_name": "...", "published_at": "2026-11-20",                          # 告知の公開日（検出遅延に使う）
        "application_start": "2026-11-21T10:00:00+09:00", "application_end": "...",   # 時刻が無ければ *_date に日付
        "conditions": {"membership_required": true, "purchase_limit": "お一人様1BOXまで", ...},
        "verified_on": "2026-11-26", "verified_by": "human"                           # 誰がいつ公式ページで確かめたか
    }]}

- 照合: source_url（正規化）が同じ・同じ retailer の記録。無ければ retailer＋商品名＋受付開始日の一致。
- 再現率 = 照合できたゴールデン / ゴールデン全体。
- 抽出精度 = 照合できた組で、ゴールデンに値がある項目のうち、記録の値が一致した割合（項目別）。日程は時刻として比べる。
  値の項目（日程・価格・上限・地域）は記録に値が無ければ不一致。真偽の項目は 3 状態（True=必須・False=不要と明記・None=不明）で比べ、
  不明（None）を「不要」（False）と同じにしない。
- 1 つの記録は 1 つのゴールデンにだけ照合する（再現率を高く見せない）。
- 検出遅延 = 最初に記録した時刻（first_seen_at）− 告知の公開日（published_at）。日付だけの公開日は、その日の 00:00（JST）とみなす
  （遅延が大きめに出る側。短く見せない）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = PROJECT_ROOT / "data" / "golden" / "lottery_golden.json"
SCHEDULE_KEYS = ("application_start", "application_end", "application_start_date", "application_end_date",
                 "winner_announcement_at", "winner_announcement_date", "purchase_start", "purchase_end",
                 "purchase_start_date", "purchase_end_date")
CONDITION_FLAGS = ("membership_required", "purchase_history_required", "x_follow_required", "x_repost_required",
                   "app_only", "id_required_at_purchase")
CONDITION_VALUES = ("application_limit", "purchase_limit", "region_limit")


def load_golden(path: Optional[Path] = None) -> list[dict]:
    p = Path(path) if path else GOLDEN_PATH
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [g for g in (d.get("items") or []) if isinstance(g, dict) and g.get("verified_on") and g.get("retailer")]


def _norm(u) -> str:
    from src.tcg.lottery.pipeline import normalize_url
    return normalize_url(str(u or "")) if u else ""


def _start_day(r: dict) -> str:
    return str(r.get("application_start") or r.get("application_start_date") or "")[:10]


def match(golden: dict, records: list[dict], used: Optional[set] = None) -> Optional[dict]:
    gu = _norm(golden.get("source_url"))
    used = used if used is not None else set()
    same = [r for r in records if r.get("retailer") == golden.get("retailer") and id(r) not in used]
    if gu:
        hits = [r for r in same if gu in {_norm(u) for u in ([r.get("source_url")] + list(r.get("source_urls") or []))}]
        # 複数商品の告知（同じ URL に記録が複数）では、商品名を含む記録を優先する
        core = str(golden.get("product_core") or golden.get("product_name") or "")
        gst = _nospace(golden.get("store_name"))
        if gst:                         # 支店の名前があれば、同じ URL の別の支店の記録に照合しない
            hits = [r for r in hits if not r.get("store_specific") or _same_store(gst, r.get("store_name"))]
        named = [r for r in hits if core and core in str(r.get("product_name") or "")]
        if named:
            return named[0]
        if len(hits) == 1 or (hits and not core):
            return hits[0]
        if hits:
            return None                      # 同じ URL の別の商品の記録に、まちがって照合しない
    gn, gs = str(golden.get("product_core") or golden.get("product_name") or ""), _start_day(golden)
    gstore = _nospace(golden.get("store_name"))
    for r in same:
        # 支店の名前があるときは支店まで一致すること（同じチェーンの別の支店の記録に結び付けない）
        if gstore and r.get("store_specific") and not _same_store(gstore, r.get("store_name")):
            continue
        if gn and gs and gn in str(r.get("product_name") or "") and _start_day(r) == gs:
            return r
    return None


def _nospace(v) -> str:
    import re as _re
    return _re.sub(r"\s+", "", str(v or ""))


_CHAIN_WORDS = re.compile(r"カードラボ|CARD\s*BOX|カードボックス|ONEPIECE麦わらストア|麦わらストア|ホビーステーション|販売買取センター")


def _same_store(a, b) -> bool:
    """支店の名前が同じか（空・チェーン名だけは一致にしない。チェーン名を除いた支店名で比べる）。"""
    x, y = _CHAIN_WORDS.sub("", _nospace(a)), _CHAIN_WORDS.sub("", _nospace(b))
    return bool(x) and bool(y) and (x == y or x in y or y in x)


def _cond_value(rec: dict, key: str):
    c = rec.get("conditions") or {}
    v = c.get(key)
    if isinstance(v, dict):
        return v.get("value")
    legacy = {"membership_required": "membership_required", "purchase_history_required": "purchase_history_required",
              "id_required_at_purchase": "identity_verification_required", "app_only": "app_required"}.get(key)
    if v is None and legacy and rec.get(legacy) is not None:
        return rec.get(legacy)                                # 構造化の前の真偽値の項目
    return v


def accuracy(pairs: list[tuple[dict, dict]]) -> dict:
    """項目別の {一致, 比較数, 割合}。ゴールデンに値がある項目だけを比べる。"""
    out: dict = {}

    def add(key, ok):
        a = out.setdefault(key, {"match": 0, "total": 0})
        a["total"] += 1
        a["match"] += int(bool(ok))
    for g, r in pairs:
        for k in SCHEDULE_KEYS:
            if g.get(k):
                gv, rv = _dt(g[k]), _dt(r.get(k))
                add(k, bool(gv and rv and gv == rv) if len(str(g[k])) > 10 else str(r.get(k) or "")[:10] == str(g[k])[:10])
        if g.get("retail_price") is not None:
            add("retail_price", r.get("retail_price") == g["retail_price"])
        gc = g.get("conditions") or {}
        for k in CONDITION_FLAGS:
            if gc.get(k) is not None:
                # 真偽は 3 状態: ゴールデンが True/False のとき、記録の True/False/None（不明）と比べる。不明は「不要」と同じにしない
                add(k, _cond_value(r, k) is gc[k])
        # 本文が「場合がある」等で、不明（値を付けない）が正解の項目。条件を何も取れていない記録では数えない
        # （何も読めていないことを「正しく不明にした」と数えない）。別の件数として出す
        has_any = any(v is not None for v in (r.get("conditions") or {}).values())
        for k in g.get("expected_unknown") or []:
            if has_any:
                add(f"{k}（不明であるべき）", _cond_value(r, k) is None)
            else:
                add(f"{k}（不明であるべき・条件を取れていない記録）", False)
        for k in CONDITION_VALUES:
            if gc.get(k):
                add(k, _nospace(gc[k]) in _nospace(_cond_value(r, k)))
    for a in out.values():
        a["rate"] = round(a["match"] / a["total"], 3) if a["total"] else None
    return out


def _dt(s) -> Optional[datetime]:
    from src.tcg.models import JST, parse_dt
    if not s:
        return None
    s = str(s)
    d = parse_dt(s) if len(s) > 10 else None
    if d is None and len(s) >= 10:
        try:
            d = datetime.fromisoformat(s[:10]).replace(tzinfo=JST)
        except ValueError:
            return None
    return d


def detection_latency(records: list[dict], *, exclude_backlog: bool = False) -> dict:
    """履歴（first_seen_at・published_at）からの検出遅延（時間）。取得元別の中央値と全体。

    exclude_backlog=True: 取得元ごとに、最初に記録した日（取得器を入れた日）に記録したものを除く
    （その日にまとめて拾った過去の告知は、検出の速さではなく取得元の追加の遅さを表すため）。
    """
    # 同じ告知（source_url）が抽選 ID を変えて記録し直されたもの（商品名の読み方の修正等）は、一番早い記録だけを使う
    # 手動台帳の記録（人が入力するまでの遅れ）は、取得器の検出の速さに混ぜない
    records = [r for r in records if not str(r.get("source_type") or "").startswith("MANUAL")]
    earliest: dict = {}
    for r in records:
        key = (str(r.get("retailer") or ""), _norm(r.get("source_url")) or str(r.get("lottery_id") or ""))
        b = _dt(r.get("first_seen_at"))
        prev = earliest.get(key)
        if prev is None or (b and (_dt(prev.get("first_seen_at")) is None or b < _dt(prev.get("first_seen_at")))):
            earliest[key] = r
    records = list(earliest.values())
    first_day: dict = {}
    for r in records:
        b = _dt(r.get("first_seen_at"))
        k = str(r.get("retailer") or "")
        if b and (k not in first_day or b.date() < first_day[k]):
            first_day[k] = b.date()
    by: dict = {}
    allv = []
    for r in records:
        if exclude_backlog:
            b = _dt(r.get("first_seen_at"))
            if b and b.date() == first_day.get(str(r.get("retailer") or "")):
                continue
        a, b = _dt(r.get("published_at")), _dt(r.get("first_seen_at"))
        if not (a and b) or b < a:
            continue
        h = (b - a).total_seconds() / 3600
        by.setdefault(str(r.get("retailer") or ""), []).append(h)
        allv.append(h)
    def summ(v):
        return {"n": len(v), "median_hours": round(median(v), 1), "max_hours": round(max(v), 1)} if v else {"n": 0}
    return {"overall": summ(allv), "by_retailer": {k: summ(v) for k, v in sorted(by.items())}}


def verifier_class(g: dict) -> str:
    """正解を誰が確かめたか: human（人が公式ページで確認）/ ai_unreviewed（AI が公式ページを読んで作った・人の確認待ち）。"""
    return "human" if str(g.get("verified_by") or "").startswith("human") else "ai_unreviewed"


ACTIVE = ("OPEN", "ENDING_SOON")


def kpis(items: list[dict], history: list[dict], *, generated_at: str = "") -> dict:
    # 応募ページの確認も、状態と同じ書き出し時点（generated_at）で判定する（実行時刻とずらさない）
    """今の公開データから測れる KPI（分母と時点つき）。測れないものは None と理由を返す（推測で埋めない）。"""
    from src.tcg.action_url import classify
    from src.tcg.models import now_jst
    n = len(items)
    pending = [e for e in items if e.get("status") in ACTIVE + ("UPCOMING",)]
    active = [e for e in items if e.get("status") in ACTIVE]
    start_unknown = [e for e in active if not (e.get("application_start") or e.get("application_start_date"))]
    from src.tcg.models import parse_dt
    now = parse_dt(generated_at) or now_jst()
    cls = [(e, classify(e, now)) for e in pending]
    app = [e for e, c in cls if (c.get("application_url") or c.get("external_entry_url"))]
    # Web で応募する抽選（公式の応募ページか外部フォーム）と、それ以外の経路（店頭・アプリ・X・会員ログイン）を分けて数える
    # 応募方法は、告知に明記された方法（application_methods）を先に使い、無ければ判定の経路（channel）を使う。
    # Web かどうかを「許可済みの外部フォームの規則に入っているか」で決めない（e-starbox・Google フォームも Web）
    def method(e, c):
        ms = list(e.get("application_methods") or [])
        if "web_form" in ms or c.get("channel") in ("WEB_OFFICIAL_FORM", "EXTERNAL_FORM"):
            return "web"
        if ms:
            return "non_web"
        return "non_web" if c.get("channel") in ("STORE_COUNTER", "APP", "SNS", "MEMBER_LOGIN") else "unknown"
    web = [(e, c) for e, c in cls if method(e, c) == "web"]
    web_ok = [e for e, c in web if c.get("application_url") or c.get("external_entry_url")]
    non_web = [(e, c) for e, c in cls if method(e, c) == "non_web"]
    unknown_ch = [e for e, c in cls if method(e, c) == "unknown"]
    exact = [e for e in items if e.get("product_match") == "exact" and not e.get("provisional_product")]
    priced = [e for e in items if e.get("retail_price") is not None and e.get("price_unit") == "BOX"]
    merged = sum(int(e.get("merged_count") or 1) for e in items)

    def rate(a, b):
        return {"num": a, "den": b, "rate": round(a / b, 3) if b else None}
    return {
        "as_of": generated_at, "lotteries_published": n,
        "active_open_or_ending": {"count": len(active), "of_which_start_date_unknown": len(start_unknown),
                                  "definition": "status が OPEN か ENDING_SOON（購入期間だけ・開始前は含まない）"},
        "application_url_confirmed": {**rate(len(app), len(pending)), "definition": "応募が済んでいない抽選（受付中・締切間近・開始前）のうち、"
                                      "TCG ハブと同じ判定で応募ページか外部フォームを確かめられたもの"},
        "web_application_url_confirmed": {**rate(len(web_ok), len(web)),
                                          "definition": "応募が済んでいない抽選のうち、応募方法が Web（公式の応募ページ・外部フォーム。告知に明記された方法か判定の経路）のもの（分母）で、"
                                                        "応募先の URL を確かめられたもの（外部フォームは external_entry_url。応募ボタンにはしない）。"
                                                        "公式の Web 応募でも URL も経路も分からない記録は application_channel_unknown に入り、分母に入らない"},
        "non_web_method_confirmed": {**rate(len(non_web), len(pending)),
                                     "definition": "応募が済んでいない抽選のうち、店頭・アプリ・X・会員ログインのどれで応募するかを確かめたもの"
                                                   "（取得元単位の既定の経路 SOURCE_CHANNEL を含む。支店ごとの違いは見ていない。"
                                                   "分母は応募が済んでいない抽選の全体）"},
        "application_channel_unknown": {"count": len(unknown_ch), "definition": "応募の経路を確かめられていない（推測で埋めない）"},
        "product_identity_confirmed": {**rate(len(exact), n), "definition": "商品マスターと完全一致（仮の商品でない）"},
        "price_confirmed": {**rate(len(priced), n), "definition": "BOX 単位と確定した価格がある"},
        "merge_rate": {**rate(merged - n, merged), "definition": "（まとめる前の件数 − まとめた後の件数）÷ まとめる前の件数（まとめた割合）"},
        "lotteries_in_history": len(history),
        "not_measured": {"recall": "人が確認したゴールデンセットが必要", "extraction_accuracy": "同上",
                         "misinformation_rate": "公開後の誤りの人による監査の記録が必要",
                         "residual_duplicate_rate": "まとめ損ねて公開に残った重複は、人の監査の記録が必要",
                         "detection_to_publish_time": "公開ページの反映時刻の記録が無い",
                         "monthly_cost": "外部 API は未契約（0 円）。CI の実行時間は未集計",
                         "cost_per_valid_lottery": "月間費用が未集計"},
    }


def extract_from_text(g: dict, text: str) -> dict:
    """保存した公式ページの本文に、今の抽出器（日程・応募条件）をかけた記録（抽出精度の測定用。照合は golden_id で 1 対 1）。"""
    from src.tcg.lottery.conditions import extract_conditions
    from src.tcg.lottery.parse import extract_schedule
    rec = {"retailer": g.get("retailer"), "source_url": g.get("source_url"), "product_name": g.get("product_name")}
    rec.update(extract_schedule(text, g.get("published_at"), product_name=g.get("product_name")))
    rec["conditions"] = {k: v for k, v in extract_conditions(text, other_products=g.get("other_products") or []).items() if v}
    return rec


def evaluate_texts(golden: list[dict], texts: dict) -> dict:
    """{source_url: 本文} を使い、ゴールデンごとに今の抽出器の値と比べる。本文の無いゴールデンは数えない（missing に出す）。"""
    golden = [g for g in golden if g.get("kind") != "non_lottery"]
    pairs = [(g, extract_from_text(g, texts[g["source_url"]])) for g in golden if g.get("source_url") in texts]
    acc = accuracy(pairs)
    acc.pop("retail_price", None)            # 価格は取得器ごとの解析で読む（この評価では抽出していないので比べない）
    return {"golden": len(golden), "with_text": len(pairs),
            "missing_text": [g.get("golden_id") for g in golden if g.get("source_url") not in texts],
            "not_evaluated": ["retail_price（取得器ごとの解析で読むため）"], "accuracy": acc}


def false_positives(negatives: list[dict], records: list[dict]) -> list[str]:
    """紛らわしい非抽選の告知（kind=non_lottery・title_contains）が、抽選の記録として載っていれば、その golden_id。"""
    out = []
    for g in negatives:
        t = _nospace(g.get("title_contains"))
        if t and any(r.get("retailer") == g.get("retailer") and t in _nospace(r.get("product_name")) for r in records):
            out.append(g.get("golden_id"))
    return out


def evaluate(golden: list[dict], records: list[dict]) -> dict:
    negatives = [g for g in golden if g.get("kind") == "non_lottery"]
    golden = [g for g in golden if g.get("kind") != "non_lottery"]
    pairs, missed = [], []
    used: set = set()
    for g in golden:
        r = match(g, records, used)
        if r:
            used.add(id(r))
            pairs.append((g, r))
        else:
            missed.append(g.get("golden_id"))
    n = len(golden)
    fp = false_positives(negatives, records)
    return {"golden": n, "matched": len(pairs), "recall": round(len(pairs) / n, 3) if n else None,
            "non_lottery_cases": len(negatives), "non_lottery_published_as_lottery": fp,
            "missed": missed, "accuracy": accuracy(pairs),
            "latency_golden": detection_latency([{**r, "published_at": g.get("published_at") or r.get("published_at")}
                                                 for g, r in pairs])}
