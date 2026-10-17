"""発見の候補を正本に登録する（Phase 28）。

承認（APPROVED）と登録（REGISTERED）を分ける。ここは人が CLI で明示したときだけ呼ばれる（CI からは呼ばない）。

- 商品: 承認済みの Apple 公式の候補だけを config/products.yaml に1件ずつ足す（TCG は既存の正本に入れない）
- イベント: 承認済みの告知の候補を、運営者が公式ページで確かめた日程で data/tcg_verified_lotteries.csv に1行足す
  （日程は推測しない。運営者が渡した値だけ）
- 既定は見込み（dry-run。何も書かない）。書くのは confirm のときだけ。書き込みは一時ファイルから置き換える（途中で
  失敗しても正本を壊さない）。commit・push はしない（人が差分を見てコミットする。戻すときはその差分を戻す）
"""
from __future__ import annotations

import csv
import difflib
import io
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from . import store as st

PRODUCT_TARGET = "config/products.yaml"
EVENT_TARGET = "data/tcg_verified_lotteries.csv"
APPLE_SOURCE = "apple_jp_official"
APPLE_URL_PREFIX = "https://www.apple.com/jp/shop/buy-iphone/"
PART_NUMBER = re.compile(r"^[A-Z0-9]{4,5}J/A$")      # 日本向けの部品番号（公式の商品データの partNumber の形）
SECTION_HEADER = ("  # =========================================\n"
                  "  # iPhone（発見の候補から人が承認して登録。Phase 28）\n"
                  "  # =========================================\n")
# 正本の項目の並び（既存の項目が先・発見の証拠が後）
FIELD_ORDER = ("id", "genre", "name", "brand", "model_number", "retail_price", "keywords", "capacity", "part_numbers",
               "colors", "official_url", "price_observed_on")
# 候補の ID は正本に書かない（台帳の registered_id で結び付ける。deploy-check #862 は候補の ID が正本にあれば
# 「自動で正本に入った」とみなす）
# 商品の登録に要る承認の証拠（公式ページで確かめたこと）
PRODUCT_EVIDENCE = ("official_url", "part_numbers", "capacity", "official_price")
# 手で確認した抽選の CSV に入れられる種類（先着・再販は CSV の種類に無いので登録しない）
EVENT_KINDS = {"LOTTERY": "LOTTERY", "PREORDER": "PREORDER"}
VERIFIED_BY = "operator（register-event-candidate。公式ページを人が確認）"


# 手元の承認で変わる項目（これ以外は対象の候補でも main と同じことを要求する。価格・部品番号が main で変わっていれば
# 承認し直す）
DECISION_FIELDS = ("status", "review", "decisions", "reviewed_at", "updated_at", "approved_product_id")


def ledgers_match_except(main: dict, local: dict, candidate_id: str) -> bool:
    """手元の台帳が main の台帳と、指定の候補の判断の項目を除いて同じか（承認だけを手元で記録した状態を許す）。"""
    if not isinstance(main, dict) or not isinstance(local, dict):
        return False
    mc, lc = dict(main.get("candidates") or {}), dict(local.get("candidates") or {})
    if candidate_id not in lc or candidate_id not in mc:
        return False
    m_rec, l_rec = mc.pop(candidate_id), lc.pop(candidate_id)
    if not isinstance(m_rec, dict) or not isinstance(l_rec, dict):
        return False
    if m_rec.get("status") in (st.REJECTED, st.REGISTERED) and m_rec.get("status") != l_rec.get("status"):
        return False                                       # main で却下・登録済みになった候補を手元の承認で登録しない
    strip = lambda d: {k: v for k, v in d.items() if k not in DECISION_FIELDS}   # noqa: E731
    rest = {k: v for k, v in main.items() if k != "candidates"} == {k: v for k, v in local.items() if k != "candidates"}
    return rest and mc == lc and strip(m_rec) == strip(l_rec)


def product_id_for(model: str, capacity: str) -> str:
    """既存の規則（prod_iphone17pro_256・prod_iphone17pm_256）で product_id を作る。TB は 1tb のように書く。"""
    base = re.sub(r"\s+", "", str(model or "").lower()).replace("promax", "pm")
    m = re.fullmatch(r"(\d{1,4})\s*(GB|TB)", str(capacity or "").strip(), re.I)
    if not base or not re.fullmatch(r"[a-z0-9]+", base) or not m:
        return ""
    cap = m.group(1) if m.group(2).upper() == "GB" else f"{m.group(1)}tb"
    return f"prod_{base}_{cap}"


def _q(v) -> str:
    import json
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_q(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)        # 二重引用符の文字列は YAML としても同じ値になる


