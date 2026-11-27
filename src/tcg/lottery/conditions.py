# -*- coding: utf-8 -*-
"""応募条件の構造化（本文のテキストから。根拠の原文つき）。

各項目は {"value": ..., "quote": 根拠の行（最大 _QUOTE_MAX 字）} か None（本文に明記が無い）。
- 真偽の項目（会員・購入履歴・購入時の本人確認）は 3 つを区別する: value=True（必須と明記）・value=False（不要と明記）・
  項目が None（不明。本文に書かれていない）。書かれていない条件を「不要」にしない。
- 上限は、応募の上限（application_limit: 回・口）と購入の上限（purchase_limit: 点・個・BOX・箱・セット・パック・枚）を分ける。
- 複数商品の告知では、ほかの商品の名前だけが書かれた行を、その商品の条件にしない（other_products）。
- 期間・金額・期限・上限は、根拠の行の中に書かれた表記をそのまま取る（年・時刻・数量を補わない）。
- 条件を述べている行のうち、どの項目にも当てはまらない行は other_conditions に原文のまま残す。
- X のフォロー・リポストは、応募・抽選・条件の語と同じ行にあるものだけ（「公式Xで最新情報を」のような案内を条件にしない）。
"""
from __future__ import annotations

import re
from typing import Optional

_QUOTE_MAX = 160
CONDITION_KEYS = ("purchase_history_required", "membership_required", "x_follow_required", "x_repost_required",
                  "app_only", "region_limit", "application_limit", "purchase_limit", "id_required_at_purchase",
                  "other_conditions")
_APPLICATION_UNITS = ("回", "口")

_PURCHASE_HISTORY = re.compile(r"購入履歴|購入実績|ご利用実績|お買い上げ実績")
_PERIOD = re.compile(r"(?:\d{4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日[^\n。]{0,24}?[〜～~\-－から]+[^\n。]{0,8}?"
                     r"(?:\d{4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日(?:\s*[（(][^）)]{1,3}[）)])?(?:\s*\d{1,2}[:：]\d{2})?")
_AMOUNT = re.compile(r"(?:税込\s*)?[\d,，]{3,}\s*円(?:\s*[（(]税込[）)])?\s*以上")
_MEMBERSHIP = re.compile(r"会員登録|会員の方|会員様|会員限定|会員証|GEO\s*ID|Ponta|プレイヤーズクラブ|ログイン(?:が必要|の上)|"
                         r"(?:[\w・ー]{2,30})会員|[A-Za-z]{2,}\s*ID\s*(?:との|の|を|で)?\s*(?:連携|登録|ログイン)")
# 会員の種類: 「○○会員」「○○の会員登録」「○○ID」「○○クラブ」の○○（カタカナ・英数字の名前）
_MEMBER_TYPE = re.compile(r"((?:[ァ-ヶーA-Za-z0-9・]{2,30})(?:の?会員|\s*ID|クラブ))")
_DEADLINE = re.compile(r"(?:(?:\d{4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日[^\n。]{0,16}?|受付開始(?:日時|時刻)?|応募(?:開始|締切)(?:日時|時刻)?)"
                       r"(?:まで|時点)に?[^\n。]{0,16}?(?:登録|ご登録|会員)")
# X の語そのもの（「インフェルノX」のような商品名の末尾・@ だけのハンドル・LINE や Instagram のフォローは X にしない）
_X_ACCOUNT = re.compile(r"(?<![A-Za-z0-9ァ-ヶー])[XＸ](?![A-Za-z0-9ァ-ヶー])|旧Twitter|Twitter|ツイッター|ポスト")
_OTHER_SNS = re.compile(r"LINE|Instagram|インスタ|TikTok|Facebook|YouTube", re.I)
_FOLLOW = re.compile(r"フォロー")
_REPOST = re.compile(r"リポスト|リツイート|(?<![A-Za-z])RT(?![A-Za-z])|引用ポスト|引用リポスト")
_APPLY_CTX = re.compile(r"応募|抽選|条件|対象|参加")
_APP_ONLY = re.compile(r"アプリ(?:限定|のみ|会員限定|からのみ|でのみ|から(?:のみ)?ご応募|内(?:で|から)のみ)|アプリ(?:で|から)の応募(?:のみ|に限り)")
_REGION = re.compile(r"(?:お住まい|在住|居住|配送先|お届け先|発送先)[^\n。]{0,30}?(?:限ります|限定|のみ|に限り|対象)|"
                     r"(?:国内|日本国内)(?:のみ|在住|に限り)|離島[^\n。]{0,12}?(?:除く|対象外|不可)|地域限定")
