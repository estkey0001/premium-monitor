"""買取起点の候補の選別（triage）と、上位 50 件の調査の待ち行列（Market Research Coverage Wave 2）。

買取の一覧の行（正本に無い商品を含む）は数百件になる。全部を人に見せず、次の5つの決まった点で分ける:

1. 識別子（JAN・メーカーの部品番号・型番コード。名前だけは候補にしない）
2. カテゴリ（スマホ・カメラ・ゲーム・PC/電子機器を優先。アクセサリ・曖昧なセットは後回し）
3. 新しさ（買取の価格を取得した日。新しいほど高く、古い・不明は低く）
4. 小売の価格を引ける見込み（対応する小売の取得器がある・部品番号から公式の価格が引ける）
5. 価格差の見込み（小売の価格が分かるときだけ。買取の価格の大きさは「調べる価値」としてだけ加点）

結果は HIGH / MEDIUM / LOW / REJECTED。**AI の予測価格は使わない**（決まった式だけ）。確定の利益ではなく、
個別の候補は非公開（.private）に置く。公開してよいのは件数だけ。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

HIGH, MEDIUM, LOW, REJECTED = "HIGH", "MEDIUM", "LOW", "REJECTED"
TIERS = (HIGH, MEDIUM, LOW, REJECTED)
TOP_QUEUE_SIZE = 50

CAT_SMARTPHONE, CAT_CAMERA, CAT_GAME, CAT_PC = "smartphone", "camera", "game", "pc_electronics"
CAT_ACCESSORY, CAT_BUNDLE, CAT_OTHER = "accessory", "vague_bundle", "other"
PRIORITY_CATEGORIES = (CAT_SMARTPHONE, CAT_CAMERA, CAT_GAME, CAT_PC)
_CATEGORY_POINTS = {CAT_SMARTPHONE: 20, CAT_CAMERA: 20, CAT_GAME: 20, CAT_PC: 15, CAT_OTHER: 5}

# 名前からの分類（決まった語だけ。付属品・曖昧なセットは先に判定して優先カテゴリから外す）
_ACCESSORY_RE = re.compile(r"ケース|カバー|フィルム|保護|ガラス|ケーブル|充電器|アダプタ|バンド|ストラップ|スタンド|リング|ホルダー|"
                           r"替え?刃|バッテリー|キャップ|フード|フィルター|三脚|ポーチ|バッグ|イヤーチップ|交換用|周辺機器|アクセサリ|フラッシュ")
_BUNDLE_RE = re.compile(r"まとめ|福袋|セット売り|詰め合わせ|ジャンク|訳あり")
_SMARTPHONE_RE = re.compile(r"iPhone|Pixel|Galaxy|Xperia|Xiaomi|Redmi|AQUOS|OPPO|Reno|arrows|Nothing Phone|ROG Phone", re.I)
_CAMERA_RE = re.compile(r"\bEOS\b|Nikon|ニコン|キヤノン|Canon|\bZ ?(?:\d|f|fc)|ILCE|ILME|α\s?\d|FUJIFILM|富士フイルム|X100|X-[TSHE]\d|"
                        r"GFX|RICOH|リコー|\bGR ?(?:IV|III|II)|LUMIX|ルミックス|OM SYSTEM|Leica|ライカ|GoPro|Osmo|DJI|Insta360|"
                        r"PowerShot|COOLPIX|インスタックス|instax|チェキ|カメラ|VLOGCAM|サイバーショット|DSC-|PENTAX|PIXPRO|ZV-|\bD\d{3,4}\b", re.I)
_GAME_RE = re.compile(r"PlayStation|プレイステーション|PS ?5|PS ?VR|Switch|Xbox|Steam Deck|ROG Ally|Legion Go|ニンテンドー|Nintendo|DualSense", re.I)
_PC_RE = re.compile(r"MacBook|Mac mini|Mac Studio|iMac|iPad|Apple Watch|AirPods|Surface|ThinkPad|Vision Pro|Quest ?\d|"
                    r"Kindle|Kobo|Fire HD|タブレット|ヘッドホン|ノートPC|パソコン|Ryzen|GeForce|RTX ?\d|Radeon|SSD|ディスプレイ", re.I)


def classify_category(name: str) -> str:
    """名前から品目を分ける。付属品・曖昧なセットを先に外す（iPhone ケースを「スマホ」にしない）。"""
    n = str(name or "")
    if _BUNDLE_RE.search(n):
        return CAT_BUNDLE
    if _ACCESSORY_RE.search(n):
        return CAT_ACCESSORY
    for cat, rx in ((CAT_SMARTPHONE, _SMARTPHONE_RE), (CAT_CAMERA, _CAMERA_RE), (CAT_GAME, _GAME_RE), (CAT_PC, _PC_RE)):
        if rx.search(n):
            return cat
    return CAT_OTHER


def _parse_ts(value, now: datetime):
    s = str(value or "").strip().replace(" JST", "")
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None and now.tzinfo is not None:
        d = d.replace(tzinfo=now.tzinfo)
    elif d.tzinfo is not None and now.tzinfo is None:
        d = d.replace(tzinfo=None)
    return d


def currentness_points(observed_at, now: datetime) -> tuple[int, str]:
    """買取の価格を取得した日の新しさ。取得した日が読めない・未来・14 日超は 0 点（古い扱い。新しく見せない）。"""
    at = _parse_ts(observed_at, now)
    if at is None:
        return 0, "unknown"
    age = now - at
    if age < timedelta(hours=-1):
        return 0, "future"
    if age <= timedelta(days=3):
        return 20, "fresh"
    if age <= timedelta(days=14):
        return 10, "recent"
    return 0, "stale"


def _value_points(price: int) -> int:
    """買取の価格の大きさ（調べる価値）。価格差の予測ではない。"""
    return 15 if price >= 100_000 else 10 if price >= 50_000 else 5 if price >= 20_000 else 0


IDENTITY_POINTS = {"JAN": 40, "PART_NUMBER": 40, "MODEL_CODE": 20}
LOOKUP_READY_POINTS = 25         # 小売の取得器が対応していて、同じ識別子で価格を引ける見込み（引けたかどうかは別）
LOOKUP_MATCHED_POINTS = 30       # 実際に小売の価格を同一性つきで引けた
HIGH_MIN_PRICE = 50_000          # 買取の価格がこれ以上（調べる価値の下限）


def triage_row(*, name: str, ident_basis: str, price: int, observed_at, now: datetime,
               lookup_ready: bool = False, lookup_matched: bool = False) -> dict:
    """1件の候補を選別する。点の内訳（why）を必ず返す（なぜその順位か人が追える）。

    REJECTED: 付属品・曖昧なセット・古い/不明な取得日（14日超）・識別子なし。LOW は優先カテゴリ外か点が足りないもの。
    """
    cat = classify_category(name)
    cur_pts, cur = currentness_points(observed_at, now)
    why: list[str] = []
    if ident_basis not in IDENTITY_POINTS:
        return {"tier": REJECTED, "score": 0, "category": cat, "currentness": cur, "why": ["no_exact_identity"]}
    if cat in (CAT_ACCESSORY, CAT_BUNDLE):
        return {"tier": REJECTED, "score": 0, "category": cat, "currentness": cur, "why": [f"category_{cat}"]}
    if cur in ("stale", "unknown", "future"):
        return {"tier": REJECTED, "score": 0, "category": cat, "currentness": cur, "why": [f"buyback_{cur}"]}
    score = IDENTITY_POINTS[ident_basis]
    why.append(f"identity_{ident_basis}+{score}")
    cp = _CATEGORY_POINTS[cat]
    score += cp
    why.append(f"category_{cat}+{cp}")
    score += cur_pts
    why.append(f"buyback_{cur}+{cur_pts}")
    lp = LOOKUP_MATCHED_POINTS if lookup_matched else (LOOKUP_READY_POINTS if lookup_ready else 0)
    if lp:
        score += lp
        why.append(("lookup_matched+" if lookup_matched else "lookup_ready+") + str(lp))
    vp = _value_points(int(price or 0))
    if vp:
        score += vp
        why.append(f"buyback_value+{vp}")
    # 点は並べ替えに使う。段階は証拠で決める（買取の価格が新しい商品は全部が高得点になるため、点だけでは絞れない）:
    #   HIGH   = 優先カテゴリ・新しい買取・JAN/部品番号で識別でき、小売の価格を引けた（または引ける見込みで買取の価格が 5 万円以上）
    #   MEDIUM = 優先カテゴリで、小売の価格を引ける見込みがある・引けた・買取の価格が 5 万円以上
    #   LOW    = それ以外
    priority = cat in PRIORITY_CATEGORIES
    exact = ident_basis in ("JAN", "PART_NUMBER")
    if priority and cur == "fresh" and exact and (lookup_matched or (lookup_ready and int(price or 0) >= HIGH_MIN_PRICE)):
        tier = HIGH
    elif priority and (lookup_ready or lookup_matched or int(price or 0) >= HIGH_MIN_PRICE):
        tier = MEDIUM
    else:
        tier = LOW
    return {"tier": tier, "score": score, "category": cat, "currentness": cur, "why": why}


def triage(candidates: list[dict], now: datetime, *, lookup_ready_of=None, lookup_results: dict | None = None) -> dict:
    """買取起点の候補（rank_product_candidates の行）を選別し、上位 50 件の待ち行列を作る。

    - lookup_ready_of(candidate) -> bool: 小売の取得器が対応しているか（無ければ False）
    - lookup_results: 候補 ID → 小売の照会の結果（status が MATCHED のものだけ、価格を引けた扱い）
    - 並びは (点の大きい順, 買取の価格の大きい順, candidate_id)。同点でも決まった順
    """
    results = lookup_results or {}
    rows = []
    counts = {t: 0 for t in TIERS}
    by_cat: dict[str, int] = {}
    ready = matched = 0
    for c in candidates:
        cid = c.get("candidate_id", "")
        if c.get("status") == "REJECTED":
            # 照会の結果、価格差が無かった行（NO_SPREAD）は、調べる価値のある候補にしない（待ち行列・HIGH に入れない）
            counts[REJECTED] += 1
            cat = classify_category(c.get("name", ""))
            by_cat[cat] = by_cat.get(cat, 0) + 1
            matched += int(bool((results.get(cid) or {}).get("status") == "MATCHED"))
            rows.append({**c, "triage": {"tier": REJECTED, "score": 0, "category": cat, "currentness": "", "why": ["lookup_no_spread"]},
                         "lookup_ready": False})
            continue
        is_ready = bool(lookup_ready_of(c)) if lookup_ready_of else False
        is_matched = (results.get(cid) or {}).get("status") == "MATCHED"
        ready += int(is_ready)
        matched += int(is_matched)
        t = triage_row(name=c.get("name", ""), ident_basis=c.get("identity_basis", ""), price=int(c.get("observed_sell_price") or 0),
                       observed_at=c.get("observed_at"), now=now, lookup_ready=is_ready, lookup_matched=is_matched)
        counts[t["tier"]] += 1
        by_cat[t["category"]] = by_cat.get(t["category"], 0) + 1
        rows.append({**c, "triage": t, "lookup_ready": is_ready})
    queue = [r for r in rows if r["triage"]["tier"] in (HIGH, MEDIUM)]
    queue.sort(key=lambda r: (-r["triage"]["score"], -int(r.get("observed_sell_price") or 0), r.get("candidate_id", "")))
    queue = queue[:TOP_QUEUE_SIZE]
    for i, r in enumerate(queue, 1):
        r["queue_rank"] = i
    stats = {"triaged": len(rows), "tier_counts": counts, "category_counts": by_cat,
             "lookup_ready": ready, "lookup_matched": matched, "top_queue": len(queue)}
    return {"rows": rows, "queue": queue, "stats": stats}