def _block(entry: dict) -> str:
    keys = [k for k in FIELD_ORDER if k in entry]
    lines = [f"  - {keys[0]}: {_q(entry[keys[0]])}\n"] + [f"    {k}: {_q(entry[k])}\n" for k in keys[1:]]
    return "".join(lines)


def _products(text: str) -> list:
    import yaml
    data = yaml.safe_load(text) or {}
    return list((data.get("products") if isinstance(data, dict) else None) or [])


def _fresh(rec: dict, now: datetime) -> bool:
    try:
        last = datetime.fromisoformat(str(rec.get("last_seen_on")) + "T00:00:00").date()
    except ValueError:
        return False
    return (now.date() - last).days < st.STALE_AFTER_DAYS


def _approval_ok(rec: dict, needed: str) -> bool:
    rv = rec.get("review") or {}
    return rv.get("decision") == st.APPROVED and needed in (rv.get("evidence_checked") or [])


def plan_product(rec: dict, yaml_text: str, *, now: datetime) -> dict:
    """承認済みの Apple の候補から、正本に足す1件と差分を作る（書かない）。errors が空のときだけ登録できる。"""
    from . import apple
    errors: list[str] = []
    if rec.get("status") != st.APPROVED:
        errors.append(f"not_approved:{rec.get('status')}")
    else:
        missing = [e for e in PRODUCT_EVIDENCE if not _approval_ok(rec, e)]
        if missing:                                                # 承認で公式ページを確かめた記録が要る
            errors.append("approval_without_check:" + ",".join(missing))
    if rec.get("genre") == "tcg":
        errors.append("tcg_not_merged_into_canonical")             # TCG は既存の正本に統合しない
    if rec.get("source") != APPLE_SOURCE:
        errors.append("not_official_source")                       # 第三者の情報だけで登録しない
    if not _fresh(rec, now):
        errors.append("stale_needs_recheck")
    url = str(rec.get("official_url") or "")
    if not url.startswith(APPLE_URL_PREFIX) or (urlparse(url).hostname or "") != "www.apple.com":
        errors.append("official_url_missing")
    parts = list(rec.get("part_numbers") or [])
    if not parts or any(not PART_NUMBER.match(str(x)) for x in parts):
        errors.append("part_numbers_missing_or_invalid")           # 公式の商品データに無い型番を作らない
    model, cap = str(rec.get("model_number") or "").strip(), str(rec.get("capacity") or "").strip()
    parsed = apple.parse_name(f"{model} {cap}")
    if not parsed or parsed["capacity"] != cap or parsed["line"] != model or rec.get("product_name") != f"{model} {cap}":
        errors.append("identity_insufficient")                     # 機種・容量を名前の推測で決めない
    price = rec.get("official_price")
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0 or len(rec.get("official_prices") or []) != 1:
        errors.append("official_price_not_single")                 # 色で価格が違う・価格が無い: 決めない
    pid = product_id_for(model, cap)
    if not pid:
        errors.append("product_id_rule")
    try:
        existing = _products(yaml_text)
    except Exception:  # noqa: BLE001
        existing, errors = [], errors + ["canonical_unreadable"]
    # 重複: 同じ ID・同じ「機種 + 容量」・同じ部品番号が正本にあれば登録しない
    if rec.get("match_to_existing"):
        errors.append("duplicate_matched_existing")
    if pid and any(str(p.get("id")) == pid for p in existing if isinstance(p, dict)):
        errors.append("duplicate_product_id")
    if parsed:
        for p in existing:
            if not isinstance(p, dict) or str(p.get("genre") or "") != "iphone":
                continue
            q = apple.parse_name(re.sub(r"\s*(SIMフリー|SIM\s*free)\s*$", "", str(p.get("name") or ""), flags=re.I))
            if q and (q["line_key"], q["capacity"]) == (parsed["line_key"], parsed["capacity"]):
                errors.append("duplicate_model_capacity")
                break
    known_parts = set()
    for p in existing:
        if isinstance(p, dict):
            known_parts |= {str(p.get("model_number") or "")} | {str(x) for x in p.get("keywords") or []} | \
                {str(x) for x in p.get("part_numbers") or []}
    if any(x in known_parts for x in parts):
        errors.append("duplicate_part_number")
    jan = str(rec.get("jan") or "").strip()
    if jan and any(isinstance(p, dict) and str(p.get("jan_code") or "") == jan for p in existing):
        errors.append("duplicate_jan")
    cap_short = re.sub(r"GB$", "", cap) if cap.endswith("GB") else cap
    entry = {"id": pid, "genre": "iphone", "name": f"{model} {cap} SIMフリー", "brand": "Apple", "model_number": "",
             "retail_price": price if isinstance(price, int) else 0,
             # 先頭は容量つきの名前（API・旧来の取得の検索語になる。機種名だけにすると別の容量に当たる）。
             # 部品番号は検索のために後ろに入れる（照合には使われない）
             "keywords": ([f"{model} {cap}", f"{model} {cap_short}"] if cap_short != cap else [f"{model} {cap}"])
             + sorted(parts),
             "capacity": cap, "part_numbers": sorted(parts), "colors": sorted(rec.get("colors") or []),
             "official_url": url, "price_observed_on": str(rec.get("last_seen_on") or "")}
    out = {"candidate_id": rec.get("candidate_id"), "product_id": pid, "entry": entry, "errors": errors,
           "target": PRODUCT_TARGET, "new_text": "", "diff": ""}
    if errors:
        return out
    new_text = insert_product(yaml_text, entry, existing)
    out["new_text"] = new_text
    out["diff"] = "".join(difflib.unified_diff(yaml_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                                               fromfile=f"a/{PRODUCT_TARGET}", tofile=f"b/{PRODUCT_TARGET}"))
    return out