_PER_PERSON = re.compile(r"(?<![0-9０-９])(?:お一人様|お１人様|お1人様|1人|一人|１人|1名様|１名様|1アカウント|１アカウント)(?:につき|あたり|様)?\s*"
                         r"[^\n。]{0,20}?([0-9０-９一二三]+)\s*(点|個|BOX|ボックス|箱|回|口|セット|パック|枚)(?:まで|限り|限定)?",
                         re.I)
_NOT_CASE = re.compile(r"(?:ない|ません|できない|でない)場合")
_OTHER_DOC = re.compile(r"会員証|会員カード|ポイントカード|当選(?:の)?画面|当選DM|当選メール|予約券|整理券|レシート")
_MAYBE = re.compile(r"場合があ|場合がござ|場合もござ|場合もあ|ことがあ|こともあ|事があ|事もあ|可能性があ|可能性もあ|場合によ")
_APPLY_BEFORE = re.compile(r"応募(?:は|できる|可能|数|回数)")
# 「当選者は各2BOXまで」「ご購入は各1点まで」（お一人様の語が無い購入の上限。当選者・購入の文脈の行だけ）
_EACH_LIMIT = re.compile(r"各\s*([0-9０-９一二三]+)\s*(点|個|BOX|ボックス|箱|セット|パック|枚)\s*(?:まで|限り)", re.I)
_PURCHASE_CTX = re.compile(r"当選者|購入|お買い求め|販売")
# 本人確認の書類（「ご本人様確認書類」「ご本人様確認証」のように「様」が挟まる書き方も含める）
_ID_DOC = re.compile(r"本人(?:様)?確認(?:書類|証)|身分証|運転免許証|マイナンバーカード|健康保険証|学生証")
_ID_ACT = re.compile(r"提示|ご持参|お持ち|確認させて|確認いたします|必要")
_ELIG_LINE = re.compile(r"応募条件|応募資格|当選資格|ご応募いただける|対象となるお客様|お客様$|お客様。|お持ちの|連携済|"
                        r"提示していただける|応募には|ご応募の際|応募の際|必須|限ります|限定")


_HEADING_ONLY = re.compile(r"^\s*(?:【[^】]*】|■[^\n]{0,12}|＜[^＞]*＞|\[[^\]]*\])\s*[:：]?\s*$")


# 否定（「不要」「問いません」「無い方でも」等）。否定は文の中の節（、・括弧で区切った部分）ごとに当てる:
# 「会員登録が必要です。購入履歴は問いません。」で会員登録まで不要にしない。同じ条件に肯定と否定が両方あれば不明（None）
_NEGATION = re.compile(r"不要|必要(?:は)?ありません|必要ない|いりません|無しで|なしで|不問|問いません|関係なく|どなたでも|"
                       r"(?:無い|ない)方でも|(?:無|な)くても|でもご?応募")
# 期間の前にこのラベルがあれば、その期間は応募・購入などの日程（購入履歴の対象期間ではない）
_SCHEDULE_LABEL = re.compile(r"(?:応募|受付|抽選|申込|申し込み|販売|購入|当選発表|抽選日|結果発表)(?:期間|日)?\s*[:：]?\s*$")
_PERIOD_NEAR = 40


def _sentences(text: str) -> list[str]:
    """文（。！!・改行で区切る）。1 行にまとめられた本文（ホビーステーション・福福トレカ）も文に分ける。"""
    return [x.strip() for x in re.split(r"[。！!\n]", text or "") if x.strip()]


def _clauses(sentence: str) -> list[str]:
    return [c for c in re.split(r"[、，,（）()]", sentence) if c.strip()]


def _pos(sentence: str, pat) -> bool:
    return any(pat.search(c) and not _NEGATION.search(c) for c in _clauses(sentence))


def _neg(sentence: str, pat) -> bool:
    return any(pat.search(c) and _NEGATION.search(c) for c in _clauses(sentence))


# 「不要」と明記されうる条件（否定の節に、その条件の語がある）
# 会員の否定は「会員登録・会員になる・入会」の語だけ（「会員証の提示は不要」は会員登録が不要という意味ではない）
_NOT_REQUIRED = (("membership_required", re.compile(r"会員登録|会員になる|入会|会員の方以外")),
                 ("purchase_history_required", _PURCHASE_HISTORY),
                 ("id_required_at_purchase", re.compile(r"本人(?:様)?確認|身分証")))


def _for_this_product(sentences, other_products) -> list[str]:
    """ほかの商品の名前が書かれた文を外す。"""
    names = [n for n in (other_products or []) if n and len(n) >= 2]
    if not names:
        return sentences
    return [s for s in sentences if not any(n in s for n in names)]


