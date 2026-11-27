# -*- coding: utf-8 -*-
"""Task1 / Task2 / Task32 / Task33 / Task34: 抽選 source の registry とカバレッジ。

「抽選0件」と表示するときに、それが
  - 本当に抽選が無い（NO_ACTIVE_LOTTERY）
  - そもそも監視していない（SOURCE_NOT_MONITORED）
  - アクセスを拒否されている（SOURCE_BLOCKED）
  - 到達できない（SOURCE_UNREACHABLE）
のどれなのかを必ず区別する。
"""
from __future__ import annotations

from typing import Optional

# ── 収集方法（Task1） ────────────────────────────────────────────────────
CM_API = "API"
CM_HTML = "HTML"
CM_PLAYWRIGHT = "PLAYWRIGHT"
CM_RSS = "RSS"
CM_OFFICIAL_NEWS = "OFFICIAL_NEWS"
CM_MANUAL_VERIFIED = "MANUAL_VERIFIED"
CM_UNAVAILABLE = "UNAVAILABLE"
COLLECTION_METHODS = (CM_API, CM_HTML, CM_PLAYWRIGHT, CM_RSS, CM_OFFICIAL_NEWS,
                      CM_MANUAL_VERIFIED, CM_UNAVAILABLE)

# ── 監視状態（Task34） ───────────────────────────────────────────────────
ST_ACTIVE_LOTTERY = "ACTIVE_LOTTERY"            # 実装済み・取得成功・抽選あり
ST_NO_ACTIVE_LOTTERY = "NO_ACTIVE_LOTTERY"      # 実装済み・取得成功・現在の抽選なし
ST_SOURCE_BLOCKED = "SOURCE_BLOCKED"            # HTTP 403 / bot チャレンジ等
ST_SOURCE_UNREACHABLE = "SOURCE_UNREACHABLE"    # タイムアウト・接続失敗
ST_SOURCE_NOT_MONITORED = "SOURCE_NOT_MONITORED"  # 収集処理が未実装
ST_SOURCE_DEGRADED = "SOURCE_DEGRADED"          # 取得できたが告知一覧を発見できない
ST_SOURCE_FAILED = "SOURCE_FAILED"              # 実装済みだが取得に失敗
SOURCE_STATES = (ST_ACTIVE_LOTTERY, ST_NO_ACTIVE_LOTTERY, ST_SOURCE_BLOCKED,
                 ST_SOURCE_UNREACHABLE, ST_SOURCE_NOT_MONITORED, ST_SOURCE_DEGRADED,
                 ST_SOURCE_FAILED)
STATE_LABELS = {
    ST_ACTIVE_LOTTERY: "抽選あり", ST_NO_ACTIVE_LOTTERY: "現在の抽選なし",
    ST_SOURCE_BLOCKED: "アクセス拒否", ST_SOURCE_UNREACHABLE: "接続できない",
    ST_SOURCE_NOT_MONITORED: "未監視（未実装）", ST_SOURCE_DEGRADED: "要確認",
    ST_SOURCE_FAILED: "取得失敗",
}

POKEMON = "POKEMON"
ONE_PIECE = "ONE_PIECE"


def _src(source_id, retailer, brands, priority, official_url, method, *,
         lottery_url=None, news_url=None, channel="ONLINE", adapter=None,
         verified=False, note=None, policy_excluded=None):
    return {
        "source_id": source_id,
        "retailer": retailer,
        "brand": list(brands),
        "priority": priority,                 # P0 / P1 / P2
        "official_url": official_url,
        "lottery_url": lottery_url,
        "news_url": news_url,
        "channel": channel,
        "collection_method": method,
        # adapter: 実装済みの抽選コレクター名。None は「監視対象として登録のみ」
        "adapter": adapter,
        # verified: URL の到達性・内容を実際に確認済みか（推測 URL を検証済みにしない）
        "verified": verified,
        "note": note,
        # policy_excluded: 取得しない方針の理由（プロジェクトの取得の作法・規約による。到達できても実装の候補にしない）
        "policy_excluded": policy_excluded,
    }


_BOTH = (POKEMON, ONE_PIECE)

