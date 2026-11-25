# -*- coding: utf-8 -*-
"""TCG Lottery Hub（docs/tcg.html）の描画。入力は src.tcg.hub.product_view.build_hub の結果。

- 抽選は全件を 1 つの表（状態・店舗・商品・締切・応募方法・地域・当選日・購入期間・確認）に出す。同じ抽選を複数の場所に重ねて出さない。
- 商品カードは商品 ID まで一致（exact）して束ねた商品だけ。束ねられない抽選は表の商品列に「未紐付け」と出す（推測で結ばない）。
- 状態は生成時刻から導出し直したもの。確認日は元データの値をそのまま出す（表示は短くしても原値を title に残す）。
- 利益は定価（検証済み）だけ。純利益は根拠が無いので「算出前」と書く。利益の並び替えは出さない。
- すべての文字は HTML エスケープ。リンクは https の公式ドメインだけ（応募の URL は検証を通ったものだけ・無ければリンクを作らない）。
- 画像はポケモンカードの公式一覧にある URL のうち pokemon-card.com 配下の https だけ。それ以外はプレースホルダ（偽の画像を作らない）。
- 色: 受付中・近日開始=青、締切間近=赤、様子見・結果待ち=橙、終了=灰。緑は購入候補・利益（根拠あり）のためだけに空けてある。
  TCG のカテゴリ色（--tcg-*）は商品の画像の面と頭文字だけに使い、状態のバッジには使わない。
- JS は絞り込みだけ（data 属性の表示切り替えと件数表示。外部の値は埋め込まない）。JS が無くても全件が見える。
"""
from __future__ import annotations

import calendar as _cal
import html as _html
import re
from datetime import datetime, timedelta
from typing import Optional

from src.tcg import action_url as au
from src.tcg.hub import product_view as pv
from src.tcg.hub import status as st
from src.tcg.hub.product_view import build_hub
from src.tcg.lottery import schema as ls
from src.tcg.models import JST, now_jst

from src.content.ui import shared_css as _shared    # 共通 CSS（legacy_css）と共通ナビ（site_nav）

TCG_LABEL = {"POKEMON": "ポケモンカード", "ONE_PIECE": "ONE PIECE カード"}
TCG_INITIAL = {"POKEMON": ("ポ", "pokemon"), "ONE_PIECE": ("OP", "onepiece")}
CANON_LABEL = {pv.C_MASTER: "商品マスタと一致", pv.C_DISCOVERED: "イベントから発見（商品マスタ外）",
               pv.C_AMBIGUOUS: "商品が複数に当てはまる", pv.C_UNMATCHED: "商品に紐付けできていない"}
PRIO_LABEL = {st.P_S: "S 今すぐ", st.P_A: "A 応募したい", st.P_B: "B 余裕あり", st.P_WATCH: "WATCH 要確認"}
CHANNEL_LABEL = {au.CH_WEB_OFFICIAL: "公式の応募ページ", au.CH_EXTERNAL_FORM: "外部の応募フォーム", au.CH_APP: "アプリ",
                 au.CH_SNS: "SNS（フォロー＆リポスト）", au.CH_MEMBER_LOGIN: "会員ログイン", au.CH_STORE_COUNTER: "店頭",
                 au.CH_UNKNOWN: "応募経路は未確認"}
CHANNEL_SHORT = {au.CH_WEB_OFFICIAL: "公式WEB", au.CH_EXTERNAL_FORM: "外部フォーム", au.CH_APP: "アプリ", au.CH_SNS: "SNS",
                 au.CH_MEMBER_LOGIN: "会員ログイン", au.CH_STORE_COUNTER: "店頭", au.CH_UNKNOWN: "未確認"}
REQ_LABEL = {au.R_MEMBERSHIP: "会員登録", au.R_APP: "アプリ", au.R_PURCHASE_HISTORY: "購入履歴", au.R_IDENTITY: "本人確認",
             au.R_STORE_PICKUP: "店頭受取", au.R_SNS: "SNS フォロー＆リポスト"}
KIND_LABEL = {"PREORDER": "予約", "STORE_LOTTERY": "店舗の抽選", "APP_LOTTERY": "アプリ抽選", "WEB_LOTTERY": "WEB 抽選", "LOTTERY": "抽選"}
PTYPE_LABEL = {"BOOSTER_BOX": "拡張パック（BOX）", "STARTER_DECK": "スターター", "CONSTRUCTED_DECK": "構築済みデッキ",
               "SPECIAL_SET": "スペシャルセット", "PREMIUM_COLLECTION": "プレミアムコレクション", "OTHER": "その他"}
CAL_SHORT = {pv.K_START: "開始", pv.K_END: "締切", pv.K_RESULT: "当選", pv.K_PURCHASE_START: "購入開始",
             pv.K_PURCHASE_END: "購入終了", pv.K_RELEASE: "発売"}
WEEKDAY = "月火水木金土日"
PRODUCT_HOSTS = ("pokemon-card.com",)          # 商品の公式ページ・画像として許可するドメイン（サブドメイン可）
IMG_W, IMG_H = 320, 240
_ST_ORDER = {s: i for i, s in enumerate(st._AGG_ORDER)}

# 状態の色（受付中・近日開始=青 / 締切間近=赤 / 様子見・結果待ち=橙 / 終了=灰）。緑は購入候補・利益のためだけに使う。
_TONE = {ls.L_OPEN: "info", ls.L_UPCOMING: "info", ls.L_ENDING_SOON: "danger", ls.L_ENDED: "gray"}