def insert_product(text: str, entry: dict, existing: list) -> str:
    """最後の iPhone の後ろに1件を足した正本の文字列（既存の行・コメント・並びは変えない）。"""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    iphones = [str(p.get("id")) for p in existing if isinstance(p, dict) and p.get("genre") == "iphone"]
    start = None
    if iphones:
        pat = re.compile(r'^  - id: "?' + re.escape(iphones[-1]) + r'"?\s*$')
        start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    if start is None:
        raise ValueError("canonical_iphone_anchor_not_found")
    end = start + 1
    while end < len(lines) and lines[end].startswith("    "):
        end += 1
    add = "\n" + ("" if SECTION_HEADER in text else SECTION_HEADER) + _block(entry)
    return "".join(lines[:end]) + add + "".join(lines[end:])


def verify_product_text(old_text: str, new_text: str, entry: dict) -> list[str]:
    """書く前の確かめ: YAML として読める・既存の商品は1件も変わらない・足すのは1件だけ。"""
    try:
        old, new = _products(old_text), _products(new_text)
    except Exception:  # noqa: BLE001
        return ["new_yaml_invalid"]
    errs = []
    if len(new) != len(old) + 1:
        errs.append("not_exactly_one_added")
    if [p for p in new if not (isinstance(p, dict) and p.get("id") == entry["id"])] != old:
        errs.append("existing_products_changed")
    added = [p for p in new if isinstance(p, dict) and p.get("id") == entry["id"]]
    if len(added) != 1 or added[0] != entry:
        errs.append("added_entry_mismatch")
    return errs


def write_product(path: Path, old_text: str, plan: dict) -> None:
    """正本を置き換える（確かめてから・一時ファイル経由）。途中で失敗したら元のまま。"""
    from src.utils.atomic_write import write_text_atomic
    errs = verify_product_text(old_text, plan["new_text"], plan["entry"])
    if errs:
        raise ValueError(",".join(errs))
    if Path(path).read_text(encoding="utf-8") != old_text:
        raise ValueError("canonical_changed_since_plan")
    write_text_atomic(path, plan["new_text"])


def monitoring_impact(entry: dict) -> list[str]:
    """登録したときに変わること（見込みの表示用）。"""
    return [
        f"seed で products の表に {entry['id']} が入る（商品詳細・検索に1件増える。容量・部品番号で検索できる）",
        "買取・販売の自動取得の対象にはならない（取得の対象は商品ごとの固定の表。足すときは実在の買取ページを確かめてから"
        "容量と SIM フリーを必須にした照合で別に追加する）",
        "Apple の発見は次回この「機種 + 容量」を正本と一致（MATCHED_EXISTING）にする（新しい候補を作らない）",
        f"retail_price {entry['retail_price']:,} 円は設定値の参考価格（公式の確認日 {entry['price_observed_on']}）。"
        "公式直販価格の確定（official_registry の証拠）・在庫は登録しない（在庫は不明のまま）",
        "買取・販売の観測が無いうちは利益を出さない（買取価格・販売価格を作らない）",
        "通知しない（新商品の登録は送信の理由にしない）",
    ]


# ---- イベント（TCG の告知 → 手で確認した抽選の CSV）----