# 2026-10-01 に各サイトのトップ・一覧を実際に取得して確認した結果に基づく
LOTTERY_SOURCES: list[dict] = [
    # ── Pokemon P0 ───────────────────────────────────────────────────
    _src("POKEMON_CENTER_ONLINE", "ポケモンセンターオンライン", (POKEMON,), "P0",
         "https://www.pokemoncenter-online.com/", CM_OFFICIAL_NEWS,
         news_url="https://www.pokemon-card.com/info/", adapter="pco_lottery",
         verified=True,
         note="抽選告知は公式ニュース一覧のリンクから発見。PCO 本体は CI から HTTP 403 "
              "のため、本文が取れない場合は手動確認済みデータで補う（bot 対策は回避しない）"),
    _src("POKEMON_CARD_OFFICIAL", "ポケモンカードゲーム公式（ニュース）", (POKEMON,), "P0",
         "https://www.pokemon-card.com/", CM_OFFICIAL_NEWS,
         news_url="https://www.pokemon-card.com/info/", adapter="pokemon_news_lottery",
         verified=True),
    # ── Pokemon / ONE PIECE P1（量販店） ─────────────────────────────
    _src("GEO", "ゲオ", _BOTH, "P1", "https://geo-online.co.jp/", CM_HTML,
         news_url="https://geo-online.co.jp/news/",
         lottery_url="https://draw.geo-online.co.jp/lottery/", channel="STORE",
         adapter="geo_lottery", verified=True),
    _src("CARD_LABO", "カードラボ", _BOTH, "P1", "https://www.c-labo.jp/", CM_HTML,
         news_url="https://www.c-labo.jp/blog/filter/tcg:25/", channel="STORE", adapter="card_labo_lottery",
         verified=True,
         note="店舗ブログに抽選・抽選予約の告知が静的 HTML で載る（応募期間・当選発表・購入期間・商品名・価格が本文のテキスト）。"
              "応募は店舗の X のフォロー＆リポストで、公式ドメインの応募ページは無い（entry_url は空）。店舗ごとの抽選として扱う。"
              "robots.txt は /wordpress/wp-admin/ だけを禁止していて、対象ページは禁止していない（確認日 2026-10-24）。"
              "利用規約の本文は未読で、許可も禁止も未確認（読んだら、この記述と取得可否を見直す）"),
    _src("HOBBY_STATION", "ホビーステーション", _BOTH, "P1", "https://www.hbst.net/", CM_HTML,
         news_url="https://www.hbst.net/result/?category=news", channel="STORE", adapter="hobby_station_lottery",
         verified=True,
         note="公式のお知らせ（WordPress）に抽選販売の告知が静的 HTML で載り、応募期間・当選発表・当選者購入期間が「■応募期間：」の"
              "固定の書式で本文のテキストにある。応募は Livepocket（外部。公式ドメインではないので entry_url は空）。店舗横断の1本の告知。"
              "robots.txt は /wordpress/wp-admin/ だけを禁止していて、対象ページは禁止していない（確認日 2026-10-28）。"
              "利用規約の本文は未読で、許可も禁止も未確認（読んだら、この記述と取得可否を見直す）"),
    _src("KIDS_REPUBLIC", "キッズリパブリック（イオン）", _BOTH, "P1", "https://www.kidsrepublic.jp/", CM_HTML,
         news_url="https://www.kidsrepublic.jp/campaign", channel="APP", adapter="kids_republic_lottery", verified=True,
         note="キャンペーン情報に、アプリ抽選の告知（応募受付期間・当選発表日・購入期間）が静的 HTML のテキストで載る。応募はキッズリパブリックの"
              "アプリ（iAEON ID 連携）で公式ドメインの応募ページは無い（entry_url は空）。本州・四国の直営おもちゃ売場。一覧にはポケカ・ONE PIECE 以外も"
              "混ざるのでタイトルで絞る。robots.txt は 404 で制限の記載なし（確認日 2026-10-29）。"
              "サイト利用規約（https://www.kidsrepublic.jp/terms、確認日 2026-11-26）: 運営はイオンリテール株式会社。第7条が私的使用を超える複製を禁じ、"
              "第3条が承認の無い営利目的の利用を禁じる。自動取得を名指しで禁じる条項は無い。応募条件の原文は出力しない（構造化した値だけ）。"
              "取得そのものを続けてよいかは人の判断待ち"),
    _src("FUKUFUKU_TOREKA", "福福トレカ", (POKEMON,), "P2", "https://pokemon.fukufukutoreka.com/", CM_HTML,
         news_url="https://pokemon.fukufukutoreka.com/lottery", channel="ONLINE", adapter="fukufuku_lottery", verified=True,
         note="小規模な通販店。抽選販売の一覧（/lottery）と詳細に、応募期間・抽選日・購入期限が静的 HTML のテキストで載る（応募期間は年が省略されるので、"
              "一覧の応募締切の年で補う）。応募は会員ログインが必要で、応募そのものは取らない（entry_url は空）。robots.txt は"
              " /*.csv$・/cart・/shopping・/mypage だけを禁止で /lottery は禁止していない（確認日 2026-10-29）。"
              "利用規約の本文は読んだ記録（確認日・URL）がなく、許可も禁止も未確認（読んだら、この記述と取得可否を見直す）"),
    _src("MUGIWARA_STORE", "ONE PIECE 麦わらストア", (ONE_PIECE,), "P1", "https://www.mugiwara-store.com/", CM_HTML,
         news_url="https://www.mugiwara-store.com/news/", channel="STORE", adapter="mugiwara_store_lottery", verified=True,
         note="公式のお知らせ（WordPress）に、ONE PIECE カードゲームの抽選販売の告知が静的 HTML のテキストで年つきで載る（抽選受付期間・抽選結果発表・"
              "商品販売期間）。応募は LivePocket（外部。店舗ごとに別のページ・公式ドメインではないので entry_url は空）。複数店舗の1本の告知。"
              "robots.txt は /wp-admin/ だけを禁止していて対象ページは禁止していない（確認日 2026-10-29）。"
              "利用規約の本文は読んだ記録（確認日・URL）がなく、許可も禁止も未確認（読んだら、この記述と取得可否を見直す）。クラウド IP から遮断されたら WORKING に数えない（回避しない）"),
    _src("TOYSRUS", "トイザらス", _BOTH, "P1", "https://www.toysrus.co.jp/", CM_HTML,
         note="2026-10-01 時点でトップページが HTTP 403（ローカル・CI とも）。解析器は未実装"),
    _src("JOSHIN", "Joshin", _BOTH, "P1", "https://joshinweb.jp/", CM_HTML,
         note="2026-10-01 時点でトップページが HTTP 403。解析器は未実装"),
    _src("EDION", "エディオン", _BOTH, "P1", "https://www.edion.com/", CM_HTML,
         note="到達可。2026-10-24 の調査: 公開のお知らせ一覧（/info.html）に TCG の告知が0件（最新は2024年）で、抽選・予約の告知が"
              "載る形を確認できない。解析器は未実装（実装の価値が低い）"),
    _src("YAMADA", "ヤマダデンキ", _BOTH, "P1", "https://www.yamada-denkiweb.com/", CM_HTML,
         note="2026-10-01 時点で応答タイムアウト。解析器は未実装"),
    _src("TSUTAYA", "TSUTAYA", _BOTH, "P1", "https://store-tsutaya.tsite.jp/", CM_HTML,
         note="2026-10-24 時点でサイト全体が保守で停止（robots.txt もトップも保守ページ。再開は 2026/10/30 の予定）。"
              "告知の有無・構造は未確認。保守明けに robots.txt から取り直して再調査する"),
    _src("BICCAMERA", "ビックカメラ", _BOTH, "P1", "https://www.biccamera.com/", CM_HTML,
         note="2026-10-01 時点で応答タイムアウト。解析器は未実装"),
    _src("YODOBASHI", "ヨドバシカメラ", _BOTH, "P1", "https://www.yodobashi.com/", CM_HTML,
         note="2026-10-01 時点で応答タイムアウト。解析器は未実装"),
    # ── P2（EC・コンビニ） ───────────────────────────────────────────
    _src("AMAZON", "Amazon", _BOTH, "P2", "https://www.amazon.co.jp/", CM_HTML,
         note="自動アクセスに応答本文を返さない（HTTP 202）。解析器は未実装",
         policy_excluded="Amazon はスクレイピングしない（取得の作法。公式 API が使えるときだけ）"),
    _src("RAKUTEN_BOOKS", "楽天ブックス", _BOTH, "P2", "https://books.rakuten.co.jp/", CM_HTML,
         note="到達可。TCG 抽選の告知一覧を発見できず、解析器は未実装"),
    _src("SEVEN_NET", "セブンネットショッピング", _BOTH, "P2", "https://7net.omni7.jp/", CM_HTML,
         note="到達可。2026-10-24 の調査: 公開のお知らせ・キャンペーンに TCG の語が0件。TCG は商品ページ単位で、告知ページが無い"
              "ので、告知の自動発見に向かない。解析器は未実装（実装の価値が低い）"),
    _src("LAWSON", "ローソン", _BOTH, "P2", "https://www.lawson.co.jp/", CM_HTML,
         news_url="https://www.lawson.co.jp/campaign/", channel="STORE",
         adapter="lawson_lottery", verified=True),
    # ── ONE PIECE P0 ─────────────────────────────────────────────────
    _src("ONEPIECE_CARD_OFFICIAL", "ONE PIECEカードゲーム公式", (ONE_PIECE,), "P0",
         "https://www.onepiece-cardgame.com/", CM_OFFICIAL_NEWS,
         news_url="https://www.onepiece-cardgame.com/news/", adapter="onepiece_news_lottery",
         verified=True),
    _src("ONEPIECE_CARD_OFFICIAL_SHOP", "ONE PIECEカードゲーム公式ショップ", (ONE_PIECE,), "P0",
         "https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/", CM_HTML,
         news_url="https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/", channel="STORE",
         adapter="bnam_onepiece_shop_lottery", verified=True,
         note="公式ショップのトップの「重要なお知らせ」に事前抽選の告知が載り、詳細の表に申込受付期間（年つき。終了側の年・月は省略されるので開始から補う）と"
              "抽選販売日（購入期間として読む）がテキストである。/news/ の一覧は 404 なのでトップから辿る。応募は会員制の購入権チケットのページ"
              "（parks2.bandainamco-am.co.jp。取得しない）で、OFFICIAL_DOMAINS に無いので entry_url は空。全店共通の1本の告知。"
              "robots.txt は User-agent: * と Sitemap だけで禁止の行が無い（確認日 2026-11-26）。サイトポリシー（https://bandainamco-am.co.jp/attention/、"
              "確認日 2026-11-26）は私的使用を超える複製を禁じる（本文は保存・転載しない）。自動取得を禁じる条項は見当たらないが、許可の明記でもない"),
    _src("CARDBOX", "CARD BOX（加盟店）", _BOTH, "P1", "https://cardbox.online/", CM_HTML,
         news_url="https://cardbox.online/news/shop_list/", channel="STORE", adapter="cardbox_lottery", verified=True,
         note="加盟店（公式サイト上の表記で107店）の店舗ニュースを1つの一覧に載せる。taxonomy（ポケモンカードゲーム／ONE PIECEカードゲーム）と件名の"
              "「抽選」「購入権」で絞り、詳細の「抽選受付期間」「当選番号の発表」を読む（年は投稿日時で補う）。当選者発表だけの告知は受付にしない。"
              "店ごとの抽選。応募は店ごとの外部フォームで公式ドメインではない（entry_url は空）。1回の実行で一覧2ページ＋詳細6件まで。"
              "robots.txt は「User-agent: * / Allow:/」で全体を許可（確認日 2026-11-26）。"
              "利用規約のページは見つからず、許可も禁止も未確認（見つけたら、この記述と取得可否を見直す）"),
    _src("PLANT", "スーパーセンター PLANT", _BOTH, "P2", "https://www.plant-co.jp/", CM_UNAVAILABLE,
         note="取得しない（2026-11-26）。「サイトのご利用について」（https://www.plant-co.jp/terms/web.html）が、私的使用を超えて他のウェブサイト・"
              "SNS で公開・使用することを認めず、リンクはトップページの URL に限り、サイトを使った営利目的の行為を禁じている。公開の LP への掲載と衝突しうるので、"
              "先方の許可を確認するまで取得器（src/collectors/tcg/lottery/plant.py。締切だけの抽選の補助関数はトレカプラザ55 が使う）を登録しない"),
    _src("TORECAPLAZA55", "トレカプラザ55", _BOTH, "P2", "https://torecaplaza55.com/", CM_HTML,
         news_url="https://torecaplaza55.com/", channel="ONLINE", adapter="torecaplaza55_lottery", verified=True,
         note="トップ（EUC-JP）の「抽選販売一覧」に、締切（MM.DD 終日締切）・ゲーム名・題名が静的 HTML で載る。詳細ページは無く、応募先は"
              "Google フォーム（取得しない。entry_url は空）。開始日は無い（締切だけの抽選）。締切の年は取得日から補い、各項目の公開の時刻（data-ts）と"
              "矛盾すれば日程にしない。ポケカ・ONE PIECE 以外は除外。1回の実行でトップ1ページだけ。"
              "robots.txt は User-agent: * に /cart/ だけを禁止で、トップは禁止していない（確認日 2026-11-26）。"
              "利用規約のページは見つからず、許可も禁止も未確認（見つけたら、この記述と取得可否を見直す）"),
    _src("PREMIUM_BANDAI", "プレミアムバンダイ", (ONE_PIECE,), "P0",
         "https://p-bandai.jp/", CM_HTML,
         news_url="https://p-bandai.jp/chara/onepiece/", adapter="premium_bandai_lottery",
         verified=True),
]
SOURCE_BY_ID: dict[str, dict] = {s["source_id"]: s for s in LOTTERY_SOURCES}