CSS = """
:root{--bg:#f6f7f9;--fg:#1c2330;--mut:#566072;--card:#fff;--line:#d9dee6;--acc:#1f5fbf;--warn:#a45a00;
--t-info-fg:#1d4ed8;--t-info-bg:#eff6ff;--t-info-bd:#bfdbfe;--t-danger-fg:#b91c1c;--t-danger-bg:#fef2f2;--t-danger-bd:#fecaca;
--t-warn-fg:#b45309;--t-warn-bg:#fffbeb;--t-warn-bd:#fde68a;--t-gray-fg:#475569;--t-gray-bg:#f1f5f9;--t-gray-bd:#e2e8f0;
--t-ok-fg:#166534;--t-ok-bg:#f0fdf4;--t-ok-bd:#bbf7d0;--tcg-pokemon:#6d28d9;--tcg-onepiece:#155e75;--k-result:#a21caf}
@media(prefers-color-scheme:dark){:root{--bg:#10141b;--fg:#e6e9ef;--mut:#a3adbb;--card:#181e28;--line:#2b3442;--acc:#7fb0ff;--warn:#e0a24a;
--t-info-fg:#93c5fd;--t-info-bg:#10223f;--t-info-bd:#1e3a8a;--t-danger-fg:#fca5a5;--t-danger-bg:#3b1212;--t-danger-bd:#7f1d1d;
--t-warn-fg:#fcd34d;--t-warn-bg:#3a2a08;--t-warn-bd:#78350f;--t-gray-fg:#cbd5e1;--t-gray-bg:#1e293b;--t-gray-bd:#334155;--t-ok-fg:#86efac;--t-ok-bg:#0f2a1a;--t-ok-bd:#166534;--k-result:#e879f9}}
*{box-sizing:border-box}body{overflow-wrap:anywhere;margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Hiragino Sans",sans-serif}
main{max-width:1240px;margin:0 auto;padding:16px}h1{font-size:24px;margin:.2em 0}
h2{font-size:18px;margin:1.6em 0 .5em;padding:0 0 .2em .6em;border-left:4px solid var(--acc);scroll-margin-top:var(--jump-offset)}
h3{font-size:15px;margin:.2em 0}a{color:var(--acc)}.mut{color:var(--mut);font-size:13px}
.head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}.snap{margin:.2em 0;color:var(--mut)}
details.note{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 12px;margin:8px 0}
details summary{cursor:pointer;color:var(--mut);min-height:44px;min-width:44px}details.note>*:not(summary){margin:.5em 0}
nav.jump{position:sticky;top:0;z-index:5;display:flex;gap:6px;overflow-x:auto;padding:6px 0;margin:.6em 0;background:var(--bg)}
/* アンカーのジャンプ先が固定ナビの下に隠れない余白: 768px 以上は nav.jump（約 56px）+ 余白、767px 以下は共通ナビ（53px）+ nav.jump（約 56px）+ 余白 */
:root{--jump-offset:64px}
@media(max-width:767px){nav.jump{top:53px}:root{--jump-offset:125px}}/* 共通ナビ（site-nav）が 767px 以下で上部に固定される高さ（min-height 53px）ぶん下げる */
nav.jump a{flex:none;display:inline-flex;align-items:center;border:1px solid var(--line);background:var(--card);border-radius:999px;padding:0 14px;text-decoration:none;font-size:14px;min-height:44px}
.sum{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.sum .c{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;padding:8px 12px;color:var(--mut);font-size:13px}
.sum .c b{display:block;font-size:30px;line-height:1.2;color:var(--fg)}
.sum .c.info{border-left-color:var(--t-info-fg)}.sum .c.danger{border-left-color:var(--t-danger-fg)}.sum .c.danger b{color:var(--t-danger-fg)}
.sub{display:flex;flex-wrap:wrap;gap:4px 16px;margin:8px 0;color:var(--mut);font-size:13px}.sub b{color:var(--fg)}
.box{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:8px 0}.box.warn{border-color:var(--warn)}
.box details{margin-top:4px}
.sb{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:0 8px;font-size:12px;line-height:1.7;white-space:nowrap;margin:0 4px 2px 0}
.sb.info{color:var(--t-info-fg);background:var(--t-info-bg);border-color:var(--t-info-bd)}
.sb.danger{color:var(--t-danger-fg);background:var(--t-danger-bg);border-color:var(--t-danger-bd)}
.sb.ok{color:var(--t-ok-fg);background:var(--t-ok-bg);border-color:var(--t-ok-bd)}
.sb.warn{color:var(--t-warn-fg);background:var(--t-warn-bg);border-color:var(--t-warn-bd)}
.sb.gray{color:var(--t-gray-fg);background:var(--t-gray-bg);border-color:var(--t-gray-bd)}
.sb.out{color:var(--mut);background:transparent}
.tcgtag{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:20px;padding:0 4px;border-radius:4px;color:#fff;font-size:12px;font-weight:700;margin-right:4px;vertical-align:middle}
.tcgtag.pokemon,.pimg.ph.pokemon{background:var(--tcg-pokemon)}.tcgtag.onepiece,.pimg.ph.onepiece{background:var(--tcg-onepiece)}
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.pcard{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:grid;grid-template-columns:72px minmax(0,1fr);gap:4px 10px;padding:8px 10px;align-content:start;scroll-margin-top:var(--jump-offset)}
.pimg{grid-row:1;grid-column:1;width:72px;height:72px;display:flex;align-items:center;justify-content:center;background:var(--t-gray-bg);color:#fff;font-size:28px;font-weight:700;border-radius:8px;overflow:hidden}
.pimg img{width:100%;height:100%;object-fit:contain;display:block}.pimg.ph{background-image:none}
.phead{grid-row:1;grid-column:2;min-width:0;display:flex;flex-direction:column;gap:2px}.phead h3{font-size:15px;line-height:1.35;margin:0}
.pcard>.pmeta,.pcard>.chips,.pcard>.pfoot,.pcard>.pnote{grid-column:1/-1}.pnote.nw{white-space:nowrap}
.pmeta{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 12px;margin:0}.pmeta dl{display:contents;margin:0}.pmeta dl>div{min-width:0;display:flex;gap:4px;align-items:baseline}
.pmeta dd small{display:block;font-weight:400;color:var(--mut);font-size:12px}.pmeta dt{color:var(--mut);font-size:12px;line-height:1.4}.pmeta dd{margin:0;font-weight:700;font-size:15px;line-height:1.4;overflow-wrap:anywhere}
[data-fb-live][hidden],[data-fb-stale][hidden]{display:none!important}.rb-expired [data-fb-live],.rb-expired [data-fb-stale],.rb-expired [data-rb-open]{display:none!important}[data-rb-expired][hidden]{display:none!important}.pnote,.pcard>p.pnote{margin:0;color:var(--mut);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:4px}.chip{border:1px solid var(--line);border-radius:8px;padding:0 8px;font-size:12px;line-height:1.6;color:var(--mut)}
.chip b{font-size:14px;color:var(--fg);margin-right:3px}
.chip.info{border-color:var(--t-info-bd);background:var(--t-info-bg)}.chip.danger{border-color:var(--t-danger-bd);background:var(--t-danger-bg)}
.pfoot{display:flex;flex-wrap:wrap;align-items:center;gap:0 12px;font-size:14px}
.pfoot details{flex:1 1 auto}.pfoot details[open]{flex-basis:100%}.pfoot details summary{display:inline-flex;align-items:center;min-height:44px;min-width:44px;font-size:13px}
.pfoot details>div{display:flex;flex-direction:column;gap:2px;padding-bottom:6px}
.chip.warn{border-color:var(--t-warn-bd);background:var(--t-warn-bg)}
b.sb{font-weight:400}
.pimg.ph{flex-direction:column;line-height:1.1}.pimg.ph small{font-size:10px;font-weight:400;opacity:.9}
.tcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px;display:flex;flex-direction:column;gap:6px;min-width:0;align-self:start;scroll-margin-top:var(--jump-offset)}
.tc-top{display:grid;grid-template-columns:72px minmax(0,1fr);gap:10px;align-items:start}
.tc-id{min-width:0}.tc-id h3{font-size:15px;line-height:1.35;margin:2px 0}.tc-tags{display:flex;flex-wrap:wrap;align-items:center;gap:2px}
.tc-meta{margin:0;color:var(--mut);font-size:12px}
.tc-strip{list-style:none;margin:0;padding:0;border:1px solid var(--line);border-radius:8px;overflow:hidden;font-variant-numeric:tabular-nums}
.tc-strip>li{display:grid;grid-template-columns:5.2em minmax(0,1fr);gap:0 8px;align-items:baseline;padding:6px 10px;border-top:1px solid var(--line)}
.tc-strip>li:first-child{border-top:0}.tc-strip em{font-style:normal;color:var(--mut);font-size:12px}
.tc-val{min-width:0;overflow-wrap:anywhere}.tc-val>span{display:block}.tc-val small,.tc-others small{display:block;color:var(--mut);font-size:12px;line-height:1.45}
.tc-strip .amt{font-size:18px;line-height:1.3;font-weight:700}
.tc-strip [data-strip-profit] .amt{font-size:20px}
.tc-others,.tc-lotd{border-top:1px solid var(--line)}
.tc-others summary,.tc-lotd summary{display:flex;align-items:center;min-height:44px;color:var(--mut);font-size:13px}
.tc-others ul,.tc-lotd ul{list-style:none;margin:0;padding:0}
.tc-others li,.tc-lotd li{padding:6px 0;border-top:1px solid var(--line);font-size:13px;min-width:0;overflow-wrap:anywhere}
.tc-others li:first-child,.tc-lotd li:first-child{border-top:0}
.tc-others li>b{display:block}.tc-others .amt{font-size:15px;font-variant-numeric:tabular-nums}.tc-others p.mut{margin:.2em 0}
.tc-lot{display:flex;flex-direction:column;gap:4px}.tc-lot .pnote{margin:0}
.tc-lotd li>b{margin-right:6px}.tc-lotd small{display:block;color:var(--mut);font-size:12px}
.tc-foot{display:flex;flex-wrap:wrap;align-items:center;gap:0 12px;font-size:14px}
.tc-foot a,.tc-others li a,.tc-lotd li a,.tc-lotd>a{display:inline-flex;align-items:center;min-height:44px;margin-right:12px}
.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin:.6em 0}
.filters label{font-size:13px;color:var(--mut);min-width:0}.filters select{display:block;width:100%;max-width:100%;min-height:44px;font-size:15px}
.lt-wrap{overflow-x:auto}table.lt{width:100%;min-width:1000px;border-collapse:collapse;background:var(--card);font-size:13px}
.lt th{text-align:left;color:var(--mut);font-weight:600;padding:6px 8px;border-bottom:2px solid var(--line);white-space:nowrap}
.lt td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
.lt tr.ev td:first-child{border-left:4px solid var(--st,var(--line))}
.lt tr.t-info{--st:var(--t-info-fg)}.lt tr.t-danger{--st:var(--t-danger-fg);background:var(--t-danger-bg)}.lt tr.t-warn{--st:var(--t-warn-fg)}.lt tr.t-gray{--st:var(--t-gray-fg);color:var(--mut)}
.lt td[data-label="締切"],.lt td[data-label="当選日"]{white-space:nowrap}.lt td[data-label="商品"]{min-width:200px}.lt td[data-label="店舗"]{min-width:110px}
.lt a,.pfoot a,.lt summary,.box summary,details.note>summary,.lt td[data-label="商品"] a{display:inline-flex;align-items:center;min-height:44px}
.lt td.how{line-height:1.4}.lt td.how details{display:inline-block}.lt td.how details[open]{display:block}.lt td.how small{display:inline}
.lt .nl-m{display:none}
.lt small{display:block;color:var(--mut);font-size:12px}.lt details summary{font-size:13px}.ev[hidden]{display:none!important}
.empty{background:var(--card);border:1px dashed var(--line);border-radius:8px;padding:12px;color:var(--mut)}.empty[hidden]{display:none}
.cal-month{margin:.8em 0}.cal-month h3{margin:.2em 0}
.cg{position:relative;display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}
.cg>div{background:var(--card);min-height:64px;padding:3px 4px;font-size:12px;min-width:0}.cg .wh{min-height:0;text-align:center;color:var(--mut);background:var(--bg)}
.cg .gap{grid-column:1/-1;min-height:0;text-align:center;color:var(--mut);background:var(--bg);padding:6px}.cg .off{background:var(--bg)}.cg .today{background:var(--t-info-bg);outline:2px solid var(--t-info-fg);outline-offset:-2px}.cg .today .d{color:var(--t-info-fg)}
.cg .d{font-weight:700;margin-right:4px;font-size:13px}
main .cg summary{display:block;list-style:none;cursor:pointer;color:var(--fg);min-height:44px}main .cg summary::before,main .cg details[open]>summary::before{content:none}.cg summary::-webkit-details-marker{display:none}.cg ul{margin:.3em 0;padding:0;list-style:none}.cg li{margin:.2em 0}
.cg details[open]>ul{position:absolute;left:0;right:0;z-index:3;margin:2px 0 0;padding:8px 12px;background:var(--card);border:1px solid var(--line);box-shadow:0 4px 12px rgba(0,0,0,.25);font-size:13px}
.cg li{overflow-wrap:break-word;word-break:normal}
.k{display:inline-block;border-radius:4px;padding:0 4px;font-size:12px;margin:0 2px 2px 0;line-height:1.5;white-space:nowrap}
.k-START{background:var(--t-info-fg);color:var(--bg)}.k-END{background:var(--t-danger-fg);color:var(--bg)}.k-RESULT{background:var(--k-result);color:var(--bg)}
.k-PURCHASE_START,.k-PURCHASE_END{background:var(--t-gray-fg);color:var(--bg)}.k-RELEASE{background:var(--fg);color:var(--bg)}
.dot{display:none;width:8px;height:8px;border-radius:50%;margin:0 2px 2px 0}.dot.k-START{background:var(--t-info-fg)}.dot.k-END{background:var(--t-danger-fg)}
.dot.k-RESULT{background:var(--k-result)}.dot.k-PURCHASE_START,.dot.k-PURCHASE_END{background:var(--t-gray-fg)}.dot.k-RELEASE{background:var(--fg)}
.agenda{display:none}.agenda ul,.callist ul{padding-left:1.1em;margin:.2em 0}
dl.kv{display:grid;grid-template-columns:8em 1fr;gap:2px 8px;margin:.3em 0}dl.kv dt{color:var(--mut)}dl.kv dd{margin:0;overflow-wrap:anywhere}
footer{margin:2em 0 1em;color:var(--mut);font-size:13px}
@media(max-width:900px){
.sum{grid-template-columns:repeat(2,minmax(0,1fr))}.sum .c b{font-size:26px}
table.lt{min-width:0}.lt thead{display:none}.lt,.lt tbody{display:block}.lt-wrap{overflow:visible}
.lt tr.ev{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0 12px;border:1px solid var(--line);border-left:4px solid var(--st,var(--line));border-radius:8px;background:var(--card);margin:8px 0;padding:6px 10px}
.lt tr.t-danger{background:var(--t-danger-bg)}
.lt td{display:block;position:relative;padding:2px 0;border:0;min-width:0;grid-column:span 1}.lt tr.ev td:first-child{border-left:0}.lt td.na{display:none}
.lt td[data-label="店舗"]{order:1}.lt td[data-label="状態"]{order:2;text-align:right}.lt td[data-label="確認"]{order:9;grid-column:1/-1;font-size:12px;color:var(--mut)}
.lt td[data-label="商品"]{order:4;grid-column:1/-1}
.lt td[data-label="締切"]{order:5;grid-column:1/-1}.lt td[data-label="当選日"]{order:6}
.lt td[data-label="購入期間"]{order:7}.lt td[data-label="店舗"] small,.lt td[data-label="商品"] small span{display:none}.lt td[data-label="応募方法"]{order:8;grid-column:1/-1;display:flex;flex-wrap:wrap;align-items:center;gap:0 8px}
.lt td[data-label="地域"]{order:10;grid-column:1/-1;font-size:12px;color:var(--mut)}
.lt td[data-label="締切"]::before,.lt td[data-label="当選日"]::before,.lt td[data-label="購入期間"]::before,.lt td[data-label="地域"]::before{content:attr(data-label) "　";color:var(--mut);font-size:12px}
.lt td[data-label="地域"]::before{content:"地域 "}
.lt td[data-label="締切"],.lt td[data-label="当選日"]{white-space:normal}
.lt td small{display:inline;margin-left:6px}.lt td[data-label="締切"] small{display:inline;margin:0 0 0 10px}
.lt td[data-label="確認"] .sb{margin:0 6px 0 0;line-height:1.5;padding:0 6px}.lt td[data-label="確認"] small{display:inline;margin:0}
.lt td[data-label="商品"] small{margin:0}.lt td[data-label="状態"] .sb{margin:0 4px 0 0}
.lt td.how details[open]{flex-basis:100%}.lt td.how small.nl-d{display:none}.lt td small.nl-m{display:inline}
.cg>div{min-height:48px;padding:2px}.cg .k{display:none}.cg .dot{display:inline-block}
dl.kv{grid-template-columns:6em 1fr}.agenda{display:block}
main{padding:12px}h1{font-size:20px}h2{margin:1.2em 0 .4em}.sum{gap:6px}.sum .c{padding:4px 8px;font-size:12px}.sum .c b{font-size:22px;line-height:1.1}
.pgrid{gap:8px}.tcard{padding:8px}.tc-top{grid-template-columns:56px minmax(0,1fr);gap:8px}.tc-top .pimg{width:56px;height:56px;font-size:20px}.tc-strip>li{padding:4px 8px}.tc-strip .amt{font-size:17px}.pcard{grid-template-columns:48px minmax(0,1fr);padding:6px 8px;gap:2px 8px}.pimg{width:48px;height:48px;font-size:20px}
.pfoot details[open]{flex-basis:100%}.lt tr.ev{margin:6px 0;padding:4px 10px}.box{margin:6px 0}}
@media(min-width:901px){.dot{display:none!important}}
"""

from src.tcg import runtime_freshness as rf               # noqa: E402


def _CFG() -> dict:
    """買取の設定（しきい値は config/tcg_buyback.yaml が唯一の定義。ページの属性に出す値もここから）。"""
    from src.tcg import buyback as _bb
    return _bb.load_config()


