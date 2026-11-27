"""応募条件の構造化（src/tcg/lottery/conditions.py）。明記のある項目だけを、根拠の行つきで埋める。"""
from src.tcg.lottery.conditions import CONDITION_KEYS, condition_summary, extract_conditions

PCO = """【応募条件】
ポケモンセンターオンラインの会員登録が必要です。2026年12月1日(月) 10:00の受付開始までにご登録ください。
2026年6月1日～2026年11月30日の期間に、ポケモンセンターオンラインで5,000円以上のご購入履歴があるお客様が対象です。
■注意事項
お一人様1BOXまでとさせていただきます。
お届け先は日本国内に限ります。
"""

SHOP = """抽選販売のお知らせ
応募方法：当店公式Xアカウント(@shop_tcg)をフォロー＆この投稿をリポストで応募完了
当選者は店頭受け取りの際に本人確認書類（運転免許証等）をご提示ください。
お1人様1回まで応募可能です。
公式Xでも最新情報をお届けしています。フォローしてね！
"""

APP = """キッズリパブリックアプリ限定の抽選です。
応募にはiAEON IDとの連携済みのアプリが必要です。
"""


def test_pco_style_conditions_are_structured_with_quotes():
    c = extract_conditions(PCO)
    assert set(c) == set(CONDITION_KEYS)
    m = c["membership_required"]
    assert m["value"] is True and "会員登録" in m["quote"]
    assert m["deadline"] and "受付開始までに" in m["deadline"]
    assert m["type"] == "ポケモンセンターオンラインの会員"
    assert c["other_conditions"] is None                      # 「【応募条件】」の見出しだけの行は条件にしない
    ph = c["purchase_history_required"]
    assert ph["value"] is True and ph["amount"].startswith("5,000円以上")
    assert ph["period"].startswith("2026年6月1日") and "11月30日" in ph["period"]
    assert c["purchase_limit"]["value"].startswith("お一人様1BOX") and c["application_limit"] is None
    assert c["region_limit"] and "日本国内" in c["region_limit"]["quote"]
    assert c["x_follow_required"] is None and c["x_repost_required"] is None and c["app_only"] is None


def test_shop_x_conditions_and_id_at_purchase():
    c = extract_conditions(SHOP)
    assert c["x_follow_required"]["value"] is True and c["x_repost_required"]["value"] is True
    assert "応募" in c["x_follow_required"]["quote"]          # 「最新情報をお届け」の案内の行ではない
    assert c["id_required_at_purchase"]["value"] is True and "本人確認書類" in c["id_required_at_purchase"]["quote"]
    assert c["application_limit"]["value"].startswith("お1人様1回") and c["purchase_limit"] is None


def test_x_follow_in_a_plain_notice_is_not_a_condition():
    c = extract_conditions("公式Xでも最新情報をお届けしています。フォローしてね！\n抽選の日程は後日お知らせします。")
    assert c["x_follow_required"] is None


def test_app_only_and_summary_labels():
    c = extract_conditions(APP)
    assert c["app_only"]["value"] is True
    assert c["membership_required"]["type"] == "iAEON ID"    # ID の連携も会員の条件として扱う
    labels = condition_summary(c)
    assert "アプリ限定" in labels and "iAEON IDが必要" in labels


def test_nothing_is_guessed_when_not_written():
    c = extract_conditions("抽選販売を実施します。応募期間：12月1日〜12月3日")
    assert all(c[k] is None for k in CONDITION_KEYS)
    assert condition_summary(c) == []
    assert extract_conditions("") == {k: None for k in CONDITION_KEYS}


def test_condition_chips_and_tier_tag_on_the_lottery_card():
    from src.content.tcg_hub_page import _cond_chips, _tier_tag
    from src.tcg.lottery.conditions import strip_quotes
    c = {k: v for k, v in extract_conditions(PCO).items() if v}
    html = _cond_chips(c)
    assert "お一人様1BOXまで" in html and "5,000円以上" in html and "登録期限" in html
    assert "title=" not in html and "させていただきます" not in html       # 根拠の行（原文）はページに出さない
    assert _cond_chips(strip_quotes(c)) == html
    assert "会員登録は不要" in _cond_chips({"membership_required": {"value": False}})
    assert _cond_chips({"id_required_at_purchase": {"value": False}}) == '<span class="req cd">本人確認は不要</span>'
    assert _cond_chips(None) == "" and _cond_chips({}) == ""
    assert "カードショップ" in _tier_tag("CARDBOX") and "メーカー公式" in _tier_tag("POKEMON_CENTER_ONLINE")
    assert _tier_tag("UNKNOWN_SHOP") == ""


def _build(adapter_cls, body):
    a = adapter_cls()
    return a.build_from_article(title="拡張パック「テスト」抽選販売のお知らせ", body=body,
                                url="https://example.invalid/x", published_at="2026-11-20T00:00:00+09:00",
                                targets=[{"product_name": "ポケモンカードゲーム 拡張パック「テスト」", "retail_price": None}])