# ── 公式ソースのレジストリ（区分・公式ドメイン・お知らせ一覧・抽選ページの URL の形・robots.txt の確認日） ──
# 区分は「誰の公式の告知か」を表す（信頼の段階ではない。どの区分も、その運営者自身の公式ページだけを根拠にする）。
TIER_MAKER_OFFICIAL = "MAKER_OFFICIAL"     # メーカー・メーカー直営の公式ストア
TIER_MAJOR_RETAILER = "MAJOR_RETAILER"     # 全国・地域チェーン（量販店・大手カードショップチェーン）
TIER_CARD_SHOP = "CARD_SHOP"               # カードショップ・加盟店・個店（店舗自身の公式告知）
TIERS = (TIER_MAKER_OFFICIAL, TIER_MAJOR_RETAILER, TIER_CARD_SHOP)
TIER_LABELS = {TIER_MAKER_OFFICIAL: "メーカー公式", TIER_MAJOR_RETAILER: "大手チェーン", TIER_CARD_SHOP: "カードショップ"}

# robots_checked_on: robots.txt を取得して、一覧のパスが禁止されていないことを確かめた日（空なら変更検知で読まない）。
# robots_note: そのときの結果。list_urls: 変更検知で読むお知らせ一覧（取得器の一覧と同じページ。新しいページを増やさない）。
# lottery_url_patterns: 抽選・予約の記事の URL の形（パス＋クエリに対する正規表現。取得器の解析器と同じ形）。
SOURCE_PROFILE: dict[str, dict] = {
    "POKEMON_CENTER_ONLINE": {"tier": TIER_MAKER_OFFICIAL, "list_urls": [],
                              "robots_note": "告知はポケモンカード公式ニュースから発見する（POKEMON_CARD_OFFICIAL と同じ一覧。二重に読まない）"},
    "POKEMON_CARD_OFFICIAL": {"tier": TIER_MAKER_OFFICIAL, "list_urls": ["https://www.pokemon-card.com/info/"],
                              "lottery_url_patterns": [r"^/info/\d{6}\.html$"],   # 記事は 6 桁（/info/2025.html のような年の一覧を除く）
                              "robots_checked_on": "2026-11-26", "robots_note": "robots.txt が無い（HTML を返す）。禁止の記載なし"},
    "GEO": {"tier": TIER_MAJOR_RETAILER, "list_urls": [],
            "robots_note": "2026-11-26 に robots.txt が HTTP 403（Akamai）。変更検知の対象にしない（回避しない）"},
    "CARD_LABO": {"tier": TIER_MAJOR_RETAILER, "list_urls": ["https://www.c-labo.jp/blog/filter/tcg:25/"],
                  "lottery_url_patterns": [r"^/shop/[^/]+/blog/\d+/$"],
                  "robots_checked_on": "2026-10-24", "robots_note": "/wordpress/wp-admin/ だけを禁止"},
    "HOBBY_STATION": {"tier": TIER_MAJOR_RETAILER, "list_urls": ["https://www.hbst.net/result/?category=news"],
                      "lottery_url_patterns": [r"^/\?p=\d+$"],
                      "robots_checked_on": "2026-10-28", "robots_note": "/wordpress/wp-admin/ だけを禁止"},
    "KIDS_REPUBLIC": {"tier": TIER_MAJOR_RETAILER, "list_urls": ["https://www.kidsrepublic.jp/campaign"],
                      "lottery_url_patterns": [r"^/campaign/campaign_detail/[A-Za-z0-9_\-]+$"],
                      "robots_checked_on": "2026-10-29", "robots_note": "robots.txt が 404。禁止の記載なし"},
    "FUKUFUKU_TOREKA": {"tier": TIER_CARD_SHOP, "list_urls": ["https://pokemon.fukufukutoreka.com/lottery"],
                        "lottery_url_patterns": [r"^/lottery/\d+$"],
                        "robots_checked_on": "2026-10-29", "robots_note": "/*.csv$・/cart・/shopping・/mypage だけを禁止"},
    # 区分は運営者の証拠（会社概要・特定商取引法の表記）を確かめてから付ける。2026-11-26 の調査で証拠が見つからなかったので空（表示しない）
    "MUGIWARA_STORE": {"tier": "", "list_urls": ["https://www.mugiwara-store.com/news/"],
                       "lottery_url_patterns": [r"^/news/\d+/$"],
                       "robots_checked_on": "2026-10-29", "robots_note": "/wp-admin/ だけを禁止"},
    "TOYSRUS": {"tier": TIER_MAJOR_RETAILER}, "JOSHIN": {"tier": TIER_MAJOR_RETAILER},
    "EDION": {"tier": TIER_MAJOR_RETAILER}, "YAMADA": {"tier": TIER_MAJOR_RETAILER},
    "TSUTAYA": {"tier": TIER_MAJOR_RETAILER}, "BICCAMERA": {"tier": TIER_MAJOR_RETAILER},
    "YODOBASHI": {"tier": TIER_MAJOR_RETAILER}, "AMAZON": {"tier": TIER_MAJOR_RETAILER},
    "RAKUTEN_BOOKS": {"tier": TIER_MAJOR_RETAILER}, "SEVEN_NET": {"tier": TIER_MAJOR_RETAILER},
    "LAWSON": {"tier": TIER_MAJOR_RETAILER, "list_urls": ["https://www.lawson.co.jp/campaign/"],
               "robots_checked_on": "2026-11-26", "include": "TCG",
               "robots_note": "/service/collaboration/ubereats/pharmaceuticals/ と /lab/challengers/ だけを禁止"},
    "ONEPIECE_CARD_OFFICIAL": {"tier": TIER_MAKER_OFFICIAL, "list_urls": ["https://www.onepiece-cardgame.com/news/"],
                               "lottery_url_patterns": [r"^/news/.+"],
                               "robots_checked_on": "2026-11-26", "robots_note": "robots.txt が 404。禁止の記載なし"},
    "ONEPIECE_CARD_OFFICIAL_SHOP": {"tier": "",
                                    "list_urls": ["https://bandainamco-am.co.jp/official_shop/onepiece-cardgame/"],
                                    "robots_checked_on": "2026-11-26", "robots_note": "User-agent: * と Sitemap だけで禁止の行が無い"},
    "CARDBOX": {"tier": TIER_CARD_SHOP, "list_urls": ["https://cardbox.online/news/shop_list/"],
                "lottery_url_patterns": [r"^/news/detail/\?id=\d+"],
                "robots_checked_on": "2026-11-26", "robots_note": "User-agent: * / Allow:/ で全体を許可"},
    "PLANT": {"tier": TIER_MAJOR_RETAILER},
    "TORECAPLAZA55": {"tier": TIER_CARD_SHOP, "list_urls": [],
                      "robots_note": "詳細ページが無く、一覧（トップ）に抽選が直接並ぶので URL の差分では検知できない（取得器が毎回読む）"},
    "PREMIUM_BANDAI": {"tier": TIER_MAKER_OFFICIAL, "list_urls": ["https://p-bandai.jp/chara/onepiece/"],
                       "robots_checked_on": "2026-11-26", "include": "TCG", "robots_note": "/mypage/・/search/ 等だけを禁止。/chara/ は禁止していない"},
}
# 一般的すぎる語（販売・受付）は入れない（キャンペーン・サービスの案内まで拾う）。URL の形が無い一覧は include で TCG の語に絞る
LOTTERY_KEYWORDS = ("抽選", "予約", "再販", "応募", "入荷", "当選", "購入権", "BOX販売")
TCG_KEYWORDS = ("ポケモンカード", "ポケカ", "ONE PIECEカード", "ワンピースカード", "カードゲーム")