JS = """
(function(){try{
var f=document.getElementById('flt');if(!f)return;
var cnt=document.getElementById('cnt'),none=document.getElementById('none');
function run(){var v={},n=0,t=0;['tcg','product','retailer','region','state'].forEach(function(k){v[k]=f.elements[k].value;});
document.querySelectorAll('.ev').forEach(function(e){var d=e.dataset,ok=true;
['tcg','product','retailer','region'].forEach(function(k){if(v[k]&&d[k]!==v[k])ok=false;});
if(v.state&&(' '+d.state+' ').indexOf(' '+v.state+' ')<0)ok=false;e.hidden=!ok;
if(e.closest('#lt-live')){t++;if(ok)n++;}});
if(cnt)cnt.textContent=n+' / '+t+' 件を表示';if(none)none.hidden=n>0||t===0;}
f.addEventListener('change',run);
document.querySelectorAll('a[data-pf]').forEach(function(a){a.addEventListener('click',function(){f.elements.product.value=a.getAttribute('data-pf');run();});});
}catch(e){}})();
"""


def _short(v) -> str:
    """確認日時の表示（元の値の先頭 16 文字 = 分まで。値そのものは変えない）。"""
    t = str(v or "").strip()
    return t[:16].replace("T", " ") if t else "不明"


def _apply_deadline(v) -> str:
    """応募期限の表示。時刻があればその時刻、日付のみなら 23:59（日付の終わり）まで。"""
    t = str(v or "").strip()
    if len(t) > 10 and t[10] in "T ":
        return _short(t)
    return f"{t[:10]} 23:59"


def _e(v) -> str:
    return _html.escape("" if v is None else str(v), quote=True)


def _link(url, label) -> str:
    return f'<a href="{_e(url)}" target="_blank" rel="noopener nofollow">{_e(label)}</a>' if url else ""


def _host_ok(url) -> Optional[str]:
    """https かつ PRODUCT_HOSTS 配下なら正規化した URL。それ以外は None。"""
    r = au.safe_https(url)
    if r and any(r[0] == h or r[0].endswith("." + h) for h in PRODUCT_HOSTS):
        return r[1]
    return None


def _product_link(url) -> str:
    u = _host_ok(url)
    return _link(u, "公式の商品ページ") if u else ""


def _image_src(url) -> Optional[str]:
    return _host_ok(url)


def show_time(time, verified: bool = True) -> Optional[str]:
    """表示してよい時刻。None なら日付のみで出す。
    00:00 ちょうどは「日付だけ公表（時刻は補完された 0 時）」と「公式が 0 時と明示」を区別できないので、確認済みでも日付のみに倒す。
    未確認の行は時刻も未確認なので日付のみ。確認済みの 00:00 以外の時刻は原値のまま出す（原値は title に残す）。"""
    t = str(time or "").strip()
    if not t or t == "00:00" or not verified:
        return None
    return t


def _md(w: dict, yr: str, verified: bool = True) -> str:
    """表示用の日付。時刻あり=`11/20 23:59`、日付のみ=`11/22`（時刻は作らない。00:00 も日付のみ。title に原値と「時刻未公表／未確認」）。
    今年以外は年を付ける（`27/01/05`）。"""
    if not w or not w.get("date"):
        return "未公表"
    y, m, d = str(w["date"]).split("-")
    ds = f"{m}/{d}" if y == yr else f"{y[2:]}/{m}/{d}"
    t = show_time(w.get("time"), verified)
    if t:
        return f'<span title="{_e(w["date"] + " " + t)}">{_e(ds)} {_e(t)}</span>'
    if w.get("time"):                                           # 00:00・未確認: 原値は title にだけ残す
        why = "00:00 は公表の有無を判別できないため日付のみ" if verified else "時刻は未確認のため日付のみ"
        return f'<span title="原値 {_e(w["date"] + " " + w["time"])}（{why}・日付のみ表示）">{_e(ds)}</span>'
    return f'<span title="{_e(w["date"])}（日付のみ・{"時刻未公表" if verified else "時刻未公表／未確認"}）">{_e(ds)}</span>'


def _range(a: dict, b: dict, yr: str, verified: bool = True) -> str:
    if not (a.get("date") or b.get("date")):
        return "未公表"
    return (f'{_md(a, yr, verified)}〜{_md(b, yr, verified)}' if (a.get("date") and b.get("date"))
            else (f'{_md(a, yr, verified)}〜' if a.get("date") else f'〜{_md(b, yr, verified)}'))


def _vshort(v) -> str:
    """確認日の短い表示 `11/20 16:15`（原値は title に残す）。"""
    t = _short(v)
    try:
        return datetime.strptime(t, "%Y-%m-%d %H:%M").strftime("%m/%d %H:%M")
    except ValueError:
        return _e(t)


def _yen(n) -> str:
    return f"¥{int(n):,}"


def _wd(date: str) -> str:
    try:
        return WEEKDAY[datetime.strptime(date, "%Y-%m-%d").weekday()]
    except ValueError:
        return ""


def _badge(text, tone="out") -> str:
    return f'<span class="sb {tone}">{_e(text)}</span>'


LABEL_PURCHASE_ONLY = "購入期間中（当選者のみ・新規応募不可）"
RB_EXPIRED_APPLY = "応募期限を過ぎました。公式ページで再確認してください"
RB_EXPIRED_PURCHASE = "購入期間は終了しました。公式ページで再確認してください"
RB_EXPIRED_SECTION_HEAD = "応募期限を過ぎた行があります。下の行で再確認してください"
RB_EXPIRED_SECTION_BODY = "価格は生成時点のものです。応募期限を過ぎた行は、実行できる価格ではありません。各行の期限と公式ページで再確認してください。"
RB_EXPIRED_GROUP = "期限が過ぎた抽選があります。抽選一覧で再確認してください"
_INTAKE_FOR_RB = (ls.L_OPEN, ls.L_ENDING_SOON, ls.L_UPCOMING)


def _until_iso(d) -> str:
    """{date, time} → JS_RB の data-rb-until（時刻あり: ISO 8601 + JST。日付のみ: その日の終わりまで）。日付が無ければ空（締切の無い行には付けない）。"""
    d = d if isinstance(d, dict) else {}
    date, tm = str(d.get("date") or "")[:10], str(d.get("time") or "")[:5]
    if len(date) != 10:
        return ""
    return f"{date}T{tm}:00+09:00" if len(tm) == 5 else date


def _until_key(u: str) -> str:
    return u if len(u) > 10 else u + "T23:59:59+09:00"


def _earliest_until(vals) -> str:
    vs = [u for u in vals if u]
    return min(vs, key=_until_key) if vs else ""


def _lot_until(status, end, purchase_end) -> tuple:
    """応募できる状態（開始前・受付中・締切間近）は応募締切、購入期間中（当選者のみ）は購入期間の終了で失効する。(until, 失効後の文言)。失効しない状態は ("", "")。"""
    if status in _INTAKE_FOR_RB:
        return _until_iso(end), RB_EXPIRED_APPLY
    if status == ls.L_WINNER_PURCHASE_PERIOD:
        return _until_iso(purchase_end), RB_EXPIRED_PURCHASE
    return "", ""


def _rb_wrap(inner: str, until: str, expired_inner: str) -> str:
    """締切のある表示を JS_RB で切り替えられる形にする。until が無ければそのまま（締切の無い行は変えない）。"""
    if not until:
        return inner
    return f'<span data-rb-open>{inner}</span><span data-rb-expired hidden>{expired_inner}</span>'


def _tone(status) -> str:
    return _TONE.get(status, "warn")


def _status_badge(status, label) -> str:
    return _badge(label, _tone(status))


def _prio_badge(p) -> str:
    return _badge(PRIO_LABEL[p], "out") if p and p != st.P_WATCH else ""         # WATCH（要確認）は全行に付けず、凡例と「未確認」表示で足りる


def _tcgtag(tcg) -> str:
    ini, cls = TCG_INITIAL.get(tcg, ("?", ""))
    return f'<span class="tcgtag {cls}" title="{_e(TCG_LABEL.get(tcg, tcg))}">{_e(ini)}</span>'


def _state_tokens(v: dict, flags: set) -> str:
    toks = []
    if v["status"] == ls.L_OPEN:
        toks.append("open")
    if v["status"] == ls.L_ENDING_SOON:
        toks.append("ending")
    if v["status"] == ls.L_UPCOMING:
        toks.append("upcoming")
    toks += sorted(flags)
    return " ".join(toks)


def _ev_row(v: dict, pidx: dict, yr: str, flags: set) -> str:
    ev = v["ev"]
    shop = pv.retailer_label(ev)
    sub = ev.get("retailer_name") or ""
    if pv._is_enum_like(sub, str(ev.get("retailer") or "")):         # 列挙値は副表示にも出さない
        sub = ""
    region = ev.get("prefecture") or ""
    bound = v.get("canonical") in (pv.C_MASTER, pv.C_DISCOVERED)
    p_key = pidx.get((ev.get("tcg"), ev.get("product_id"))) if bound else None
    attrs = (f'data-tcg="{_e(ev.get("tcg"))}" data-product="{_e(p_key or "none")}" data-retailer="{_e(ev.get("retailer"))}" '
             f'data-region="{_e(region or "unknown")}" data-state="{_e(_state_tokens(v, flags))}"')
    pname = _e(ev.get("product_name") or "商品名不明")
    if p_key:
        product = f'{_tcgtag(ev.get("tcg"))}<a href="#{_e(p_key)}">{pname}</a>'
    else:
        product = (f'{_tcgtag(ev.get("tcg"))}{pname}<small>{_badge("未紐付け", "out")}'
                   f'<span title="{_e(CANON_LABEL.get(v.get("canonical"), ""))}">推測で商品に結んでいません</span></small>')
    reqs = [REQ_LABEL.get(r, r) for r in v["requirements"]]
    elig = (str(ev.get("eligibility_text") or "")[:200]) or None
    cond = (f'<details><summary>条件</summary>{_e("、".join(reqs)) if reqs else "明記なし"}'
            f'{"（原文: " + _e(elig) + "）" if elig else ""}</details>') if (reqs or elig) else '<small>条件: 明記なし</small>'
    until, exp_msg = _lot_until(v["status"], v["end"], v["purchase_end"])
    apply_a = _link(v["application_url"], "応募ページ")
    if apply_a and until:                                       # 期限後は応募リンクを隠す
        apply_a = f'<span data-rb-open>{apply_a}</span>'
    links = [apply_a, _link(v["announcement_url"], "公式の告知")]
    links = " / ".join(x for x in links if x)
    nolink = '' if v["application_url"] else '<small class="nl-d">応募ページの URL は未確認</small>'
    nolink_m = '' if v["application_url"] else '<small class="nl-m"> ・応募URL未確認</small>'
    ch = v["channel"]
    kind = KIND_LABEL.get(v["entry_kind"], v["entry_kind"])
    verify = (_badge("確認済み", "out") if v["verified"]
              else f'<span class="sb warn" title="未確認（公式での再確認待ち）">未確認</span>')
    if ev.get("conflict"):
        verify += _badge("日程に食い違い", "danger")
    ver_raw = ev.get("last_verified_at") or ev.get("observed_at") or "不明"
    aux = (_badge("今日締切", "danger") if "deadline" in flags else _badge("新着", "info") if "new" in flags else "") + _prio_badge(v["priority"])   # 優先度は今日締切・新着の行にも並べる
    slabel = LABEL_PURCHASE_ONLY if v["status"] == ls.L_WINNER_PURCHASE_PERIOD else v["status_label"]      # 購入期間中は当選者だけ（新規応募不可）
    st_cell = _rb_wrap(f'{_status_badge(v["status"], slabel)}<small>（生成時点）</small>', until, _badge(exp_msg, "warn")) + aux
    if not until:
        st_cell = f'{_status_badge(v["status"], slabel)}{aux}'
    ok = v["verified"]
    no_res = not v["result"].get("date")
    if until:
        attrs += f' data-rb-card data-rb-until="{_e(until)}"'
    return (f'<tr class="ev t-{_tone(v["status"])}" {attrs}>'
            f'<td data-label="状態">{st_cell}</td>'
            f'<td data-label="店舗"><b>{_e(shop)}</b>{"<small>" + _e(sub) + "</small>" if sub and sub != shop else ""}</td>'
            f'<td data-label="商品">{product}</td>'
            f'<td data-label="締切"{W2 if no_res else ""}>{_md(v["end"], yr, ok)}<small>開始 {_md(v["start"], yr, ok)}</small></td>'
            f'<td data-label="応募方法" class="how"><span title="{_e(CHANNEL_LABEL.get(ch, ch))}">{_e(CHANNEL_SHORT.get(ch, ch))}</span>・{_e(kind)}'
            f'{"<small>" + links + "</small>" if links else ""}{nolink}{cond}</td>'
            f'<td data-label="地域"{"" if region else NA}>{_e(region) if region else "—"}</td>'
            f'<td data-label="当選日"{"" if v["result"].get("date") else NA}>{_md(v["result"], yr, ok)}</td>'
            f'<td data-label="購入期間"{"" if (v["purchase_start"].get("date") or v["purchase_end"].get("date")) else NA}>{_range(v["purchase_start"], v["purchase_end"], yr, ok)}</td>'
            f'<td data-label="確認">{verify}<small title="{_e(ver_raw)}">確認 {_vshort(ver_raw)}</small>{nolink_m}</td></tr>')