def plan_event(rec: dict, csv_text: str, *, product: str, start: str, end: str, official_page_checked: bool,
               now: datetime, existing_events=()) -> dict:
    """承認済みの告知の候補から、運営者が確かめた日程で CSV に足す1行を作る（書かない）。"""
    from src.tcg.lottery import manual
    from src.tcg.models import TCG_TYPES, parse_dt
    errors: list[str] = []
    if rec.get("status") != st.APPROVED:
        errors.append(f"not_approved:{rec.get('status')}")
    elif not (_approval_ok(rec, "schedule") and _approval_ok(rec, "official_url")):
        errors.append("approval_without_schedule_check")          # 日程と公式の URL を確かめた記録が要る
    if not official_page_checked:
        errors.append("official_page_not_checked")
    if not str(rec.get("candidate_id") or "").startswith("tcg-ann-"):
        errors.append("not_announcement")                          # 自動で集めた正式なイベントは手動で重ねない
    kind = EVENT_KINDS.get(str(rec.get("kind") or ""))
    if not kind:
        errors.append(f"unsupported_event_kind:{rec.get('kind')}")
    url = str(rec.get("official_url") or "")
    if not manual.is_official_url(url):
        errors.append("official_url_missing")
    tcg = str(rec.get("tcg") or "").upper()
    if tcg not in TCG_TYPES:
        errors.append("tcg_unknown")
    if not str(product or "").strip():
        errors.append("product_required")
    ds, de = parse_dt(start or ""), parse_dt(end or "")
    # 日程は運営者が公式ページで確かめた値だけ（推測しない）。時差つきの ISO8601 で両方が要る
    # 日本の公式ページの時刻だけ（+09:00。時差なしを補わない・Z / +00:00 の取り違えで9時間ずらさない）
    tz = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?\+09:00$")
    if ds is None or de is None or not tz.match(str(start or "")) or not tz.match(str(end or "")):
        errors.append("schedule_required_iso8601_with_tz")
    elif de <= ds:
        errors.append("schedule_end_before_start")
    elif de < now:
        errors.append("schedule_already_ended")
    elif (ds - now).days > 365:
        errors.append("schedule_too_far")                         # 年の打ち間違い
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    header = next(csv.reader(io.StringIO(csv_text)), None) or list(manual.CSV_COLUMNS)
    retailer = str(rec.get("source") or "").upper()
    row = {c: "" for c in header}
    row.update({"tcg": tcg, "product": str(product or "").strip(), "retailer": retailer, "event_type": kind or "",
                "store_specific": "false", "application_start": start or "", "application_end": end or "",
                "human_confirmed": "true", "source_url": url, "verified_at": now.isoformat(timespec="seconds"),
                "verified_by": VERIFIED_BY,
                "notes": f"発見の候補 {rec.get('candidate_id')} から登録。日程は運営者が公式ページで確かめた値"})
    # 同じ抽選: 同じ店・同じ開始（分まで）で、同じ告知の URL か、正規化した商品名が同じ（表記の揺れで重ねない）。
    # 自動で集めた抽選（exports/tcg/lotteries.json の items）とも比べる
    from src.tcg.lottery.schema import product_key
    pk, s16 = product_key(row["product"]), row["application_start"][:16]
    for r in list(rows) + [{"retailer": e.get("retailer"), "source_url": e.get("source_url"),
                             "product": e.get("product_name"), "application_start": e.get("application_start")}
                            for e in existing_events or () if isinstance(e, dict)]:
        if str(r.get("retailer") or "").upper() == retailer and str(r.get("application_start") or "")[:16] == s16 \
                and (r.get("source_url") == url or product_key(str(r.get("product") or "")) == pk):
            errors.append("duplicate_event")
            break
    if not errors:
        _ev, err = manual._row_to_event(row)
        if err:
            errors.append(f"row_invalid:{err}")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator="\n")
    w.writerow(row)
    base = csv_text if (not csv_text or csv_text.endswith("\n")) else csv_text + "\n"
    if not base:
        hb = io.StringIO()
        csv.writer(hb, lineterminator="\n").writerow(header)
        base = hb.getvalue()
    new_text = base + buf.getvalue()
    return {"candidate_id": rec.get("candidate_id"), "row": row, "errors": errors, "target": EVENT_TARGET,
            "registered_id": f"{retailer}|{url}|{row['application_start']}",
            "new_text": "" if errors else new_text,
            "diff": "" if errors else "".join(difflib.unified_diff(
                csv_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
                fromfile=f"a/{EVENT_TARGET}", tofile=f"b/{EVENT_TARGET}"))}


def write_event(path: Path, old_text: str, plan: dict) -> None:
    from src.tcg.lottery import manual
    from src.utils.atomic_write import write_text_atomic
    new = list(csv.DictReader(io.StringIO(plan["new_text"])))
    old = list(csv.DictReader(io.StringIO(old_text)))
    if len(new) != len(old) + 1 or new[:-1] != old:
        raise ValueError("existing_rows_changed")
    _ev, err = manual._row_to_event(new[-1])
    if err:
        raise ValueError(f"row_invalid:{err}")
    if (Path(path).read_text(encoding="utf-8") if Path(path).exists() else "") != old_text:
        raise ValueError("csv_changed_since_plan")
    write_text_atomic(path, plan["new_text"])