def _domain_of(url: str) -> str:
    from urllib.parse import urlsplit
    h = (urlsplit(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def source_profile(source_id: str) -> dict:
    """取得元の公式ソースの情報（区分・公式ドメイン・一覧・URL の形・robots.txt の確認）。登録に無ければ空。"""
    s = SOURCE_BY_ID.get(source_id)
    if not s:
        return {}
    p = SOURCE_PROFILE.get(source_id) or {}
    domains = sorted({d for d in (_domain_of(s.get("official_url")), _domain_of(s.get("news_url")),
                                  _domain_of(s.get("lottery_url"))) if d})
    return {"source_id": source_id, "chain": s["retailer"], "tier": p.get("tier") or "",
            "tier_label": TIER_LABELS.get(p.get("tier") or "", ""), "official_domains": domains,
            "list_urls": list(p.get("list_urls") or []), "lottery_url_patterns": list(p.get("lottery_url_patterns") or []),
            "robots_checked_on": p.get("robots_checked_on") or "", "robots_note": p.get("robots_note") or ""}


# 応募条件の根拠の行（原文）を公開の出力に出してよい取得元（利用規約で転載が認められていることを人が確認したものだけ）。
# 空のあいだは、どの取得元も構造化した値だけを出す（ポケカ公式・ONE PIECE 公式ショップ・キッズリパブリックは規約が転載・複製を断っている。
# ほかは規約が未読・未確認）。
QUOTE_ALLOWED: frozenset = frozenset()


# 利用規約・サイトポリシーが転載・複製を断っている取得元（応募条件の原文 eligibility_text も出さない。構造化した値だけ）
NO_REPRINT: frozenset = frozenset({"POKEMON_CENTER_ONLINE", "POKEMON_CARD_OFFICIAL", "ONEPIECE_CARD_OFFICIAL_SHOP", "KIDS_REPUBLIC"})


def quote_allowed(source_id) -> bool:
    return str(source_id or "") in QUOTE_ALLOWED


def _drop_tracking(url: str) -> str:
    """計測用のパラメータ（utm_*・fbclid・gclid）だけを外す（?p= ・?id= のように記事を区別するクエリは残す）。"""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    sp = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(sp.query, keep_blank_values=True)
         if not (k.lower().startswith("utm_") or k.lower() in ("fbclid", "gclid"))]
    return urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(q), ""))