W2 = ' class="w2"'                                      # 当選日の列が無いときの締切セル
NA = ' class="na"'                                      # 値が無いセル（モバイルのカードでは出さない）
_HEAD = ("<tr><th>状態</th><th>店舗</th><th>商品</th><th>締切</th><th>応募方法</th><th>地域</th>"
         "<th>当選日</th><th>購入期間</th><th>確認</th></tr>")


def _table(views, pidx, yr, flagmap, tid) -> str:
    rows = "".join(_ev_row(v, pidx, yr, flagmap.get(id(v), set())) for v in views)
    return f'<div class="lt-wrap" id="{tid}"><table class="lt"><thead>{_HEAD}</thead><tbody>{rows}</tbody></table></div>'


TCG_SHORT = {"POKEMON": "ポケカ", "ONE_PIECE": "ワンピ"}          # 画像が無いときのプレースホルダに添える種別


def _img_block(p: dict) -> str:
    """商品画像。ポケカで商品マスタに一致し、URL が pokemon-card.com の https のときだけ <img>。それ以外はブランド色＋頭文字＋種別のプレースホルダ（偽の画像を作らない）。"""
    ini, cls = TCG_INITIAL.get(p["tcg"], ("?", ""))
    src = _image_src(p.get("image_url")) if p["tcg"] == "POKEMON" and p["canonical"] == pv.C_MASTER else None
    if src:
        return (f'<div class="pimg {cls}"><img src="{_e(src)}" alt="{_e(p.get("name") or "")}" loading="lazy" decoding="async" '
                f'referrerpolicy="no-referrer" width="{IMG_W}" height="{IMG_H}"></div>')
    return (f'<div class="pimg ph {cls}" role="img" aria-label="商品画像なし（{_e(TCG_LABEL.get(p["tcg"], p["tcg"]))}）">'
            f'<b>{_e(ini)}</b><small>{_e(TCG_SHORT.get(p["tcg"], ""))}</small></div>')


def _susp_label(r: dict) -> str:
    t = r.get("suspended_text") or "お申込一時停止中"
    return f"{t}（今は買い取っていません）" if "停止" in t else f"{t}（買取として扱いません）"


# ───────────────────────── 商品カード（1 商品 1 枚: 画像・利益ストリップ・最高額の買取店・折りたたみの他店・抽選） ─────────────────────────
# 鮮度（data-fb-*）の約束: 買取由来の値（最高買取・利益・ROI・差額・前提・状態バッジ・他店の価格）は、必ず data-fb-live の <span> の中に入れる。
# live の内側は <b> / <small> / <a> だけ（<div> と <span> の入れ子を作らない。正規表現で live を取り除く検査が途中で切れて金額を見落とさないため）。
# グループは取得時刻が同じ要素だけで作る（取得時刻が違う要素を同じ group にすると、片方だけ期限切れのとき表示と『再確認待ち』が食い違う）:
#   最高買取と差額（観測は最高買取の行）= {g}-b／利益・ROI・状態バッジ（観測は利益の基準店の取得）= {g}-p／他店は行ごと {g}-oN。各 live の直後に同じ group の stale を置く。
def _live(g: str, obs, cfg: dict, inner: str) -> str:
    return f'<span data-fb-live data-fb-group="{g}" {rf.attrs(obs, cfg)} hidden>{inner}</span>'


def _stale(g: str, cfg: dict, inner: str) -> str:
    return f'<span data-fb-stale data-fb-group="{g}" data-fb-max="{rf.thresholds(cfg)[0]:g}">{inner}</span>'


def _stale_txt(obs, lead: str = "価格再確認待ち") -> str:
    """鮮度切れのとき最初から出ている文（金額は出さない）。JS が data-fb-why を『取得から N 時間以上経過』に書き換える。"""
    return f'{lead}<small>（<span data-fb-why>表示時点の鮮度を確認できていません</span>）・取得 {_vshort(obs)}</small>'


def _https(url) -> Optional[str]:
    return url if isinstance(url, str) and url.startswith("https://") else None


def _shop_link(r: dict) -> str:
    u = _https(r.get("item_url")) or _https(r.get("source_url"))
    return f'<a href="{_e(u)}" target="_blank" rel="noopener nofollow">買取店のページ</a>' if u else ""


PREMISE_BUY = "この利益は、公式定価で購入できた場合の計算です。購入できるかどうか（在庫・抽選）は示していません"


def _strip(c: dict, g: str, cfg: dict) -> str:
    """利益ストリップ: 公式定価 → 最高買取（最高額の 1 店）→ 利益。最高買取の店が利益の基準店と違えば、利益の下に差額を別行で出す。"""
    pr, bbv, m = c["profit"], c.get("buyback"), c.get("msrp")
    gb, gp = f"{g}-b", f"{g}-p"                                  # 最高買取・差額 / 利益・状態バッジ（取得時刻が違うので別グループ）
    unit = str(c.get("unit") or "")
    ex = (bbv or {}).get("highest_executable")
    net = pr.get("net_profit")
    if m:
        chk = _short(m.get("checked_at"))[:10]
        v_msrp = f'<b class="amt">{_yen(m["retail_price"])}</b><small>公式の{_e(unit) if unit else ""}価格・確認 {_e(chk)}</small>'
    elif c.get("pack_price"):
        v_msrp = (f'<b class="amt">未確認</b><small>公式が明記した価格は 1 パック {_yen(c["pack_price"])} だけです。'
                  'BOX の定価はパック価格から計算していません</small>')
    else:
        v_msrp = '<b class="amt">未確認</b><small>公式の定価が確認できていません</small>'
    if ex:
        src = "単一ソース" if bbv.get("single_source") else f'{bbv["shop_count"]}店で確認'
        cond = "新品未開封・受付中" if ex.get("accept_state") == "ACTIVE" else "新品未開封"
        inner = (f'<b class="amt">{_yen(ex["price"])}</b><small>{_e(ex["shop_name"])}・{_e(ex.get("unit") or unit)}・{cond}・'
                 f'確認 {_vshort(ex["checked_at"])}・{_e(src)}</small><small>{_shop_link(ex)}</small>')
        v_best = _live(gb, ex["checked_at"], cfg, inner) + _stale(gb, cfg, _stale_txt(ex["checked_at"]))
    elif bbv and bbv.get("outlier"):
        v_best = '<b class="amt">確認待ち</b><small>最高の買取価格が他店や定価と大きく離れているため、確認待ちです（利益に使っていません）</small>'
    elif bbv:
        v_best = '<b class="amt">未確認</b><small>鮮度・条件を確認できた買取価格がありません（掲載だけの価格は下の買取店に参考表示）</small>'
    else:
        v_best = '<b class="amt">未確認</b><small>買取店のページに、この商品の買取価格が見つかっていません</small>'
    rows = [("公式定価", v_msrp, "msrp"), ("最高買取", v_best, "best")]
    if net is not None:
        neg = net <= 0
        small = ("赤字です・" if neg else "") + f'ROI {pr["roi_pct"]:.1f}%'
        base = f'基準: {pr.get("sell_shop_name") or ""} 買取 {_yen(pr["sell_price"])}・定価 {_yen(pr["acquisition_cost"])}'
        premise = f'前提: {pr.get("route") or ""}（交通費・時間は含みません）。店頭の買取価格が Web 掲載と同じかは未確認で、箱の状態により減額・返送になる場合があります'
        if pr.get("single_source"):
            premise += '・買取は 1 店のみ（単一ソース）'
        inner = f'<b class="amt {"neg" if neg else "pos"}">{_e(pr["label"])}</b><small>{_e(small)}</small><small>{_e(base)}</small>'
        if c.get("state") == pv.O_WATCH and not neg:
            inner += '<small>黒字でも投資利益率が基準に届かないため、様子見です</small>'
        inner += f'<small>{_e(premise)}</small><small>{_e(PREMISE_BUY)}</small>'
        v_profit = _live(gp, pr.get("sell_observed_at"), cfg, inner) + _stale(gp, cfg, _stale_txt(pr.get("sell_observed_at"), "利益は価格再確認待ち"))
    elif bbv and bbv.get("outlier"):
        v_profit = '<b class="amt">確認待ち（利益に使っていません）</b>'
    elif not m:
        v_profit = '<b class="amt">算出前</b><small>公式定価が未確認のため利益は算出前です</small>'
    else:
        v_profit = f'<b class="amt">算出前</b><small>{_e(pr.get("reason") or "買取の根拠が無いため算出していません")}</small>'
    rows.append(("利益", v_profit, "profit"))
    if net is not None and ex and m and pr.get("sell_shop") != ex.get("shop"):
        diff = ex["price"] - m["retail_price"]
        inner = (f'<b class="amt">{diff:+,}円</b><small>最高買取 − 定価（費用除く・参考）</small>'
                 f'<small>最高買取の店（{_e(ex["shop_name"])}）と、利益の基準にした店（{_e(pr.get("sell_shop_name") or "")}）は別です</small>'
                 '<small>最高買取の店は送料・費用が未確認のため、利益ではなく差額です</small>')
        v_diff = _live(gb, ex["checked_at"], cfg, inner) + _stale(gb, cfg, "価格再確認待ち")
        rows.append(("差額（参考）", v_diff, "diff"))
    cls = "tc-strip is-wait" if c.get("state") == pv.O_WATCH else "tc-strip"
    lis = "".join(f'<li data-strip-{k}><em>{lbl}</em><span class="tc-val">{v}</span></li>' for lbl, v, k in rows)
    return f'<ul class="{cls}" data-strip>{lis}</ul>'


def _other_state(r: dict, ex, outlier) -> tuple:
    """(種別, 状態の文言)。実行可能・外れ値の疑い・受付停止・参考（条件未確認・掲載のみ・鮮度切れ）。"""
    from src.tcg import buyback as _bb
    if outlier and r["shop"] == outlier["shop"] and r.get("executable"):
        return "outlier", "外れ値の疑い・確認待ち（最高買取にしていません・価格は出しません）"
    if r.get("executable"):
        return "executable", "買取対象（新品未開封・受付中）" if r.get("accept_state") == "ACTIVE" else "買取対象（新品未開封）"
    if r.get("suspended"):
        return "suspended", _susp_label(r) + "・最高買取にしません"
    if r.get("condition") not in _bb.EXECUTABLE_CONDITIONS:
        return "reference", "条件未確認・参考（条件: " + str(r.get("condition") or "不明") + "）・最高買取にしません"
    return "reference", "掲載のみ・参考（取得が古いか単位を確認できません）・最高買取にしません"


