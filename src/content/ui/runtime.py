"""新UIの抽選の表示モデル（VM）と、閲覧時の状態（runtime state）。

状態の判定は既存の `src.tcg.lottery.schema.compute_lottery_status` だけを使い、新しい判定は作らない。
生成は1日1回なので、閲覧時の状態はブラウザ側の `deriveLotteryRuntimeState`
（lottery_runtime.js）で計算し直す。これは compute_lottery_status を JavaScript に移したもので、
tests/test_new_ui_runtime.py で Python 側の `derive_runtime_state` と固定時刻で一致を確かめている。

状態・カウントダウン・ボタン・件数・並び順は、すべて derive_runtime_state の結果だけから決める。
元データは変更しない（表示用に写し取るだけ）。
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from src.content.ui import status as st
from src.tcg.lottery import schema as ls
from src.tcg.lottery.manual import is_official_url
from src.tcg.models import JST, parse_dt

_WEEK = "月火水木金土日"
JS_PATH = Path(__file__).with_name("lottery_runtime.js")

# 旧来の抽選（カメラ・ゲーム機）の公式ドメイン。TCG の公式ドメイン一覧は変えずに、ここで足す
_LEGACY_OFFICIAL_DOMAINS = (
    "nintendo.co.jp", "nintendo.com", "playstation.com", "sony.jp", "sony.co.jp",
    "fujifilm-x.com", "fujifilm.com", "ricoh-imaging.co.jp", "ricohimagingstore.com", "canon.jp", "nikon-image.com",
    "apple.com",
)

# VM の日時項目（短いキー → 元の項目名）。日時は時刻が公表されているものだけ、
# 日付だけのものは *_date に入れる（時刻を作らない）
TIME_KEYS = (
    ("as", "application_start"), ("asd", "application_start_date"),
    ("ae", "application_end"), ("aed", "application_end_date"),
    ("wa", "winner_announcement_at"), ("wad", "winner_announcement_date"),
    ("ps", "purchase_start"), ("psd", "purchase_start_date"),
    ("pe", "purchase_end"), ("ped", "purchase_end_date"),
)

OPEN_STATUSES = ("OPEN", "ENDING_SOON")
# 種類（VM の k）。抽選・予約（受付期間のあるもの）と、発売日だけが公式に出ている発売待ち
KIND_LOTTERY, KIND_PREORDER, KIND_RELEASE = "lottery", "preorder", "release"
# 予約の受付は、抽選と同じ状態コードのまま文言だけ変える（予約を在庫ありとは扱わない）
PREORDER_LABELS = {"OPEN": "予約受付中", "ENDING_SOON": "予約締切間近", "UPCOMING": "予約開始待ち"}
# HOME の並び順（小さいほど上）。99 は HOME に出さない
BUCKET_ENDING, BUCKET_OPEN, BUCKET_BUY, BUCKET_UPCOMING, BUCKET_CONFLICT = 0, 1, 2, 3, 4
BUCKET_WAIT, BUCKET_SKIP = 5, 6
BUCKET_HIDDEN = 99
# 抽選・予約の件数に数える状態（「今ユーザーが確認する価値のある」もの。受付終了・終了・日程不明は数えない）
COUNTED_STATUSES = ("ENDING_SOON", "OPEN", "UPCOMING", "SOURCE_CONFLICT", "WINNER_PURCHASE_PERIOD",
                    "RESULT_PENDING", "WINNER_ANNOUNCED", "RELEASE_WAIT")


# ── URL ─────────────────────────────────────────────────────────

def safe_url(url) -> str:
    """https: の URL だけを通す（javascript: / data: / vbscript: / http: / 空は空文字）。

    ブラウザと Python で URL の解釈が食い違う書き方（バックスラッシュ・%5C・userinfo の @・空白や制御文字・
    非 ASCII）は、開かれるホストが判定と違う可能性があるので拒否する。
    """
    s = str(url or "").strip()
    if not s or not s.isascii() or any(ord(ch) <= 0x20 or ch == "\x7f" for ch in s):
        return ""
    if "\\" in s or "%5c" in s.lower():
        return ""
    try:
        p = urlparse(s)
        host = p.hostname
        port = p.port
    except ValueError:
        return ""
    if p.scheme.lower() != "https" or not host or "@" in p.netloc or port is not None:
        return ""
    if p.netloc.lower() != host:
        return ""
    return s


def is_official(url: str) -> bool:
    if not url:
        return False
    if is_official_url(url):
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in _LEGACY_OFFICIAL_DOMAINS)


def official_url(url) -> str:
    u = safe_url(url)
    return u if is_official(u) else ""


# ── 日時の正規化（推測しない） ─────────────────────────────────────

def _exact(value) -> str:
    """時刻を含む日時だけを ISO 形式（JST）にする。日付だけ・不正な値は空文字。"""
    s = str(value or "").strip()
    if len(s) < 16 or s[10] not in "T ":
        return ""
    d = parse_dt(s.replace(" ", "T", 1))
    return d.isoformat() if d else ""


def _day(value) -> str:
    s = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return ""


def _split(value) -> tuple[str, str]:
    """1つの値を (日時, 日付) に分ける（旧来の抽選の entry_end_at など）。"""
    ex = _exact(value)
    return (ex, "") if ex else ("", _day(value))


# ── VM（表示用の写し） ──────────────────────────────────────────────

def _num(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def price_text(value) -> str:
    """定価の表示。無ければ空、0 円・負・不正な値は「価格確認中」（金額を出さない）。"""
    if value is None or value == "":
        return ""
    v = _num(value)
    if v is None or v <= 0:
        return "価格確認中"
    return f"¥{int(v):,}"


def confirmation_label(ev: dict) -> str:
    """ユーザー向けの「情報の確かさ」。内部の high / medium / low はそのまま出さない。"""
    if ev.get("conflict"):
        return "日程要確認"
    if ev.get("collection_method") == "MANUAL_VERIFIED" and not ev.get("verified"):
        return "確認待ち"
    if str(ev.get("confidence") or "").lower() == "low":
        return "参考情報"
    if ev.get("verified"):
        return "公式確認済み"
    return "公式情報"


def tcg_vm(ev: dict, idx: int) -> dict:
    """TCG 抽選（exports/tcg/latest.json の lotteries の1件）→ VM。"""
    retailer = str(ev.get("retailer_name") or ev.get("retailer") or "")
    if ev.get("store_specific") and ev.get("store_name"):
        retailer = f"{retailer} {ev['store_name']}"
    conf = confirmation_label(ev)
    info = safe_url(ev.get("source_url"))
    vm = {
        "id": str(ev.get("lottery_id") or f"tcg-{idx}"),
        "src": "tcg", "cat": str(ev.get("tcg") or ""),
        "t": str(ev.get("product_name") or ""),
        "sub": retailer + (f"・{conf}" if conf in ("確認待ち", "参考情報") else ""),
        "price": price_text(ev.get("retail_price")),
        "conflict": bool(ev.get("conflict")),
        "ann": bool(ev.get("announcement_only")),
        "apply": official_url(ev.get("entry_url")),
        "info": info, "info_official": is_official(info),
        "result": official_url(ev.get("result_url")),
        "purchase": official_url(ev.get("purchase_url")),
        "conf": conf,
        # 人による確認待ちの転記・確かさが低いものには「応募する」を出さない（manual.py の方針）
        "unv": conf in ("確認待ち", "参考情報"),
        "k": KIND_PREORDER if str(ev.get("event_type") or "").upper() == "PREORDER" else KIND_LOTTERY,
        "rd": "",
    }
    for i in range(0, len(TIME_KEYS), 2):
        (s_exact, k_exact), (s_day, k_day) = TIME_KEYS[i], TIME_KEYS[i + 1]
        ex, day_from_exact = _split(ev.get(k_exact))
        vm[s_exact] = ex
        # 日時の欄に日付だけが入っている場合は日付として扱う（時刻は作らない）
        vm[s_day] = "" if ex else (_day(ev.get(k_day)) or day_from_exact)
    return vm


def legacy_id(it: dict, idx: int) -> str:
    """旧来の抽選の VM の id（照合で旧UIの判定と突き合わせるのにも使う）。"""
    return str(it.get("id") or f"legacy-{idx}")


def legacy_vm(it: dict, idx: int) -> dict:
    """旧来の抽選（カメラ・ゲーム機。lottery_events）→ VM。"""
    as_, asd = _split(it.get("entry_start_at") or it.get("entry_start"))
    ae, aed = _split(it.get("entry_end_at") or it.get("entry_end"))
    wa, wad = _split(it.get("result_announcement_at"))
    info = safe_url(it.get("url"))
    return {
        "id": legacy_id(it, idx),
        "src": "legacy", "cat": "",
        "t": str(it.get("product_name") or ""), "sub": str(it.get("brand") or ""),
        "price": "", "conflict": False, "ann": False,
        "apply": official_url(it.get("entry_form_url")),
        "info": info, "info_official": is_official(info),
        "result": "", "purchase": "", "conf": "公式情報", "unv": False,
        "as": as_, "asd": asd, "ae": ae, "aed": aed, "wa": wa, "wad": wad,
        "ps": "", "psd": "", "pe": "", "ped": "",
        "k": KIND_LOTTERY, "rd": "",
    }


def release_id(ev: dict) -> str:
    import hashlib
    key = f'{ev.get("product_name") or ""}|{ev.get("store") or ""}|{ev.get("release_date") or ""}'
    return "rel-" + hashlib.md5(key.encode("utf-8")).hexdigest()[:10]


def release_vm(ev: dict) -> dict | None:
    """公式に発売日が出ている発売予定（exports/tcg/latest.json の events の COMING_SOON）→ VM。

    使うのは、公式ドメインの https のページで、発売日（年月日）が読めるものだけ。日付に時刻を足さない。
    予約の受付期間は公式に出ていないので、予約受付中とは言わない（発売待ちとだけ出す）。
    """
    from src.tcg.product_types import parse_release_date
    if ev.get("status") != "COMING_SOON" or ev.get("stale"):
        return None
    info = official_url(ev.get("canonical_url")) or official_url(ev.get("source_url"))
    rd = parse_release_date(str(ev.get("release_date") or ""))
    if not info or not rd:
        return None
    return {
        "id": release_id(ev), "src": "release", "cat": "",
        "t": str(ev.get("product_name") or ""), "sub": "",
        "price": "", "conflict": False, "ann": False,
        "apply": "", "info": info, "info_official": True,
        "result": "", "purchase": "", "conf": "公式情報", "unv": False,
        "as": "", "asd": "", "ae": "", "aed": "", "wa": "", "wad": "",
        "ps": "", "psd": "", "pe": "", "ped": "",
        "k": KIND_RELEASE, "rd": rd[:10],
    }


def build_vms(tcg_report: dict | None, legacy_items: list | None) -> list[dict]:
    """新UIで扱う抽選の VM。終了（ENDED）は生成時点で外す（閲覧時に復活することはない）。

    同じイベントが TCG と旧来の抽選の両方に入らないよう、TCG 側を優先して商品名で重複を外す。
    """
    vms: list[dict] = []
    for i, ev in enumerate((tcg_report or {}).get("lotteries") or []):
        if isinstance(ev, dict) and ev.get("status") != "ENDED":
            vms.append(tcg_vm(ev, i))
    tcg_keys = {ls.product_key(v["t"]) for v in vms}
    seen_ids: set[str] = set()
    for i, raw in enumerate(legacy_items or []):
        try:
            it = raw if isinstance(raw, dict) else dict(raw)
        except (TypeError, ValueError):
            continue
        if it.get("reference_only"):
            continue
        vm = legacy_vm(it, i)
        # TCG 側にある商品は TCG を優先する。旧来の抽選どうしは店・期間が違えば別の抽選なので残す
        key = ls.product_key(vm["t"])
        if (key and key in tcg_keys) or vm["id"] in seen_ids:
            continue
        seen_ids.add(vm["id"])
        vms.append(vm)
    # 発売予定（公式の発売日があるもの）。同じ商品・店・発売日は1件にする
    for ev in (tcg_report or {}).get("events") or []:
        if not isinstance(ev, dict):
            continue
        vm = release_vm(ev)
        if vm and vm["id"] not in seen_ids:
            seen_ids.add(vm["id"])
            vms.append(vm)
    return vms


# ── 閲覧時の状態 ────────────────────────────────────────────────────

def _as_event(vm: dict) -> dict:
    return {key: (vm.get(short) or None) for short, key in TIME_KEYS}


def _ms(d: datetime | None) -> int | None:
    return None if d is None else int(round(d.timestamp() * 1000))


def _fmt_exact(iso: str) -> str:
    d = parse_dt(iso).astimezone(JST)
    return f"{d.month}/{d.day}({_WEEK[d.weekday()]}) {d.hour:02d}:{d.minute:02d}"


def _fmt_day(ymd: str) -> str:
    d = date.fromisoformat(ymd)
    return f"{d.month}/{d.day}({_WEEK[d.weekday()]})"


def _when(vm: dict, exact_key: str, day_key: str, suffix: str) -> str:
    if vm.get(exact_key):
        return f"{_fmt_exact(vm[exact_key])} {suffix}"
    if vm.get(day_key):
        return f"{_fmt_day(vm[day_key])} {suffix}・時刻未公表"
    return ""


def countdown_text(target_ms: int, now_ms: int) -> str:
    """残り時間（日・時間・分のどれか1つ）。秒は出さない。"""
    diff = target_ms - now_ms
    if diff <= 0:
        return ""
    if diff >= 86_400_000:
        return f"{diff // 86_400_000}日"
    if diff >= 3_600_000:
        return f"{diff // 3_600_000}時間"
    return f"{max(diff // 60_000, 1)}分"


def _info_cta(vm: dict, style: str = "secondary") -> dict | None:
    if not vm.get("info"):
        return None
    return {"kind": "info", "label": "公式情報を見る" if vm.get("info_official") else "情報元を見る",
            "url": vm["info"], "style": style, "track": "lottery_info_click"}


def _release_state(vm: dict, now: datetime) -> dict:
    """発売待ち（発売日だけが公式に出ているもの）。発売日の 0 時を過ぎたら一覧から外す（在庫は確認していない）。"""
    now_ms = _ms(now)
    rd = vm.get("rd") or ""
    day0 = datetime.fromisoformat(rd + "T00:00:00+09:00") if rd else None
    waiting = day0 is not None and now < day0
    status = "RELEASE_WAIT" if waiting else ("ENDED" if day0 is not None else "UNKNOWN")
    s = st.get(status)
    rest = countdown_text(_ms(day0), now_ms) if waiting else ""
    return {
        "status": status, "label": s.label, "icon": s.icon, "tone": s.tone,
        "when": f"{_fmt_day(rd)} 発売予定" if waiting else ("発売日を過ぎました" if day0 else "日程は未公表です"),
        "cd_text": f"発売まで あと{rest}" if rest else "",
        "cta": _info_cta(vm),
        "bucket": BUCKET_WAIT if waiting else BUCKET_HIDDEN, "sort": _ms(day0) if waiting else 0,
        "open": False, "ending_today": False, "starting_24h": False, "upcoming": False,
    }


def derive_runtime_state(vm: dict, now: datetime) -> dict:
    """抽選1件の閲覧時の状態。状態・残り時間・ボタン・件数・並び順はこの結果だけで決める。"""
    now = now.astimezone(JST)
    if vm.get("k") == KIND_RELEASE:
        return _release_state(vm, now)
    now_ms = _ms(now)
    preorder = vm.get("k") == KIND_PREORDER
    ev = _as_event(vm)
    base = ls.compute_lottery_status(ev, now)
    # 公式情報が食い違うものは、時刻が進んでも受付中にしない
    status = "SOURCE_CONFLICT" if vm.get("conflict") else base
    s_passed, _s_not_yet = ls._bound(ev, "application_start", "application_start_date")
    e_passed, e_not_yet = ls._bound(ev, "application_end", "application_end_date")
    is_open = status in OPEN_STATUSES

    # ── ボタン（1カード1つ） ──
    cta = None
    if is_open:
        # 「応募する」: 公式の https URL・開始時刻を過ぎた・締切前と言い切れる（日付だけの締切は
        # 締切日の 0 時まで）・日程の食い違いが無い、をすべて満たすときだけ
        if (vm.get("apply") and not vm.get("unv") and s_passed is not None and now >= s_passed
                and e_not_yet is not None and now < e_not_yet):
            cta = {"kind": "apply", "label": "予約する" if preorder else "応募する", "url": vm["apply"],
                   "style": "primary", "track": "lottery_apply_click"}
        else:
            # 確認待ちは「応募する」と見間違えないよう控えめなボタンにする
            cta = _info_cta(vm, "secondary" if vm.get("unv") else "primary")
    elif status == "WINNER_PURCHASE_PERIOD":
        if vm.get("purchase"):
            cta = {"kind": "purchase", "label": "購入ページ（当選者のみ）", "url": vm["purchase"],
                   "style": "primary", "track": "lottery_purchase_click"}
        elif vm.get("result"):
            cta = {"kind": "result", "label": "結果を確認", "url": vm["result"],
                   "style": "primary", "track": "lottery_result_click"}
        else:
            cta = _info_cta(vm)
    elif status in ("RESULT_PENDING", "WINNER_ANNOUNCED") and vm.get("result"):
        cta = {"kind": "result", "label": "結果を確認", "url": vm["result"], "style": "secondary",
               "track": "lottery_result_click"}
    else:
        # UPCOMING・日程要確認・終了・不明: 公式情報だけ（応募・購入のボタンは出さない）
        cta = _info_cta(vm)

    # ── 日時の文言・残り時間 ──
    cd_prefix, cd_key = "", ""
    if is_open:
        when, cd_prefix, cd_key = _when(vm, "ae", "aed", "締切"), "締切まで", "ae"
    elif status == "UPCOMING":
        when, cd_prefix, cd_key = _when(vm, "as", "asd", "開始"), "開始まで", "as"
    elif status == "WINNER_PURCHASE_PERIOD":
        when, cd_prefix, cd_key = _when(vm, "pe", "ped", "購入期限"), "購入期限まで", "pe"
    elif status == "RESULT_PENDING":
        when = _when(vm, "wa", "wad", "当選発表") or "当選発表待ち"
    elif status == "WINNER_ANNOUNCED":
        when = "当選発表済み"
    elif status == "CLOSED":
        when = _when(vm, "ae", "aed", "受付終了") or "受付終了"
    elif status == "ENDED":
        when = "終了しました"
    elif status == "SOURCE_CONFLICT":
        when = "日程は公式情報でご確認ください"
    else:
        when = "日程は未公表です"
    cd_text = ""
    if cd_key and vm.get(cd_key):
        rest = countdown_text(_ms(parse_dt(vm[cd_key])), now_ms)
        cd_text = f"{cd_prefix} あと{rest}" if rest else ""

    # ── HOME の件数・並び順 ──
    today = now.date().isoformat()
    ae_day = parse_dt(vm["ae"]).astimezone(JST).date().isoformat() if vm.get("ae") else vm.get("aed")
    as_ms = _ms(parse_dt(vm["as"])) if vm.get("as") else None
    counted = not vm.get("ann")
    ending_today = counted and is_open and ae_day == today
    # 「まもなく開始」は抽選だけ（予約開始待ちは数えない）
    starting_24h = counted and not preorder and status == "UPCOMING" and (
        (as_ms is not None and as_ms - now_ms <= 86_400_000)
        or (as_ms is None and vm.get("asd") == today))
    if not counted:
        bucket, sort = BUCKET_HIDDEN, 0
    elif status == "ENDING_SOON":
        bucket, sort = BUCKET_ENDING, _ms(e_passed) or 0
    elif status == "OPEN":
        bucket, sort = BUCKET_OPEN, _ms(e_passed) or 0
    elif status == "UPCOMING":
        bucket, sort = BUCKET_UPCOMING, _ms(_s_not_yet) or 0
    elif status == "SOURCE_CONFLICT":
        # 日程要確認は受付中には数えないが、存在に気づけるよう HOME に出す（ボタンは公式情報だけ）
        bucket, sort = BUCKET_CONFLICT, 0
    elif status == "WINNER_PURCHASE_PERIOD":
        # 当選者の購入期限が残っているもの（購入期限が近い順）
        bucket, sort = BUCKET_BUY, _ms(ls._bound(ev, "purchase_end", "purchase_end_date")[0]) or 0
    elif status in ("RESULT_PENDING", "WINNER_ANNOUNCED"):
        bucket, sort = BUCKET_WAIT, _ms(e_passed) or 0
    else:
        bucket, sort = BUCKET_HIDDEN, 0
    s = st.get(status)
    label = PREORDER_LABELS.get(status, s.label) if preorder else s.label
    tone = s.tone
    unconfirmed = bool(vm.get("unv")) and is_open
    if unconfirmed:
        # 人の確認がまだの告知は「受付中」と言い切らない（応募ボタンも出さない）
        label, tone = f"{label}（確認待ち）", "warning"
    return {
        "status": status, "label": label, "icon": s.icon, "tone": tone,
        "when": when, "cd_text": cd_text, "cta": cta,
        "bucket": bucket, "sort": sort,
        # 「抽選受付中」の件数は抽選だけ（予約の受付は数えない）
        "open": counted and is_open and not preorder and not unconfirmed, "ending_today": ending_today,
        "starting_24h": starting_24h, "upcoming": counted and not preorder and status == "UPCOMING",
    }


def next_start_note(vms: list[dict], states: dict[str, dict]) -> str:
    """受付中が0件のときにタイルへ添える「次: 10/2(金) 12:00 開始」。"""
    ups = [v for v in vms if states[v["id"]]["upcoming"]]
    if not ups:
        return ""
    v = min(ups, key=lambda v: (states[v["id"]]["sort"], v["id"]))
    if v.get("as"):
        return f"次: {_fmt_exact(v['as'])} 開始"
    if v.get("asd"):
        return f"次: {_fmt_day(v['asd'])} 開始"
    return ""


def config() -> dict:
    """ブラウザ側の判定に渡す定数（Python 側の定数・対応表と同じ値）。"""
    return {
        "ending_soon_ms": int(ls.ENDING_SOON_WINDOW / timedelta(milliseconds=1)),
        "closed_ms": int(ls.CLOSED_RETENTION / timedelta(milliseconds=1)),
        "start_only_ms": int(ls.START_ONLY_RETENTION / timedelta(milliseconds=1)),
        "preorder_labels": PREORDER_LABELS,
        "statuses": {k: {"label": s.label, "icon": s.icon, "tone": s.tone}
                     for k, s in st.STATUSES.items()},
    }


def data_json(vms: list[dict]) -> str:
    """<script type="application/json"> に入れる JSON（</script> で閉じられないようにする）。"""
    raw = json.dumps({"vms": vms, "cfg": config()}, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def runtime_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")
