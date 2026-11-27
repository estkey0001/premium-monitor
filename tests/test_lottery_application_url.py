"""応募先の確認（応募 URL の確認率 0/8 の調査で見つけた、公式の告知に載った外部フォームを取得器が捨てていた件の回帰）。"""
from datetime import datetime

from src.collectors.tcg.lottery.base import external_form_in
from src.tcg.action_url import classify
from src.tcg.models import JST

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=JST)
HBST = ("「ポケモンカードゲームMEGA 拡張パック ムニキスゼロ/ハドウシーカー」の再販商品を抽選販売いたします。\n"
        "■応募方法：Livepocket（ライブポケット）を使用したWEB抽選を行います。\n抽選受付ページリンク\n"
        "ムニキスゼロ：\nhttps://livepocket.jp/e/aaaa1\nハドウシーカー：\nhttps://livepocket.jp/e/bbbb2\n"
        "■応募期間：2026年11月24日(火)12：00～11月26日(木)23：59まで")


NAMES = ["拡張パック「ムニキスゼロ」", "拡張パック「ハドウシーカー」"]


def test_external_form_is_taken_per_product_from_the_official_announcement():
    assert external_form_in(HBST, "HOBBY_STATION", NAMES[1], NAMES) == "https://livepocket.jp/e/bbbb2"
    assert external_form_in(HBST, "HOBBY_STATION", NAMES[0], NAMES) == "https://livepocket.jp/e/aaaa1"
    assert external_form_in(HBST, "HOBBY_STATION", "拡張パック二種（再販）", NAMES + ["拡張パック二種（再販）"]) is None
    assert external_form_in(HBST, "HOBBY_STATION", NAMES[1]) is None      # 対象商品が 1 つの告知なのに URL が 2 つ → 決めない
    assert external_form_in(HBST, "CARDBOX", NAMES[1], NAMES) is None     # その取得元に認めた形ではない


def test_external_form_of_another_product_is_never_taken():
    one = "ハドウシーカー：https://livepocket.jp/e/hadou ムニキスゼロは店頭で抽選します"
    assert external_form_in(one, "HOBBY_STATION", NAMES[0], NAMES) is None       # URL が 1 つでも、別の商品のもの（直前の名前が違う）
    assert external_form_in(one, "HOBBY_STATION", NAMES[1], NAMES) == "https://livepocket.jp/e/hadou"
    rev = "https://livepocket.jp/e/hadou（ハドウシーカー） https://livepocket.jp/e/munikis（ムニキスゼロ）"
    assert external_form_in(rev, "HOBBY_STATION", NAMES[1], NAMES) is None       # 「URL（商品名）」の順は取り違えうるので取らない
    one = "お申し込みはこちら 熊本店 https://livepocket.jp/e/od_5n"
    assert external_form_in(one, "MUGIWARA_STORE", "x") == "https://livepocket.jp/e/od_5n"
    assert external_form_in("https://livepocket.jp/e/mypage", "MUGIWARA_STORE", "x") is None   # 個別のフォームでない


def test_collector_keeps_the_external_form_and_classify_treats_it_as_external_only():
    from src.collectors.tcg.lottery.hbst import HobbyStationLotteryAdapter
    a = HobbyStationLotteryAdapter()
    evs = a.build_from_article(title="【2026.11.24】抽選販売「拡張パック「ハドウシーカー」（再販）」", body=HBST,
                               url="https://www.hbst.net/?p=412193", published_at="2026-11-24T00:00:00+09:00", tcg_hint="POKEMON",
                               targets=[{"product_name": n, "retail_price": None} for n in reversed(NAMES)])
    assert evs and evs[0]["entry_url"] is None and evs[0]["external_form_url"] == "https://livepocket.jp/e/bbbb2"
    assert evs[1]["external_form_url"] == "https://livepocket.jp/e/aaaa1"            # 商品ごとに自分のフォーム
    c = classify(evs[0], NOW)
    assert c["external_entry_url"] == "https://livepocket.jp/e/bbbb2" and c["application_url"] is None   # 応募ボタンにはしない
    from src.content.ui import runtime as rt
    assert rt.tcg_vm(evs[0], 0)["apply"] == ""


def test_kpis_split_web_url_rate_and_other_methods():
    from src.tcg.lottery.evaluation import kpis
    hb = {"status": "OPEN", "retailer": "HOBBY_STATION", "source_type": "RETAILER_OFFICIAL",
          "source_url": "https://www.hbst.net/?p=1", "external_form_url": "https://livepocket.jp/e/bbbb2"}
    clabo = {"status": "OPEN", "retailer": "CARD_LABO", "source_type": "STORE_OFFICIAL",
             "source_url": "https://www.c-labo.jp/shop/a/blog/1/"}
    unknown = {"status": "UPCOMING", "retailer": "CARDBOX", "source_type": "STORE_OFFICIAL",
               "source_url": "https://cardbox.online/news/detail/?id=1"}
    k = kpis([hb, clabo, unknown], [], generated_at="2026-11-26T12:00:00+09:00")
    assert (k["web_application_url_confirmed"]["num"], k["web_application_url_confirmed"]["den"]) == (1, 1)
    assert (k["non_web_method_confirmed"]["num"], k["non_web_method_confirmed"]["den"]) == (1, 3)
    assert k["application_channel_unknown"]["count"] == 1