def store_master(history_items=None) -> list[dict]:
    """店舗の台帳（登録済みの取得元）: 法人・チェーン・区分・公式ドメイン・告知の一覧・取得条件・robots の確認日・運営者の証拠・
    発見した抽選の件数（履歴の source_url ごとに 1 件。支店はチェーンの中の store_name の数）。公式 SNS は人が確かめるまで空。"""
    from src.tcg.lottery.manual import STORE_PRIMARY_DOMAINS, is_official_url, is_store_primary_url
    from src.tcg.lottery.pipeline import normalize_url
    found: dict = {}
    branches: dict = {}
    for h in history_items or []:
        if isinstance(h, dict) and h.get("retailer"):
            found.setdefault(h["retailer"], set()).add(_drop_tracking(normalize_url(str(h.get("source_url") or h.get("lottery_id") or ""))))
            if h.get("store_specific") and h.get("store_name"):
                branches.setdefault(h["retailer"], set()).add(h["store_name"])
    rows = []
    for s in LOTTERY_SOURCES:
        p = source_profile(s["source_id"])
        url = s.get("news_url") or s["official_url"]
        ev = next((dict(v, domain=d) for d, v in STORE_PRIMARY_DOMAINS.items()
                   if any(x == d or x.endswith("." + d) for x in p["official_domains"])), None)
        rows.append({"source_id": s["source_id"], "chain": s["retailer"], "tier": p["tier"], "tier_label": p["tier_label"],
                     "official_domains": p["official_domains"], "notice_list_urls": p["list_urls"],
                     "collection": ("停止（方針）" if s.get("policy_excluded") or s.get("collection_method") == CM_UNAVAILABLE
                                    else "取得器あり" if s.get("adapter") else "未実装"),
                     "robots_checked_on": p["robots_checked_on"],
                     "primary_evidence": ("maker_or_chain_official" if is_official_url(url) else
                                          (ev or {}).get("strength") if is_store_primary_url(url) else None),
                     "official_sns": [], "branches": len(branches.get(s["source_id"], ())),
                     "lotteries_found": len(found.get(s["source_id"], ()))})
    return rows