def _others(c: dict, g: str, cfg: dict) -> str:
    """折りたたみの『他の買取店』。閉じた状態では最高額の 1 店（ストリップ）だけが見える。店数は重複しない店で数える（行数ではない）。"""
    bbv = c.get("buyback")
    if not bbv:
        return ""
    ex, outlier = bbv.get("highest_executable"), bbv.get("outlier")
    rows = [r for r in bbv.get("others") or [] if not (ex and r["shop"] == ex["shop"] and r.get("executable"))]
    if not rows:
        return ""
    lis = []
    for k, r in enumerate(rows):
        gk = f'{g}-o{k}'
        kind, label = _other_state(r, ex, outlier)
        unit = str(r.get("unit") or c.get("unit") or "")
        same = bool(ex) and r["shop"] == ex["shop"]
        if kind == "outlier":
            body = f'<small>{_e(label)}</small>'
        else:
            inner = f'<b class="amt">{_yen(r["price"])}</b><small>{_e(unit)}・確認 {_vshort(r["checked_at"])}</small>'
            if kind == "executable":
                inner += f'<small>{_e(label)}</small>'
            body = _live(gk, r["checked_at"], cfg, inner) + _stale(gk, cfg, _stale_txt(r["checked_at"]))
            if kind != "executable":
                body += f'<small>{_e(label)}</small>'
        if same:
            body += '<small>最高買取の店と同じ店の別条件です（店数には数えません）</small>'
        lis.append(f'<li data-other-shop="{_e(r["shop"])}" data-other-kind="{kind}"><b>{_e(r["shop_name"])}</b>'
                   f'<span class="tc-val">{body}</span>{_shop_link(r)}</li>')
    n_same = sum(1 for r in rows if ex and r["shop"] == ex["shop"])
    n_shops = len({r["shop"] for r in rows if not (ex and r["shop"] == ex["shop"])})
    if ex:
        title = f'他の買取店（{n_shops} 店）' if n_shops else '最高買取の店の別条件（参考）'
        if n_same and n_shops:
            title += f'・同じ店の別条件 {n_same} 件'
        elif n_same:
            title = f'最高買取の店の別条件（{n_same} 件・参考）'
        guide = ('実行可能（受付中・条件を確認できた）な店の中での最高額を上に出しています。'
                 '条件未確認・受付停止・掲載のみの店は、価格が高くても参考で、最高買取にしません。')
    else:
        title = f'掲載のある買取店（{n_shops} 店・参考）'
        if outlier:
            guide = '最高買取は確認待ち（外れ値確認中）です。確認が済むまで、下の価格は参考で、最高買取にも利益にも使いません。'
        else:
            guide = '最高買取は確認できていません（鮮度・条件を確認できた価格がありません）。下の価格はすべて参考で、最高買取にしません。'
    return (f'<details class="tc-others" data-others><summary>{title}</summary>'
            f'<p class="mut">{_e(guide)}</p>'
            f'<ul>{"".join(lis)}</ul></details>')


def _unknown_when(i: dict, yr: str) -> str:
    """状態が UNKNOWN（日程の食い違い・未確認・日程未確認）の抽選の本文。締切済みとは言わない（締切を断定できない）。応募できるとも言わない。"""
    end = _md(i["end"], yr, False)
    if i["conflict"]:
        return f'情報源で日程が食い違っています（公式で確認してください）・締切 {end}'
    if not i["verified"] and i["status"] in (ls.L_OPEN, ls.L_ENDING_SOON, ls.L_UPCOMING):
        return '公式で再確認待ちのため、応募の可否を断定しません'
    return f'日程が未確認です（締切 {end}）。応募できるかどうかは公式ページで確認してください'


def _lot_item(i: dict, yr: str) -> str:
    eff = i["eff_status"]
    tone = "warn" if (eff == ls.L_UNKNOWN or i["winner_only"]) else _tone(eff)
    ok = i["verified"] and not i["conflict"]
    if eff == ls.L_UNKNOWN:
        when = _unknown_when(i, yr)
    elif eff == ls.L_UPCOMING:
        when = f'開始 {_md(i["start"], yr, ok)}・締切 {_md(i["end"], yr, ok)}'
    elif i["winner_only"]:
        when = f'購入期間 {_range(i["purchase_start"], i["purchase_end"], yr, ok)}'
    elif eff in (ls.L_OPEN, ls.L_ENDING_SOON):
        when = f'締切 {_md(i["end"], yr, ok)}'
    else:
        when = f'応募は締切済み（締切 {_md(i["end"], yr, ok)}）'
    reqs = "、".join(REQ_LABEL.get(r, r) for r in i["requirements"])
    cond = "条件: " + (reqs if reqs else "明記なし")
    if eff in (ls.L_OPEN, ls.L_ENDING_SOON, ls.L_UPCOMING, ls.L_WINNER_PURCHASE_PERIOD) or i["winner_only"]:
        until, exp_msg = _lot_until(ls.L_WINNER_PURCHASE_PERIOD if i["winner_only"] else eff, i["end"], i["purchase_end"])
    else:
        until = exp_msg = ""
    apply_a = _link(i["application_url"], "応募ページ")
    if apply_a and until:                                       # 期限後は応募リンクを隠す
        apply_a = f'<span data-rb-open>{apply_a}</span>'
    links = " ".join(x for x in (apply_a, _link(i["announcement_url"], "公式の告知")) if x)
    badge_html = (_rb_wrap(f'{_badge(i["status_label"], tone)}<small>（生成時点）</small>', until, _badge(exp_msg, "warn"))
                  if until else _badge(i["status_label"], tone))
    rb_attrs = f' data-rb-card data-rb-until="{_e(until)}"' if until else ""
    return (f'<li data-lot-item data-lot-status="{_e(eff)}"{rb_attrs}><b>{_e(i["shop"])}</b>{badge_html}'
            f'<small>{_e(KIND_LABEL.get(i["kind"], i["kind"]))}・{when}・{_e(cond)}</small>{links}</li>')


def _lot_show(items: list) -> list:
    """カードに出す抽選（最大 3 件）。並びの先頭から 3 件（受付中・締切間近は段階 0 で先頭に並ぶので、必ず含まれる。3 件を超えるときは締切が近い順の 3 件）。
    日程未確認があるのに 3 件の外に隠れるときは、3 件目と入れ替えて 1 件は見せる（入れ替えで落ちるのは、受付中・締切間近が 4 件以上のときの 3 件目だけ。
    受付中・締切間近を全部落とすことはない）。"""
    idx = list(range(min(3, len(items))))
    unk = [k for k, i in enumerate(items) if i["eff_status"] == ls.L_UNKNOWN]
    if unk and idx and not any(k in unk for k in idx):
        idx[-1] = unk[0]
    return [items[k] for k in idx]


def _lot_block(c: dict, yr: str, pk: Optional[str], unbound_applying: int, rb_open: Optional[list] = None, ann: Optional[dict] = None) -> str:
    cn = c["counts"]
    items_all = c.get("lottery_items") or []

    def chip(n, lbl, tone, eff=None, field="end"):
        if not n:
            return ""
        until = _earliest_until(_until_iso(i[field]) for i in items_all if i["eff_status"] == eff) if eff else ""
        if not until:                                            # 締切が読めない件数は静的のまま（失効を判定できない）
            return f'<span class="chip {tone}"><b>{n}</b>{lbl}</span>'
        # 件数は再計算しない。その group で最も早い締切を過ぎたら「期限が過ぎた抽選があります」に切り替える（fail-closed）
        return (f'<span class="chip {tone}" data-rb-card data-rb-until="{_e(until)}"><span data-rb-open><b>{n}</b>{lbl}（生成時点）</span>'
                f'<span data-rb-expired hidden><b>{n}</b>（生成時点）→ {RB_EXPIRED_GROUP}</span></span>')
    chips = (chip(cn.get("open"), "受付中", "info", ls.L_OPEN) + chip(cn.get("ending_soon"), "締切間近", "danger", ls.L_ENDING_SOON)
             + chip(cn.get("result_pending"), "当選発表待ち", "warn")
             + chip(cn.get("purchase_period"), "購入期間中（当選者のみ）", "warn", ls.L_WINNER_PURCHASE_PERIOD, "purchase_end")
             + chip(cn.get("upcoming"), "近日開始", "info", ls.L_UPCOMING))
    if cn.get("unknown"):                                        # 受付中の数には入れない（応募できると断定しない）
        chips += f'<span class="chip warn" data-chip-unknown>日程未確認 <b>{cn["unknown"]}</b></span>'
    out = f'<div class="chips">{chips}</div>' if chips else ""
    if not (cn.get("open") or cn.get("ending_soon") or cn.get("upcoming")):
        note = "この商品に紐付いた、応募受付中の抽選はありません" + ("。紐付け前の告知は抽選一覧を参照" if unbound_applying > 0 else "")
        if cn.get("unknown"):
            note += "。日程未確認の抽選は、応募できるか公式ページで確認してください"
        if not c.get("has_events"):
            note = "現在確認できる抽選なし（" + note + "）"
        out += f'<p class="pnote">{_e(note)}</p>'
    if rb_open:       # 販売店の告知（BOX 価格の節）で応募受付中の行。抽選の紐付け・チップ・受付中の数には入れない（案内だけ）
        hint = "販売店の告知で応募受付中の行があります（下の「販売店の BOX 価格」節を参照"
        hint += "。商品の紐付けは未確認）" if any(r.get("human_confirmed") is not True for r in rb_open) else "）"
        an = sorted({n for r in rb_open for n in _rb_ann_names(r, ann)})
        if an:            # 同じ告知 URL の抽選の告知名（複数商品を指す）を短く併記（どの商品の価格かは推測しない）
            hint += f"告知名は{'／'.join('「' + n + '」' for n in an)}です（どれの価格かは公式ページで確認）"
        until = _earliest_until(str(r.get("apply_end") or "").strip() for r in rb_open)       # _rb_refs と同じく apply_end の原値を JS_RB に渡す
        if until:         # OPEN は静的に「受付中」と書かない。期限を併記し、期限後は JS_RB が切り替える（複数行は最も早い期限で案内全体を切り替える）
            dl = f"（応募期限 {_e(_apply_deadline(until))}まで・生成時点の判定）"
            out += (f'<p class="pnote" data-rb-hint data-rb-card data-rb-until="{_e(until)}"><span data-rb-open>{_e(hint)}{dl}</span>'
                    f'<span data-rb-expired hidden>応募期限を過ぎました。販売店の告知ページで再確認してください</span></p>')
        else:
            out += f'<p class="pnote" data-rb-hint>{_e(hint)}（応募期限は未確認・生成時点の判定）</p>'
    items = c.get("lottery_items") or []
    if items:
        show = _lot_show(items)
        link = (f'<a href="#lottery" data-pf="{pk}">表で見る（この商品の抽選 {len(items)} 件）</a>' if pk
                else "")
        out += (f'<details class="tc-lotd" data-lot-details><summary>抽選 {len(items)} 件（受付中・締切間近 → 開始前 → 日程未確認 → 結果待ち・購入期間の順・同じ段階は締切が近い順・最大 3 件。受付中・締切間近は必ず含みます）</summary>'
                f'<ul>{"".join(_lot_item(i, yr) for i in show)}</ul>{link}</details>')
    return f'<div class="tc-lot" data-lot>{out}</div>'


def _card(c: dict, dom_id: str, pk: Optional[str], yr: str, cfg: dict, unbound_applying: int, rb_open: Optional[list] = None, ann: Optional[dict] = None) -> str:
    g = dom_id
    state, pr = c.get("state"), c["profit"]
    net = pr.get("net_profit")
    badge = ""
    if state and net is not None:
        neg = net <= 0
        label = "赤字" if neg else (c["state_label"] + ("（単一ソース）" if pr.get("single_source") else ""))
        tone = "out" if state == pv.O_PROFIT else "warn"
        gp = f"{g}-p"                                            # 利益と同じ取得時刻（sell_observed_at）なので同じ group
        badge = (_live(gp, pr.get("sell_observed_at"), cfg, f'<b class="sb {tone}">{_e(label)}</b>')
                 + _stale(gp, cfg, '<b class="sb warn">確認待ち</b>'))
    ptype = PTYPE_LABEL.get(c["product_type"], "") if c.get("product_type") else ""      # 日本語ラベルが無い種別は、生の値を出さず省く
    meta = [_e(TCG_LABEL.get(c["tcg"], c["tcg"]))]
    if ptype:
        meta.append(_e(ptype))
    if c.get("unit"):
        meta.append(_e(c["unit"]))
    meta_html = "・".join(meta)
    if c.get("release_date"):
        meta_html += "・発売 " + _md({"date": c["release_date"], "time": None}, yr)
    off = _product_link(c.get("official_url") or (c.get("msrp") or {}).get("official_url")) or '<span class="mut">公式ページ未確認</span>'
    st_attr = "profit" if state == pv.O_PROFIT else ("watch" if state == pv.O_WATCH else "none")
    return (f'<article class="tcard" id="{g}" data-card data-card-key="{_e(c["tcg"])}:{_e(c["product_id"])}" data-card-state="{st_attr}">'
            f'<div class="tc-top">{_img_block(c)}<div class="tc-id"><div class="tc-tags">{_tcgtag(c["tcg"])}{badge}</div>'
            f'<h3>{_e(c["name"])}</h3><p class="tc-meta">{meta_html}</p></div></div>'
            f'{_strip(c, g, cfg)}{_others(c, g, cfg)}{_lot_block(c, yr, pk, unbound_applying, rb_open, ann)}'
            f'<div class="tc-foot">{off}</div></article>')


