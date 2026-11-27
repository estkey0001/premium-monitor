"""抽選の収集の評価（再現率・抽出精度・検出遅延）。通信しない。"""
import json

from src.tcg.lottery.evaluation import detection_latency, evaluate, load_golden

REC = [
    {"lottery_id": "a", "retailer": "CARD_LABO", "source_url": "https://www.c-labo.jp/shop/x/blog/1/",
     "product_name": "拡張パック「テスト」", "application_start": "2026-11-21T10:00:00+09:00",
     "application_end": "2026-11-23T23:59:00+09:00", "retail_price": 5400,
     "conditions": {"membership_required": {"value": True}, "purchase_limit": {"value": "お一人様1BOXまで"}},
     "published_at": "2026-11-20", "first_seen_at": "2026-11-20T15:00:00+09:00"},
    {"lottery_id": "b", "retailer": "HOBBY_STATION", "source_url": "https://www.hbst.net/?p=2",
     "product_name": "別の商品", "application_start_date": "2026-11-25",
     "published_at": "2026-11-24", "first_seen_at": "2026-11-26T12:00:00+09:00"},
]


def test_recall_and_field_accuracy():
    golden = [
        {"golden_id": "g1", "retailer": "CARD_LABO", "source_url": "https://www.c-labo.jp/shop/x/blog/1/",
         "application_start": "2026-11-21T10:00:00+09:00", "application_end": "2026-11-23T20:00:00+09:00",
         "retail_price": 5400, "conditions": {"membership_required": True, "purchase_limit": "お一人様1BOXまで",
                                              "x_follow_required": True}, "verified_on": "2026-11-26"},
        {"golden_id": "g2", "retailer": "GEO", "source_url": "https://geo-online.co.jp/x", "verified_on": "2026-11-26"},
    ]
    r = evaluate(golden, REC)
    assert r["golden"] == 2 and r["matched"] == 1 and r["recall"] == 0.5 and r["missed"] == ["g2"]
    acc = r["accuracy"]
    assert acc["application_start"]["rate"] == 1.0 and acc["application_end"]["rate"] == 0.0   # 締切の時刻の食い違いを数える
    assert acc["retail_price"]["rate"] == 1.0 and acc["membership_required"]["rate"] == 1.0
    assert acc["purchase_limit"]["rate"] == 1.0
    assert acc["x_follow_required"]["rate"] == 0.0                     # 記録に無い条件は不一致


def test_match_by_product_and_start_day_when_url_differs():
    golden = [{"golden_id": "g", "retailer": "HOBBY_STATION", "source_url": "https://www.hbst.net/?p=999",
               "product_name": "別の商品", "application_start_date": "2026-11-25", "verified_on": "2026-11-26"}]
    assert evaluate(golden, REC)["matched"] == 1


def test_latency_and_onboarding_day_exclusion():
    lat = detection_latency(REC)
    assert lat["by_retailer"]["CARD_LABO"]["median_hours"] == 15.0          # 日付だけの公開日は 00:00 とみなす
    assert lat["by_retailer"]["HOBBY_STATION"]["median_hours"] == 60.0
    # 取得元を入れた日（その取得元の最初の記録日）に記録したものは除く
    assert detection_latency(REC, exclude_backlog=True)["overall"] == {"n": 0}


def test_latency_uses_the_earliest_record_of_the_same_announcement():
    # 商品名の読み方の修正で抽選 ID が変わり、同じ告知が後日に記録し直されても、遅延は最初の記録で数える
    again = dict(REC[0], lottery_id="a2", first_seen_at="2026-11-25T12:00:00+09:00")
    lat = detection_latency([REC[0], again])
    assert lat["by_retailer"]["CARD_LABO"] == {"n": 1, "median_hours": 15.0, "max_hours": 15.0}


def test_golden_requires_verification_date(tmp_path):
    p = tmp_path / "g.json"
    p.write_text(json.dumps({"schema": 1, "items": [{"retailer": "GEO"}, {"retailer": "GEO", "verified_on": "2026-11-26"}]}),
                 encoding="utf-8")
    assert len(load_golden(p)) == 1                                     # 確かめた日の無い行は正解として使わない
    assert load_golden(tmp_path / "none.json") == []


def test_schedule_compared_as_time_and_one_record_per_golden():
    g = {"retailer": "CARD_LABO", "source_url": "https://www.c-labo.jp/shop/x/blog/1/",
         "application_start": "2026-11-21T10:00+09:00", "verified_on": "2026-11-26"}
    r = evaluate([dict(g, golden_id="g1"), dict(g, golden_id="g2")], REC)
    assert r["accuracy"]["application_start"]["rate"] == 1.0              # 秒の有無が違っても同じ時刻
    assert r["matched"] == 1 and r["missed"] == ["g2"]                    # 同じ記録を2つのゴールデンに数えない