def frontier_sources() -> list[dict]:
    """変更検知（src/discovery/engine/frontier）で読む、登録済みの取得元のお知らせ一覧。

    読むのは: 取得器があり（adapter）・内容を確認済み（verified）・取得しない方針でない・robots.txt の確認日があるものだけ。
    一覧のページは取得器が読むものと同じ（新しいページへのアクセスを増やさない）。同じ URL は1回だけ。
    """
    out, seen = [], set()
    for s in LOTTERY_SOURCES:
        p = source_profile(s["source_id"])
        if not (s.get("adapter") and s.get("verified") and not s.get("policy_excluded")
                and s.get("collection_method") != CM_UNAVAILABLE and p.get("robots_checked_on")):
            continue
        for u in p["list_urls"]:
            if u in seen:
                continue
            seen.add(u)
            idx = p["list_urls"].index(u) + 1                  # 取得元の中の順番（全体の通し番号にしない。並び替えで状態が切れない）
            out.append({"id": f"registry:{s['source_id']}" + ("" if len(p["list_urls"]) == 1 else f":{idx}"),
                        "kind": "list", "url": u, "enabled": True, "checked_on": p["robots_checked_on"],
                        # checked_on は robots.txt の確認日（利用規約の確認ではない。規約の確認は note を見る）
                        "evidence": f"registry:{s['source_id']}（robots.txt のみ確認: {p['robots_note']}）",
                        "terms_checked": False,
                        "include": list(TCG_KEYWORDS if (SOURCE_PROFILE.get(s["source_id"]) or {}).get("include") == "TCG"
                                        else LOTTERY_KEYWORDS),
                        "url_patterns": p["lottery_url_patterns"],
                        "source_id": s["source_id"], "tier": p["tier"]})
    return out