BODY = ("抽選販売を行います。\n応募期間：11月21日 10:00～11月23日 23:59\n" + PCO)


def test_published_events_keep_structured_values_but_no_quotes():
    from src.collectors.tcg.lottery.clabo import CardLaboLotteryAdapter
    from src.collectors.tcg.lottery.pokemon_official import PokemonNewsLotteryAdapter
    from src.tcg.lottery.registry import QUOTE_ALLOWED
    assert not QUOTE_ALLOWED                                     # 規約で転載を確かめた取得元はまだ無い
    evs = _build(CardLaboLotteryAdapter, BODY)
    assert evs
    c = evs[0]["conditions"]
    assert c["purchase_limit"] == {"value": "お一人様1BOXまで"}       # 値は残し、根拠の行は出さない
    assert "other_conditions" not in c and all("quote" not in v for v in c.values())
    assert evs[0]["eligibility_text"]                            # 規約が未確認の取得元の既存の原文は従来どおり
    pk = _build(PokemonNewsLotteryAdapter, BODY)
    assert pk and not pk[0]["eligibility_text"] and pk[0]["membership_required"] is True   # 転載を断る取得元は原文を出さない



import pytest  # noqa: E402


@pytest.mark.parametrize("text", [
    "LINE公式アカウント(@cardshop)をフォローして応募",
    "Instagram(@shop_tcg)をフォローして抽選に参加",
    "インフェルノX 抽選応募 フォローお願いします",
    "先着11人 抽選で3BOX",
    "当選者は店頭でのお受け取りのみとなります",
    "無断未受取が複数回あると対象外",
    "ご購入いただいたお客様には特典カードをプレゼント",
])
def test_lookalikes_are_not_conditions(text):
    assert all(v is None for v in extract_conditions(text).values()), text


@pytest.mark.parametrize("text,key", [
    ("応募時に身分証は必要ありません", "id_required_at_purchase"),
    ("会員登録は不要です。どなたでもご応募いただけます。", "membership_required"),
    ("購入履歴は不要です", "purchase_history_required"),
])
def test_stated_not_required_is_false_not_unknown(text, key):
    c = extract_conditions(text)
    assert c[key]["value"] is False                                  # 「不要」と明記 = False（不明の None と区別する）
    assert all(v is None for k, v in c.items() if k != key)


def test_application_and_purchase_limits_are_separate():
    c = extract_conditions("お一人様1回まで応募可能です。当選者はお一人様1BOXまで購入できます。")
    assert c["application_limit"]["value"] == "お一人様1回まで" and c["purchase_limit"]["value"] == "お一人様1BOXまで"


def test_conditions_of_another_product_are_not_applied():
    body = "【商品A】ポケモンセンターの会員登録が必要です\n【商品B】お一人様2BOXまで"
    a = extract_conditions(body, other_products=["商品B"])
    assert a["membership_required"]["value"] is True and a["purchase_limit"] is None
    b = extract_conditions(body, other_products=["商品A"])
    assert b["membership_required"] is None and b["purchase_limit"]["value"] == "お一人様2BOXまで"


def test_negative_wording_that_states_a_requirement_is_kept():
    assert extract_conditions("購入履歴が無い方は対象外となります")["purchase_history_required"]["value"] is True
    assert extract_conditions("旧Twitterをフォローのうえ応募")["x_follow_required"]["value"] is True


def test_merge_fills_empty_conditions_only_from_an_official_source():
    from src.tcg.lottery.merge import merge_lotteries
    from src.tcg.lottery.schema import LotteryEvent
    base = dict(tcg="POKEMON", product_name="拡張パック「テスト」", retailer="GEO", application_start_date="2026-11-21",
                application_end_date="2026-11-23")
    top = LotteryEvent(**base, source_type="MANUFACTURER_OFFICIAL", source_url="https://a.invalid/1").to_dict()
    low = LotteryEvent(**base, source_type="RETAILER_OFFICIAL", source_url="https://a.invalid/2",
                       conditions={"purchase_limit": {"value": "お一人様1BOXまで"}}).to_dict()
    com = LotteryEvent(**base, source_type="COMMUNITY", source_url="https://a.invalid/3",
                       conditions={"app_only": {"value": True}}).to_dict()
    [m] = merge_lotteries([top, low])
    assert m["conditions"] == {"purchase_limit": {"value": "お一人様1BOXまで"}}     # 基準側の空の条件を公式の記録で埋める
    [m2] = merge_lotteries([top, com])
    assert m2["conditions"] == {}                                                   # 非公式の記録では埋めない


def test_application_word_before_the_limit_makes_it_an_application_limit():
    c = extract_conditions("※応募はお一人様1セットまでとなります。")
    assert c["application_limit"]["value"] == "お一人様1セットまで" and c["purchase_limit"] is None


