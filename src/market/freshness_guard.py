"""鮮度の偽装（値が変わっていないのに観測日時だけ新しくした更新）を見つける。

手動で管理する CSV（data/manual_*.csv など）では、価格・状態・URL・根拠が同じなのに
observed_at だけを新しくすると、古い値が「最近確認した値」に見えてしまう。
このモジュールは、2つの版の CSV を比べて、そうした行を一覧にする。

- 自動取得の行（data_source が auto_scraped など）は対象外。取得のたびに観測日時が変わるのは正しい
- 人が再確認した場合は、observed_at ではなく verified_at（確認日）を別に持つこと
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

# 観測日時の列（ファイルごとに列名が違う）
TIMESTAMP_FIELDS = ("observed_at", "checked_at", "recorded_at", "reported_at")
# 自動取得とみなす data_source（観測日時が毎回変わってよい）
AUTO_SOURCES = frozenset({
    "auto_scraped", "fetch_failed", "product_not_listed", "suspicious_rejected", "api", "html",
})
# 行を同一とみなすキーの候補（ファイルにある列だけ使う）
KEY_CANDIDATES = (
    "product_alias", "product_id", "buyback_shop", "shop", "shop_name", "source", "platform",
    "market", "price_type", "is_sold", "currency", "condition", "event_id", "lottery_id",
    "product_name", "product", "retailer", "store_name", "tcg", "shrink_status",
)
# 手動で管理する CSV（検査の対象）。自動で追記する履歴（overseas_price_history.csv 等）は含めない
MANUAL_CSV_GLOBS = ("data/manual_*.csv", "data/tcg_secondary_prices.csv",
                    "data/tcg_restock_reports.csv", "data/tcg_verified_lotteries.csv")


@dataclass(frozen=True)
class Violation:
    file: str
    key: tuple
    old_ts: str
    new_ts: str


# 「データ値・根拠」とみなす列（これが同じなら、日時だけの更新とみなす）。
# confidence やメモなど価格と関係ない列を変えても、値が同じなら日時だけの更新として扱う
EVIDENCE_FIELDS = (
    "buyback_price", "price", "sale_price", "price_local", "currency", "condition", "url",
    "item_url", "source_url", "entry_url", "is_sold", "price_type", "price_basis", "shrink_status",
    "application_start", "application_end", "retail_price", "quantity_if_known", "text",
)


def _parse_ts(value: str):
    """日時を比較できる形にする（タイムゾーン付きは JST に揃える。読めなければ文字列のまま）。"""
    from datetime import datetime, timedelta, timezone
    s = (value or "").strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    jst = timezone(timedelta(hours=9))
    return (d if d.tzinfo else d.replace(tzinfo=jst)).astimezone(jst)


def _norm(value) -> str:
    """比較用に値を正規化する（「428,000」「¥428000」→「428000」、URL のクエリは比べない）。"""
    s = (value or "").strip()
    digits = s.replace(",", "").replace("¥", "").replace("￥", "").replace("円", "")
    if digits.replace(".", "", 1).isdigit():
        return str(float(digits))
    if s.startswith("http"):
        return s.split("?", 1)[0].rstrip("/")
    return s


def _rows(text: str) -> list[dict]:
    """CSV を読む。先頭の「#」で始まるコメント行は読み飛ばす。"""
    lines = [ln for ln in (text or "").splitlines() if not ln.lstrip().startswith("#")]
    return list(csv.DictReader(io.StringIO("\n".join(lines))))


def _ts_field(header: list[str]) -> str | None:
    return next((f for f in TIMESTAMP_FIELDS if f in header), None)


def _is_auto(row: dict) -> bool:
    return (row.get("data_source") or "").strip() in AUTO_SOURCES


def timestamp_only_updates(old_text: str, new_text: str, file: str = "") -> list[Violation]:
    """old → new で「タイムスタンプ以外が同じなのに、タイムスタンプが新しくなった」手動の行を返す。"""
    old_rows, new_rows = _rows(old_text), _rows(new_text)
    if not old_rows or not new_rows:
        return []
    header = list(new_rows[0].keys())
    ts = _ts_field(header)
    if not ts:
        return []
    keys = [k for k in KEY_CANDIDATES if k in header]
    if not keys:
        return []
    values = [c for c in header if c in EVIDENCE_FIELDS] or [c for c in header if c != ts]

    def key_of(r):
        return tuple((r.get(k) or "").strip() for k in keys)

    old_by_key: dict[tuple, list[dict]] = {}
    for r in old_rows:
        old_by_key.setdefault(key_of(r), []).append(r)
    out = []
    for r in new_rows:
        for o in old_by_key.get(key_of(r), []):
            # 自動取得の再観測（古い行も新しい行も自動取得）は対象外。
            # 手動の行を data_source だけ auto_scraped に書き換えた場合は対象にする
            if _is_auto(r) and _is_auto(o):
                continue
            same_values = all(_norm(o.get(c)) == _norm(r.get(c)) for c in values)
            old_ts, new_ts = (o.get(ts) or "").strip(), (r.get(ts) or "").strip()
            if not (same_values and old_ts and new_ts):
                continue
            a, b = _parse_ts(old_ts), _parse_ts(new_ts)
            newer = (b > a) if type(a) is type(b) else (new_ts > old_ts)
            if newer:
                out.append(Violation(file, key_of(r), old_ts, new_ts))
                break
    return out