def _q(line: str) -> str:
    return line[:_QUOTE_MAX]


def _ctx(s: str) -> bool:
    return bool(_APPLY_CTX.search(s) or _ELIG_LINE.search(s) or "必要" in s or "以上" in s)


def _near_period(s: str, kpos: int) -> Optional[str]:
    """購入履歴の語の近く（同じ文・_PERIOD_NEAR 字以内）にある期間。応募・販売などのラベルの付いた期間は使わない。"""
    best = None
    for m in _PERIOD.finditer(s):
        if _SCHEDULE_LABEL.search(s[max(0, m.start() - 12):m.start()]):
            continue
        dist = min(abs(m.end() - kpos), abs(m.start() - kpos))
        if dist <= _PERIOD_NEAR and (best is None or dist < best[0]):
            best = (dist, m.group(0).strip())
    return best[1] if best else None


def _purchase_history(sentences) -> Optional[dict]:
    for s in sentences:
        k = _PURCHASE_HISTORY.search(s)
        if k and _pos(s, _PURCHASE_HISTORY) and _ctx(s):
            a = _AMOUNT.search(s)
            return {"value": True, "period": _near_period(s, k.start()),
                    "amount": a.group(0).strip() if a else None, "quote": _q(s)}
    return None


def _membership(sentences) -> Optional[dict]:
    for i, s in enumerate(sentences):
        if not (_MEMBERSHIP.search(s) and _pos(s, _MEMBERSHIP) and _ctx(s)):
            continue
        t = _MEMBER_TYPE.search(s)
        # 登録の期限は同じ文か、すぐ次の文（「会員登録が必要です。〇日までにご登録ください。」）から
        d = _DEADLINE.search(s) or (_DEADLINE.search(sentences[i + 1]) if i + 1 < len(sentences) else None)
        return {"value": True, "type": t.group(1).strip() if t else None,
                "deadline": d.group(0).strip() if d else None, "quote": _q(s)}
    return None


def _x_flags(sentences) -> tuple[Optional[dict], Optional[dict]]:
    follow = repost = None
    for s in sentences:
        if not (_X_ACCOUNT.search(s) or _REPOST.search(s)) or not _APPLY_CTX.search(s):
            continue
        if _OTHER_SNS.search(s) and not _X_ACCOUNT.search(s):
            continue
        if follow is None and _pos(s, _FOLLOW):
            follow = {"value": True, "quote": _q(s)}
        if repost is None and _pos(s, _REPOST):
            repost = {"value": True, "quote": _q(s)}
    return follow, repost


def _first_match(sentences, pattern, *, group=0, need=None) -> Optional[dict]:
    for s in sentences:
        m = pattern.search(s)
        if m and _pos(s, pattern) and (need is None or need.search(s)):
            return {"value": m.group(group).strip() if group is not None else True, "quote": _q(s)}
    return None


