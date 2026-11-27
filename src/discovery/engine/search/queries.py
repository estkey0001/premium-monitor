"""商品起点の検索クエリ（商品名の本体・型番 × 抽選・予約などの語）。通信しない。

- 素材: 商品マスターの名前の本体（「」の中）・型番（【OP-19】等）・登録済みの別名（aliases。無ければ使わない）
- 語: 抽選／抽選販売／予約／予約受付／店頭抽選／オンライン抽選／再販／入荷／当選発表／BOX販売／買取
  （買取は抽選の関門に合わないので purpose="buyback" として別の系統に回す）
- 段（tier）: 1 = 発売 -7〜+30 日か受付中・開始前の抽選がある商品（全部の語・毎日）、
  2 = 発売 -30〜+90 日（抽選・予約・再販・3 日に 1 回）、3 = それ以外（再販だけ・7 日に 1 回）
- 上限は抽選の発見のクエリだけで数え、段ごとに最低の枠を取る。今日使わない分は件数を返し、同じ段の中の順番を日ごとに回して翌日以降に使う
検索の結果は URL の手掛かりだけで、スニペット・タイトルは扱わない（search/base.SearchHit）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

QUERY_WORDS: tuple[str, ...] = ("抽選", "抽選販売", "予約", "予約受付", "店頭抽選", "オンライン抽選", "再販", "入荷",
                                "当選発表", "BOX販売", "買取")
TIER2_WORDS: tuple[str, ...] = ("抽選", "予約", "再販")
TIER3_WORDS: tuple[str, ...] = ("再販",)
TIER_EVERY_DAYS = {1: 1, 2: 3, 3: 7}
ACTIVE_STATES = ("OPEN", "ENDING_SOON", "UPCOMING")
_CORE = re.compile(r"「([^」]{2,40})」")
_CODE = re.compile(r"【\s*([A-Z]{1,4}\d?-\d{1,3})\s*】|\b([A-Z]{2,4}-\d{2,3})\b")


@dataclass(frozen=True)
class SearchQuery:
    query_id: str
    text: str
    product_id: str
    word: str
    form: str            # name / code / alias
    tier: int
    purpose: str         # lottery / buyback


def _stable(*parts) -> str:
    import hashlib
    return "q-" + hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def _day(v) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(v)[:10]).date() if v else None
    except ValueError:
        return None


def seeds_of(product: dict) -> list[tuple[str, str]]:
    """[(form, 文字)]。名前の本体（「」の中。無ければ名前そのもの）・型番・登録済みの別名。"""
    name = str(product.get("name") or "")
    out: list[tuple[str, str]] = []
    cores = _CORE.findall(name)
    core = cores[-1] if cores else re.sub(r"【[^】]*】", "", name).strip()
    if core:
        out.append(("name", core))
    code = str(product.get("product_code") or "")
    if not code:
        m = _CODE.search(name)
        code = (m.group(1) or m.group(2)) if m else ""
    if code:
        out.append(("code", code.upper()))
    for a in product.get("aliases") or []:
        if isinstance(a, str) and a.strip():
            out.append(("alias", a.strip()))
    seen, uniq = set(), []
    for f, t in out:
        if t not in seen:
            seen.add(t)
            uniq.append((f, t))
    return uniq


def select_products(products: list[dict], lotteries: list[dict], *, today: date) -> list[tuple[dict, int]]:
    """[(商品, 段)]。受付中・開始前の抽選がある商品と、発売が近い商品ほど上の段。"""
    active = {e.get("product_id") for e in lotteries or [] if isinstance(e, dict) and e.get("status") in ACTIVE_STATES}
    out = []
    for p in products or []:
        if not isinstance(p, dict) or not p.get("product_id"):
            continue
        rd = _day(p.get("release_date"))
        days = (rd - today).days if rd else None
        # days = 発売日 − 今日（負は発売済み）
        if p["product_id"] in active or (days is not None and -7 <= days <= 30):
            tier = 1
        elif days is not None and -30 <= days <= 90:
            tier = 2
        else:
            tier = 3
        out.append((p, tier))
    return out


def build_queries(selected: list[tuple[dict, int]], *, today: date) -> list[SearchQuery]:
    """段ごとの語と曜日の回し方でクエリを作る（段 2・3 は product_id と日付で回す）。"""
    out = []
    for p, tier in selected:
        every = TIER_EVERY_DAYS[tier]
        if every > 1 and (today.toordinal() + sum(map(ord, p["product_id"]))) % every:
            continue
        words = QUERY_WORDS if tier == 1 else TIER2_WORDS if tier == 2 else TIER3_WORDS
        for form, seed in seeds_of(p):
            for w in words:
                out.append(SearchQuery(query_id=_stable(p["product_id"], w, form, seed), text=f"\"{seed}\" {w}",
                                       product_id=p["product_id"], word=w, form=form, tier=tier,
                                       purpose="buyback" if w == "買取" else "lottery"))
    return out


TIER_SHARE = {1: 0.6, 2: 0.25, 3: 0.15}          # 段ごとの最低の枠（上限に対する割合）。余った枠はほかの段に回す


def apply_budget(queries: list[SearchQuery], *, max_per_day: int,
                 today: Optional[date] = None) -> tuple[list[SearchQuery], list[SearchQuery]]:
    """(今日使う, 今日は使わない)。抽選の発見のクエリだけを数える（買取のクエリは別の系統なので枠を使わない・返さない）。

    段ごとに最低の枠（TIER_SHARE）を取り、余りは段の小さい順に回す（段 1 だけで枠が埋まり、段 2・3 が使われ続けないことを防ぐ）。
    同じ段の中の順番は日ごとに回すので、今日使わなかったクエリも翌日以降に使われる（持ち越しの状態は保存しない）。
    """
    import hashlib
    day = (today or date.today()).toordinal()

    def rot(q):
        return hashlib.sha1(f"{day}|{q.query_id}".encode("utf-8")).hexdigest()
    lot = [q for q in queries if q.purpose == "lottery"]
    by_tier = {t: sorted([q for q in lot if q.tier == t], key=rot) for t in (1, 2, 3)}
    use: list[SearchQuery] = []
    for t in (1, 2, 3):
        quota = int(max_per_day * TIER_SHARE[t])
        use += by_tier[t][:quota]
        by_tier[t] = by_tier[t][quota:]
    for t in (1, 2, 3):                                 # 余った枠を段の小さい順に
        room = max_per_day - len(use)
        if room <= 0:
            break
        use += by_tier[t][:room]
        by_tier[t] = by_tier[t][room:]
    later = [q for t in (1, 2, 3) for q in by_tier[t]]
    return use, later
