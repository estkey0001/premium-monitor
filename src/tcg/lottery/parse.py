# -*- coding: utf-8 -*-
"""抽選告知の本文から、日程・対象商品・応募条件を取り出す。

方針:
  - 日時はラベル（抽選応募受付期間 / 応募期間 / 抽選結果発表日 / 注文期間 /
    購入期間 / お届け時期 等）の近くにあるものだけ採用する。出現順で割り当てない。
  - 年の書かれていない日付（「9/28(月) 11:00」「10月2日（金）12時00分」）は、
    記事の公開年から補い、曜日が書かれていれば一致を検証する。曜日が合わなければ
    採用しない（推測で日付を作らない）。
  - 時刻の書かれていない日付は、00:00 や 23:59 を補わない。
    application_end ではなく application_end_date（YYYY-MM-DD）に入れ、
    状態判定では「その日が終わるまでは締切前、翌日以降は締切後」とだけ扱う。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from src.tcg.models import JST, parse_dt

_WEEKDAYS = "月火水木金土日"

# 1つの日時トークン。年は任意、曜日は任意、時刻は「12:00」「12時00分」「12時」
_DT = re.compile(
    r"(?:(?P<y>\d{4})\s*[年/.\-]\s*)?"
    r"(?P<m>\d{1,2})\s*[月/]\s*(?P<d>\d{1,2})\s*日?"
    r"\s*(?:[（(]\s*(?P<w>[月火水木金土日])(?:・祝)?\s*[）)])?"
    r"(?:\s*(?P<h>\d{1,2})\s*(?:時|[:：])\s*(?P<mi>\d{2})?\s*分?)?"
)

# ラベル → フィールド（期間ラベルは開始・終了の2つを取る）
_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("application", ("抽選応募受付期間", "抽選応募期間", "応募受付期間", "応募期間",
                     "受付期間", "抽選受付期間", "エントリー期間", "申込期間")),
    ("winner_announcement_at", ("抽選結果発表日", "抽選結果発表", "当選発表日", "当選発表",
                                "結果発表")),
    ("purchase", ("注文および、支払い期間", "注文期間", "購入期間", "お支払い期間",
                  "購入手続き期間", "支払い期間", "ご購入期間")),
    ("purchase_end", ("購入期限", "お支払い期限", "購入手続き期限")),
)
# ラベルから次のラベルまでを1区間とする。ただし長すぎる区間は打ち切る
_SEGMENT_MAX = 600
# 商品別の書き分けが無い場合に、ラベル直後から見る文字数
_PERIOD_WINDOW = 120
_POINT_WINDOW = 60

# 時刻が書かれていない場合の「日付のみ」フィールド
DATE_ONLY_FIELD = {
    "application_start": "application_start_date",
    "application_end": "application_end_date",
    "winner_announcement_at": "winner_announcement_date",
    "purchase_start": "purchase_start_date",
    "purchase_end": "purchase_end_date",
}


def _resolve_year(m: int, d: int, base: Optional[datetime], explicit_year: Optional[int],
                  weekday: Optional[str]) -> Optional[int]:
    """年を決める。

    - 年が明記されていればそれを使う（曜日があれば一致を検証）。
    - 年が無ければ記事の公開年、または翌年（年末の記事で1月の日付が来る場合）。
      曜日が書かれていれば、曜日が一致する年だけを採用する。
      曜日が無ければ、公開日から見て半年以上前にならない年を選ぶ。
    - どれにも当てはまらなければ None（日付を作らない）。
    """
    if explicit_year:
        candidates = [explicit_year]
    elif base is not None:
        candidates = [base.year, base.year + 1]
    else:
        return None
    for y in candidates:
        try:
            dt = datetime(y, m, d, tzinfo=JST)
        except ValueError:
            continue
        if weekday is not None and _WEEKDAYS[dt.weekday()] != weekday:
            continue
        if explicit_year or base is None:
            return y
        # 公開日から半年以上前・1年以上先の日付にはしない（曜日が合っていても）
        if -366 <= (dt - base).days and (base - dt).days <= 183:
            return y
    return None


def _to_iso(match: re.Match, base: Optional[datetime]) -> tuple[Optional[str], bool]:
    """日時トークンを ISO8601(JST) にする。戻り値は (iso, 時刻が書かれていたか)。"""
    g = match.groupdict()
    try:
        m, d = int(g["m"]), int(g["d"])
    except (TypeError, ValueError):
        return None, False
    y = _resolve_year(m, d, base, int(g["y"]) if g.get("y") else None, g.get("w"))
    if y is None:
        return None, False
    has_time = g.get("h") is not None
    try:
        dt = datetime(y, m, d, int(g["h"] or 0), int(g["mi"] or 0), tzinfo=JST)
    except ValueError:
        return None, False
    return dt.isoformat(), has_time


def _tokens(text: str, base: Optional[datetime]) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for mt in _DT.finditer(text or ""):
        iso, has_time = _to_iso(mt, base)
        if iso:
            out.append((iso, has_time))
    return out


_QUOTED = re.compile(r"「([^」]{2,40})」")


def _product_tag(product_name: str) -> Optional[str]:
    """商品名から、本文中で商品を指す見出し語（「」内の名前）を取り出す。"""
    names = _QUOTED.findall(product_name or "")
    return names[-1] if names else None


def _segment_for_product(seg: str, tag: Optional[str]) -> str:
    """ラベル区間の中に商品別の行があれば、その商品の行だけを返す。

    例: 「拡張パック「X」BOX：9月4日 13時…」「「Y」デッキ：9月4日 17時…」
    商品別の行が無ければ（全商品共通の日程）区間をそのまま返す。
    """
    if not tag:
        return seg
    lines = [ln for ln in seg.split("\n") if ln.strip()]
    tagged = [ln for ln in lines if "「" in ln and "：" in ln]
    if not tagged:
        return seg
    # 「」内の名前が完全一致する行だけ（部分一致で別商品の行を拾わない）
    mine = [ln for ln in tagged if tag in _QUOTED.findall(ln)]
    return "\n".join(mine)


def extract_schedule(text: str, published_at: Optional[str] = None,
                     product_name: Optional[str] = None) -> dict:
    """ラベル近傍の日時だけを抽選のフィールドに割り当てる。

    戻り値のキー: application_start / application_end / winner_announcement_at /
    purchase_start / purchase_end。読めないものは含めない。
    end < start の組は破棄する。
    product_name を渡すと、商品ごとに日程が書き分けられている告知では
    その商品の行だけを使う。
    """
    base = parse_dt(published_at)
    raw = text or ""
    out: dict = {}
    for field_name, labels in _LABELS:
        for label in labels:
            pos = raw.find(label)
            if pos < 0:
                continue
            seg = raw[pos + len(label): pos + len(label) + _SEGMENT_MAX]
            # 次のラベル（別項目）が現れたらそこで切る
            cut = len(seg)
            for _f, other in _LABELS:
                for o in other:
                    if o in label or label in o:
                        continue
                    j = seg.find(o)
                    if 0 < j < cut:
                        cut = j
            for stop in ("【", "・お届け", "お届け時期", "発送"):
                j = seg.find(stop)
                if 0 < j < cut:
                    cut = j
            seg = seg[:cut]
            part = _segment_for_product(seg, _product_tag(product_name or ""))
            if part == seg:
                # 商品別の書き分けが無い場合はラベル直後だけを見る
                span = _PERIOD_WINDOW if field_name in ("application", "purchase") else _POINT_WINDOW
                part = seg[:span]
            toks = _tokens(part, base)
            if not toks:
                continue

            def _put(key: str, tok: tuple[str, bool]) -> None:
                iso, has_time = tok
                if has_time:
                    out.setdefault(key, iso)
                else:
                    # 時刻が書かれていない。00:00 や 23:59 を補わず、日付だけを持つ
                    out.setdefault(DATE_ONLY_FIELD[key], iso[:10])

            if field_name == "application":
                _put("application_start", toks[0])
                if len(toks) > 1:
                    _put("application_end", toks[1])
            elif field_name == "purchase":
                _put("purchase_start", toks[0])
                if len(toks) > 1:
                    _put("purchase_end", toks[1])
            else:
                _put(field_name, toks[0])
            break
    for a, b in (("application_start", "application_end"),
                 ("purchase_start", "purchase_end")):
        sa = parse_dt(out.get(a) or out.get(DATE_ONLY_FIELD[a]))
        sb = parse_dt(out.get(b) or out.get(DATE_ONLY_FIELD[b]))
        if sa and sb and sb.date() < sa.date():
            for k in (a, b, DATE_ONLY_FIELD[a], DATE_ONLY_FIELD[b]):
                out.pop(k, None)
        elif sa and sb and out.get(a) and out.get(b) and sb < sa:
            out.pop(a, None)
            out.pop(b, None)
    return out


# ── 対象商品 ──────────────────────────────────────────────────────────────
_TARGET_HEAD = re.compile(r"【\s*(?:対象商品|抽選販売を実施する商品|抽選販売対象商品|商品)\s*】")
_BULLET = re.compile(r"^\s*[・●■◆]\s*(.+?)\s*$")
_PRODUCT_WORD = re.compile(r"ポケモンカード|ONE\s*PIECE|ワンピース|拡張パック|ブースター|BOX|ボックス|"
                           r"パック|デッキ|セット|コレクション")
_PRICE_IN_LINE = re.compile(r"([0-9][0-9,]{2,8})\s*円\s*[（(]?\s*税込")


def extract_target_products(text: str) -> list[dict]:
    """【対象商品】等の見出し直後の箇条書きから商品名（と明記された価格）を取り出す。"""
    lines = (text or "").split("\n")
    out: list[dict] = []
    for i, line in enumerate(lines):
        if not _TARGET_HEAD.search(line):
            continue
        for nxt in lines[i + 1:i + 12]:
            # 次の見出し・日程ラベルが来たら商品リストは終わり
            if nxt.strip().startswith("【") or any(
                    lab in nxt for _f, labels in _LABELS for lab in labels):
                break
            m = _BULLET.match(nxt)
            if not m:
                if out:
                    break
                continue
            name = m.group(1).strip()
            if not _PRODUCT_WORD.search(name):
                continue   # 商品名らしくない箇条書き（注意書き等）は商品にしない
            price = None
            pm = _PRICE_IN_LINE.search(name)
            if pm:
                try:
                    price = int(pm.group(1).replace(",", ""))
                except ValueError:
                    price = None
                name = name[:pm.start()].strip()
            out.append({"product_name": name, "retail_price": price})
        if out:
            break
    return out


# ── Task9: 応募条件 ───────────────────────────────────────────────────────
_ELIGIBILITY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("membership_required", ("会員登録", "会員の方", "会員証", "会員機能", "GEO ID",
                             "ログインが必要", "プレイヤーズクラブ", "会員限定", "Ponta")),
    ("app_required", ("アプリ",)),
    ("identity_verification_required", ("本人確認", "本人認証", "マイナンバーカード")),
    ("purchase_history_required", ("購入履歴", "購入実績", "ご利用実績", "お買い上げ実績")),
    ("store_pickup_required", ("店頭でのお渡し", "店舗でのお渡し", "店頭受取", "店舗受取",
                               "ご来店", "レジにて")),
)
_ELIG_HEAD = re.compile(r"応募条件|応募資格|当選資格|ご応募いただける方|対象となるお客様")
# 支払方法の記載がある行（原文のまま保持する。単純化しない）
_PAYMENT_LINE = re.compile(r"支払方法|支払い方法|お支払い方法|決済")


# 応募条件を述べている行の目印（条件を述べていない行のキーワードで判定しない）
_ELIG_CONTEXT = re.compile(r"応募条件|応募資格|当選資格|ご応募いただける|対象となるお客様|"
                           r"お客様$|お客様。|お持ちの|連携済|提示していただける|応募には|"
                           r"ご応募の際|応募の際")
# 「応募条件」「応募資格」だけの行（括弧の無い見出し）
_BARE_HEAD = re.compile(r"^\s*(応募条件|応募資格|当選資格)\s*[:：]?\s*$")
# 見出し行（【…】 / ■… / ＜…＞）
_SECTION_HEAD = re.compile(r"^\s*(【[^】]+】|■|＜[^＞]+＞|\[[^\]]+\])")
# 「未認証でも応募できる枠がある」等、条件が必須ではないことを示す表現
_TIERED = re.compile(r"未認証枠|本人未認証|認証がお済みでない方も|未認証の方も")


def extract_eligibility(text: str) -> dict:
    """応募条件を構造化する。明記がある項目だけ True、それ以外は None。

    - 応募条件を述べている行（応募条件 / 当選資格 / 〜のお客様 等）だけから判定する。
    - 「本人認証済み枠」と「未認証枠」のように、条件を満たさなくても応募できる枠が
      ある場合は、その条件を必須（True）にしない。原文で枠の違いを示す。
    - 原文（条件の行）を eligibility_text に必ず残す。False は付けない（不明 = None）。
    """
    t = text or ""
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    ctx_lines: list[str] = []
    for i, ln in enumerate(lines):
        if _ELIG_HEAD.search(ln) and (_SECTION_HEAD.match(ln) or _BARE_HEAD.match(ln)):
            # 【応募条件】のような見出し: 見出しの後ろを次の見出しまで（最大8行）取る
            ctx_lines.append(ln)
            for nxt in lines[i + 1:i + 9]:
                if (_SECTION_HEAD.match(nxt) or _BARE_HEAD.match(nxt)
                        or any(lab in nxt for _f, labels in _LABELS for lab in labels)):
                    break
                ctx_lines.append(nxt)
        elif _ELIG_HEAD.search(ln) or _ELIG_CONTEXT.search(ln):
            # 「〜を応募条件としております」「〜のお客様」等、条件を述べている行そのもの
            ctx_lines.append(ln)
    ctx = "\n".join(ctx_lines)
    out: dict = {k: None for k, _ in _ELIGIBILITY_RULES}
    for k, words in _ELIGIBILITY_RULES:
        if any(w in ctx for w in words):
            out[k] = True
    tiered = bool(_TIERED.search(t))
    if tiered:
        # 本人認証は「当選しやすくなる枠」の条件であり、応募の必須条件ではない
        out["identity_verification_required"] = None
        if out.get("membership_required") and "プレイヤーズクラブ" in ctx and not any(
                w in ctx for w in ("会員登録", "会員の方", "会員証", "GEO ID", "Ponta")):
            out["membership_required"] = None
    pay_lines = [ln for ln in lines if _PAYMENT_LINE.search(ln) and len(ln) <= 160]
    out["payment_method_requirement"] = " / ".join(dict.fromkeys(pay_lines))[:400] or None
    seen: set[str] = set()
    uniq = [x for x in ctx_lines if not (x in seen or seen.add(x))]
    text_out = "\n".join(uniq)[:800]
    if tiered:
        text_out = ("※本人認証の有無で応募枠が分かれています（未認証でも応募可・"
                    "認証済みの方が当選しやすい）\n" + text_out)
    out["eligibility_text"] = text_out or None
    return out


# ── 商品名の整形（記事タイトルから作る場合） ──────────────────────────────
_TITLE_NOISE = (
    re.compile(r"^\s*\d{1,2}月\d{1,2}日\s*[（(][^）)]{1,3}[）)]\s*発売\s*"),
    re.compile(r"(の)?\s*(抽選販売|抽選|予約)(受付|受け付け|応募)?(の|に)?(ついて|お知らせ|ご案内).*$"),
    re.compile(r"(の)?\s*(追加)?抽選販売.*$"),
    re.compile(r"の追加$"),
)


def product_name_from_title(title: str) -> str:
    """記事タイトルから商品名部分を取り出す（発売日の前置き・「抽選販売受付のお知らせ」を除く）。"""
    s = (title or "").strip()
    for pat in _TITLE_NOISE:
        s = pat.sub("", s).strip()
    # 『…』で囲まれていれば中身を使う
    m = re.search(r"『(.+?)』", s)
    if m:
        s = m.group(1).strip()
    return s.strip("「」『』 ") or (title or "").strip()