def source_state(source: dict, health: Optional[dict], active_lotteries: int) -> str:
    """source の監視状態を決める（Task34）。"""
    if not source.get("adapter"):
        if health and health.get("blocked"):
            return ST_SOURCE_BLOCKED
        if health and health.get("unreachable"):
            return ST_SOURCE_UNREACHABLE
        return ST_SOURCE_NOT_MONITORED
    if not health:
        return ST_SOURCE_FAILED
    if health.get("blocked"):
        return ST_SOURCE_BLOCKED
    if health.get("unreachable"):
        return ST_SOURCE_UNREACHABLE
    status = health.get("status")
    if status == "FAILED":
        return ST_SOURCE_FAILED
    if status == "DEGRADED":
        return ST_SOURCE_DEGRADED
    return ST_ACTIVE_LOTTERY if active_lotteries > 0 else ST_NO_ACTIVE_LOTTERY


# Market Research Foundation H2: 取得元の分類（何を優先して実装・確認するかの判断に使う）
SC_WORKING = "WORKING"                                  # 取得器があり、取得できている
SC_IMPLEMENTED_BUT_BLOCKED = "IMPLEMENTED_BUT_BLOCKED"  # 取得器はあるが、遮断（403・429・robots の禁止）されている
SC_ACCESSIBLE_UNIMPLEMENTED = "ACCESSIBLE_UNIMPLEMENTED"  # 到達できるが、取得器が無い（実装の候補。robots・規約を確認してから）
SC_UNREACHABLE = "UNREACHABLE"                          # 到達できない（接続失敗・robots に届かない・遮断で取得器も無い）
SC_UNSUPPORTED = "UNSUPPORTED"                          # 公式の URL が無い等で、取得の対象にできない
SOURCE_CLASSES = (SC_WORKING, SC_IMPLEMENTED_BUT_BLOCKED, SC_ACCESSIBLE_UNIMPLEMENTED, SC_UNREACHABLE, SC_UNSUPPORTED)
SOURCE_CLASS_LABELS = {SC_WORKING: "取得できている", SC_IMPLEMENTED_BUT_BLOCKED: "実装済みだが遮断",
                       SC_ACCESSIBLE_UNIMPLEMENTED: "到達できるが未実装", SC_UNREACHABLE: "到達できない",
                       SC_UNSUPPORTED: "対象にできない"}


def source_class(row: dict) -> str:
    """取得元の分類（行は pipeline の rows。state・adapter・reachable・collection_method を使う）。

    遮断された取得元は回避しない。分類は優先順位の判断のためで、遮断を避ける手段の提案ではない。
    """
    if row.get("policy_excluded") or row.get("collection_method") == CM_UNAVAILABLE or not (row.get("official_url") or ""):
        return SC_UNSUPPORTED
    state = row.get("state")
    if row.get("adapter"):
        if state == ST_SOURCE_BLOCKED:
            return SC_IMPLEMENTED_BUT_BLOCKED
        if state in (ST_SOURCE_UNREACHABLE, ST_SOURCE_FAILED):
            return SC_UNREACHABLE
        return SC_WORKING
    if state in (ST_SOURCE_BLOCKED, ST_SOURCE_UNREACHABLE) or row.get("blocked") or row.get("unreachable"):
        return SC_UNREACHABLE
    return SC_ACCESSIBLE_UNIMPLEMENTED if row.get("reachable") is True else SC_UNREACHABLE


def load_source_candidates(path=None) -> dict:
    """監視していない取得元の候補（config/tcg_source_candidates.yaml。H5）。fetch はしない・実装の約束でもない。

    戻り: {"status", "basis", "candidates": [{id, name, channel, url, verified, note}], "count"}。読めなければ空。
    登録簿（LOTTERY_SOURCES）と同じ id・名前のものは候補から外す（二重に数えない）。
    """
    from pathlib import Path

    import yaml
    p = Path(path) if path else Path(__file__).resolve().parent.parent.parent.parent / "config" / "tcg_source_candidates.yaml"
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {"status": "UNAVAILABLE", "basis": "", "candidates": [], "count": 0}
    known = {s["source_id"] for s in LOTTERY_SOURCES} | {s["retailer"] for s in LOTTERY_SOURCES}
    allc = [c for c in d.get("candidates") or [] if isinstance(c, dict) and c.get("id")
            and str(c.get("id")) not in known and str(c.get("name")) not in known]
    # 取得しない方針（policy_excluded）の売り場は、実装の候補ではなく除外として別に持つ
    rows = [{"id": str(c.get("id") or ""), "name": str(c.get("name") or ""), "channel": str(c.get("channel") or ""),
             "url": str(c.get("url") or ""), "verified": bool(c.get("verified")), "note": str(c.get("note") or "")}
            for c in allc if not c.get("policy_excluded")]
    excluded = [{"id": str(c["id"]), "name": str(c.get("name") or ""), "reason": str(c.get("policy_excluded"))}
                for c in allc if c.get("policy_excluded")]
    return {"status": str(d.get("status") or ""), "basis": str(d.get("basis") or ""), "candidates": rows, "count": len(rows),
            "policy_excluded": excluded}


LIST_OK, DETAIL_OK, BLOCKED_FLAG, PARSER_DEGRADED, TRUNCATED_FLAG = "LIST_OK", "DETAIL_OK", "BLOCKED", "PARSER_DEGRADED", "TRUNCATED"
HEALTH_FLAGS = (LIST_OK, DETAIL_OK, BLOCKED_FLAG, PARSER_DEGRADED, TRUNCATED_FLAG)