# 販売店の BOX 価格: 応募期限を過ぎたカードは、表示時にも利益を隠す（生成から時間が経っても、期限後の価格を条件付きの利益として見せない）
JS_RB = r"""
(function(){function rb(){try{var now=Date.now(),chg=false;document.querySelectorAll('[data-rb-card]').forEach(function(c){var u=c.getAttribute('data-rb-until');
var t=u?Date.parse(u.length===10?u+'T23:59:59+09:00':u):NaN;var ex=(isNaN(t)||now>t);c.classList.toggle('rb-expired',ex);
c.querySelectorAll('[data-rb-expired]').forEach(function(e){e.hidden=!ex});
var s=c.getAttribute('data-state');if(s!==null){var o=c.getAttribute('data-state-orig');if(o===null){o=s;c.setAttribute('data-state-orig',o);}
var ns=ex?o.split(' ').filter(function(k){return k&&['open','ending','upcoming','today','deadline','new'].indexOf(k)<0}).concat(['closed']).join(' '):o;
if(ns!==s){c.setAttribute('data-state',ns);chg=true;}}});
if(chg){var fm=document.getElementById('flt');if(fm)fm.dispatchEvent(new Event('change'));}}catch(e){}}
rb();setInterval(rb,60000);window.addEventListener('pageshow',rb);document.addEventListener('visibilitychange',rb);})();
"""


RB_UNBOUND = "（商品の紐付けは未確認）"


def _rb_unbound(r: dict) -> str:
    """台帳の行の商品が人に確認されていない（human_confirmed が True でない）ときの併記。商品名を断定しない。確認済みの行には出さない。"""
    return RB_UNBOUND if (r or {}).get("human_confirmed") is not True else ""


_MULTI_RE = re.compile(r"[0-9０-９二三四五六七八九十]+種|セット")


def _url_key(u) -> str:
    u = str(u or "").strip().lower()
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u.rstrip("/")


def _announce_index(views) -> dict:
    """告知 URL（正規化）→ その URL を根拠にした抽選の告知名（商品名）の一覧。複数商品を指す語（「二種」「N種」「セット」）を含む名前だけ集める。
    台帳の行の商品が未確認のとき、同じ告知の名前と食い違って見えることを併記するための索引（商品の紐付けはしない）。"""
    idx: dict = {}
    for v in views or []:
        ev = (v or {}).get("ev") if isinstance(v, dict) else None
        if not isinstance(ev, dict):
            continue
        name = str(ev.get("product_name") or "").strip()
        if not name or not _MULTI_RE.search(name):
            continue
        for u in (ev.get("source_url"), v.get("announcement_url")):
            k = _url_key(u)
            if k and name not in idx.setdefault(k, []):
                idx[k].append(name)
    return idx


def _rb_ann_names(r: dict, ann) -> list:
    names = (ann or {}).get(_url_key((r or {}).get("source_url"))) or []
    own = str((r or {}).get("display_name") or "").strip()
    return [n for n in names if n != own]


def _rb_ann(r: dict, ann) -> str:
    """同じ告知 URL の抽選の告知名が複数商品を指すとき、どの商品の価格かは公式で確認するよう併記する。無ければ空（推測で紐付けない）。"""
    names = _rb_ann_names(r, ann)
    if not names:
        return ""
    k = "二種" if any(("二種" in n or "2種" in n) for n in names) else "含まれる商品"
    return f"告知名は{'／'.join('「' + n + '」' for n in names)}です。{k}のうちどちらの価格かは公式ページで確認してください"


def _rb_link(url) -> str:
    return (f'<a href="{_e(url)}" rel="noopener noreferrer" target="_blank">販売店の告知ページ</a>'
            if isinstance(url, str) and url.startswith("https://") else '<span class="mut">根拠 URL なし</span>')


def _rb_card(o: dict, i: int, ann: Optional[dict] = None) -> str:
    """販売店の BOX 価格による「条件付き」の利益。公式定価とは別ラベル。緑の購入推奨にしない。応募期限は表示時にも判定する。"""
    cfg = _CFG()
    pr, bbv, r = o["profit"], o["buyback"], o["retailer"]
    ex = bbv["highest_executable"]
    mx = rf.thresholds(cfg)[0]
    g = f"rb{i}"
    live = f'data-fb-live data-fb-group="{g}" {rf.attrs(pr.get("sell_observed_at"), cfg)} hidden'
    live_ex = f'data-fb-live data-fb-group="{g}" {rf.attrs(ex["checked_at"], cfg)} hidden'
    unit = _e(o["unit"])
    neg = pr["net_profit"] <= 0
    until = _e(str(r.get("apply_end") or ""))
    badge = (f'<span {live}>{_badge("条件付き" + ("（赤字）" if neg else ""), "warn")}</span>'
             f'<span data-fb-stale data-fb-group="{g}" data-fb-max="{mx:g}">{_badge("確認待ち", "warn")}</span>')
    meta = f'<div><dt>販売店価格（{unit}）</dt><dd>{_yen(r["price_jpy"])}<small>{_e(r.get("price_class_label") or "販売店の価格")}・{_e(r["shop"])}の実販売価格・メーカー定価ではありません</small></dd></div>'
    apply_end = r.get("apply_end")
    apply_note = f"（応募期限 {_e(_apply_deadline(apply_end))}・生成時点の判定）" if apply_end else "（生成時点の判定）"
    if r.get("start_unconfirmed"):
        apply_note += "・応募開始日は未確認（応募期間内の可能性）"
    meta += f'<div><dt>応募</dt><dd><span data-rb-open>{_e(r["accept_label"])}{apply_note}</span><span data-rb-expired hidden>応募期限を過ぎました</span><small>締切 {_e(_short(r.get("apply_end")))}・購入 {_e(_short(r.get("purchase_start")))}〜{_e(_short(r.get("purchase_end")))}</small></dd></div>'
    meta += f'<div><dt>受取</dt><dd>{_e(r.get("shipping") or "未確認")}</dd></div>'
    meta += (f'<div {live_ex}><dt>最高買取</dt><dd>{_yen(ex["price"])}<small>{_e(ex["shop_name"])}・{unit}</small></dd></div>')
    meta += (f'<div {live}><dt>条件付きの純利益</dt><dd title="{_e(pr.get("route") or "")}">{_e(pr["label"])}'
             f'<small>{"赤字" if neg else "当選した場合"}: 買取 {_yen(pr["sell_price"])}・販売店価格 {_yen(pr["acquisition_cost"])}</small></dd></div>'
             f'<div {live}><dt>ROI</dt><dd>{pr["roi_pct"]:.1f}%</dd></div>')
    meta += (f'<div data-fb-stale data-fb-group="{g}" data-fb-max="{mx:g}"><dt>純利益・ROI</dt><dd>価格再確認待ち'
             f'<small>取得から{mx:g}時間を超えた買取価格は、利益の根拠にしません</small></dd></div>')
    notes = [f'条件: {o["condition"]}', *(["応募開始日未確認（応募期間内の可能性。開始前でないことは確認できていません）"] if r.get("start_unconfirmed") else []), "購入推奨ではありません。購入できる保証はなく、今すぐ行動できる項目ではありません",
             f'確認 {_short(r.get("verified_at"))}・JAN 未確認・箱の状態（新品・シュリンク）未確認・人の確認 {"済" if r.get("human_confirmed") else "未"}']
    nt = "".join(f'<span class="pnote">{_e(n)}</span>' for n in notes)
    an = _rb_ann(r, ann)
    if an:
        nt += f'<span class="pnote">{_e(an)}</span>'
    nt += (f'<span class="pnote" data-rb-until="{until}">応募の期限を過ぎた場合、この利益は無効です（表示時に判定します）</span>'
           f'<span class="pnote" data-rb-expired hidden>応募期限を過ぎました。この利益は参考にしないでください</span>')
    return (f'<section class="pcard opp" id="{g}" data-rb-card data-rb-until="{until}">{_img_block(o)}<div class="phead">'
            f'<div>{_tcgtag(o["tcg"])}{badge}{_badge("抽選・当選した場合のみ", "out")}</div><h3>{_e(o["name"])}<small class="mut">{_rb_unbound(r)}</small></h3></div>'
            f'<div class="pmeta"><dl>{meta}</dl>{nt}</div><div class="pfoot">{_rb_link(r.get("source_url"))}</div></section>')


def _rb_refs(refs: list, ann: Optional[dict] = None) -> str:
    """参考情報（応募終了・当選者のみ・期間外・不明・算出不可・不採用）。利益は出さない。"""
    if not refs:
        return ""
    def _item(r: dict) -> str:
        name = r.get("display_name") or (f'商品ID: {r.get("product_id")}' if r.get("product_id") else "商品不明")
        rejected = r.get("kind") == "REJECTED"
        price = "" if rejected or not isinstance(r.get("price_jpy"), int) else _yen(r["price_jpy"])        # 不採用の行は価格を出さない
        is_open = not rejected and r.get("accept_state") == "OPEN"
        if is_open:       # OPEN は静的に「受付中」と書かない。期限を併記し、期限後は JS（data-rb-until）で「過ぎました」に切り替える
            end = r.get("apply_end")
            state = (f'<span data-rb-open>（応募期限 {_e(_apply_deadline(end)) if end else "未確認"}まで・生成時点の判定）</span>'
                     f'<span data-rb-expired hidden>（応募期限を過ぎました）</span>')
            attrs = f' data-rb-card data-rb-until="{_e(str(end or ""))}"'
        else:
            state = "" if rejected else f'（{_e(r.get("accept_label") or "")}）'
            attrs = ""
        pcl = "" if rejected or not r.get("price_class_label") else f'（{_e(r["price_class_label"])}）'
        return (f'<li{attrs}>{_e(r.get("shop") or "")}・{_e(name)}{_e(_rb_unbound(r))}{"・" + price if price else ""}{pcl}'
                f'{state}— {_e(r.get("reason") or "")}{("・" + _e(_rb_ann(r, ann))) if _rb_ann(r, ann) else ""}・確認 {_e(_short(r.get("verified_at")))}・{_rb_link(r.get("source_url"))}</li>')
    # OPEN（応募期間中）で利益を計算できない行は、「過去の参考情報」に混ぜず別の小見出しにする
    open_refs = [r for r in refs if r.get("kind") != "REJECTED" and r.get("accept_state") == "OPEN"]
    past_refs = [r for r in refs if r not in open_refs]
    html = ""
    if open_refs:
        until = _earliest_until(str(r.get("apply_end") or "").strip() for r in open_refs)       # 各行の _item と同じく apply_end の原値。節の見出し・本文は最も早い期限で切り替える
        head = f'応募受付中だが条件付き利益を計算できない（{len(open_refs)}）'
        body = '応募期間中の価格ですが、買取価格の不足・価格の食い違いなど（理由は各行）で利益を計算できません。実行できる価格ではありません。'
        if until:         # 件数は再計算しない（fail-closed）。期限後は「受付中」と書かず、下の行で再確認させる
            head = (f'<span data-rb-card data-rb-until="{_e(until)}"><span data-rb-open>{_e(head)}</span>'
                    f'<span data-rb-expired hidden>{RB_EXPIRED_SECTION_HEAD}（{len(open_refs)}）</span></span>')
            body = (f'<span data-rb-card data-rb-until="{_e(until)}"><span data-rb-open>{_e(body)}</span>'
                    f'<span data-rb-expired hidden>{RB_EXPIRED_SECTION_BODY}</span></span>')
        else:
            head = _e(head) + "（生成時点）"
        html += (f'<details class="note" open id="retailer-open-refs"><summary>{head}</summary>'
                 f'<p class="mut">{body}</p>'
                 f'<ul>{"".join(_item(r) for r in open_refs)}</ul></details>')
    if past_refs:
        html += (f'<details class="note"><summary>過去の参考情報（販売店の BOX 価格・利益は出しません）（{len(past_refs)}）</summary>'
                 '<p class="mut">応募が終わった・当選者のみ・期間外・不明の価格です。実行できる価格ではないので、利益には使いません。</p>'
                 f'<ul>{"".join(_item(r) for r in past_refs)}</ul></details>')
    return html


