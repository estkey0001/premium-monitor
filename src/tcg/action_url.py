"""TCG イベントの応募先（告知の URL と応募の URL の分離）・応募の経路・要件・完成度（Coverage Wave 7a）。

- **告知の URL**（announcement_url）= 情報元の告知ページ（`source_url`）。告知があるだけでは応募できると扱わない。
- **応募の URL**（application_url）= 公式に確認できた `entry_url` で、**取得元の公式ドメインにある https の URL だけ**。
  外部の応募フォーム（LivePocket など）は公式の告知からリンクされていても公式ドメインではないので application_url にしない
  （`external_entry_url` として運営者向けに残し、`EXTERNAL_FORM` と分けて数える）。確認できなければ None（作らない・推測しない）。
- **応募の経路**（channel）: 公式サイトの応募ページ・外部フォーム・アプリ・SNS（X のフォロー＆リポスト）・会員ログイン・店頭・不明。
  取得元ごとの経路は、登録簿に記録した調査（取得日つきの note）に基づく。イベントに応募ページの URL か要件の明記があれば、そちらを優先する。
- **要件**（requirements）: 会員・アプリ・購入履歴・本人確認・店頭受取・SNS。明記があるものだけ（無いものを False と決めつけない）。
- **完成度**（quality）: complete / partial / review_required。内部向けのみ。顧客向けの確定表現には使わない。
  complete は 7 項目（商品・小売・応募開始・応募終了・当選発表・購入期間・応募の URL）がすべて揃い、日程に矛盾が無いものだけ。
  日程の矛盾・商品の同一性の食い違いは review_required（推測で直さない）。

個別のイベントは非公開（.private）。公開してよいのは件数だけ。購入・応募の自動実行はしない。
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

from src.tcg import event_quality as eq
from src.tcg.detection_delay import specific_url
from src.tcg.lottery.registry import SOURCE_BY_ID
from src.tcg.lottery.schema import OFFICIAL_LOTTERY_SOURCES

CH_WEB_OFFICIAL = "WEB_OFFICIAL_FORM"      # 公式ドメインの応募ページ（application_url がある）
CH_EXTERNAL_FORM = "EXTERNAL_FORM"         # 外部の応募フォーム（公式ドメインではない。application_url にしない）
CH_APP = "APP"                             # 店・事業者のアプリでの応募
CH_SNS = "SNS"                             # X などのフォロー＆リポスト
CH_MEMBER_LOGIN = "MEMBER_LOGIN"           # 会員ログインが必要な通販の応募（応募そのものは取らない）
CH_STORE_COUNTER = "STORE_COUNTER"         # 店頭での受付
CH_UNKNOWN = "UNKNOWN"                     # 経路を確認できていない
CHANNELS = (CH_WEB_OFFICIAL, CH_EXTERNAL_FORM, CH_APP, CH_SNS, CH_MEMBER_LOGIN, CH_STORE_COUNTER, CH_UNKNOWN)

# 取得元ごとの応募の経路（登録簿 `registry.LOTTERY_SOURCES` の note に取得日つきで記録した調査の結論）。
# ここに無い取得元は UNKNOWN（推測で埋めない）。
SOURCE_CHANNEL: dict[str, str] = {
    "CARD_LABO": CH_SNS,                # 店舗の X のフォロー＆リポスト。公式ドメインの応募ページは無い
    "HOBBY_STATION": CH_EXTERNAL_FORM,  # Livepocket（外部）
    "MUGIWARA_STORE": CH_EXTERNAL_FORM,  # LivePocket（外部・店舗ごとに別のページ）
    "KIDS_REPUBLIC": CH_APP,            # アプリ（iAEON ID 連携）
    "FUKUFUKU_TOREKA": CH_MEMBER_LOGIN,  # 会員ログインが必要
}

R_MEMBERSHIP, R_APP, R_PURCHASE_HISTORY, R_IDENTITY, R_STORE_PICKUP, R_SNS = (
    "MEMBERSHIP", "APP", "PURCHASE_HISTORY", "IDENTITY_VERIFICATION", "STORE_PICKUP", "SNS_FOLLOW_REPOST")
_REQUIREMENT_FIELDS = (("membership_required", R_MEMBERSHIP), ("app_required", R_APP),
                       ("purchase_history_required", R_PURCHASE_HISTORY),
                       ("identity_verification_required", R_IDENTITY), ("store_pickup_required", R_STORE_PICKUP))

Q_COMPLETE, Q_PARTIAL, Q_REVIEW = "complete", "partial", "review_required"
QUALITY = (Q_COMPLETE, Q_PARTIAL, Q_REVIEW)
COMPLETENESS_FIELDS = ("product", "retailer", "application_start", "application_end", "winner_announcement", "purchase_window", "application_url")


_AUTHORITY = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\.?$")
_BAD_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")
_BAD_ENCODED = re.compile(r"%(?:2e|2f|5c|25|[01][0-9a-f]|7f)", re.I)    # 符号化されたドット・スラッシュ・バックスラッシュ・% 自身（二重符号化）・制御文字
_NEWS_SEGMENTS = frozenset({"news", "info", "blog", "topics", "campaign", "category", "search", "tag", "archive", "column"})
_INDEX_FILES = frozenset({"index.html", "index.htm", "index.php"})
CHANNEL_READY = frozenset({CH_EXTERNAL_FORM, CH_APP, CH_SNS, CH_MEMBER_LOGIN, CH_STORE_COUNTER})
# 外部フォームを公式の応募先として認める組み合わせ（取得元 → (許可ホスト, パスの形)）。明示した組み合わせだけ。
# 別の取得元のフォームのホストを横流用しない。一般の外部フォーム（Google フォームなど）を全部許可しない。パスの形は個別のフォームだけ
# （/login・/mypage・主催者のページ・一覧は不可）。LivePocket は誰でも主催者になれるので、ホストだけでは「その店のフォーム」の証拠にならない
# （同じホストの別主催者のフォームは URL だけでは区別できない。運営者向けの `external_entry_url` と件数にとどめ、行動の通知には使わない）。
_LIVEPOCKET_EVENT = re.compile(r"^/e/(?!(?i:login|logout|mypage|signup|register|search|help|terms|top)/?$)[A-Za-z0-9_-]{3,}/?$", re.ASCII)
_LIVEPOCKET_HOSTS = ("livepocket.jp", "t.livepocket.jp")                  # ホストは完全一致（サブドメインを無条件に許可しない）
EXTERNAL_FORM_RULES: dict[str, tuple[tuple[str, re.Pattern], ...]] = {
    "HOBBY_STATION": tuple((h, _LIVEPOCKET_EVENT) for h in _LIVEPOCKET_HOSTS),
    "MUGIWARA_STORE": tuple((h, _LIVEPOCKET_EVENT) for h in _LIVEPOCKET_HOSTS),
}
EXTERNAL_FORM_HOSTS: dict[str, frozenset[str]] = {r: frozenset(h for h, _ in rules) for r, rules in EXTERNAL_FORM_RULES.items()}
# 公式ドメインの応募ページとして認めるパスの形（取得元 → ((ホスト, パスの形), …)）。ホストは完全一致・数字は ASCII だけ。
# **形は暫定**: GEO は登録簿の抽選一覧（draw.geo-online.co.jp/lottery/）の配下の個別ページと推定した形で、人が実際の応募ページで確認していない。
# 確認するまで、実データで応募の URL が確認できる件数は 0 のままになりうる（件数のために広げない）。
# ここに無い取得元（会員ログインが必要な福福トレカ・URL の形を確認していないポケモンセンターなど）は application_url を持たない。
# 新しい取得元・形は、人が公式ページで確認し、取得日つきでここに足す。
APPLICATION_PATH_RULES: dict[str, tuple[tuple[str, re.Pattern], ...]] = {
    "GEO": (("draw.geo-online.co.jp", re.compile(r"^/lottery/[0-9]+/?$", re.ASCII)),),
}
# 告知ページそのものが応募も兼ねると確認できた取得元（応募の URL = 告知の URL を認める）。確認できていないので空（件数のために足さない）
SELF_APPLICATION_SOURCES: frozenset[str] = frozenset()


_PCT = re.compile(r"%([0-9A-Fa-f]{2})")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def _norm_pct(text: str) -> str:
    """符号化の正規化（RFC 3986）: 英数字・`-._~` の %XX は復号し、残りの %xx は大文字にそろえる（%61 と a を同じ URL にする）。"""
    return _PCT.sub(lambda m: chr(int(m.group(1), 16)) if chr(int(m.group(1), 16)) in _UNRESERVED else "%" + m.group(1).upper(), text)


def _host_ok(host: str) -> bool:
    """ホスト名の形式（ラベルは 63 文字以下・ハイフンで始まらず終わらない・全体 253 文字以下・IP リテラルでない・punycode でない）。"""
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2:
        return False
    for lb in labels:
        if not lb or len(lb) > 63 or lb.startswith("-") or lb.endswith("-") or lb.lower().startswith("xn--"):
            return False
    return not labels[-1].isdigit() and any(c.isalpha() for c in labels[-1])      # 最後のラベルが数字だけ = IPv4 など


def _resolve_path(path: str) -> str | None:
    """dot segment を解決し、連続するスラッシュを 1 つにする。ルートより上へ出る `..` は None（拒否）。パスの大文字小文字は変えない。"""
    out: list[str] = []
    for seg in path.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if not out:
                return None
            out.pop()
            continue
        out.append(seg)
    # 元が `/` で終わるときは残す（サーバーによってはスラッシュの有無でページが変わる。同一性の比較は _ident が無視する）
    return "/" + "/".join(out) + ("/" if out and path.endswith("/") else "")


def safe_https(url) -> tuple[str, str] | None:
    """https の URL を検証・正規化して (ホスト名, 正規化した URL) を返す。安全に読めなければ None（許可リスト方式・曖昧なら拒否）。

    拒否: https 以外・小文字でないスキーム・空白・制御文字・非 ASCII（不可視文字・全角・結合文字・方向制御など）・バックスラッシュ・
    連続スラッシュ・`;`（パスのパラメータ）・query / path に埋め込んだ別の URL・`%25`（二重符号化）・`@`（認証情報。空も）・443 以外のポート・ASCII 以外のホスト・形式が不正なホスト・IP リテラル・punycode・
    符号化されたドット / スラッシュ / 制御文字（`%2e` `%2f` `%5c` `%00`…）・ルートより上へ出るパス。
    正規化: ホストを小文字・末尾のドットと `:443` を除く・dot segment を解決・符号化を RFC 3986 でそろえる・fragment を捨てる。
    文字を勝手に削って別の URL として通すことはしない（拒否する）。
    """
    raw = str(url or "").strip()
    if not raw or _BAD_CHARS.search(raw) or not raw.startswith("https://"):
        return None
    if re.search(r"[<>\"'`|^{}]", raw):
        return None                                               # HTML・引用符・シェルで意味を持つ文字（RFC 3986 の予約・非予約文字の外）
    if not raw.isascii():
        return None                                               # 非 ASCII（不可視文字・全角・結合文字・IDN など）は元の形で通さない
    try:
        p = urlsplit(raw)
    except ValueError:
        return None
    if _BAD_ENCODED.search(p.path) or _BAD_ENCODED.search(p.query) or _BAD_ENCODED.search(p.netloc):
        return None
    netloc = p.netloc
    if netloc.endswith(":443"):
        netloc = netloc[:-4]
    if "@" in netloc or ":" in netloc or not _AUTHORITY.match(netloc):
        return None
    host = netloc.lower().rstrip(".")
    if not _host_ok(host):
        return None
    if re.search(r"%(?![0-9A-Fa-f]{2})", p.path + "?" + p.query):
        return None                                              # 不正な符号化（孤立した `%`・`%ZZ`）
    if ";" in p.path or "//" in p.path or "//" in p.query:
        return None                                              # `;`（`..;/`）・埋め込み URL（リダイレクト）・連続スラッシュ（サーバーで別のパスとして扱う場合がある）
    path = _resolve_path(_norm_pct(p.path))
    if path is None:
        return None
    return host, "https://" + host + path + (("?" + _norm_pct(p.query)) if p.query else "")


def _https_host(url) -> str:
    r = safe_https(url)
    return r[0] if r else ""


def _base(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def official_hosts(retailer: str) -> frozenset[str]:
    """取得元の公式ドメイン（登録簿の公式・応募の一覧の URL のホスト。告知の一覧 news_url は含めない）。登録簿に無い取得元は空。"""
    src = SOURCE_BY_ID.get(str(retailer or ""))
    if not src:
        return frozenset()
    hosts = {_base(_https_host(src.get(k))) for k in ("official_url", "lottery_url")}
    return frozenset(h for h in hosts if h)


def _host_in(host: str, allowed) -> bool:
    return any(host == h or host.endswith("." + h) for h in allowed)


def _is_official(url, retailer: str) -> bool:
    host = _https_host(url)
    return bool(host) and _host_in(host, official_hosts(retailer))


def _source_host_ok(host: str, retailer: str) -> bool:
    """告知の URL のホストが、その取得元の公式ドメイン（登録簿の official_url / lottery_url / news_url のホスト）にあるか。無関係なホストの告知は確定の根拠にしない。"""
    src = SOURCE_BY_ID.get(retailer) or {}
    allowed = set(official_hosts(retailer)) | {_base(_https_host(src.get("news_url")))} - {""}
    return any(host == h or host.endswith("." + h) or _base(host) == h for h in allowed)


def _no_query(url: str) -> str:
    """応募の URL は query を持たない（許可した形に query は無い。リダイレクト系のパラメータを行動の URL に残さない）。"""
    return url.split("?", 1)[0]


def _ident(url) -> str:
    """告知かどうかの比較用の同一性: ホスト + 解決したパス（大文字小文字・末尾のスラッシュ・index.html・query・fragment を無視）。"""
    r = safe_https(url)
    if not r:
        return ""
    sp = urlsplit(r[1])
    segs = [x.lower() for x in sp.path.split("/") if x]
    if segs and segs[-1] in _INDEX_FILES:
        segs.pop()
    return _base(sp.netloc) + "/" + "/".join(segs)


def _extra_urls(i: dict) -> list:
    """追加の情報元（source_urls）。list / tuple 以外（文字列など）は 1 要素として扱う（文字列を 1 文字ずつ回さない）。"""
    extra = i.get("source_urls") or []
    return list(extra) if isinstance(extra, (list, tuple)) else [extra]


def _is_listing_or_announcement(entry, i: dict, retailer: str) -> bool:
    """応募の URL が、告知ページ・一覧・トップページ（query や大文字小文字・`..`・index.html を足しただけのものを含む）なら応募の URL ではない。"""
    e = _ident(entry)
    src = SOURCE_BY_ID.get(retailer) or {}
    others = {_ident(i.get("source_url"))} | {_ident(u) for u in _extra_urls(i) if isinstance(u, str)}
    others |= {_ident(src.get(k)) for k in ("official_url", "news_url")}
    return e in {o for o in others if o}


def _rule_ok(url, rules) -> bool:
    """URL のホスト（完全一致）とパスが、明示した許可の組み合わせ（ホスト, パスの形）のどれかに合うか。"""
    r = safe_https(url)
    if not r:
        return False
    path = urlsplit(r[1]).path
    return any(r[0] == h and pat.fullmatch(path) for h, pat in rules)   # fullmatch（`$` は末尾の改行の前にも一致するため）


def _event_specific(url, retailer: str, i: dict) -> bool:
    """応募の URL は出来事固有でなければならない（トップ・一覧・検索・カテゴリ・お知らせ・キャンペーン一覧は不可）。"""
    r = safe_https(url)
    if not r or not specific_url(r[1]):
        return False
    segs = {x.lower() for x in urlsplit(r[1]).path.split("/") if x}
    return not (segs & _NEWS_SEGMENTS)


def _window_conflict(i: dict, now: datetime) -> bool:
    """日程の矛盾（終了が開始より前・当選発表が応募終了より前・購入の終了が開始より前）。推測で直さない。

    日付だけの値は終了を 23:59:59 に補うので、日付（暦日）で比べる（同じ日の当選発表を矛盾にしない）。
    """
    st, _ = eq._pick(i, "application_start", "application_start_date", now)
    en, _ = eq._pick(i, "application_end", "application_end_date", now, end_of_day=True)
    wa, _ = eq._pick(i, "winner_announcement_at", "winner_announcement_date", now)
    ps, _ = eq._pick(i, "purchase_start", "purchase_start_date", now)
    pe, _ = eq._pick(i, "purchase_end", "purchase_end_date", now, end_of_day=True)
    pairs = ((st, en), (en, wa), (wa, ps), (ps, pe))
    return any(a is not None and b is not None and b.date() < a.date() for a, b in pairs)


def classify(i: dict, now: datetime) -> dict:
    """1 イベントの応募先の分類。入力が壊れていても例外にしない。"""
    i = i if isinstance(i, dict) else {}
    retailer = str(i.get("retailer") or "").strip().upper()
    ann = safe_https(i.get("source_url"))
    announcement = ann[1] if ann else None
    # 告知の URL（情報元）が、あるのに安全に読めない（http・大文字のスキーム・ポート・全角など）ときは、同じページかを判定できないので応募の URL を確定しない
    # 告知の URL が無い（比べる相手がない）・文字列でない要素が混ざる場合も確定しない
    extra = _extra_urls(i)
    source_unreadable = (ann is None or not _source_host_ok(ann[0], retailer) or any(not isinstance(u, str) or (u.strip() and safe_https(u) is None) for u in extra))
    entry = str(i.get("entry_url") or "").strip() or None
    safe = safe_https(entry) if entry else None
    # 応募の URL = 公式の情報元（source_type）で、公式ドメインの https で、出来事固有で、告知ページ・一覧・トップそのものでないもの。
    # 曖昧なら null（ただし告知と同じ URL は、告知が応募を兼ねると確認できた取得元 SELF_APPLICATION_SOURCES だけ例外）
    official_source = str(i.get("source_type") or "") in OFFICIAL_LOTTERY_SOURCES
    is_ann = bool(safe) and _is_listing_or_announcement(entry, i, retailer)
    self_ok = is_ann and retailer in SELF_APPLICATION_SOURCES and _ident(entry) == _ident(i.get("source_url"))
    specific = bool(safe) and _event_specific(entry, retailer, i)
    allowed_path = bool(safe) and _rule_ok(entry, APPLICATION_PATH_RULES.get(retailer, ()))
    application = (_no_query(safe[1]) if (safe and official_source and _is_official(entry, retailer) and specific and allowed_path
                                           and not source_unreadable and (not is_ann or self_ok)) else None)
    # 外部フォーム = 取得元ごとに明示した許可ホストにある、出来事固有の https の URL（公式の情報元のときだけ）
    external = (_no_query(safe[1]) if (safe and application is None and official_source and not is_ann and not source_unreadable
                                       and _rule_ok(entry, EXTERNAL_FORM_RULES.get(retailer, ()))) else None)
    if application:
        channel = CH_WEB_OFFICIAL
    elif external:
        channel = CH_EXTERNAL_FORM
    elif official_source and (i.get("app_required") is True or str(i.get("channel") or "") == "APP"):
        channel = CH_APP
    else:
        channel = SOURCE_CHANNEL.get(retailer, CH_UNKNOWN) if official_source else CH_UNKNOWN   # 非公式の情報元は登録簿の経路を使わない
    if channel == CH_UNKNOWN and official_source and i.get("store_pickup_required") is True:
        channel = CH_STORE_COUNTER

    reqs = [name for key, name in _REQUIREMENT_FIELDS if i.get(key) is True]
    if channel == CH_SNS:
        reqs.append(R_SNS)
    if channel == CH_APP and R_APP not in reqs:
        reqs.append(R_APP)
    if channel == CH_MEMBER_LOGIN and R_MEMBERSHIP not in reqs:
        reqs.append(R_MEMBERSHIP)

    st, _ = eq._pick(i, "application_start", "application_start_date", now)
    en, _ = eq._pick(i, "application_end", "application_end_date", now, end_of_day=True)
    wa, _ = eq._pick(i, "winner_announcement_at", "winner_announcement_date", now)
    ps, _ = eq._pick(i, "purchase_start", "purchase_start_date", now)
    pe, _ = eq._pick(i, "purchase_end", "purchase_end_date", now, end_of_day=True)
    flags = {
        "product": bool(i.get("product_id")) and str(i.get("product_match") or "") == "exact" and not i.get("provisional_product"),
        "retailer": bool(retailer),
        "application_start": st is not None, "application_end": en is not None,
        "winner_announcement": wa is not None,                    # 日付として読めない値（TBD など）は「ある」にしない
        "purchase_window": ps is not None and pe is not None,
        "application_url": application is not None,
    }
    missing = [k for k in COMPLETENESS_FIELDS if not flags[k]]
    review = _window_conflict(i, now) or (bool(i.get("product_id")) and str(i.get("product_match") or "") == "ambiguous")
    quality = Q_REVIEW if review else (Q_COMPLETE if not missing else Q_PARTIAL)
    # 応募の URL が無い経路（SNS・アプリ・外部フォーム・会員・店頭）でも、日程と商品がそろい経路が分かるものは運営者向けに別に数える。
    # actionable ではない（応募の URL が確認できないので行動の通知には使わない）
    # 応募先の URL が渡されたのに拒否された（読めない・許可外）ものは、経路の確認とは言えない。告知が読めないものも立てない。
    entry_ok = entry is None or application is not None or external is not None
    channel_ready = (quality != Q_REVIEW and set(missing) == {"application_url"} and channel in CHANNEL_READY
                     and not source_unreadable and entry_ok)
    return {"announcement_url": announcement, "application_url": application, "external_entry_url": external,
            "channel": channel, "requirements": reqs, "region": str(i.get("region") or ""),
            "store": str(i.get("store_name") or ""), "completeness": sum(flags.values()), "missing": missing,
            "quality": quality, "actionable_event": quality == Q_COMPLETE, "channel_ready": channel_ready}