def extract_conditions(text: str, *, other_products=None) -> dict:
    """本文 → 応募条件（CONDITION_KEYS）。明記の無い項目は None。other_conditions は原文の文のリスト（無ければ None）。

    other_products: 同じ告知のほかの対象商品の名前（その名前が書かれた文は、この商品の条件にしない）。
    """
    sents = _for_this_product(_sentences(text), other_products)
    out: dict = {k: None for k in CONDITION_KEYS}
    out["purchase_history_required"] = _purchase_history(sents)
    out["membership_required"] = _membership(sents)
    out["x_follow_required"], out["x_repost_required"] = _x_flags(sents)
    out["app_only"] = _first_match(sents, _APP_ONLY, group=None)
    out["region_limit"] = _first_match(sents, _REGION)
    for s in sents:
        for m in _PER_PERSON.finditer(s):
            # 上限の前（同じ節の中）に「応募は」「応募できる」等があれば、単位に関係なく応募の上限
            clause_prefix = re.split(r"[、，,]", s[:m.start()])[-1]
            applying = bool(_APPLY_BEFORE.search(clause_prefix)) or m.group(2) in _APPLICATION_UNITS
            key = "application_limit" if applying else "purchase_limit"
            if out[key] is None:
                out[key] = {"value": m.group(0).strip(), "quote": _q(s)}
        m = _EACH_LIMIT.search(s)
        if m and out["purchase_limit"] is None and _PURCHASE_CTX.search(s):
            out["purchase_limit"] = {"value": m.group(0).strip(), "quote": _q(s)}
    # 「提示をお願いする場合があります」のような条件つきの書き方は、必須とも不要とも言えないので不明（None）にする。
    # 判定は節の単位（「本人確認書類をご持参ください（お忘れの場合は…ことがあります）」の必須の節は残す）
    # 本人確認の書類の語がある文で、「場合がある」の節に提示・持参・確認の語があれば条件つき
    # （「本人確認書類（運転免許証など）のご提示をお願いする場合があります」。括弧・読点で節が分かれても拾う）。
    # 「お忘れの場合はご購入いただけないことがあります」の節には提示・確認の語が無いので、必須のまま
    _ACT_IN_MAYBE = re.compile(r"提示|持参|お持ち|確認")

    def _id_clause_maybe(sent):
        # 「お持ちでない場合は購入できないことがあります」のような、提示できないときの扱い（〜ない場合）は条件つきにしない
        return bool(_ID_DOC.search(sent)) and any(_MAYBE.search(c) and _ACT_IN_MAYBE.search(c) and not _NOT_CASE.search(c)
                                                  for c in _clauses(sent))
    # 「不要」を打ち消すのも、本人確認の書類・本人確認の語がある文の条件つきの言及だけ（会員証の提示などでは打ち消さない）
    id_maybe = any(_MAYBE.search(x) and re.search(r"提示|持参|確認", x) and re.search(r"本人(?:様)?確認|身分証|運転免許証|マイナンバー", x)
                   for x in sents) or any(
        _MAYBE.search(x) and re.search(r"提示|持参", x) and i > 0 and re.search(r"本人(?:様)?確認|身分証", sents[i - 1])
        and not _OTHER_DOC.search(x)                    # 別の書類（会員証・当選の画面等）の提示の話は、本人確認の話ではない
        for i, x in enumerate(sents))
    idm = _first_match([x for x in sents if not _id_clause_maybe(x)], _ID_DOC, need=_ID_ACT)
    out["id_required_at_purchase"] = {"value": True, "quote": idm["quote"]} if idm else None
    # 「不要」と明記された条件: 必須の明記が無ければ False。両方あれば、どちらとも言えないので不明（None）
    for key, pat in _NOT_REQUIRED:
        neg = next((s for s in sents if _neg(s, pat)), None)
        if neg is None:
            continue
        out[key] = {"value": False, "quote": _q(neg)} if out[key] is None else None
    # 本人確認は「不要。ただし提示をお願いする場合があります」のように条件つきの言及があれば、不要とも必須とも言えない（不明）
    if id_maybe and isinstance(out["id_required_at_purchase"], dict) and out["id_required_at_purchase"].get("value") is False:
        out["id_required_at_purchase"] = None
    used = {v["quote"] for k, v in out.items() if isinstance(v, dict)}
    other = [_q(s) for s in sents if _ELIG_LINE.search(s) and _q(s) not in used and len(s) >= 6
             and not _HEADING_ONLY.match(s) and not _NEGATION.search(s)]
    out["other_conditions"] = list(dict.fromkeys(other))[:5] or None
    return out


def strip_quotes(conditions: Optional[dict]) -> dict:
    """原文の転載を禁じるサイト向け: 根拠の行（quote）と原文のリスト（other_conditions）を外し、構造化した値だけ残す。"""
    out = {}
    for k, v in (conditions or {}).items():
        if k == "other_conditions" or not isinstance(v, dict):
            continue
        out[k] = {kk: vv for kk, vv in v.items() if kk != "quote"}
    return out


def condition_summary(conditions: Optional[dict]) -> list[str]:
    """表示用の短いラベル（明記のある条件だけ）。"""
    c = conditions or {}
    labels = []

    def val(k):
        v = c.get(k)
        return v.get("value") if isinstance(v, dict) else None
    if val("membership_required") is True:
        t = c["membership_required"].get("type")
        labels.append(f"{t}が必要" if t else "会員登録が必要")
    elif val("membership_required") is False:
        labels.append("会員登録は不要")
    if val("purchase_history_required") is True:
        labels.append("購入履歴が必要")
    elif val("purchase_history_required") is False:
        labels.append("購入履歴は不要")
    if c.get("x_follow_required") or c.get("x_repost_required"):
        labels.append("X のフォロー・リポスト" if c.get("x_repost_required") else "X のフォロー")
    if c.get("app_only"):
        labels.append("アプリ限定")
    if c.get("region_limit"):
        labels.append("地域の限定あり")
    for k, head in (("application_limit", "応募 "), ("purchase_limit", "購入 ")):
        if val(k):
            labels.append(head + str(val(k)))
    if val("id_required_at_purchase") is True:
        labels.append("購入時に本人確認")
    elif val("id_required_at_purchase") is False:
        labels.append("本人確認は不要")
    return labels