_MISMATCH_KIND = {"PRICE_MISMATCH": "価格", "SCHEDULE_MISMATCH": "日程", "COLLECTOR_NOT_OPEN": "受付状態"}


def _rb_mismatch(errors: list) -> str:
    """台帳（人手の確認値）と自動取得の食い違い。0 件なら出さない。1 件以上で、店・商品・種別・双方の値と扱いを併記する。"""
    errs = [e for e in errors if isinstance(e, dict) and e.get("kind") in _MISMATCH_KIND]
    if not errs:
        return ""
    def _item(e: dict) -> str:
        k = e["kind"]
        name = e.get("display_name") or (f'商品ID: {e.get("product_id")}' if e.get("product_id") else "商品不明")
        if k == "PRICE_MISMATCH":
            vals = f'台帳 {_yen(e["manual_price"])}／自動取得 {_yen(e["collector_price"])}' if isinstance(e.get("manual_price"), int) and isinstance(e.get("collector_price"), int) else ""
            if e.get("resolution") == "ledger_kept_unit_unknown":
                note = "単位が確認できない自動取得の価格と食い違っています。台帳の値を維持しました。公式ページで確認してください"
            else:
                note = "利益計算に使わず参考止まりにしました。公式ページで確認してください"
        elif k == "SCHEDULE_MISMATCH":
            vals = f'{_e(e.get("field") or "")}: 台帳 {_e(e.get("manual_value") or "")}／自動取得 {_e(e.get("collector_value") or "")}'
            note = "自動取得の値を採用しました。公式ページで確認してください"
        else:
            vals = ""
            note = "台帳の値を維持しました。公式ページで確認してください"
        return (f'<li>{_e(e.get("shop") or "")}・{_e(name)}・{_MISMATCH_KIND[k]}{"・" + vals if vals else ""} — {note}'
                f'（{_e(e.get("message") or "")}）・{_rb_link(e.get("source_url"))}</li>')
    return (f'<details class="note" open id="retailer-mismatch"><summary>台帳と自動取得の食い違い（{len(errs)} 件）</summary>'
            '<p class="mut">人が確認した台帳の値と、自動取得（collector）の値が合わない行です。誤読の可能性があるため、必ず公式ページで確認してください。</p>'
            f'<ul>{"".join(_item(e) for e in errs)}</ul></details>')


def _cal_item(c: dict) -> str:
    t0 = show_time(c["time"], c["verified"])                    # 00:00 は日付のみ（未確認行・補完の 0 時を時刻に見せない）
    if t0:
        t = f'<span title="{_e(c["time"])}">{_e(t0)}</span> '
    else:                                                       # 時刻が無い項目は「日付のみ」と分かるよう日付を出す
        t = ''                                                  # 日付は日付見出し・日の枠が示す。行ごとに「日付のみ」を繰り返さない（注記は一覧の先頭に 1 回）
    store = c["store"] if not pv._is_enum_like(c["store"], "") else ""                       # 列挙値（POKEMON_CENTER_ONLINE 等）は副表示にも出さない
    where = " ".join(x for x in (c["retailer"], store) if x)
    return (f'<li><span class="k k-{c["kind"]}">{_e(CAL_SHORT[c["kind"]])}</span> {t}<b>{_e(c["label"])}</b>'
            f'{" <span class=mut>" + _e(where) + "</span>" if where else ""}{"" if c["verified"] else " <span class=mut>[未確認]</span>"}</li>')


def _cal_list(cal: list) -> str:
    out, cur = ['<p class="mut">時刻が書かれていない項目は日付のみです（時刻は補っていません）。</p>'], None
    for c in cal:
        if c["date"] != cur:
            if cur is not None:
                out.append("</ul>")
            cur = c["date"]
            out.append(f'<h3>{_e(cur[5:].replace("-", "/"))}（{_e(_wd(cur))}）</h3><ul>')
        out.append(_cal_item(c))
    out.append("</ul>")
    return "".join(out)


def _cal_grid(cal: list, today: str) -> str:
    by_day: dict = {}
    for c in cal:
        by_day.setdefault(c["date"], []).append(c)
    months = sorted({d[:7] for d in by_day})[:3]
    out = []
    for ym in months:
        y, m = int(ym[:4]), int(ym[5:7])
        cells = "".join(f'<div class="wh">{w}</div>' for w in "日月火水木金土")
        skipping = False
        for week in _cal.Calendar(firstweekday=6).monthdayscalendar(y, m):
            keys = [f"{y:04d}-{m:02d}-{d:02d}" for d in week if d]
            if all(k < today for k in keys):                         # 今日より前だけの週は出さない（データは今日以降だけ）
                continue
            if not any(k in by_day or k == today for k in keys):     # 予定が無く今日も含まない週は畳む（連続する空週は 1 行にまとめる）
                if not skipping:
                    cells += '<div class="gap">予定のない週は省略しています</div>'
                    skipping = True
                continue
            skipping = False
            for d in week:
                if not d:
                    cells += '<div class="off"></div>'
                    continue
                key = f"{y:04d}-{m:02d}-{d:02d}"
                items = by_day.get(key, [])
                cls = ' class="today"' if key == today else ""
                if not items:
                    cells += f'<div{cls}><span class="d">{d}</span></div>'
                    continue
                kinds: dict = {}
                for c in items:
                    kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
                chips = " ".join(f'<span class="k k-{k}">{_e(CAL_SHORT[k])}{n}</span>' for k, n in kinds.items())
                dots = "".join(f'<i class="dot k-{k}"></i>' for k in kinds)                     # モバイルは日付＋点だけ（種別は開くと分かる）
                aria = f"{m}/{d} " + " ".join(f"{CAL_SHORT[k]}{n}" for k, n in kinds.items())
                cells += (f'<div{cls}><details><summary aria-label="{_e(aria)}"><span class="d">{d}</span>{chips}{dots}</summary>'
                          f'<ul>{"".join(_cal_item(c) for c in items)}</ul></details></div>')
        out.append(f'<div class="cal-month"><h3>{y}年{m}月</h3><div class="cg">{cells}</div></div>')
    return "".join(out)


def _agenda(cal: list, today: str) -> str:
    try:
        end = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
    except ValueError:
        return ""
    soon = [c for c in cal if today <= c["date"] <= end]
    if not soon:
        return '<div class="agenda"><p class="empty">今後 7 日に予定されている応募開始・締切・当選発表・発売は確認できていません。下の「日付順の一覧」で先の予定を見られます。</p></div>'
    return f'<div class="agenda"><h3>今後 7 日の予定</h3>{_cal_list(soon)}</div>'


def _calendar(cal: list, today: str) -> str:
    if not cal:
        return '<p class="empty">これから先の日程は確認できていません。新しい抽選や発売日が公式に出ると、ここに並びます。</p>'
    legend = " ".join(f'<span class="k k-{k}">{_e(v)}</span>' for k, v in CAL_SHORT.items())
    return (f'<p class="mut">{legend}</p><div class="cal-grid">{_cal_grid(cal, today)}</div>{_agenda(cal, today)}'
            f'<details class="note callist"><summary>日付順の一覧で見る（{len(cal)} 件）</summary>{_cal_list(cal)}</details>')