def test_human_and_ai_verified_golden_are_kept_apart():
    from src.tcg.lottery.evaluation import verifier_class
    assert verifier_class({"verified_by": "human:ops"}) == "human"
    assert verifier_class({"verified_by": "ai:claude（人の確認待ち）"}) == "ai_unreviewed"
    assert verifier_class({}) == "ai_unreviewed"                         # 確認者の無い正解は人の確認として数えない


def test_kpis_have_denominators_and_separate_start_unknown():
    from src.tcg.lottery.evaluation import kpis
    items = [{"status": "OPEN", "application_end": "2026-11-30T23:59:00+09:00", "product_match": "exact"},
             {"status": "ENDING_SOON", "application_start": "2026-11-20T10:00:00+09:00", "retail_price": 5400, "price_unit": "BOX"},
             {"status": "WINNER_PURCHASE_PERIOD"}, {"status": "UPCOMING"}]
    k = kpis(items, [], generated_at="t")
    assert k["active_open_or_ending"]["count"] == 2 and k["active_open_or_ending"]["of_which_start_date_unknown"] == 1
    assert k["application_url_confirmed"]["den"] == 3                     # 購入期間だけの行は分母に入れない
    assert k["product_identity_confirmed"] == {**k["product_identity_confirmed"], "num": 1, "den": 4}
    assert k["price_confirmed"]["num"] == 1 and "recall" in k["not_measured"]


def test_golden_file_is_real_data_with_verifier_and_no_page_text():
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "data" / "golden" / "lottery_golden.json"
    items = load_golden(p)
    assert len([g for g in items if g.get("kind") != "non_lottery"]) >= 8
    assert {g["retailer"] for g in items} >= {"HOBBY_STATION", "CARDBOX", "CARD_LABO", "FUKUFUKU_TOREKA", "MUGIWARA_STORE"}
    for g in items:
        assert g["verified_on"] and g["verified_by"].startswith(("human", "ai:"))
        assert not {"text", "body", "quote", "eligibility_text", "email", "phone"} & set(g)   # 本文・個人情報を入れない
    raw = p.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "@" not in raw


def test_non_lottery_announcement_published_as_lottery_is_counted():
    from src.tcg.lottery.evaluation import false_positives
    neg = [{"golden_id": "n", "retailer": "HOBBY_STATION", "title_contains": "休業"}]
    assert false_positives(neg, [{"retailer": "HOBBY_STATION", "product_name": "一部店舗休業のお知らせ"}]) == ["n"]
    assert false_positives(neg, REC) == []


def test_multi_product_announcement_is_not_matched_to_another_products_record():
    from src.tcg.lottery.evaluation import match
    recs = [{"retailer": "HOBBY_STATION", "source_url": "https://www.hbst.net/?p=1", "product_name": "拡張パック「A」"},
            {"retailer": "HOBBY_STATION", "source_url": "https://www.hbst.net/?p=1", "product_name": "拡張パック二種"}]
    g = {"retailer": "HOBBY_STATION", "source_url": "https://www.hbst.net/?p=1", "product_core": "B"}
    assert match(g, recs) is None and match({**g, "product_core": "A"}, recs) is recs[0]


def test_fallback_match_requires_the_same_branch():
    from src.tcg.lottery.evaluation import match
    recs = [{"retailer": "CARD_LABO", "store_specific": True, "store_name": "カードラボ姫路店", "product_name": "神の支配",
             "application_start_date": "2026-11-06", "source_url": "https://www.c-labo.jp/shop/himeji/blog/1/"}]
    g = {"retailer": "CARD_LABO", "source_url": "https://www.c-labo.jp/blog/2/", "product_core": "神の支配",
         "application_start_date": "2026-11-06", "store_name": "カードラボ鹿児島店"}
    assert match(g, recs) is None and match({**g, "store_name": "カードラボ姫路店"}, recs) is recs[0]


def test_same_url_multi_branch_records_match_only_the_golden_branch():
    from src.tcg.lottery.evaluation import match
    u = "https://www.mugiwara-store.com/news/1/"
    recs = [{"retailer": "MUGIWARA_STORE", "store_specific": True, "store_name": "ONE PIECE 麦わらストア 福岡店", "source_url": u,
             "product_name": "熊本県スペシャル"},
            {"retailer": "MUGIWARA_STORE", "store_specific": True, "store_name": "ONE PIECE 麦わらストア 熊本店", "source_url": u,
             "product_name": "熊本県スペシャル"}]
    g = {"retailer": "MUGIWARA_STORE", "source_url": u, "product_core": "熊本県スペシャル", "store_name": "ONE PIECE 麦わらストア 熊本店"}
    assert match(g, recs) is recs[1]
    assert match({**g, "store_name": "カードラボ"}, [dict(recs[0], store_name="")]) is None          # 空・チェーン名だけは一致にしない