def test_deploy_check_763_stays_ok_with_an_external_form():
    """外部フォームは entry_url（公式ドメインだけ）に入れないので、#763 を落とさない（Daily LP を止めない）。"""
    import scripts.deploy_check as dc
    ev = {"tcg": "POKEMON", "retailer": "HOBBY_STATION", "source_type": "RETAILER_OFFICIAL", "source_url": "https://www.hbst.net/?p=1",
          "entry_url": None, "external_form_url": "https://livepocket.jp/e/bbbb2"}
    from src.tcg.lottery.manual import is_official_url
    assert not (ev.get("entry_url") and not is_official_url(ev["entry_url"]))
    assert "external_form_url" not in dc.__dict__.get("_ENTRY_KEYS", ())


def test_application_methods_from_the_announcement_text():
    from src.tcg.lottery.parse import detect_application_methods
    assert detect_application_methods("下記のフォームの注意事項をご確認の上、ご応募ください。https://shoplottery.e-starbox.com/lottery/entry?code=x") == ["web_form"]
    assert detect_application_methods("アカウントをフォロー＆対象ポストのリポストでご応募いただけます。") == ["sns"]
    assert detect_application_methods("レジで意思表示をされた方にQRコードを差し出します。QRコードを携帯端末で読み取っていただきます") == ["store"]
    assert detect_application_methods("応募には会員ログインが必要です") == ["member_login"]
    assert detect_application_methods("抽選販売を行います。") == []                          # 書かれていなければ推測しない


def test_web_is_decided_by_the_stated_method_not_by_the_allowed_form_rules():
    """e-starbox は外部フォームの許可の規則に無いが、告知に Web のフォームと書かれていれば Web の分母に入る（URL は未確認のまま）。"""
    from src.tcg.lottery.evaluation import kpis
    cb = {"status": "OPEN", "retailer": "CARDBOX", "source_type": "STORE_OFFICIAL",
          "source_url": "https://cardbox.online/news/detail/?id=1864", "application_methods": ["web_form"]}
    tp = {"status": "OPEN", "retailer": "TORECAPLAZA55", "source_type": "STORE_OFFICIAL", "source_url": "https://torecaplaza55.com/"}
    k = kpis([cb, tp], [], generated_at="2026-11-26T12:00:00+09:00")
    assert (k["web_application_url_confirmed"]["num"], k["web_application_url_confirmed"]["den"]) == (0, 2)
    assert k["application_channel_unknown"]["count"] == 0


def test_deadline_only_row_is_not_in_the_open_or_today_filters():
    from src.content.tcg_hub_page import _state_tokens
    v = {"status": "OPEN", "deadline_only": True}
    toks = _state_tokens(v, {"today", "new"}).split()
    assert "deadline_only" in toks and not {"open", "ending", "today"} & set(toks) and "new" in toks
    assert "open" in _state_tokens({"status": "OPEN", "deadline_only": False}, set()).split()


def test_application_methods_ignore_negated_methods():
    from src.tcg.lottery.parse import detect_application_methods as dm
    assert dm("アプリでの応募はできません。") == []
    assert dm("応募フォームはございません。店頭にて抽選を行います。") == ["store"]
    assert dm("店頭での受付は行いません。応募は下記フォームから。") == ["web_form"]
    assert dm("応募フォームから応募できない場合は店舗へお問い合わせください。") == ["web_form"]   # 条件の説明は否定にしない
    # 読点の後ろの別のことへの否定（重複応募・キャンセル・電話）や「〜ではありません」は、方法の否定にしない
    assert dm("応募フォームから応募、重複応募はできません。") == ["web_form"]
    assert dm("アプリから応募、キャンセルはできません。") == ["app"]
    assert dm("店頭にて受付、電話での受付はできません") == ["store"]
    assert dm("livepocket.jpより応募、変更・キャンセル不可") == ["web_form"]
    assert dm("WEB抽選は先着順ではありません。") == ["web_form"]
    # 「実施しません」「公開していません」「不要」「条件ではありません」も方法の否定（KPI の Web の分母を膨らませない）
    for t in ("店頭での抽選は実施しません", "オンライン抽選は当店では実施しておりません", "応募フォームは公開していません",
              "会員ログインは不要です", "応募にはフォローは不要です", "フォローは応募条件ではありません"):
        assert dm(t) == [], t
    assert dm("店頭にて抽選を行います。抽選券は不要です") == ["store"]                # 別のものの「不要」は方法の否定にしない
    for t, want in (("WEB抽選は会員登録不要です。", ["web_form"]), ("WEB抽選は購入履歴不要", ["web_form"]),
                    ("応募フォームは事前登録不要", ["web_form"]), ("店頭にて抽選は予約不要", ["store"]),
                    ("WEB抽選は一部店舗は対象外です", ["web_form"])):
        assert dm(t) == want, t                                                    # ほかの条件の「不要」「対象外」は方法の否定にしない