def render(hub: dict, *, generated_label: Optional[str] = None) -> str:
    """hub は build_hub の結果。壊れた hub でも例外にしない（空のページを返す）。"""
    hub = hub if isinstance(hub, dict) else build_hub(None, None, None)
    s = hub["stats"]
    ck = hub["checked_at"]
    products = hub["products"]
    yr = str(hub["today"])[:4]
    pidx = {(p["tcg"], p["product_id"]): f"p{i}" for i, p in enumerate(products)}
    rate = "—" if s["bind_rate"] is None else f'{round(s["bind_rate"] * 100)}%'
    rate_live = "—" if s["bind_rate_live"] is None else f'{round(s["bind_rate_live"] * 100)}%'
    _evs = [v["ev"] for v in hub["events"]]
    retailers = sorted({k: pv.retailer_filter_label(k, _evs) for k in {(e.get("retailer") or "") for e in _evs} if k}.items())   # 同じ小売は 1 つ（代表ラベルを日本語名に固定）
    regions = sorted({v["ev"].get("prefecture") for v in hub["events"] if v["ev"].get("prefecture")})
    opt = lambda items: "".join(f'<option value="{_e(k)}">{_e(lbl)}</option>' for k, lbl in items)

    flagmap: dict = {}
    for v in hub["today_list"]:
        flagmap.setdefault(id(v), set()).add("today")
    for v in hub["deadline_today"]:
        flagmap.setdefault(id(v), set()).add("deadline")
    for v in hub["new"]:
        flagmap.setdefault(id(v), set()).add("new")
    def _rank(v):                                               # 今日締切 → 受付中・締切間近 → 近日開始 → その他（結果待ち等）
        if "deadline" in flagmap.get(id(v), ()):
            return 0
        return 1 if v["status"] in st.APPLYING else 2 if v["status"] == ls.L_UPCOMING else 3 + _ST_ORDER.get(v["status"], 99)
    ordered = sorted(hub["events"], key=lambda v: (_rank(v), v["end"]["date"] or "9999", v["end"]["time"] or "99"))
    live = [v for v in ordered if v["status"] != ls.L_ENDED]
    ended = [v for v in ordered if v["status"] == ls.L_ENDED]

    filters = (
        '<form id="flt" class="filters" onsubmit="return false">'
        f'<label>TCG<select name="tcg"><option value="">すべて</option>{opt(TCG_LABEL.items())}</select></label>'
        f'<label>商品<select name="product"><option value="">すべて</option>{opt((f"p{i}", p["name"]) for i, p in enumerate(products))}'
        f'<option value="none">商品に紐付けできていない抽選</option></select></label>'
        f'<label>店舗<select name="retailer"><option value="">すべて</option>{opt(retailers)}</select></label>'
        f'<label>地域<select name="region"><option value="">すべて</option>{opt((r, r) for r in regions)}<option value="unknown">地域の記載なし</option></select></label>'
        '<label>状態<select name="state"><option value="">すべて</option><option value="open">受付中</option>'
        '<option value="ending">締切間近</option><option value="upcoming">近日開始</option>'
        '<option value="today">今日応募可能</option><option value="deadline">今日締切</option><option value="new">新着</option></select></label></form>')

    opps = hub.get("opportunities") or []
    card_list = hub.get("cards")
    if card_list is None:                                       # build_hub 以外で作った hub でも落とさない（同じ統合規則で作り直す）
        card_list = pv.build_cards(products, opps)
    live_evs = [v for v in hub["events"] if v["status"] != ls.L_ENDED]
    u_apply = _earliest_until(_until_iso(v["end"]) for v in live_evs if v["status"] in st.APPLYING)
    u_up = _earliest_until(_until_iso(v["end"]) for v in live_evs if v["status"] == ls.L_UPCOMING)
    u_today = _earliest_until(_until_iso(v["end"]) for v in hub["deadline_today"])

    def _sum_tile(lbl, val, tone, until=""):
        if not until:
            return f'<div class="c {tone}"><b>{_e(val)}</b>{_e(lbl)}</div>'
        # 件数は再計算しない。最も早い締切を過ぎたら、生成時点の件数だと断って再確認を促す（fail-closed）
        return (f'<div class="c {tone}" data-rb-card data-rb-until="{_e(until)}"><span data-rb-open><b>{_e(val)}</b>{_e(lbl)}（生成時点）</span>'
                f'<span data-rb-expired hidden><b>{_e(val)}</b>（生成時点）→ {RB_EXPIRED_GROUP}</span></div>')
    sum_cards = "".join(_sum_tile(*t) for t in (
        ("受付中（締切間近・未確認を含む）", s["applying"], "info", u_apply), ("今日締切", s["deadline_today"], "danger" if s["deadline_today"] else "", u_today),
        ("近日開始", s["upcoming"], "info", u_up), ("商品数（商品カード）", len(card_list), "")))
    count_note = ('<details class="note" id="count-def"><summary>件数の数え方</summary><p class="mut">件数は未確認の抽選も含めて 1 件ずつ数えます。'
                  'HOME の件数とは、まとめ方（商品・店舗ごと）や未確認の扱いが違い、一致しないことがあります。</p></details>')
    low = (f'<div class="box warn"><b>商品に紐付けできた抽選は {_e(rate if rate == rate_live else rate + "、終了を除くと " + rate_live)} です。</b>残りは表に「未紐付け」と出しています。'
           '<details><summary>詳しく</summary>商品名が似ているだけでは商品に結ばず、紐付けできていない抽選は推測で商品に結んでいません。</details></div>') if (s["bind_rate"] is not None and s["bind_rate"] < 0.5) else ""

    gen = _e(generated_label or hub["now"])
    stale_banner = ""
    try:                                                       # 元の抽選データが古いときは警告（収集が止まっても新鮮に見せない）
        from datetime import date as _date
        gd = _date.fromisoformat(str(ck["lotteries_generated_at"] or "")[:10])
        nd = _date.fromisoformat(str(hub["now"])[:10])
        if (nd - gd).days >= 2:
            stale_banner = f'<div class="box warn"><b>抽選データの取得が {(nd - gd).days} 日前です（取得 {_e(ck["lotteries_generated_at"])}）。</b>最新の状況ではない可能性があります。</div>'
    except (ValueError, TypeError):
        stale_banner = '<div class="box warn"><b>抽選データの取得日時が確認できません。</b>最新の状況ではない可能性があります。</div>'

    notes = (
        '<details class="note"><summary>このページの見方・注意</summary>'
        f'<p><b>この一覧の「受付中」「今日締切」などの状態は {gen} 時点のものです。</b>'
        'このページは 1 日 1 回の更新で、開いている間は進みません。締切を過ぎていないか、応募の前に必ず公式ページで確認してください。</p>'
        '<p class="mut">応募優先度: S=締切間近で応募ページまで確認済み／A=受付中で商品に紐付け済み／B=その他の受付中・開始前／'
        'WATCH=日程未確認・未確認・商品に紐付けできていないもの。利益や点数ではなく、既存の判定を並べたものです。</p>'
        '<p class="mut">色: 青=受付中・近日開始／赤=締切間近／橙=結果待ち・様子見・未確認／灰=終了。'
        'ポ・OP の色は TCG の種類を表すだけで、状態とは関係ありません。</p>'
        '<p class="mut">利益: 買取店自身のページの価格（同一商品・同じ単位・新品未開封・新鮮なもの）と公式の定価が<b>そろった商品だけ</b>、純利益などの利益を出します。'
        '公式が BOX 価格を公表していない商品の BOX 買取は、利益を<b>算出前</b>にしています（パック価格から BOX の定価は作りません）。順位は利益では決めません。'
        '日付が「日付のみ」のものは、公式が時刻を出していません（時刻を補っていません）。</p></details>')

    if live:
        live_html = _table(live, pidx, yr, flagmap, "lt-live")
    else:
        live_html = ('<p class="empty">いま受付中・開始前・結果待ちの抽選・予約は確認できていません。'
                     '近日の予定は<a href="#calendar">カレンダー</a>、終了した抽選は下の「終了した抽選」を見てください。</p><div id="lt-live"></div>')
    ended_html = (f'<details class="note"><summary>終了した抽選（{len(ended)} 件）</summary>{_table(ended, pidx, yr, flagmap, "lt-ended")}</details>'
                  if ended else "")
    cfg = _CFG()
    hs = hub.get("stats") or {}
    by_tcg = hs.get("unbound_applying_by_tcg")
    unbound_total = int(hs.get("unbound_applying") or 0)
    rbs = hub.get("retailer_opportunities") or []
    rb_open_by: dict = {}                    # (tcg, product_id) → 応募受付中（OPEN）の販売店行（台帳＋collector 由来。不採用の行は除く）
    for r in [o.get("retailer") for o in rbs if isinstance(o, dict)] + [r for r in (hub.get("retailer_references") or []) if isinstance(r, dict) and r.get("kind") != "REJECTED"]:
        if isinstance(r, dict) and r.get("accept_state") == "OPEN" and r.get("product_id"):
            rb_open_by.setdefault((r.get("tcg"), r["product_id"]), []).append(r)
    ann = _announce_index(hub.get("events"))
    cards = []
    for n, c in enumerate(card_list):
        pk = pidx.get(c["key"])
        # 未紐付けの受付中は、そのカードの TCG のものだけ数える（TCG が読めない告知は全 TCG に数える）。集計が無い hub は全体の件数
        ub = unbound_total if not isinstance(by_tcg, dict) else int(by_tcg.get(c["tcg"], 0)) + int(by_tcg.get("", 0))
        cards.append(_card(c, pk or f"c{n}", pk, yr, cfg, ub, rb_open_by.get(c["key"]), ann))
    n_calc = sum(1 for c in card_list if c["profit"].get("net_profit") is not None)
    rb_html = (
        f'<h2 id="retailer-box">販売店の BOX 価格による条件付きの利益（{len(rbs)}）</h2>'
        '<p class="mut">メーカー公式定価ではなく、<b>販売店のページに載っている BOX 価格</b>です。抽選に当選した場合にだけ購入できるので「条件付き」で、購入推奨・今すぐ行動には入れません。'
        '応募期間中の価格だけを計算し、応募終了・当選者のみの価格は下の参考情報に留めます。パック価格×入数で BOX 価格を作ることはしません。</p>'
        + (f'<div class="pgrid">{"".join(_rb_card(o, i, ann) for i, o in enumerate(rbs))}</div>' if rbs else
           '<p class="empty">いま応募期間中で、利益を計算できる販売店の BOX 価格はありません。</p>')
        + _rb_refs(hub.get("retailer_references") or [], ann)
        + _rb_mismatch(hub.get("retailer_validation_errors") or []))
    opp_html = (
        f'<h2 id="opportunities">商品と利益（{len(card_list)}）</h2>'
        f'<p class="mut">1 商品 1 枚。公式定価で買って、買取店で売ったときの利益を、買取店の最高額の 1 店で見せます（利益が計算できる商品 {n_calc}／'
        f'生成時点の内訳: 黒字 {s["opportunities_profit"]}・様子見 {s["opportunities_watch"]}）。'
        '並び: 利益が計算できる商品（利益の大きい順）→ 応募受付中・締切間近の抽選がある商品（締切が近い順）→ その他（発売日が新しい順）。'
        '表示時に買取価格が古ければ、買取と利益は消えて「価格再確認待ち」になります。</p>'
        '<p class="mut" id="img-credit">商品画像はポケモンカードゲーム公式サイトの画像を参照表示しています。画像の権利は各権利者に帰属します。'
        'ONE PIECE カードは公式に商品固有の画像がないため、商品画像はありません。</p>'
        '<details class="note"><summary>見方（黒字・様子見・確認待ち・差額）</summary>'
        '<p class="mut">利益 = 買取価格 − 公式定価（費用の根拠がある基準店の価格で計算。交通費・時間は含みません）。'
        '条件（すべて）: 公式の定価（同じ販売単位）／新品未開封の買取価格が実行可能／JAN で同一商品／価格が新しい。外れ値の疑い・買取が停止中・受付状態が不明な価格は利益に使いません。</p>'
        '<p class="mut">黒字＝純利益が正で、投資利益率が既存の基準（30%）以上。様子見＝黒字でも投資利益率がそれ未満、または赤字（少額の黒字を強い推奨にしません）。'
        '確認待ち＝表示時点で価格の取得から 8 時間を超えている（金額は出しません）。</p>'
        '<p class="mut">最高買取の店が利益の基準にした店と違うときは、差額（最高買取 − 定価）を別行で出します。最高買取の店は送料・費用が未確認なので、利益ではなく差額です。'
        '「今すぐ買える」ことは示しません。購入できる経路は別に確認してください。</p></details>'
        + (f'<div class="pgrid">{"".join(cards)}</div>' if cards else
           '<p class="empty">商品に束ねられた抽選も、利益を計算できる商品もまだありません。公式の商品名と一致した抽選が出ると、ここに商品カードが並びます。</p>')
    )

    body = (
        f'<div class="head"><h1>TCG 抽選ハブ</h1><span class="snap">状態は {gen} の画面生成時点のものです（情報の確認日は下の「確認日」）。応募前に必ず公式ページで確認してください。</span></div>'
        '<p class="mut">ポケモンカード・ONE PIECE カードの公式の抽選・予約をまとめています。自動応募はしません。</p>'
        f'{notes}{stale_banner}<div class="sum">{sum_cards}</div>{count_note}'
        '<nav class="jump" aria-label="ページ内の移動"><a href="#opportunities">商品・利益</a><a href="#lottery">抽選一覧</a>'
        '<a href="#calendar">カレンダー</a><a href="#checked">確認日</a></nav>'
        f'{low}{opp_html}{rb_html}<h2 id="products">商品の束ね方（商品 {s["products"]}）</h2>'
        '<details class="note"><summary>商品の束ね方</summary><p class="mut">商品に束ねたのは、商品 ID まで一致（exact）した抽選だけです。ポケモンカードは公式の商品一覧と照合しています。'
        'ONE PIECE は公式の商品ページで確認できた商品だけを商品一覧に入れています（確認した発売日・価格だけ。画像は出しません）。商品コード（EB-05 等）が一致するか、商品名の本体が完全一致して候補が 1 件のときだけ束ねます。部分一致だけでは束ねません。</p></details>'
        f'<h2 id="lottery">抽選一覧（{len(live)}）</h2>{filters}'
        '<p class="mut">日付（例 <b>11/22</b>）だけのものは、公式が時刻を出していない「日付のみ」の項目です。</p>'
        '<p class="mut" id="cnt" aria-live="polite"></p>'
        '<p class="empty" id="none" hidden>条件に合う抽選がありません。絞り込みを「すべて」に戻すか、条件を変えてください。</p>'
        f'{live_html}{ended_html}'
        f'<h2 id="calendar">カレンダー（{s["calendar"]}）</h2>'
        '<p class="mut">今日以降の応募開始・締切・当選発表・購入期間・発売日。日の枠を開くと中身が見えます。</p>'
        f'{_calendar(hub["calendar"], hub["today"])}'
        f'<h2 id="checked">確認日</h2><dl class="kv"><dt>抽選データ</dt><dd>取得 {_e(_short(ck["lotteries_generated_at"]))}／判定 {_e(_short(ck["lotteries_evaluated_at"]))}</dd>'
        f'<dt>商品一覧</dt><dd>{_e(_short(ck["registry_generated_at"]))}</dd><dt>定価</dt><dd>{_e(_short(ck["msrp_generated_at"]))}</dd>'
        f'<dt>画面生成</dt><dd>{gen}（状態を導出した時点。情報の確認時刻ではありません）</dd></dl>'
        '<footer>状態は生成時点のものです。応募・購入の前に必ず公式ページで確認してください。本ページは購入や利益を保証しません。</footer>')
    legacy = _shared.legacy_css()
    nav = _shared.site_nav("tcg")
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>TCG 抽選ハブ | プレ値速報</title><meta name="robots" content="index,follow">'
            f'<meta name="tcg-source-generated-at" content="{_e(ck["lotteries_generated_at"] or "")}"><style>{legacy}{CSS}</style></head>'
            f'<body>{nav}<main>{body}</main><script>{JS}{rf.JS_FRESHNESS}{JS_RB}</script></body></html>')


def render_from_json(lotteries, registry, msrp, now: Optional[datetime] = None, buyback=None) -> str:
    """公開済み JSON の辞書から直接ページを作る。"""
    now = (now or now_jst()).astimezone(JST)
    return render(build_hub(lotteries, registry, msrp, now, buyback), generated_label=now.strftime("%Y-%m-%d %H:%M JST"))