def test_each_n_box_for_winners_is_a_purchase_limit():
    c = extract_conditions("当選者は各2BOXまでご購入いただけます。")
    assert c["purchase_limit"]["value"] == "各2BOXまで" and c["application_limit"] is None
    assert extract_conditions("各2BOXまで在庫があります")["purchase_limit"] is None        # 当選者・購入の文脈が無い行は使わない


# ── 最終レビューの指摘（否定の範囲・購入履歴の期間）の回帰 ──────────────────
def _vals(c):
    return {k: (v.get("value") if isinstance(v, dict) else v) for k, v in c.items() if v and k != "other_conditions"}


def test_negation_applies_only_to_its_own_clause_on_a_single_line():
    one_line = "応募には会員登録が必要です。購入履歴は問いません。ご購入時に本人確認書類をご提示ください。お一人様1BOXまで"
    assert _vals(extract_conditions(one_line)) == {"membership_required": True, "purchase_history_required": False,
                                                   "id_required_at_purchase": True, "purchase_limit": "お一人様1BOXまで"}
    assert _vals(extract_conditions("会員登録が必要です（購入履歴は不要）")) == {"membership_required": True,
                                                                          "purchase_history_required": False}
    assert extract_conditions("購入履歴が無い方でもご応募いただけます")["purchase_history_required"]["value"] is False


def test_same_condition_both_required_and_not_required_is_unknown():
    assert extract_conditions("会員登録が必要です。会員登録は不要です。")["membership_required"] is None


def test_purchase_history_period_is_never_the_application_period():
    from pathlib import Path

    from src.collectors.tcg.lottery import fukufuku
    fx = Path(__file__).parent / "fixtures" / "fukufuku"
    card = fukufuku.parse_listing((fx / "list.html").read_text(encoding="utf-8"))[0]
    text = fukufuku._text((fx / "detail_91.html").read_text(encoding="utf-8"))
    body = f"{fukufuku.schedule_text(card, text)} {text}"                   # 取得器と同じ本文の作り方
    ph = extract_conditions(body)["purchase_history_required"]
    assert ph["value"] is True and ph["period"] is None                   # 「応募期間：…」を購入履歴の期間にしない


def test_limits_split_by_clause_not_by_sentence():
    c = extract_conditions("お一人様1回限り応募可能、購入はお一人様1BOXまで")
    assert (c["application_limit"]["value"], c["purchase_limit"]["value"]) == ("お一人様1回限り", "お一人様1BOXまで")


def test_member_card_not_needed_is_not_membership_not_required():
    c = extract_conditions("ご購入時に本人確認をさせていただきます。会員証の提示は不要です")
    assert c["membership_required"] is None


@pytest.mark.parametrize("text", ["予約時にご本人様確認書類のご提示をお願いします。", "予約時にご本人様確認証のご提示をお願いします。",
                                  "ご購入時に本人確認証をお持ちください。"])
def test_id_document_with_sama_is_detected(text):
    assert extract_conditions(text)["id_required_at_purchase"]["value"] is True


def test_id_not_needed_and_other_products_id_are_not_required():
    assert extract_conditions("ご本人様確認書類の提示は不要です。")["id_required_at_purchase"]["value"] is False
    body = "【商品A】予約時にご本人様確認書類のご提示をお願いします。\n【商品B】お一人様1BOXまで"
    assert extract_conditions(body, other_products=["商品A"])["id_required_at_purchase"] is None     # 別の商品の条件を付けない


@pytest.mark.parametrize("text", ["販売時に身分証明書のご提示をお願いする場合があります。",
                                  "ご予約並びにご購入時に、免許証やマイナンバーなど本人確認書類をご提示頂く場合がございます。"])
def test_conditional_id_request_is_unknown_not_required(text):
    assert extract_conditions(text)["id_required_at_purchase"] is None


@pytest.mark.parametrize("text,expect", [
    ("原則として本人確認書類は不要ですが、提示をお願いする場合があります。", None),
    ("本人確認書類は不要です。ただし不正が疑われる場合は提示をお願いする場合があります。", None),
    ("本人確認書類の提示をお願いする事があります。", None),
    ("本人確認書類の提示をお願いする可能性があります。", None),
    ("場合によっては本人確認書類の提示をお願いします。", None),
    ("本人確認書類をご持参ください（お忘れの場合はご購入いただけないことがあります）。", True),
    ("本人確認書類（運転免許証など）のご提示をお願いする場合があります。", None),
    ("本人確認書類は、ご提示いただく場合があります。", None),
    ("本人確認書類の提示は不要です。会員証の提示をお願いする場合があります。", False),
    ("本人確認書類をご提示ください、お持ちでない場合は購入できないことがあります。", True),
    ("本人確認書類が必要です（ご提示いただけない場合は購入をお断りすることがあります）。", True),
])
def test_conditional_or_mixed_id_wording(text, expect):
    v = extract_conditions(text)["id_required_at_purchase"]
    assert (v["value"] if v else None) is expect