def source_health_flags(row: dict) -> list[str]:
    """取得元の状態を、1つの状態に潰さず分ける: 一覧を読めた / 詳細を読めた / 遮断された / 一覧・詳細の構造が読めない / 取りこぼしがある。

    手元では取得できて CI では遮断される取得元は BLOCKED（WORKING とは数えない）。pages は取得の記録（page_type・http_status）。
    """
    pages = [p for p in (row.get("pages") or []) if isinstance(p, dict)]
    flags = []
    if any(p.get("page_type") in ("listing", "list") and p.get("http_status") == 200 for p in pages):
        flags.append(LIST_OK)
    if any(p.get("page_type") in ("news", "product", "detail") and p.get("http_status") == 200 for p in pages):
        flags.append(DETAIL_OK)
    if row.get("blocked"):
        flags.append(BLOCKED_FLAG)
    if int(row.get("structure_changed_pages") or 0) > 0:
        flags.append(PARSER_DEGRADED)
    if row.get("truncated") is True:
        flags.append(TRUNCATED_FLAG)
    return flags


ZERO_ACTIVE_NOT_PROVEN = "NOT_PROVEN_MARKET_EMPTY"   # 受付中が 0 件でも、市場に無いとは言えない（取得元の不足・遮断・到達不能がある）
ZERO_ACTIVE_NO_GAP = "NO_KNOWN_COLLECTOR_GAP"          # 取得元の未実装・遮断・到達不能が無いのに 0 件（それでも、登録外の売り場は見ていない）


def announcement_funnel(rows: list[dict]) -> dict:
    """取得の流れ: 告知（候補の記事）→ 解析できたイベント → 日程が読めず要確認 → 棄却 → 受付中。

    「受付中 0 件」が、本当に市場に無いのか、取得器が足りないのかを区別する材料。0 件でも「市場に無い」と断定しない:
    取得元の未実装・遮断・到達不能が1つでもあれば NOT_PROVEN_MARKET_EMPTY（収集の不足の可能性）。
    """
    def _sum(key):
        return sum(int(r.get(key) or 0) for r in rows if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool))
    active = _sum("active_lotteries")
    truncated = sum(1 for r in rows if r.get("truncated") is True)           # 詳細の取得に上限があり、取りこぼした取得元
    gap = sum(1 for r in rows if source_class(r) in (SC_IMPLEMENTED_BUT_BLOCKED, SC_ACCESSIBLE_UNIMPLEMENTED, SC_UNREACHABLE)
              or r.get("truncated") is True)
    # 数え方は取得元ごとに近似（候補の記事の定義・棄却の数え方は取得器ごとに違う）。合計は目安で、保存則を満たさない
    out = {"raw_announcements": _sum("candidate_articles"), "parsed_events": _sum("accepted_lotteries"),
           "review_required": _sum("announcements"), "rejected": _sum("rejected"), "active_lotteries": active,
           "sources_with_gap": gap, "sources_truncated": truncated,
           # 詳細の取得の内訳（取得上限があるときの取りこぼしを数える。None でなく 0 を出す）
           "detail_candidates": _sum("detail_candidates"), "detail_fetched": _sum("detail_fetched"),
           "skipped_due_to_limit": _sum("skipped_due_to_limit"), "skipped_ended": _sum("skipped_ended"),
           # 取得元の状態を分けた件数（LIST_OK / DETAIL_OK / BLOCKED / PARSER_DEGRADED / TRUNCATED。1つの取得元が複数に数えられる）
           "sources_list_ok": sum(1 for r in rows if LIST_OK in (r.get("health_flags") or [])),
           "sources_detail_ok": sum(1 for r in rows if DETAIL_OK in (r.get("health_flags") or [])),
           "sources_blocked": sum(1 for r in rows if BLOCKED_FLAG in (r.get("health_flags") or [])),
           "sources_parser_degraded": sum(1 for r in rows if PARSER_DEGRADED in (r.get("health_flags") or []))}
    if active == 0:
        out["zero_active_interpretation"] = ZERO_ACTIVE_NOT_PROVEN if gap else ZERO_ACTIVE_NO_GAP
    return out


def coverage_summary(rows: list[dict]) -> dict:
    """Task33: Lottery Source Coverage。"""
    def _n(cond):
        return sum(1 for r in rows if cond(r))
    return {
        "configured_sources": len(rows),
        "implemented_collectors": _n(lambda r: bool(r.get("adapter"))),
        "reachable_sources": _n(lambda r: r.get("reachable") is True),
        "healthy_sources": _n(lambda r: r.get("state") in (ST_ACTIVE_LOTTERY,
                                                           ST_NO_ACTIVE_LOTTERY)),
        "blocked_sources": _n(lambda r: r.get("state") == ST_SOURCE_BLOCKED),
        "unreachable_sources": _n(lambda r: r.get("state") == ST_SOURCE_UNREACHABLE),
        "not_implemented_sources": _n(lambda r: not r.get("adapter")),
        "sources_with_active_lottery": _n(lambda r: r.get("state") == ST_ACTIVE_LOTTERY),
        "lottery_events_found": sum(int(r.get("active_lotteries") or 0) for r in rows),
        # H2: 分類ごとの件数（キーは SOURCE_CLASSES。0 件も出す）
        "source_classes": {c: _n(lambda r, c=c: source_class(r) == c) for c in SOURCE_CLASSES},
        # Wave 1 Stage G: 取得の流れ（告知 → イベント → 要確認 → 受付中）と、受付中が 0 件のときの解釈
        "funnel": announcement_funnel(rows),
    }
