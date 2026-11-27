# -*- coding: utf-8 -*-
"""TCG の公開ページ（2 ページ）の描画。入力は src.tcg.hub.product_view.build_hub の結果。

- docs/tcg.html（render）= 商品と利益: 締切が近い抽選の帯（最大 3 行）→ 商品から探す（画像の格子）→ 利益ランキング → 商品ごとのカード → 販売店の BOX 価格（条件付き）。
- docs/tcg-lottery.html（render_lottery）= 抽選: 抽選カレンダー（上部・コンパクト）→ 抽選一覧（締切が近い順。終了は閉じた details）。
- 白背景の固定（data-theme="light"）。色・文字・余白は TCG の CSS 内の --tc-* だけで持つ（共通 CSS は変えない）。
- 文章の説明・注釈は出さない。状態は短いラベル（価格再確認待ち・条件付き・確認待ち・当選者のみ・未確認・—）で示し、但し書きは最下部の 1 か所だけ。
- 品質の規則は従来どおり: 買取由来の金額は data-fb-live（最初は hidden・JS が FRESH を確かめたときだけ表示）の中だけ・各 live の直後に同じ group の stale。
  group は取得時刻が同じ要素だけ（最高買取+差額 = {g}-b／利益+状態バッジ = {g}-p／他店は行ごと {g}-oN）。締切のある表示は JS_RB で期限後に切り替える。
  「公式ページで応募する」は応募 URL があり、受付中・締切間近・確認済み・日程の食い違いなしのときだけ。それ以外は告知へのリンクだけ。
- 画像は公式サイト（ポケカ = pokemon-card.com・ONE PIECE = onepiece-cardgame.com）の https だけ。読み込み失敗時は定数のプレースホルダに切り替える。
- すべての文字は HTML エスケープ。リンクは https の公式ドメインだけ。
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
from src.content.ui import product_image as _pi      # 公式画像の参照表示と、代わりの画像（SVG）

PAGE_PRODUCTS = "tcg.html"
PAGE_LOTTERY = "tcg-lottery.html"

TCG_LABEL = {"POKEMON": "ポケモンカード", "ONE_PIECE": "ONE PIECE カード"}
TCG_SHORT = {"POKEMON": "ポケカ", "ONE_PIECE": "ワンピ"}
TCG_INITIAL = {"POKEMON": ("ポ", "pokemon"), "ONE_PIECE": ("OP", "onepiece")}
CANON_LABEL = {pv.C_MASTER: "商品マスタと一致", pv.C_DISCOVERED: "イベントから発見（商品マスタ外）",
               pv.C_AMBIGUOUS: "商品が複数に当てはまる", pv.C_UNMATCHED: "商品に紐付けできていない"}
PRIO_LABEL = {st.P_S: "S 今すぐ", st.P_A: "A 応募したい", st.P_B: "B 余裕あり", st.P_WATCH: "WATCH 要確認"}
CHANNEL_LABEL = {au.CH_WEB_OFFICIAL: "公式の応募ページ", au.CH_EXTERNAL_FORM: "外部の応募フォーム", au.CH_APP: "アプリ",
                 au.CH_SNS: "SNS（フォロー＆リポスト）", au.CH_MEMBER_LOGIN: "会員ログイン", au.CH_STORE_COUNTER: "店頭",
                 au.CH_UNKNOWN: "応募経路は未確認"}
CHANNEL_SHORT = {au.CH_WEB_OFFICIAL: "公式Web応募", au.CH_EXTERNAL_FORM: "Webフォーム", au.CH_APP: "アプリ応募", au.CH_SNS: "SNS応募",
                 au.CH_MEMBER_LOGIN: "会員サイト応募", au.CH_STORE_COUNTER: "店頭応募", au.CH_UNKNOWN: ""}
_ONLINE = (au.CH_WEB_OFFICIAL, au.CH_EXTERNAL_FORM, au.CH_APP, au.CH_SNS, au.CH_MEMBER_LOGIN)
REQ_LABEL = {au.R_MEMBERSHIP: "会員", au.R_APP: "アプリ", au.R_PURCHASE_HISTORY: "購入履歴", au.R_IDENTITY: "本人確認",
             au.R_STORE_PICKUP: "店頭受取", au.R_SNS: "SNS"}
KIND_LABEL = {"PREORDER": "予約", "STORE_LOTTERY": "店舗の抽選", "APP_LOTTERY": "アプリ抽選", "WEB_LOTTERY": "WEB 抽選", "LOTTERY": "抽選"}
PTYPE_LABEL = {"BOOSTER_BOX": "拡張パック", "STARTER_DECK": "スターター", "CONSTRUCTED_DECK": "構築済みデッキ",
               "SPECIAL_SET": "スペシャルセット", "PREMIUM_COLLECTION": "プレミアムコレクション", "OTHER": "その他"}
UNIT_LABEL = {"BOX": "BOX", "PACK": "パック", "SET": "セット", "DECK": "デッキ"}
CAL_SHORT = {pv.K_START: "開始", pv.K_END: "締切", pv.K_RESULT: "当選", pv.K_PURCHASE_START: "購入開始",
             pv.K_PURCHASE_END: "購入終了", pv.K_RELEASE: "発売"}
CAL_TINY = {pv.K_START: "始", pv.K_END: "締", pv.K_RESULT: "当", pv.K_RELEASE: "発"}
CAL_KINDS = (pv.K_START, pv.K_END, pv.K_RESULT, pv.K_RELEASE)      # カレンダーに出す種類（購入開始・購入終了は出さない。発売は控えめな印）
WEEKDAY = "月火水木金土日"
PRODUCT_HOSTS = ("pokemon-card.com",)          # 商品の公式ページとして許可するドメイン（サブドメイン可）
IMG_W, IMG_H = 320, 240
_ST_ORDER = {s: i for i, s in enumerate(st._AGG_ORDER)}

# 状態の色（受付中・近日開始=青 / 締切間近=赤 / 様子見・結果待ち=橙 / 終了=灰）。緑は利益のためだけに使う。
_TONE = {ls.L_OPEN: "info", ls.L_UPCOMING: "info", ls.L_ENDING_SOON: "danger", ls.L_ENDED: "gray"}

FOOT_NOTE = "価格・状態は確認時点のものです。応募・購入の前に公式ページで確認してください。"
IMG_CREDIT = _pi.IMG_CREDIT                              # 出典表記（新UIと同じ文言）

CSS = """
:root{--tc-bg:#fff;--tc-surface:#f4f5f7;--tc-line:#e2e5ea;--tc-fg:#1a1d23;--tc-mut:#5b6270;--tc-link:#1f5fae;
--tc-cta:#2563eb;--tc-cta-edge:#1d4ed8;--tc-profit:#0f7a3d;--tc-profit-bg:#eaf6ee;--tc-loss:#c0262d;--tc-loss-bg:#fdecec;
--tc-urgent:#c0262d;--tc-open:#1f5fae;--tc-soon:#a34f00;--tc-soon-bg:#fff3e3;--tc-unk:#4a5160;--tc-unk-bg:#eef0f3;
--tc-s1:4px;--tc-s2:8px;--tc-s3:12px;--tc-s4:16px;--tc-s5:24px;--tc-s6:40px;--tc-r-card:8px;--tc-r-btn:6px;--tc-r-badge:4px;
--tc-f-h1:20px;--tc-f-h2:17px;--tc-f-name:15px;--tc-f-amt:20px;--tc-f-num:15px;--tc-f-body:14px;--tc-f-sub:12px}
html{color-scheme:light}
html body{background:var(--tc-bg);color:var(--tc-fg)}
*{box-sizing:border-box}body{overflow-wrap:anywhere;margin:0;font-size:var(--tc-f-body);line-height:1.55}
main{max-width:1080px;margin:0 auto;padding:var(--tc-s3) var(--tc-s4) var(--tc-s6)}
a{color:var(--tc-link)}a.nm,.tc-id h3,.rk td.nm a{color:var(--tc-fg);text-decoration:none}a.nm:hover,.rk td.nm a:hover{text-decoration:underline}
h1{font-size:var(--tc-f-h1);line-height:1.35;margin:var(--tc-s2) 0 0}
h2{font-size:var(--tc-f-h2);margin:var(--tc-s6) 0 var(--tc-s3);scroll-margin-top:var(--jump-offset)}
h3{font-size:var(--tc-f-name);margin:0}
.mut{color:var(--tc-mut);font-size:var(--tc-f-sub)}
.ph{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 var(--tc-s3)}.upd{margin:0;color:var(--tc-mut);font-size:var(--tc-f-sub);font-variant-numeric:tabular-nums}
.warnbar{margin:var(--tc-s2) 0;padding:var(--tc-s2) var(--tc-s3);background:var(--tc-soon-bg);color:var(--tc-soon);font-size:var(--tc-f-sub)}
/* TCG 内のナビ: 1 段目 = ページの切り替え、2 段目 = ページ内の移動。固定。各 44px 以上 */
nav.jump{position:sticky;top:0;z-index:5;margin:var(--tc-s2) calc(-1*var(--tc-s4)) 0;padding:0 var(--tc-s4);background:var(--tc-bg);border-bottom:1px solid var(--tc-line)}
nav.jump .jt,nav.jump .js{display:flex;overflow-x:auto;scrollbar-width:none}
nav.jump a{flex:none;display:inline-flex;align-items:center;min-height:44px;padding:0 var(--tc-s3);color:var(--tc-fg);text-decoration:none;white-space:nowrap}
nav.jump .jt a{font-size:15px;border-bottom:3px solid transparent}nav.jump .jt a[aria-current=page]{font-weight:700;border-bottom-color:var(--tc-fg)}
nav.jump .js{border-top:1px solid var(--tc-line)}nav.jump .js a{min-height:40px;padding:0 10px;font-size:13px;color:var(--tc-mut)}
:root{--jump-offset:104px}
@media(max-width:767px){nav.jump{top:53px}:root{--jump-offset:160px}}
/* バッジ・ボタン（ピルにしない・影なし） */
.sb{display:inline-block;max-width:100%;border-radius:var(--tc-r-badge);padding:0 6px;font-size:var(--tc-f-sub);font-weight:700;line-height:1.7;white-space:normal;overflow-wrap:anywhere;margin:0 4px 2px 0;color:var(--tc-unk);background:var(--tc-unk-bg)}
.sb.info{color:#fff;background:var(--tc-open)}.sb.danger{color:#fff;background:var(--tc-urgent)}
.sb.warn{color:var(--tc-soon);background:var(--tc-soon-bg)}.sb.gray{color:var(--tc-mut);background:var(--tc-surface)}.sb.out{color:var(--tc-unk);background:var(--tc-unk-bg)}
.sb.pf{color:var(--tc-profit);background:var(--tc-profit-bg)}.sb.ls{color:var(--tc-loss);background:var(--tc-loss-bg)}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 var(--tc-s4);border:1px solid var(--tc-line);border-radius:var(--tc-r-btn);background:var(--tc-bg);color:var(--tc-link);font-weight:700;font-size:var(--tc-f-body);text-decoration:none;white-space:nowrap}
.btn.cta{background:var(--tc-cta);border-color:var(--tc-cta);border-bottom:2px solid var(--tc-cta-edge);color:#fff}
.btn.cta.ann{background:var(--tc-bg);color:var(--tc-cta);border:1px solid var(--tc-cta)}
a.lk{display:inline-flex;align-items:center;min-height:44px;color:var(--tc-mut);font-size:var(--tc-f-sub)}
.left{color:var(--tc-urgent);font-weight:700;margin-left:6px}
.tcgtag{color:var(--tc-mut);font-size:var(--tc-f-sub);margin-right:6px;font-weight:400}
.empty{color:var(--tc-mut);margin:var(--tc-s2) 0}.empty[hidden]{display:none}
[data-fb-live][hidden],[data-fb-stale][hidden],[data-js-only][hidden],[data-nojs][hidden],[data-rk][hidden],[data-cnt-hide][hidden],.unb[hidden],.lt-tabs a[hidden]{display:none!important}
.nojs{font-size:var(--tc-f-sub);color:var(--tc-mut)}li.sr[hidden],.soon ul[hidden],[data-soon-expired][hidden],[data-soon-none][hidden]{display:none!important}
.cg .past .k{background:var(--tc-surface);color:var(--tc-mut);border-color:transparent}.ev.rb-expired{opacity:.55}.rb-expired [data-fb-live],.rb-expired [data-fb-stale],.rb-expired [data-rb-open]{display:none!important}[data-rb-expired][hidden]{display:none!important}
/* 画像（白地に contain） */
.pimg{flex:none;width:72px;height:54px;display:flex;align-items:center;justify-content:center;background:#fff;color:var(--tc-mut);border:1px solid var(--tc-line);border-radius:var(--tc-r-badge);overflow:hidden}
.pimg img,.pimg svg{width:100%;height:100%;object-fit:contain;display:block}
.pimg>.phs{display:block;width:100%;height:100%}.pimg>.phs[hidden]{display:none}
/* 締切が近い抽選の帯 */
.soon{margin:var(--tc-s4) 0 0;border-top:2px solid var(--tc-fg)}
.soon-h{display:flex;justify-content:space-between;align-items:center;gap:var(--tc-s2)}.soon-h h2{margin:var(--tc-s2) 0}
.soon-h a{display:inline-flex;align-items:center;min-height:44px;font-size:var(--tc-f-body)}
.soon ul{list-style:none;margin:0;padding:0}
.sr{display:grid;grid-template-columns:64px minmax(0,1fr) auto;gap:2px var(--tc-s3);align-items:center;padding:var(--tc-s2) 0;border-top:1px solid var(--tc-line)}
.sr>.pimg{width:64px;height:48px}.sr>:nth-child(n+3){grid-column:3}
.sr-t{min-width:0}.sr-t a.nm{font-weight:700}.sr-t small{display:block;color:var(--tc-mut);font-size:var(--tc-f-sub)}
/* 画像で選ぶ（横スクロール） */
.thumbs{display:flex;gap:var(--tc-s2);overflow-x:auto;margin:var(--tc-s5) calc(-1*var(--tc-s4)) 0;padding:0 var(--tc-s4) var(--tc-s1);scrollbar-width:thin}
a.th{flex:none;width:120px;display:flex;flex-direction:column;gap:4px;color:var(--tc-fg);text-decoration:none;font-size:var(--tc-f-sub);line-height:1.35}
a.th .pimg{width:120px;height:90px}
@media(min-width:768px){a.th{width:160px;font-size:13px}a.th .pimg{width:160px;height:120px}}
a.th span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
/* 利益ランキング */
table.rk{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.rk th{text-align:left;color:var(--tc-mut);font-weight:400;font-size:var(--tc-f-sub);padding:var(--tc-s1) var(--tc-s2);border-bottom:1px solid var(--tc-fg)}
.rk td{padding:var(--tc-s2);border-bottom:1px solid var(--tc-line);vertical-align:top}
.rk td.n{text-align:right;white-space:nowrap}.rk td.nm a{font-weight:700}.rk small{display:block;color:var(--tc-mut);font-size:var(--tc-f-sub)}
.rk .pos,.rk .wt{color:var(--tc-profit);font-size:var(--tc-f-num);font-weight:800}.rk .wt{color:var(--tc-fg)}
@media(max-width:599px){.rk thead{display:none}.rk,.rk tbody,.rk tr{display:block}.rk tr{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:0 var(--tc-s3);padding:var(--tc-s2) 0;border-bottom:1px solid var(--tc-line)}
.rk td{border:0;padding:0}.rk td.nm{grid-column:1/-1}.rk td.st{display:none}.rk td.n{text-align:left}.rk td[data-label]::before{content:attr(data-label) " ";color:var(--tc-mut);font-size:var(--tc-f-sub);font-weight:400}}
/* 商品の行（1 商品 1 行。375 = 画像 | 名前、その下に数字 3 つ。768 以上 = 表のような列） */
.cat-h{display:flex;align-items:baseline;gap:var(--tc-s2);margin:var(--tc-s5) 0 0;font-size:var(--tc-f-name);scroll-margin-top:var(--jump-offset)}
.cat-h small{color:var(--tc-mut);font-weight:400;font-size:var(--tc-f-sub)}
.plist{border-top:1px solid var(--tc-fg)}.pl-head{display:none}
.tcard{display:grid;grid-template-columns:96px minmax(0,1fr);gap:var(--tc-s2) var(--tc-s3);padding:var(--tc-s3) 0;border-bottom:1px solid var(--tc-line);min-width:0;scroll-margin-top:var(--jump-offset)}
.tcard:target{background:var(--tc-soon-bg)}
.tc-img{grid-column:1;grid-row:1}.tc-img .pimg{width:96px;height:72px}
.tc-id{grid-column:2;grid-row:1;min-width:0}.tc-id h3{font-size:var(--tc-f-name);line-height:1.4;margin:0 0 2px}.tc-tags{display:flex;flex-wrap:wrap;gap:2px}
.tc-meta{margin:0;color:var(--tc-mut);font-size:var(--tc-f-sub)}.tc-meta a{margin-left:6px}
.tc-strip{grid-column:1/-1;grid-row:2;list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--tc-s1) var(--tc-s2);font-variant-numeric:tabular-nums}
.tc-strip>li{min-width:0;display:flex;flex-direction:column}
.tc-strip em{font-style:normal;color:var(--tc-mut);font-size:11px;line-height:1.4}
.tc-val{min-width:0;overflow-wrap:anywhere}.tc-val small{display:block;color:var(--tc-mut);font-size:var(--tc-f-sub);line-height:1.4}.tc-val .amt small.u{display:inline}
.tc-strip .amt{font-size:var(--tc-f-num);font-weight:700;display:inline-block;white-space:nowrap}.amt small.u{font-size:11px;font-weight:400;color:var(--tc-mut);margin-right:3px}
.tc-strip [data-strip-profit] .amt{font-size:var(--tc-f-amt);font-weight:800}
.tc-strip .amt.na,.tc-strip [data-strip-profit] .amt.na{font-size:var(--tc-f-num);font-weight:400;color:var(--tc-mut)}
.amt.sm{font-size:var(--tc-f-sub);font-weight:400}.unv{color:var(--tc-mut);font-size:11px;margin-right:6px}
.stale-note{margin:0 0 var(--tc-s2);padding:var(--tc-s2) var(--tc-s3);background:var(--tc-surface);color:var(--tc-unk);font-size:var(--tc-f-sub)}.stale-note[hidden]{display:none}small.why[hidden]{display:none!important}
.tc-meta a,.tc-val a,a.lk,.tc-others li>a,.tc-lotd li a,.pfoot a{white-space:nowrap}
.amt.pos{color:var(--tc-profit)}.amt.neg{color:var(--tc-loss)}.is-wait .amt.pos{color:var(--tc-fg)}.amt.off,.amt.pack{color:var(--tc-mut);font-weight:400}
.tc-strip>li[data-strip-diff]{grid-column:2/-1;flex-direction:row;flex-wrap:wrap;gap:0 6px;align-items:baseline}.tc-strip [data-strip-diff] .amt{font-size:var(--tc-f-sub);font-weight:400}
.tc-lot{margin-top:4px;display:flex;flex-wrap:wrap;align-items:center;gap:0 var(--tc-s3)}.tc-lot:empty{display:none}
.pnote{margin:0;color:var(--tc-mut);font-size:var(--tc-f-sub)}.pnote.unb{margin:var(--tc-s1) 0}.pnote a{display:inline-flex;align-items:center;min-height:32px}
.chips{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 var(--tc-s3)}.chips .lbl{font-size:11px;color:var(--tc-mut);border:1px solid var(--tc-line);border-radius:var(--tc-r-badge);padding:0 4px}.chip{font-size:var(--tc-f-sub);color:var(--tc-mut)}
.chip{color:var(--tc-fg)}.chip b{font-weight:700;color:inherit}.chip.rb-expired:not(.exp),.chip.exp:not(.rb-expired){display:none}
.tc-more{grid-column:2/-1;grid-row:3;display:flex;flex-wrap:wrap;gap:0 var(--tc-s5)}
.tc-others,.tc-lotd{flex:1 1 260px;min-width:0}.tc-others[open],.tc-lotd[open]{flex-basis:100%}
.tc-others summary,.tc-lotd summary{min-height:40px;font-size:13px;color:var(--tc-link)}
.tc-others .oh{margin:var(--tc-s2) 0 2px;font-size:var(--tc-f-sub);font-weight:700}
.tc-others ul,.tc-lotd ul{list-style:none;margin:0;padding:0}
.tc-others li,.tc-lotd li{display:flex;flex-wrap:wrap;align-items:center;gap:2px var(--tc-s2);padding:6px 0;border-top:1px solid var(--tc-line);font-size:var(--tc-f-body);min-width:0;overflow-wrap:anywhere}
.tc-others li .tc-val{display:flex;flex-wrap:wrap;gap:0 var(--tc-s2);align-items:baseline}.tc-others li .tc-val small{display:inline;margin-left:6px}
.tc-others ul.ref li,.tc-others ul.ref li b{color:var(--tc-mut);font-size:var(--tc-f-sub);font-weight:400}
.tc-others li>a,.tc-lotd li a:not(.btn){display:inline-flex;align-items:center;min-height:40px;font-size:var(--tc-f-sub)}
.tc-lotd li small{color:var(--tc-mut);font-size:var(--tc-f-sub)}.tc-lotd li .btn{margin-left:auto}
.tc-lotd>a{display:inline-flex;align-items:center;min-height:44px;font-size:var(--tc-f-sub)}
@media(min-width:768px){
.pl-head{display:grid;grid-template-columns:120px minmax(0,2fr) minmax(0,1fr) minmax(0,1.3fr) minmax(0,1.3fr);gap:var(--tc-s3);padding:var(--tc-s1) 0;border-bottom:1px solid var(--tc-line);color:var(--tc-mut);font-size:11px}
.tcard{grid-template-columns:120px minmax(0,2fr) minmax(0,1fr) minmax(0,1.3fr) minmax(0,1.3fr);gap:var(--tc-s1) var(--tc-s3);align-items:start}
.tc-img{grid-row:1/span 3}.tc-img .pimg{width:120px;height:90px}
.tc-strip{display:contents}.tc-strip em{display:none}
.tc-strip>li[data-strip-msrp]{grid-column:3;grid-row:1}.tc-strip>li[data-strip-best]{grid-column:4;grid-row:1}.tc-strip>li[data-strip-profit]{grid-column:5;grid-row:1}
.tc-strip>li[data-strip-diff]{grid-column:4/6;grid-row:2}
.tc-more{grid-column:2/-1;grid-row:3}}
/* 販売店の BOX 価格（条件付き） */
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,420px),1fr));gap:var(--tc-s3)}
.pcard{border:1px solid var(--tc-line);border-radius:var(--tc-r-card);padding:var(--tc-s3);display:grid;grid-template-columns:72px minmax(0,1fr);gap:var(--tc-s2) var(--tc-s3);min-width:0;scroll-margin-top:var(--jump-offset)}
.phead{min-width:0}.phead h3{line-height:1.4}.pcard>.pmeta,.pcard>.pfoot{grid-column:1/-1}
.pmeta dl{margin:0}.pmeta dl>div{display:grid;grid-template-columns:7em minmax(0,1fr);gap:0 var(--tc-s2);padding:4px 0;border-top:1px solid var(--tc-line)}
.pmeta dt{color:var(--tc-mut);font-size:var(--tc-f-sub)}.pmeta dd{margin:0;font-weight:600;font-variant-numeric:tabular-nums}.pmeta dd small{margin-left:6px;font-weight:400;color:var(--tc-mut);font-size:var(--tc-f-sub)}
.pfoot a{display:inline-flex;align-items:center;min-height:44px}
details.note{margin:var(--tc-s2) 0;border-top:1px solid var(--tc-line)}details.note summary{min-height:44px}
details.note ul{margin:0;padding-left:1.1em}details.note .tc-others ul,details.note .tc-lotd ul{padding-left:0}details.note li{margin:4px 0}details.note li a{display:inline-flex;align-items:center;min-height:44px}
details.nobb{margin-top:var(--tc-s5)}details.nobb>.plist{border-top:0}
/* 抽選一覧 */
.lt-tabs{display:flex;gap:0;overflow-x:auto;border-bottom:1px solid var(--tc-line);scrollbar-width:none}
.lt-tabs a{flex:none;display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 var(--tc-s3);color:var(--tc-fg);text-decoration:none;border-bottom:3px solid transparent;white-space:nowrap}
.lt-tabs a[aria-current=true]{font-weight:700;border-bottom-color:var(--tc-fg)}.lt-tabs a b{font-weight:700;color:var(--tc-mut)}
.lt-chips{display:flex;flex-wrap:wrap;gap:var(--tc-s2);margin:var(--tc-s3) 0}.lt-chips[hidden]{display:none}
.lt-chips button{min-height:44px;padding:0 var(--tc-s3);border:1px solid var(--tc-line);border-radius:var(--tc-r-btn);background:var(--tc-bg);color:var(--tc-fg);font:inherit}
.lt-chips button[aria-pressed=true]{border-color:var(--tc-link);color:var(--tc-link);font-weight:700}
.filters{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:var(--tc-s2);margin:var(--tc-s2) 0}
.filters label{font-size:var(--tc-f-sub);color:var(--tc-mut);min-width:0}.filters select{display:block;width:100%;max-width:100%;min-height:44px;font-size:15px}
details.flt[hidden]{display:none}
.lt-sec{margin:var(--tc-s4) 0 0}.lt-sec[hidden],.lt-more[hidden]{display:none}.lt-sec h3{font-size:var(--tc-f-body);color:var(--tc-mut);font-weight:700;margin:0 0 var(--tc-s1);scroll-margin-top:var(--jump-offset)}
.lt-more{scroll-margin-top:var(--jump-offset)}
.lt-wrap{overflow:visible}table.lt{width:100%;min-width:0;border-collapse:collapse}
.lt thead{display:none}.lt{display:block}
/* 抽選は画像が主役のカード（375 = 2 列、広い画面 = 3〜4 列） */
.lt tbody{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,220px),1fr));gap:var(--tc-s3)}
@media(max-width:519px){.lt tbody{grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--tc-s2)}}
.lt tr.ev{position:relative;display:flex;flex-direction:column;min-width:0;border:1px solid var(--tc-line);border-radius:var(--tc-r-card);overflow:hidden;background:var(--tc-bg);padding:0 0 var(--tc-s3);scroll-margin-top:var(--jump-offset)}
.lt tr.ev:target{outline:2px solid var(--tc-cta)}
.lt td{display:block;padding:0 10px;border:0;min-width:0;overflow-wrap:anywhere}.lt td.na{display:none}
.lt td.im{order:0;padding:0;height:160px;background:var(--tc-surface);margin-bottom:var(--tc-s2)}
.lt td.im .pimg{width:100%;height:100%;border:0;border-radius:0;background:transparent;padding:6px}.lt td[data-label="商品"]>.tcgtag{display:none}
.lt td[data-label="状態"]{position:absolute;top:8px;left:8px;padding:0;z-index:1}
.lt td[data-label="状態"] .sb{font-size:12px;line-height:1.9;padding:0 8px}
.lt td.how{display:contents}
.lt .chn{order:1;align-self:flex-start;margin:0 10px 4px;display:inline-flex;align-items:center;height:24px;padding:0 8px;border:1px solid var(--tc-line);border-radius:12px;background:#fff;color:var(--tc-fg);font-size:12px;font-weight:700}
.lt .chn.ch-online{color:var(--tc-open);border-color:var(--tc-open)}.lt .chn.ch-store{color:var(--tc-profit);border-color:var(--tc-profit)}
.lt .reqs{order:1;display:flex;flex-wrap:wrap;gap:2px 4px;padding:0 10px;margin-bottom:2px}
.lt td[data-label="商品"]{order:2;font-weight:700;font-size:var(--tc-f-body);line-height:1.4}
.lt td[data-label="商品"] a.nm,.lt td[data-label="商品"]>span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.lt td[data-label="店舗"]{order:3;font-size:13px;line-height:1.4;margin-top:2px}.lt td[data-label="店舗"] b{font-weight:700}
.lt td[data-label="店舗"] small{color:var(--tc-mut);font-size:var(--tc-f-sub);margin-left:4px}.lt small.tier{display:none}
.lt td[data-label="締切"]{order:4;margin-top:4px;font-size:var(--tc-f-sub);color:var(--tc-mut);font-variant-numeric:tabular-nums}
.lt td[data-label="締切"] small{display:block;font-size:11px}.lt td[data-label="締切"] small.left{display:inline;margin-left:4px;font-size:var(--tc-f-sub)}
.lt td[data-label="当選日"],.lt td[data-label="購入期間"],.lt td[data-label="地域"]{order:5;font-size:11px;color:var(--tc-mut)}
.lt td[data-label="締切"]::before,.lt td[data-label="当選日"]::before,.lt td[data-label="購入期間"]::before{content:attr(data-label) " "}
.lt td[data-label="確認"]{order:6;margin-top:2px}
.lt .btns{order:7;display:flex;flex-direction:column;gap:4px;margin-top:auto;padding:var(--tc-s2) 10px 0}
.lt .btns .btn{width:100%;white-space:normal;text-align:center;line-height:1.3;padding:6px 8px}.lt .btns a.lk{justify-content:center}
.lt .btns .nojs{font-size:var(--tc-f-sub)}
.lt td{min-width:0}.lt small{font-size:var(--tc-f-sub)}.ev[hidden]{display:none!important}
.req{display:inline-block;border:1px solid var(--tc-line);border-radius:var(--tc-r-badge);padding:0 4px;color:var(--tc-mut);font-size:11px;line-height:1.6}
.req.cd{color:var(--tc-fg);max-width:100%;overflow-wrap:anywhere}
@media(max-width:519px){.lt td.im{height:120px}.lt .chn{margin:0 8px 4px;height:22px;font-size:11px;padding:0 6px}.lt td{padding:0 8px}.lt .reqs,.lt .btns{padding-left:8px;padding-right:8px}
.lt td[data-label="商品"]{font-size:13px}.lt .btns .btn{font-size:13px;min-height:44px}}
#lt-live .lt .ev.rb-expired{display:none}
/* 抽選ページの上部（商品から選ぶ・方式から選ぶ・件数と最終更新） */
.pick{margin:var(--tc-s4) 0 0}.pick h2,.lt-h{font-size:var(--tc-f-h2);margin:var(--tc-s5) 0 var(--tc-s2)}
.pick-row{display:flex;gap:var(--tc-s2);overflow-x:auto;margin:0 calc(-1*var(--tc-s4));padding:0 var(--tc-s4) var(--tc-s1);scrollbar-width:thin}
a.pk{flex:none;width:118px;display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px 6px 8px;background:var(--tc-surface);border-radius:var(--tc-r-card);color:var(--tc-fg);text-decoration:none;font-size:13px;line-height:1.35;text-align:center}
a.pk .pimg{width:100%;height:96px;border:0;background:transparent}
a.pk span{display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;width:100%}a.pk small{color:var(--tc-mut);font-size:11px}
a.pk[aria-current=true]{outline:2px solid var(--tc-cta)}
.mtiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--tc-s2)}
.mtiles button{display:flex;align-items:center;gap:10px;min-height:60px;padding:var(--tc-s2) var(--tc-s3);border:1px solid var(--tc-line);border-radius:var(--tc-r-card);background:var(--tc-bg);color:var(--tc-fg);font:inherit;text-align:left;cursor:pointer}
.mtiles button[aria-pressed=true]{border-color:var(--tc-cta);box-shadow:inset 0 0 0 1px var(--tc-cta)}
.mtiles i{flex:none;display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:8px;font-style:normal;font-size:16px}
.mtiles .ic-online{background:#e8f0fe;color:var(--tc-open)}.mtiles .ic-store{background:#fdf1e6;color:#a34f00}
.mtiles b{display:block;font-size:var(--tc-f-body)}.mtiles small{color:var(--tc-mut);font-size:var(--tc-f-sub)}
.lt-bar{display:flex;justify-content:space-between;align-items:baseline;gap:var(--tc-s2);margin:var(--tc-s2) 0;font-size:13px;font-weight:700}.lt-bar span.u{color:var(--tc-mut);font-weight:400;font-variant-numeric:tabular-nums}
details.calx{margin:var(--tc-s3) 0 0;border:1px solid var(--tc-line);border-radius:var(--tc-r-card);padding:0 var(--tc-s3)}details.calx>summary{min-height:48px;display:flex;align-items:center;font-weight:700;cursor:pointer}
details.calx[open]{padding-bottom:var(--tc-s3)}
/* 抽選カレンダー（コンパクト。セルに種類の短い文字と件数） */
.cal-month{margin:var(--tc-s2) 0}.cal-month h3{margin:0 0 var(--tc-s1);font-size:var(--tc-f-body)}
.cal-more>.cal-month{margin-top:var(--tc-s3)}
.cg{position:relative;display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:1px;background:var(--tc-line);border:1px solid var(--tc-line)}
.cg>div{background:var(--tc-bg);min-height:44px;padding:2px 3px;font-size:var(--tc-f-sub);min-width:0}.cg .wh{min-height:0;text-align:center;color:var(--tc-mut);background:var(--tc-surface)}
.cg .gap{grid-column:1/-1;min-height:0;text-align:center;color:var(--tc-mut);background:var(--tc-surface);padding:2px}.cg .off{background:var(--tc-surface)}
.cg .today{outline:2px solid var(--tc-fg);outline-offset:-2px}
.cg .d{display:block;font-weight:700;font-size:var(--tc-f-sub)}
main .cg summary{display:block;list-style:none;cursor:pointer;color:var(--tc-fg);min-height:40px}main .cg summary::before,main .cg details[open]>summary::before{content:none}.cg summary::-webkit-details-marker{display:none}
.cg ul{margin:0;padding:0;list-style:none}.cg li{margin:.2em 0;overflow-wrap:break-word;word-break:normal}.cg li a{color:var(--tc-fg)}
.cg details[open]>ul{position:absolute;left:0;right:0;z-index:3;margin:2px 0 0;padding:8px 12px;background:var(--tc-bg);border:1px solid var(--tc-fg);font-size:13px}
.k{display:inline-block;border-radius:var(--tc-r-badge);padding:0 4px;font-size:11px;margin:0 2px 2px 0;line-height:1.5;white-space:nowrap}
.k-START{background:var(--tc-open);color:#fff}.k-END{background:var(--tc-urgent);color:#fff}.k-RESULT{background:var(--tc-soon-bg);color:var(--tc-soon)}
.k-PURCHASE_START,.k-PURCHASE_END{background:var(--tc-surface);color:var(--tc-mut)}.k-RELEASE{background:transparent;color:var(--tc-mut);border:1px solid var(--tc-line)}
.k .ks{display:none}
.cal-legend{display:flex;flex-wrap:wrap;gap:2px;margin:0 0 var(--tc-s1)}
.agenda ul,.callist ul{padding-left:1.1em;margin:.2em 0}
footer.foot{margin:var(--tc-s6) 0 0;padding-top:var(--tc-s3);border-top:1px solid var(--tc-line);color:var(--tc-mut);font-size:var(--tc-f-sub)}footer.foot p{margin:2px 0}
@media(max-width:599px){.sr{grid-template-columns:64px minmax(0,1fr)}.sr>:nth-child(n+3){grid-column:2}.sr .btn{justify-self:start}}
@media(max-width:767px){.tc-strip .emx{display:none}
.cg>div{min-height:40px;padding:1px 2px}.k .kl{display:none}.k .ks{display:inline}.cg .k{padding:0 2px;font-size:10px}
main{padding:var(--tc-s2) var(--tc-s4) var(--tc-s6)}.tcard{padding:10px 0}.tc-strip [data-strip-profit] .amt{font-size:17px}
.pcard{grid-template-columns:56px minmax(0,1fr);padding:10px}.pcard .pimg{width:56px;height:42px}}
@media(min-width:768px){h1{font-size:22px}}
"""

from src.tcg import runtime_freshness as rf               # noqa: E402


def _CFG() -> dict:
    """買取の設定（しきい値は config/tcg_buyback.yaml が唯一の定義。ページの属性に出す値もここから）。"""
    from src.tcg import buyback as _bb
    return _bb.load_config()


# 抽選ページの絞り込み（タブ・オンライン/店頭・詳しい絞り込み）。JS が無くても全件が見え、タブはページ内リンクとして働く。
JS = """
(function(){try{
var f=document.getElementById('flt');if(!f)return;
var cnt=document.getElementById('cnt'),none=document.getElementById('none'),tab='all',ch='';
function fromHash(){var h=location.hash||'';if(h.indexOf('#prod-')===0&&f.elements.product){f.elements.product.value=h.slice(6);return true;}return false;}fromHash();
function run(){var v={},n=0,m=0;['tcg','product','retailer','region','state'].forEach(function(k){v[k]=f.elements[k]?f.elements[k].value:'';});
document.querySelectorAll('.ev').forEach(function(e){var d=e.dataset,ok=true;
['tcg','product','retailer','region'].forEach(function(k){if(v[k]&&d[k]!==v[k])ok=false;});
if(v.state&&(' '+d.state+' ').indexOf(' '+v.state+' ')<0)ok=false;if(ch&&d.ch!==ch)ok=false;e.hidden=!ok;});
document.querySelectorAll('[data-lt-group]').forEach(function(s){var g=s.getAttribute('data-lt-group');
var k=s.querySelectorAll('.ev:not([hidden]):not(.rb-expired)').length;s.hidden=(tab!=='all'&&g!==tab)||k===0;
if(tab===g&&s.tagName==='DETAILS')s.open=true;if(!s.hidden&&(g==='ending'||g==='open'))n+=k;else if(!s.hidden&&s.tagName!=='DETAILS')m+=k;});
document.querySelectorAll('[data-tab]').forEach(function(a){a.setAttribute('aria-current',a.getAttribute('data-tab')===tab?'true':'false');});
document.querySelectorAll('[data-ch-btn]').forEach(function(b){b.setAttribute('aria-pressed',b.getAttribute('data-ch-btn')===ch?'true':'false');});
document.querySelectorAll('[data-pk]').forEach(function(a){a.setAttribute('aria-current',a.getAttribute('data-pk')===v.product?'true':'false');});
var act=tab!=='all'||ch||['tcg','product','retailer','region','state'].some(function(k){return v[k];});
if(cnt)cnt.textContent=act?'受付中 '+n+'件'+(m?'・ほか '+m+'件':''):'';
if(none){var any=document.querySelectorAll('section[data-lt-group]:not([hidden]) .ev:not([hidden]):not(.rb-expired)').length;none.hidden=any>0||!act;}}
f.addEventListener('change',run);
document.querySelectorAll('[data-tab]').forEach(function(a){a.addEventListener('click',function(ev){ev.preventDefault();tab=a.getAttribute('data-tab');run();});});
document.querySelectorAll('[data-ch-btn]').forEach(function(b){b.addEventListener('click',function(){var c=b.getAttribute('data-ch-btn');ch=(ch===c?'':c);run();});});
document.querySelectorAll('[data-pk]').forEach(function(a){a.addEventListener('click',function(ev){ev.preventDefault();var k=a.getAttribute('data-pk');
f.elements.product.value=(f.elements.product.value===k?'':k);run();var l=document.getElementById('lottery');if(l)l.scrollIntoView();});});
window.addEventListener('hashchange',function(){if(fromHash())run();});
document.querySelectorAll('[data-js-only]').forEach(function(e){e.hidden=false;});
run();
}catch(e){}})();
"""

# 鮮度が切れた価格が 1 つでもあれば、表の上の注記を出す（各セルは「再確認待ち」だけ）。JS_FRESHNESS の判定結果（stale の hidden）を読むだけ
JS_STALE_NOTE = r"""
(function(){function f(){try{var n=document.querySelector('[data-stale-note]');if(!n)return;var any=false;
document.querySelectorAll('.tc-strip [data-fb-stale],.rk [data-fb-stale]').forEach(function(e){if(!e.hidden&&!(e.closest&&e.closest('.rb-expired')))any=true;});n.hidden=!any;
}catch(x){}try{var rk=document.querySelector('[data-rk]');if(rk){var a=false;rk.querySelectorAll('[data-fb-live]').forEach(function(e){if(!e.hidden)a=true;});rk.hidden=!a;}}catch(x){}}
f();setInterval(f,60000);document.addEventListener('visibilitychange',f);window.addEventListener('pageshow',f);})();
"""

# 締切までの残り時間（「あと18時間」）。締切は固定の事実なので、表示時に計算すれば正しい。JS が無ければ締切時刻だけ。締切後は空（行は JS_RB が切り替える）
JS_LEFT = r"""
(function(){function f(){try{var now=Date.now();
document.querySelectorAll('[data-left-until]').forEach(function(e){var u=e.getAttribute('data-left-until')||'';
var t=Date.parse(u.length===10?u+'T23:59:59+09:00':u);if(isNaN(t)||t<=now){e.textContent='';return;}
var hr=Math.floor((t-now)/3600000);e.textContent=hr<1?'あと1時間未満':(hr<48?'あと'+hr+'時間':'あと'+Math.floor(hr/24)+'日');});
document.querySelectorAll('[data-cnt-untils]').forEach(function(e){var n=0;(e.getAttribute('data-cnt-untils')||'').split(' ').forEach(function(u){if(!u)return;
if(u==='-'){n++;return;}var t=Date.parse(u.length===10?u+'T23:59:59+09:00':u);if(!isNaN(t)&&t>now)n++;});e.textContent=String(n);
var h=e.getAttribute('data-cnt-hide');if(h){var c=e.closest(h);if(c)c.hidden=(n===0);}});
var sb=document.getElementById('soon');if(sb){var ex=0,lv=0;sb.querySelectorAll('li.sr').forEach(function(li){var u=li.getAttribute('data-rb-until')||'';
var t=u?Date.parse(u.length===10?u+'T23:59:59+09:00':u):NaN;var gone=!isNaN(t)&&now>t;li.hidden=gone;if(gone)ex++;else lv++;});
var xe=sb.querySelector('[data-soon-expired]');if(xe){xe.hidden=(ex===0);var b=xe.querySelector('b');if(b)b.textContent=String(ex);}
var ne=sb.querySelector('[data-soon-none]');if(ne)ne.hidden=(lv>0);var ul=sb.querySelector('ul');if(ul)ul.hidden=(lv===0);}
var today=new Date(now+9*3600000).toISOString().slice(0,10);document.querySelectorAll('[data-day]').forEach(function(e){var k=e.getAttribute('data-day');e.classList.toggle('past',k<today);e.classList.toggle('today',k===today);});
}catch(x){}}
function openTo(id){var t=id&&document.getElementById(id);if(!t)return false;var d=t.parentElement&&t.parentElement.closest('details');
while(d){d.open=true;d=d.parentElement&&d.parentElement.closest('details');}if(t.tagName==='DETAILS')t.open=true;t.scrollIntoView();return true;}
try{document.querySelectorAll('[data-js-only]').forEach(function(e){e.hidden=false;});document.querySelectorAll('[data-nojs]').forEach(function(e){e.hidden=true;});
document.querySelectorAll('a[href^="#"]').forEach(function(a){a.addEventListener('click',function(ev){var id=(a.getAttribute('href')||'').slice(1);
var t=id&&document.getElementById(id);if(t&&((t.tagName==='DETAILS'&&!t.open)||(t.parentElement&&t.parentElement.closest('details:not([open])')))){ev.preventDefault();openTo(id);try{history.replaceState(null,'','#'+id);}catch(x){}}});});
if(location.hash)openTo(location.hash.slice(1));}catch(x){}
f();setInterval(f,60000);window.addEventListener('pageshow',f);})();
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


def _link(url, label, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{_e(url)}" target="_blank" rel="noopener nofollow">{_e(label)}</a>' if url else ""


def _host_in(url, hosts) -> Optional[str]:
    r = au.safe_https(url)
    if r and any(r[0] == h or r[0].endswith("." + h) for h in hosts):
        return r[1]
    return None


def _host_ok(url) -> Optional[str]:
    """https かつ PRODUCT_HOSTS 配下なら正規化した URL。それ以外は None。"""
    return _host_in(url, PRODUCT_HOSTS)


def _product_link(url) -> str:
    u = _host_ok(url)
    return _link(u, "公式ページ") if u else ""


def _image_src(url, tcg: str = "POKEMON") -> Optional[str]:
    """商品画像の URL。その TCG の公式ドメインの画像で、その画像に権利者の利用許可の記録（IMAGE_RIGHTS_PERMISSION）があるときだけ（判定は verified_products.image_publishable が唯一の定義）。"""
    from src.tcg import verified_products as _vp
    return url if _vp.image_publishable(tcg, url) else None


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
    if verified and w.get("time") == "00:00" and w.get("precision") == "datetime":     # 時刻付きの 0 時: 期限（JS_RB は 0:00 で失効）と同じ時刻を出す
        return f'<span title="{_e(w["date"])} 00:00（0 時ちょうど・この時刻で締切）">{_e(ds)} 0:00</span>'
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


def _roi(v) -> str:
    """ROI の表示（整数の %）。"""
    return f"{float(v):.0f}%"


def _wd(date: str) -> str:
    try:
        return WEEKDAY[datetime.strptime(date, "%Y-%m-%d").weekday()]
    except ValueError:
        return ""


def _badge(text, tone="out") -> str:
    return f'<span class="sb {tone}">{_e(text)}</span>'


LABEL_PURCHASE_ONLY = "購入期間中・当選者のみ"
RB_EXPIRED_APPLY = "応募期限を過ぎました"
RB_EXPIRED_PURCHASE = "購入期間は終了しました"
RB_EXPIRED_SECTION_HEAD = "応募期限を過ぎた行があります"
RB_EXPIRED_GROUP = "期限切れの抽選あり"
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
    return f'<small class="prio">{_e(PRIO_LABEL[p])}</small>' if p and p != st.P_WATCH else ""


def _tcgtag(tcg) -> str:
    return f'<span class="tcgtag">{_e(TCG_SHORT.get(tcg, ""))}</span>' if tcg in TCG_SHORT else ""


def _lot_anchor(lottery_id) -> str:
    """抽選の行のアンカー id（英数字と - _ だけ）。"""
    s = re.sub(r"[^A-Za-z0-9_-]", "-", str(lottery_id or ""))
    return "L-" + (s or "x")


def can_apply(status, verified, conflict, url) -> bool:
    """「公式ページで応募する」を出してよいか: 応募 URL があり、受付中・締切間近・確認済み・日程の食い違いなし。"""
    return bool(url) and status in st.APPLYING and bool(verified) and not conflict


APPLY_HOWTO = "公式の告知を見る"     # 告知へのリンク（応募ページではない。直接応募できると誤解させない）


def _ann_btn(url) -> str:
    return _link(url, "公式の告知", "btn")                    # 開始前・未確認の告知（応募ボタンの文言 APPLY_HOWTO は使わない。#853）


def _state_tokens(v: dict, flags: set) -> str:
    toks = []
    if v.get("deadline_only"):
        # 締切だけ分かる行（受付開始の根拠なし）は、絞り込みの「受付中」「締切間近」「今日応募可能」に入れない
        toks.append("deadline_only")
        toks += sorted(f for f in flags if f not in ("today", "deadline"))
        return " ".join(toks)
    if v["status"] == ls.L_OPEN:
        toks.append("open")
    if v["status"] == ls.L_ENDING_SOON:
        toks.append("ending")
    if v["status"] == ls.L_UPCOMING:
        toks.append("upcoming")
    toks += sorted(flags)
    return " ".join(toks)


def _ch_key(ch) -> str:
    return "online" if ch in _ONLINE else "store" if ch == au.CH_STORE_COUNTER else "unknown"


def _lot_buttons(status, verified, conflict, app_url, ann_url, until: str, deadline: str = "", deadline_only: bool = False) -> str:
    """抽選のボタン。受付中・締切間近で確認済み・食い違いなし・受付開始の根拠あり:
    応募 URL があれば「公式ページで応募する」（塗りの青）、無ければ告知へ「公式の告知を見る」（APPLY_HOWTO。枠線の青。応募ページではない）。
    これらは JS が動くときだけ出す（締切後は JS_RB が隠す）。JS が無いときは「締切 …・公式の告知」のテキストリンク（締切後に押せるボタンを残さない）。
    締切だけ分かり受付開始の根拠が無い行（deadline_only）・開始前・未確認: 告知へのリンク「公式の告知」（枠線）。結果待ち・当選者のみ・終了: 灰色の小さなリンク。"""
    ok = status in st.APPLYING and bool(verified) and not conflict and not deadline_only
    if ok and (app_url or ann_url):
        url, lab, cls = (app_url, "公式ページで応募する", "btn cta") if app_url else (ann_url, APPLY_HOWTO, "btn cta ann")
        b = f'<a class="{cls}" href="{_e(url)}" target="_blank" rel="noopener nofollow" data-js-only hidden>{_e(lab)}</a>'
        alt = f'<span class="nojs" data-nojs>{("締切 " + deadline + "・") if deadline else ""}{_link(ann_url, "公式の告知") if ann_url else _link(app_url, "公式の応募ページ")}</span>'
        return f'<span data-rb-open>{b}{alt}</span>' if until else b + alt
    if ann_url and (status in st.INTAKE or status == ls.L_UNKNOWN or deadline_only):
        b = _ann_btn(ann_url)
        return f'<span data-rb-open>{b}</span>' if until else b
    if ann_url:
        return _link(ann_url, "公式の告知", "lk")
    return ""


def _ev_row(v: dict, pidx: dict, yr: str, flags: set, cards: Optional[dict] = None) -> str:
    ev = v["ev"]
    shop = pv.retailer_label(ev)
    sub = ev.get("retailer_name") or ""
    if pv._is_enum_like(sub, str(ev.get("retailer") or "")):         # 列挙値は副表示にも出さない
        sub = ""
    region = ev.get("prefecture") or ""
    bound = v.get("canonical") in (pv.C_MASTER, pv.C_DISCOVERED)
    p_key = pidx.get((ev.get("tcg"), ev.get("product_id"))) if bound else None
    conflict = bool(ev.get("conflict"))
    ch = v["channel"]
    attrs = (f'id="{_e(_lot_anchor(v.get("lottery_id")))}" '
             f'data-tcg="{_e(ev.get("tcg"))}" data-product="{_e(p_key or "none")}" data-retailer="{_e(ev.get("retailer"))}" '
             f'data-region="{_e(region or "unknown")}" data-state="{_e(_state_tokens(v, flags))}" data-ch="{_ch_key(ch)}" '
             f'data-lot-state="{_e(v["status"])}" data-verified="{1 if v["verified"] else 0}"' + (' data-conflict' if conflict else '')
             + (' data-deadline-only' if v.get("deadline_only") else ''))
    pname = _e(ev.get("product_name") or "商品名不明")
    card = (cards or {}).get(p_key) if p_key else None
    img = _img_block(card) if card else _ev_img(ev)
    if p_key:
        product = f'{_tcgtag(ev.get("tcg"))}<a class="nm" href="{PAGE_PRODUCTS}#{_e(p_key)}">{pname}</a>'
    else:
        product = f'{_tcgtag(ev.get("tcg"))}<span title="{_e(CANON_LABEL.get(v.get("canonical"), ""))}">{pname}</span>'
    chs = CHANNEL_SHORT.get(ch, ch)
    reqs = "".join(f'<span class="req">{_e(REQ_LABEL.get(r, r))}</span>' for r in v["requirements"]
                   if REQ_LABEL.get(r, r) not in chs)                 # 応募方法と同じ語（SNS など）は重ねない
    reqs += _cond_chips(ev.get("conditions"))
    until, exp_msg = _lot_until(v["status"], v["end"], v["purchase_end"])
    btns = _lot_buttons(v["status"], v["verified"], conflict, v["application_url"], v["announcement_url"], until, _md(v["end"], yr, v["verified"]),
                        bool(v.get("deadline_only")))
    verify = "" if v["verified"] else '<span class="sb out" title="未確認（公式での再確認待ち）">未確認</span>'
    if conflict:
        verify += _badge("日程に食い違い", "danger")
    if v["status"] == ls.L_WINNER_PURCHASE_PERIOD:                      # 購入期間中は当選者だけ（新規応募不可）
        lab, tone = LABEL_PURCHASE_ONLY, "warn"
    elif "deadline" in flags and not v.get("deadline_only"):            # バッジは 1 つ（今日締切は締切間近と重ねない。締切だけの行は「締切前」のまま）
        lab, tone = "今日締切", "danger"
    else:
        lab, tone = v["status_label"], ("warn" if v.get("deadline_only") else _tone(v["status"]))
    st_cell = _rb_wrap(_badge(lab, tone), until, _badge(exp_msg, "gray"))
    ok = v["verified"]
    no_res = not v["result"].get("date")
    left = (f'<small class="left" data-left-until="{_e(until)}"></small>' if (until and v["status"] in st.APPLYING and not v.get("deadline_only")) else "")
    if until:
        attrs += f' data-rb-card data-rb-until="{_e(until)}"'
    return (f'<tr class="ev t-{"warn" if v.get("deadline_only") else _tone(v["status"])}" {attrs}>'
            f'<td class="im">{img}</td>'
            f'<td data-label="状態">{st_cell}</td>'
            f'<td data-label="店舗"><b>{_e(shop)}</b>{"<small>" + _e(sub) + "</small>" if sub and sub != shop else ""}'
            f'{_tier_tag(ev.get("retailer"))}</td>'
            f'<td data-label="商品">{product}</td>'
            f'<td data-label="締切"{W2 if no_res else ""}>{_md(v["end"], yr, ok)}{left}<small>開始 {_md(v["start"], yr, ok)}</small></td>'
            f'<td data-label="応募方法" class="how"><span class="chn ch-{_ch_key(ch)}" title="{_e(CHANNEL_LABEL.get(ch, ch))}・{_e(KIND_LABEL.get(v["entry_kind"], v["entry_kind"]))}">{_e(chs)}</span>'
            f'{"<span class=" + chr(34) + "reqs" + chr(34) + ">" + reqs + "</span>" if reqs else ""}<span class="btns">{btns}</span></td>'
            f'<td data-label="地域"{"" if region else NA}>{_e(region) if region else "—"}</td>'
            f'<td data-label="当選日"{"" if v["result"].get("date") else NA}>{_md(v["result"], yr, ok)}</td>'
            f'<td data-label="購入期間"{"" if (v["purchase_start"].get("date") or v["purchase_end"].get("date")) else NA}>{_range(v["purchase_start"], v["purchase_end"], yr, ok)}</td>'
            f'<td data-label="確認"{"" if verify else NA}>{verify}</td></tr>')


def _tier_tag(retailer) -> str:
    """店舗の区分（メーカー公式・大手チェーン・カードショップ）。公式ソースのレジストリに無ければ出さない。"""
    from src.tcg.lottery.registry import source_profile
    lab = (source_profile(str(retailer or "")) or {}).get("tier_label") or ""
    return f'<small class="tier">{_e(lab)}</small>' if lab else ""


def _cond_chips(conditions) -> str:
    """構造化した応募条件の詳細（会員の種類と登録期限・購入履歴の期間と金額・X・アプリ限定・応募と購入の上限・地域・購入時の本人確認）。

    既存の要件のラベル（会員・購入履歴等）に、本文に明記された具体的な値を足す。「不要」と明記された条件は「〜は不要」と出す。
    明記の無い項目（不明）は出さない。根拠の行（quote）は公開の出口で外れているので、title にも出さない。"""
    c = conditions if isinstance(conditions, dict) else {}
    out = []

    def chip(text):
        out.append(f'<span class="req cd">{_e(text)}</span>')

    def val(k):
        v = c.get(k)
        return v.get("value") if isinstance(v, dict) else None
    m = c.get("membership_required")
    if val("membership_required") is True:
        if m.get("type"):
            chip(str(m["type"]))
        if m.get("deadline"):
            chip("登録期限 " + str(m["deadline"])[:40])
    elif val("membership_required") is False:
        chip("会員登録は不要")
    ph = c.get("purchase_history_required")
    if val("purchase_history_required") is True and (ph.get("amount") or ph.get("period")):
        chip("購入履歴 " + " ".join(str(x) for x in (ph.get("period"), ph.get("amount")) if x)[:48])
    elif val("purchase_history_required") is False:
        chip("購入履歴は不要")
    if val("x_follow_required") is True or val("x_repost_required") is True:
        chip("X フォロー・リポスト" if val("x_repost_required") is True else "X フォロー")
    if val("app_only") is True:
        chip("アプリ限定")
    if val("application_limit"):
        chip("応募 " + str(val("application_limit"))[:24])
    if val("purchase_limit"):
        chip("購入 " + str(val("purchase_limit"))[:24])
    if val("region_limit"):
        chip(str(val("region_limit"))[:24])
    if val("id_required_at_purchase") is True:
        chip("購入時に本人確認")
    elif val("id_required_at_purchase") is False:
        chip("本人確認は不要")
    return "".join(out)


W2 = ' class="w2"'                                      # 当選日の列が無いときの締切セル
NA = ' class="na"'                                      # 値が無いセル（カード表示では出さない）
_HEAD = ("<tr><th>状態</th><th>店舗</th><th>商品</th><th>締切</th><th>応募方法</th><th>地域</th>"
         "<th>当選日</th><th>購入期間</th><th>確認</th></tr>")


def _table(views, pidx, yr, flagmap, tid=None, cards: Optional[dict] = None) -> str:
    rows = "".join(_ev_row(v, pidx, yr, flagmap.get(id(v), set()), cards) for v in views)
    i = f' id="{tid}"' if tid else ""
    return f'<div class="lt-wrap"{i}><table class="lt"><thead>{_HEAD}</thead><tbody>{rows}</tbody></table></div>'


# 画像の読み込みに失敗したとき、代わりの画像（SVG）に切り替える（外部の値を埋め込まない定数。deploy-check が完全一致で検査する）
IMG_ONERROR = _pi.IMG_ONERROR


def _ph_block(tcg, name="", product_type=None, code=None, default_kind: str = "商品") -> str:
    """公式画像が無い商品・商品に紐付いていない抽選の代わりの画像（ページ内の SVG。商品名の要点・型番・TCG・商品の種類）。"""
    _ini, cls = TCG_INITIAL.get(tcg, ("?", ""))
    return _pi.figure(tcg=tcg, name=name, kind=_pi.kind_of(product_type, name, default_kind), code=_pi.code_of(name, code),
                      cls=f"pimg {cls}".strip(), tag="div")


def _ev_img(ev: dict) -> str:
    """商品ページの無い抽選（商品に紐付いていない・商品が見つからない）の代わりの画像。"""
    return _ph_block(ev.get("tcg"), ev.get("product_name") or "商品名不明", None, ev.get("product_code"), "抽選")


def _img_block(p: dict) -> str:
    """商品画像。商品マスタに一致し、URL がその TCG の公式サイトの画像（image_publishable）のときだけ公式画像（直接参照・loading="lazy"）。
    それ以外・読み込みに失敗したときは代わりの画像（SVG）。"""
    _ini, cls = TCG_INITIAL.get(p["tcg"], ("?", ""))
    src = _image_src(p.get("image_url"), p["tcg"]) if p.get("canonical") == pv.C_MASTER else None
    name = p.get("name") or ""
    return _pi.figure(tcg=p["tcg"], name=name, src=src or "", kind=_pi.kind_of(p.get("product_type"), name),
                      code=_pi.code_of(name, p.get("product_code")), cls=f"pimg {cls}".strip(), tag="div")


# ───────────────────────── 商品カード（1 商品 1 枚: 画像・利益ストリップ・その他の売却先・抽選） ─────────────────────────
# 鮮度（data-fb-*）の約束: 買取由来の値（最高買取・利益・ROI・差額・状態バッジ・他店の価格）は、必ず data-fb-live の <span> の中に入れる。
# live の内側は <b> / <small> / <a> だけ（<div> と <span> の入れ子を作らない。検査が途中で切れて金額を見落とさないため）。
# グループは取得時刻が同じ要素だけで作る: 最高買取と差額 = {g}-b／利益・ROI・状態バッジ = {g}-p／他店は行ごと {g}-oN。各 live の直後に同じ group の stale を置く。
def _live(g: str, obs, cfg: dict, inner: str) -> str:
    return f'<span data-fb-live data-fb-group="{g}" {rf.attrs(obs, cfg)} hidden>{inner}</span>'


def _stale(g: str, cfg: dict, inner: str) -> str:
    return f'<span data-fb-stale data-fb-group="{g}" data-fb-max="{rf.thresholds(cfg)[0]:g}">{inner}</span>'


def _stale_txt(obs, lead: str = "再確認待ち") -> str:
    """鮮度切れのとき最初から出ている短いラベル（金額は出さない）。理由（JS が data-fb-why を『取得から N 時間以上経過』に書き換える）と
    取得時刻は画面に出さない隠し要素に置く。取得時刻は表の上の注記（JS_STALE_NOTE）に 1 回だけ出す。"""
    return f'{lead}<small class="why" hidden><span data-fb-why></span></small>'


def _https(url) -> Optional[str]:
    return url if isinstance(url, str) and url.startswith("https://") else None


def _shop_link(r: dict) -> str:
    u = _https(r.get("item_url")) or _https(r.get("source_url"))
    return f'<a href="{_e(u)}" target="_blank" rel="noopener nofollow">店のページ</a>' if u else ""


_DASH = '<b class="amt na">—</b>'


def _unit(c: dict) -> str:
    """商品の販売単位の表示（BOX・セット・デッキ）。読めなければ空。"""
    u = str(c.get("unit") or "")
    if u:
        return UNIT_LABEL.get(u, u)
    return "BOX" if c.get("product_type") == "BOOSTER_BOX" else ""


def _amt(price, unit: str = "", cls: str = "amt") -> str:
    """金額に単位を付ける（`BOX ¥7,100`）。単位は別の要素にして、金額の文字は ¥ から始める。"""
    u = f'<small class="u">{_e(unit)}</small>' if unit else ""
    return f'<b class="{cls}">{u}{_yen(price)}</b>'


def _strip(c: dict, g: str, cfg: dict) -> str:
    """利益の比較: 公式定価 → 最高買取（受付確認済みの最高額の 1 店）→ 純利益（ROI・売却先）。金額には単位を付ける。
    最高買取の欄には、受付を確認できた・定価と同じ単位の金額だけを出す。受付停止・単位違いは「—」と短い理由だけ（金額は「その他の売却先」の中）。
    最高買取の店が利益の基準店と違えば、差額を別行で出す。「未確認」は 1 商品で 1 回まで（定価の欄）。値が無い欄は灰色の「—」。"""
    pr, bbv, m = c["profit"], c.get("buyback"), c.get("msrp")
    gb, gp = f"{g}-b", f"{g}-p"
    ex = (bbv or {}).get("highest_executable")
    net = pr.get("net_profit")
    unit = _unit(c)
    if m:
        v_msrp = _amt(m["retail_price"], unit)
    elif c.get("pack_price"):                                    # BOX の定価は無い。公式の 1 パック価格だけ（パック価格×入数で BOX の定価を作らない）
        v_msrp = f'<b class="amt pack">1パック {_yen(c["pack_price"])}</b>'
    else:
        v_msrp = f'{_DASH}<small>未確認</small>'
    if ex and not _mismatch(c):
        src = "・1店のみ" if bbv.get("single_source") else ""
        exu = UNIT_LABEL.get(str(ex.get("unit") or ""), str(ex.get("unit") or "")) or unit
        inner = _amt(ex["price"], exu) + f'<small>{_e(ex["shop_name"])}{src}</small><small>{_shop_link(ex)}</small>'
        v_best = _live(gb, ex["checked_at"], cfg, inner) + _stale(gb, cfg, _stale_txt(ex["checked_at"]))
    elif ex:                                                     # 定価は 1 パック・買取は BOX 等: 比べられない
        v_best = _DASH + _best_label(gb, ex.get("checked_at"), cfg, "単位違い")
    elif bbv and bbv.get("outlier"):
        v_best = _DASH + _best_label(gb, (bbv.get("outlier") or {}).get("checked_at"), cfg, "確認待ち")
    elif bbv and _suspended_top(bbv):                             # 受付停止中の店の価格だけ（金額は「その他の売却先」の中）
        r = _suspended_top(bbv)
        v_best = _DASH + _best_label(gb, r.get("checked_at"), cfg, "受付停止中" if _susp_label(r) == "受付停止" else "受付状態不明")
    else:
        v_best = _DASH
    rows = [("公式定価", v_msrp, "msrp"), ('最高買取<span class="emx">（受付確認済み）</span>', v_best, "best")]
    if net is not None:
        neg = net <= 0
        inner = (f'<b class="amt {"neg" if neg else "pos"}">{_e(pr["label"])}</b>'
                 f'<small>ROI {_roi_pr(pr)}・{_e(pr.get("sell_shop_name") or "")}{"・赤字" if neg else ""}</small>')
        v_profit = _live(gp, pr.get("sell_observed_at"), cfg, inner) + _stale(gp, cfg, _stale_txt(pr.get("sell_observed_at")))
    elif ex and m:
        v_profit = '<b class="amt na">算出前</b>'       # 最高買取と定価はあるが利益を出せない（費用の根拠なし等）
    else:
        v_profit = _DASH                                # 定価が無い・単位が違う（1 パックと BOX）・買取が無い: 利益は出さない
    rows.append(("純利益", v_profit, "profit"))
    if net is not None and ex and m and pr.get("sell_shop") != ex.get("shop"):
        diff = ex["price"] - m["retail_price"]
        inner = f'<b class="amt">{diff:+,}円</b><small>{_e(ex["shop_name"])}・費用未確認</small>'
        v_diff = _live(gb, ex["checked_at"], cfg, inner) + _stale(gb, cfg, "再確認待ち")
        rows.append(("差額", v_diff, "diff"))
    cls = "tc-strip is-wait" if c.get("state") == pv.O_WATCH else "tc-strip"
    lis = "".join(f'<li data-strip-{k}><em>{lbl}</em><span class="tc-val">{v}</span></li>' for lbl, v, k in rows)
    return f'<ul class="{cls}" data-strip>{lis}</ul>'


def _best_label(g: str, obs, cfg: dict, label: str) -> str:
    """最高買取の欄の理由（単位違い・確認待ち・受付停止中・受付状態不明）。買取の取得に基づくので、鮮度の判定の中に置く（鮮度切れでは「再確認待ち」）。"""
    if not obs:
        return f'<small>{_e(label)}</small>'
    return _live(g, obs, cfg, f'<small>{_e(label)}</small>') + _stale(g, cfg, _stale_txt(obs))


def _mismatch(c: dict) -> bool:
    """定価が 1 パック価格だけで、商品の単位の定価が無い（買取 BOX と比べられない）。"""
    return not c.get("msrp") and bool(c.get("pack_price"))


def _roi_pr(pr: dict) -> str:
    """ROI の表示（整数の %）。丸める前の純利益と仕入れ値から 1 回だけ丸める（判定に使う roi_pct は変えない）。"""
    net, acq = pr.get("net_profit"), pr.get("acquisition_cost")
    if isinstance(net, (int, float)) and isinstance(acq, (int, float)) and not isinstance(acq, bool) and acq > 0:
        return f"{net / acq * 100:.0f}%"
    return _roi(pr.get("roi_pct") or 0)


def _susp_label(r: dict) -> str:
    """買取として扱わない行の短いラベル。停止と書かれていれば「受付停止」、受付状態が読めないだけなら「受付状態不明」（停止と断定しない）。"""
    t = (r or {}).get("suspended_text") or "お申込一時停止中"
    return "受付停止" if "停止" in t else "受付状態不明"


def _suspended_top(bbv: dict) -> Optional[dict]:
    """受付停止中の店の行のうち最高額（最高買取が無いときに灰色で見せるだけ。計算には使わない）。"""
    rows = [r for r in (bbv or {}).get("others") or [] if r.get("suspended") and isinstance(r.get("price"), int)]
    return max(rows, key=lambda r: r["price"]) if rows else None


def _other_state(r: dict, ex, outlier) -> tuple:
    """(種別, 短いラベル)。実行可能・外れ値の疑い・受付停止・参考（条件未確認・掲載のみ・鮮度切れ）。"""
    from src.tcg import buyback as _bb
    if outlier and r["shop"] == outlier["shop"] and r.get("executable"):
        return "outlier", "確認待ち"
    if r.get("executable"):
        return "executable", "受付中" if r.get("accept_state") == "ACTIVE" else "買取可"
    if r.get("suspended"):
        return "suspended", _susp_label(r)
    if r.get("condition") not in _bb.EXECUTABLE_CONDITIONS:
        return "reference", "参考"
    return "reference", "参考"


def _others(c: dict, g: str, cfg: dict) -> str:
    """折りたたみの『その他の売却先』。受付確認済み（実行可能）と、参考（受付・条件未確認・受付停止・外れ値）の 2 段。
    参考は灰色の小さい文字で、最高買取・利益には数えない。受付状態のラベルも鮮度の判定の中。費用が分かる店（利益の基準店）以外は純利益「—」。
    単位違いの商品は、最高買取の欄に金額を出さない代わりに、ここに「単位違い」の行として出す。"""
    bbv = c.get("buyback")
    if not bbv:
        return ""
    ex, outlier = bbv.get("highest_executable"), bbv.get("outlier")
    mism = _mismatch(c)
    sell_shop = (c.get("profit") or {}).get("sell_shop")
    rows = [r for r in bbv.get("others") or [] if mism or not (ex and r["shop"] == ex["shop"] and r.get("executable"))]
    if mism and ex and not any(r is ex or (r["shop"] == ex["shop"] and r.get("executable") and r.get("price") == ex["price"]) for r in rows):
        rows = [ex] + rows
    if not rows:
        return ""
    ok_l, ref_l = [], []
    for k, r in enumerate(rows):
        gk = f'{g}-o{k}'
        kind, label = _other_state(r, ex, outlier)
        if mism and kind == "executable":
            label = "単位違い（定価と比較不可）"
        same = bool(ex) and r["shop"] == ex["shop"] and not mism
        if kind == "outlier":
            body = f'<small>{_e(label)}</small>'
        else:
            over = kind != "executable" and bool(ex) and isinstance(r.get("price"), int) and r["price"] > ex["price"]
            pre = '<small class="unv">受付未確認</small>' if over else ""
            inner = (f'{pre}<b class="amt{" sm" if over else ""}">{_yen(r["price"])}</b><small>{_e(_unit(r) or _unit(c))}・{_vshort(r["checked_at"])}</small>'
                     f'<small>{_e(label)}</small>')
            body = _live(gk, r["checked_at"], cfg, inner) + _stale(gk, cfg, _stale_txt(r["checked_at"]))
        if not (kind == "executable" and r["shop"] == sell_shop):
            body += '<small title="費用未確認のため純利益は算出しません">純利益 —</small>'
        if same:
            body += '<small>同じ店の別条件</small>'
        li = (f'<li data-other-shop="{_e(r["shop"])}" data-other-kind="{kind}"><b>{_e(r["shop_name"])}</b>'
              f'<span class="tc-val">{body}</span>{_shop_link(r)}</li>')
        (ok_l if kind == "executable" else ref_l).append(li)
    out = ""
    if ok_l:
        out += f'<p class="oh">受付確認済み</p><ul>{"".join(ok_l)}</ul>'
    if ref_l:
        out += f'<p class="oh">参考（受付・条件未確認）</p><ul class="ref">{"".join(ref_l)}</ul>'
    return (f'<details class="tc-others" data-others><summary>その他の売却先（{len(rows)}）</summary>{out}</details>')


def _lot_badge_label(i: dict) -> str:
    if i["eff_status"] == ls.L_UNKNOWN:
        if i["conflict"]:
            return "日程に食い違い"
        if not i["verified"] and i["status"] in st.INTAKE:
            return "未確認"
        return "日程未確認"
    if i["winner_only"]:
        return "当選者のみ"
    return i["status_label"]


def _lot_item(i: dict, yr: str) -> str:
    eff = i["eff_status"]
    tone = "out" if eff == ls.L_UNKNOWN else "warn" if (i["winner_only"] or i.get("deadline_only")) else _tone(eff)
    ok = i["verified"] and not i["conflict"]
    if eff == ls.L_UPCOMING:
        when = f'開始 {_md(i["start"], yr, ok)}・締切 {_md(i["end"], yr, ok)}'
    elif i["winner_only"]:
        when = f'購入 {_range(i["purchase_start"], i["purchase_end"], yr, ok)}'
    else:                                                        # 日程未確認は締切を断定しない（締切済みとも言わない）
        when = f'締切 {_md(i["end"], yr, ok)}'
    if eff in (ls.L_OPEN, ls.L_ENDING_SOON, ls.L_UPCOMING, ls.L_WINNER_PURCHASE_PERIOD) or i["winner_only"]:
        until, exp_msg = _lot_until(ls.L_WINNER_PURCHASE_PERIOD if i["winner_only"] else eff, i["end"], i["purchase_end"])
    else:
        until = exp_msg = ""
    btn = _lot_buttons(eff, i["verified"], i["conflict"], i["application_url"], i["announcement_url"], until, _md(i["end"], yr, ok),
                       bool(i.get("deadline_only")))
    badge_html = _rb_wrap(_badge(_lot_badge_label(i), tone), until, _badge(exp_msg, "gray")) if until else _badge(_lot_badge_label(i), tone)
    rb_attrs = f' data-rb-card data-rb-until="{_e(until)}"' if until else ""
    va = f' data-retailer="{_e(i.get("retailer") or "")}" data-verified="{1 if i["verified"] else 0}"' + (" data-conflict" if i["conflict"] else "") + (" data-deadline-only" if i.get("deadline_only") else "")
    return (f'<li data-lot-item data-lot-status="{_e(eff)}"{va}{rb_attrs}><b>{_e(i["shop"])}</b>{badge_html}'
            f'<small>{when}</small><a href="{PAGE_LOTTERY}#{_e(_lot_anchor(i.get("lottery_id")))}">詳細</a>{btn}</li>')


def _lot_show(items: list) -> list:
    """カードに出す抽選（最大 3 件）。並びの先頭から 3 件（受付中・締切間近は段階 0 で先頭に並ぶので、必ず含まれる。3 件を超えるときは締切が近い順の 3 件）。
    日程未確認があるのに 3 件の外に隠れるときは、3 件目と入れ替えて 1 件は見せる（入れ替えで落ちるのは、受付中・締切間近が 4 件以上のときの 3 件目だけ。
    受付中・締切間近を全部落とすことはない）。"""
    idx = list(range(min(3, len(items))))
    unk = [k for k, i in enumerate(items) if i["eff_status"] == ls.L_UNKNOWN]
    if unk and idx and not any(k in unk for k in idx):
        idx[-1] = unk[0]
    return [items[k] for k in idx]


def _md_until(until: str) -> str:
    """data-rb-until の値の短い表示（`11/26 23:59`・日付のみは `11/26`）。"""
    d = until[5:10].replace("-", "/")
    t = until[11:16] if len(until) > 10 else ""
    if t == "00:00":                                          # 時刻付きの 0 時は「0:00」（失効時刻と一致させる）
        return d + " 0:00"
    return d + (" " + t if show_time(t) else "")


def _lot_block(c: dict, yr: str, pk: Optional[str], unbound_applying: int, rb_open: Optional[list] = None, ann: Optional[dict] = None, box: bool = False) -> str:
    """抽選の要約（名前の下の 1 行「抽選 受付中1件・締切 11/26 23:59」）と、販売店の抽選へのリンク（別の行）。抽選の一覧は _lot_details。"""
    cn = c["counts"]
    items_all = c.get("lottery_items") or []
    untils = []

    def chip(n, lbl, tone, eff=None, field="end", deadline_only=False):
        if not n:
            return ""
        # 受付中・締切間近の締切に、締切だけ分かる行の締切を混ぜない（件数と同じ行から締切を取る）
        until = (_earliest_until(_until_iso(i[field]) for i in items_all
                                 if (i.get("deadline_only") if deadline_only else (i["eff_status"] == eff and not i.get("deadline_only"))))
                 if (eff or deadline_only) else "")
        if not until:                                            # 締切が読めない件数は静的のまま（失効を判定できない）
            return f'<span class="chip {tone}">{lbl}<b>{n}</b>件</span>'
        untils.append(until)
        dl = ("・締切 " + _e(_md_until(until))) if (field == "end" and (eff in st.APPLYING or deadline_only)) else ""
        # 件数は再計算しない。期限後はこの件数を消し、「期限切れの抽選あり」は 1 行の末尾に 1 回だけ出す
        return (f'<span class="chip {tone}" data-rb-card data-rb-until="{_e(until)}"><span data-rb-open>{lbl}<b>{n}</b>件{dl}</span>'
                f'<span data-rb-expired hidden></span></span>')
    chips = (chip(cn.get("open"), "受付中", "info", ls.L_OPEN) + chip(cn.get("ending_soon"), "締切間近", "danger", ls.L_ENDING_SOON)
             + chip(cn.get("result_pending"), "当選発表待ち", "warn")
             + chip(cn.get("purchase_period"), "購入期間中（当選者のみ）", "warn", ls.L_WINNER_PURCHASE_PERIOD, "purchase_end")
             + chip(cn.get("upcoming"), "近日開始", "info", ls.L_UPCOMING))
    if cn.get("deadline_only"):                                  # 締切だけ分かる行（受付開始の根拠なし）。受付中の数には入れない
        # ほかのチップと同じく、締切を過ぎたら表示時に消える（締切が読めなければ静的）
        chips += chip(cn["deadline_only"], "締切前（開始日未確認）", "warn", deadline_only=True).replace(
            '<span class="chip warn"', '<span class="chip warn" data-chip-deadline-only', 1)
    if cn.get("unknown"):                                        # 受付中の数には入れない（応募できると断定しない）
        chips += f'<span class="chip warn" data-chip-unknown>日程未確認 <b>{cn["unknown"]}</b></span>'
    if untils:
        first = _earliest_until(untils)
        chips += (f'<span class="chip exp" data-rb-card data-rb-until="{_e(first)}"><span data-rb-expired hidden>{RB_EXPIRED_GROUP}</span></span>')
    out = f'<div class="chips"><span class="lbl">抽選</span>{chips}</div>' if chips else ""
    if rb_open:       # 販売店の告知（BOX 価格の節）で応募受付中の行。抽選の紐付け・チップ・受付中の数には入れない（別の行のリンクだけ）
        until = _earliest_until(str(r.get("apply_end") or "").strip() for r in rb_open)       # 販売店の行の apply_end の原値を JS_RB に渡す
        src = next((r.get("source_url") for r in rb_open if isinstance(r.get("source_url"), str) and r["source_url"].startswith("https://")), None)
        lab = "販売店の抽選（条件付き）"
        hint = f'<a href="#retailer-box">{lab}</a>' if box else (_link(src, lab) if src else lab)
        if until:         # OPEN は静的に「受付中」と書かない。期限後は JS_RB が切り替える（複数行は最も早い期限で切り替える）
            out += (f'<p class="pnote" data-rb-hint data-rb-card data-rb-until="{_e(until)}"><span data-rb-open>{hint}</span>'
                    f'<span data-rb-expired hidden>販売店の抽選は応募期限を過ぎました</span></p>')
        else:
            out += f'<p class="pnote" data-rb-hint>{hint}</p>'
    return f'<div class="tc-lot" data-lot>{out}</div>'


def _lot_details(c: dict, yr: str, pk: Optional[str]) -> str:
    """この商品の抽選（閉じた折りたたみ。最大 3 件と、抽選のページの絞り込みへのリンク）。"""
    items = c.get("lottery_items") or []
    if not items:
        return ""
    more = (f'<a href="{PAGE_LOTTERY}#prod-{_e(pk)}">この商品の抽選をすべて見る（{len(items)}）</a>' if pk else "")
    return (f'<details class="tc-lotd" data-lot-details><summary>この商品の抽選（{len(items)}）</summary>'
            f'<ul>{"".join(_lot_item(i, yr) for i in _lot_show(items))}</ul>{more}</details>')


def _card(c: dict, dom_id: str, pk: Optional[str], yr: str, cfg: dict, unbound_applying: int, rb_open: Optional[list] = None, ann: Optional[dict] = None, box: bool = False) -> str:
    """1 商品 1 行のカード（画像 | 名前・発売日 | 定価 | 最高買取 | 利益 | 抽選状況）。その他の売却先と抽選は行の中の閉じた折りたたみ。"""
    g = dom_id
    state, pr = c.get("state"), c["profit"]
    net = pr.get("net_profit")
    badge = ""
    if state and net is not None:
        neg = net <= 0
        label = "赤字" if neg else c["state_label"]
        tone = "pf" if (state == pv.O_PROFIT and not neg) else "ls" if neg else "warn"
        gp = f"{g}-p"                                            # 利益と同じ取得時刻（sell_observed_at）なので同じ group
        badge = (_live(gp, pr.get("sell_observed_at"), cfg, f'<b class="sb {tone}">{_e(label)}</b>')
                 + _stale(gp, cfg, '<b class="sb out">確認待ち</b>'))
    ptype = PTYPE_LABEL.get(c["product_type"], "") if c.get("product_type") else ""      # 日本語ラベルが無い種別は、生の値を出さず省く
    meta = [_e(TCG_SHORT.get(c["tcg"], c["tcg"]))]
    if ptype:
        meta.append(_e(ptype))
    meta_html = "・".join(meta)
    if c.get("release_date"):
        meta_html += "・発売 " + _md({"date": c["release_date"], "time": None}, yr)
    off = _product_link(c.get("official_url") or (c.get("msrp") or {}).get("official_url"))
    st_attr = "profit" if state == pv.O_PROFIT else ("watch" if state == pv.O_WATCH else "none")
    more = _others(c, g, cfg) + _lot_details(c, yr, pk)
    return (f'<article class="tcard" id="{g}" data-card data-card-key="{_e(c["tcg"])}:{_e(c["product_id"])}" data-card-state="{st_attr}">'
            f'<div class="tc-img">{_img_block(c)}</div><div class="tc-id"><div class="tc-tags">{badge}</div>'
            f'<h3>{_e(c["name"])}</h3><p class="tc-meta">{meta_html}{off}</p>{_lot_block(c, yr, pk, unbound_applying, rb_open, ann, box)}</div>'
            f'{_strip(c, g, cfg)}'
            + (f'<div class="tc-more">{more}</div>' if more else "") + '</article>')


# 締切のある表示を、表示時にも判定する（生成から時間が経っても、期限後の「受付中」・応募ボタン・条件付きの利益を見せない）
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


def _rb_target(r: dict) -> str:
    """台帳の行の商品が人に確認されていないときの、利用者向けの短いラベル（商品名を断定しない）。"""
    return '<p class="pnote">対象商品は公式で確認</p>' if (r or {}).get("human_confirmed") is not True else ""


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
    """同じ告知 URL の抽選の告知名が複数商品を指すとき、その告知名を短く併記する（どの商品の価格かは推測しない）。無ければ空。"""
    names = _rb_ann_names(r, ann)
    if not names:
        return ""
    return f"告知名{'／'.join('「' + n + '」' for n in names)}・対象商品は未確認"


def _rb_link(url) -> str:
    return (f'<a href="{_e(url)}" rel="noopener noreferrer" target="_blank">告知</a>'
            if isinstance(url, str) and url.startswith("https://") else '<span class="mut">根拠 URL なし</span>')


def _rb_card(o: dict, i: int, ann: Optional[dict] = None) -> str:
    """販売店の BOX 価格による「条件付き」の利益。公式定価とは別ラベル。緑の購入推奨にしない。応募期限は表示時にも判定する。"""
    cfg = _CFG()
    pr, bbv, r = o["profit"], o["buyback"], o["retailer"]
    ex = bbv["highest_executable"]
    mx = rf.thresholds(cfg)[0]
    g = f"rb{i}"
    # 鮮度の約束（#853）: グループは取得時刻が同じ・同じ種類の要素だけ（最高買取 = {g}-b・利益と ROI = {g}-p・状態バッジ = {g}-s）。
    # live の内側に <div>/<span> を入れない（バッジは <b>）。各 live の直後に同じグループの stale を置く
    gb, gp, gs = f"{g}-b", f"{g}-p", f"{g}-s"
    live_s = f'data-fb-live data-fb-group="{gs}" {rf.attrs(pr.get("sell_observed_at"), cfg)} hidden'
    live_p = f'data-fb-live data-fb-group="{gp}" {rf.attrs(pr.get("sell_observed_at"), cfg)} hidden'
    live_b = f'data-fb-live data-fb-group="{gb}" {rf.attrs(ex["checked_at"], cfg)} hidden'
    unit = _e(o["unit"])
    neg = pr["net_profit"] <= 0
    until = _e(str(r.get("apply_end") or ""))
    badge = (f'<span {live_s}><b class="sb warn">{_e("条件付き" + ("（赤字）" if neg else ""))}</b></span>'
             f'<span data-fb-stale data-fb-group="{gs}" data-fb-max="{mx:g}"><b class="sb out">確認待ち</b></span>')
    meta = f'<div><dt>販売店価格</dt><dd>{_yen(r["price_jpy"])}<small>{_e(r["shop"])}・{unit}</small></dd></div>'
    apply_end = r.get("apply_end")
    deadline = f"締切 {_e(_apply_deadline(apply_end))}" if apply_end else "締切未確認"
    start = "・開始日未確認" if r.get("start_unconfirmed") else ""
    meta += (f'<div><dt>応募</dt><dd><span data-rb-open>{_e(r["accept_label"])}・{deadline}{start}</span><span data-rb-expired hidden>応募期限を過ぎました</span>'
             f'<small>購入 {_e(_short(r.get("purchase_start")))}〜{_e(_short(r.get("purchase_end")))}・{_e(r.get("shipping") or "受取未確認")}</small></dd></div>')
    meta += (f'<div {live_b}><dt>最高買取</dt><dd>{_yen(ex["price"])}<small>{_e(ex["shop_name"])}</small></dd></div>'
             f'<div data-fb-stale data-fb-group="{gb}" data-fb-max="{mx:g}"><dt>最高買取（再確認）</dt><dd>価格再確認待ち</dd></div>')
    meta += (f'<div {live_p}><dt>条件付きの純利益</dt><dd title="{_e(pr.get("route") or "")}">{_e(pr["label"])}'
             f'<small>当選した場合{"・赤字" if neg else ""}・ROI {_roi(pr["roi_pct"])}</small></dd></div>'
             f'<div data-fb-stale data-fb-group="{gp}" data-fb-max="{mx:g}"><dt>純利益・ROI</dt><dd>価格再確認待ち</dd></div>')
    tail = ""
    return (f'<section class="pcard opp" id="{g}" data-rb-card data-rb-until="{until}">{_img_block(o)}<div class="phead">'
            f'<div class="tc-tags">{badge}{_badge("当選時のみ", "out")}</div><h3>{_e(o["name"])}</h3>{_rb_target(r)}</div>'
            f'<div class="pmeta"><dl>{meta}</dl>{tail}</div><div class="pfoot">{_rb_link(r.get("source_url"))}</div></section>')


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
            state = (f'<span data-rb-open>（応募期限 {_e(_apply_deadline(end)) if end else "未確認"}）</span>'
                     f'<span data-rb-expired hidden>（応募期限を過ぎました）</span>')
            attrs = f' data-rb-card data-rb-until="{_e(str(end or ""))}"'
        else:
            state = "" if rejected else f'（{_e(r.get("accept_label") or "")}）'
            attrs = ""
        an = _rb_ann(r, ann)
        return (f'<li{attrs}>{_e(r.get("shop") or "")}・{_e(name)}{_e(_rb_unbound(r))}{"・" + price if price else ""}'
                f'{state} <small class="mut">{_e(r.get("reason") or "")}{("・" + _e(an)) if an else ""}・確認 {_e(_short(r.get("verified_at")))}</small> {_rb_link(r.get("source_url"))}</li>')
    # OPEN（応募期間中）で利益を計算できない行は、「過去の参考情報」に混ぜず別の小見出しにする
    open_refs = [r for r in refs if r.get("kind") != "REJECTED" and r.get("accept_state") == "OPEN"]
    past_refs = [r for r in refs if r not in open_refs]
    html = ""
    if open_refs:
        until = _earliest_until(str(r.get("apply_end") or "").strip() for r in open_refs)       # 各行の _item と同じく apply_end の原値。節の見出しは最も早い期限で切り替える
        head = f'応募受付中だが条件付き利益を計算できない（{len(open_refs)}）'
        if until:         # 件数は再計算しない（fail-closed）。期限後は「受付中」と書かず、下の行で再確認させる
            head = (f'<span data-rb-card data-rb-until="{_e(until)}"><span data-rb-open>{_e(head)}</span>'
                    f'<span data-rb-expired hidden>{RB_EXPIRED_SECTION_HEAD}（{len(open_refs)}）</span></span>')
        else:
            head = _e(head)
        html += (f'<details class="note" open id="retailer-open-refs"><summary>{head}</summary>'
                 f'<ul>{"".join(_item(r) for r in open_refs)}</ul></details>')
    if past_refs:
        html += (f'<details class="note"><summary>過去の参考情報（販売店の BOX 価格・{len(past_refs)}）</summary>'
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
            f'<ul>{"".join(_item(e) for e in errs)}</ul></details>')


# ───────────────────────── 抽選カレンダー ─────────────────────────
def _cal_item(c: dict) -> str:
    t0 = show_time(c["time"], c["verified"])                    # 00:00 は日付のみ（未確認行・補完の 0 時を時刻に見せない）
    t = f'<span title="{_e(c["time"])}">{_e(t0)}</span> ' if t0 else ''
    store = c["store"] if not pv._is_enum_like(c["store"], "") else ""                       # 列挙値（POKEMON_CENTER_ONLINE 等）は副表示にも出さない
    where = " ".join(x for x in (c["retailer"], store) if x)
    label = _e(c["label"])
    if c.get("lottery_id"):                                     # カレンダーの項目から一覧の該当行へ
        label = f'<a href="#{_e(_lot_anchor(c["lottery_id"]))}">{label}</a>'
    return (f'<li><span class="k k-{c["kind"]}">{_e(CAL_SHORT[c["kind"]])}</span> {t}<b>{label}</b>'
            f'{" <span class=mut>" + _e(where) + "</span>" if where else ""}{"" if c["verified"] else " <span class=mut>（未確認）</span>"}</li>')


def _cal_list(cal: list) -> str:
    out, cur = [], None
    for c in cal:
        if c["date"] != cur:
            if cur is not None:
                out.append("</ul>")
            cur = c["date"]
            out.append(f'<h3>{_e(cur[5:].replace("-", "/"))}（{_e(_wd(cur))}）</h3><ul>')
        out.append(_cal_item(c))
    out.append("</ul>")
    return "".join(out)


def _cal_grid(cal: list, today: str) -> list:
    """月ごとのグリッド（最大 3 か月）。予定の無い週は畳む。セルには種類の短い文字と件数（締2・始1）。月ごとの HTML のリスト。"""
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
                    cells += f'<div{cls} data-day="{key}"><span class="d">{d}</span></div>'
                    continue
                kinds: dict = {}
                for c in items:
                    kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
                chips = "".join(f'<span class="k k-{k}"><span class="kl">{_e(CAL_SHORT[k])}</span><span class="ks">{_e(CAL_TINY.get(k, ""))}</span>{n}</span>'
                                for k, n in kinds.items())
                aria = f"{m}/{d} " + " ".join(f"{CAL_SHORT[k]}{n}" for k, n in kinds.items())
                cells += (f'<div{cls} data-day="{key}"><details><summary aria-label="{_e(aria)}"><span class="d">{d}</span>{chips}</summary>'
                          f'<ul>{"".join(_cal_item(c) for c in items)}</ul></details></div>')
        out.append(f'<div class="cal-month"><h3>{y}年{m}月</h3><div class="cg">{cells}</div></div>')
    return out


def _agenda(cal: list, today: str) -> str:
    try:
        end = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d")
    except ValueError:
        return ""
    soon = [c for c in cal if today <= c["date"] <= end and c["kind"] != pv.K_RELEASE]
    if not soon:
        return ""
    return f'<details class="note agenda"><summary>今後 7 日の抽選（{len(soon)}）</summary>{_cal_list(soon)}</details>'


def _calendar(cal: list, today: str) -> str:
    cal = [c for c in cal or [] if c.get("kind") in CAL_KINDS]          # 開始・締切・当選（と控えめな発売）だけ。購入開始・購入終了は出さない
    if not cal:
        return '<p class="empty">予定なし</p>'
    legend = "".join(f'<span class="k k-{k}">{_e(CAL_SHORT[k])}</span>' for k in CAL_KINDS)
    months = _cal_grid(cal, today)
    grid = months[0] if months else ""
    if len(months) > 1:
        grid += f'<details class="note cal-more"><summary>翌月以降（{len(months) - 1} か月）</summary>{"".join(months[1:])}</details>'
    return (f'<div class="cal-legend">{legend}</div><div class="cal-grid">{grid}</div>'
            f'<details class="note callist"><summary>日付順の一覧（{len(cal)}）</summary>{_cal_list(cal)}</details>')


# ───────────────────────── 共通の部品 ─────────────────────────
def _upd(gen: str) -> str:
    """`2026-11-26 05:37 JST` → `11/26 05:37`。読めなければそのまま。"""
    m = re.search(r"\d{4}-(\d{2})-(\d{2})[ T](\d{2}:\d{2})", str(gen or ""))
    return f"{m.group(1)}/{m.group(2)} {m.group(3)}" if m else str(gen or "")


def _gen_line(hub: dict, gen: str) -> str:
    """見出しの時刻 = 抽選データを取得した時刻（「11/26 19:26 取得」。受付状態は表示・生成の時刻で日程から判定するので「時点」とは書かない）。ページを作り直しただけで新しく見せないため、生成時刻は出さない
    （生成時刻は最下部の 1 行）。取得時刻が読めなければ生成時刻を「生成」と書く。"""
    ck = str((hub.get("checked_at") or {}).get("lotteries_generated_at") or "")
    return f"{_e(_upd(ck))} 取得" if ck else f"{_e(_upd(gen))} 生成"


def _stale_banner(hub: dict) -> str:
    """元の抽選データが古いときは警告（収集が止まっても新鮮に見せない）。"""
    ck = hub["checked_at"]
    try:
        from datetime import date as _date
        gd = _date.fromisoformat(str(ck["lotteries_generated_at"] or "")[:10])
        nd = _date.fromisoformat(str(hub["now"])[:10])
        if (nd - gd).days >= 2:
            return f'<p class="warnbar">抽選データの取得が {(nd - gd).days} 日前です（取得 {_e(_short(ck["lotteries_generated_at"]))}）</p>'
        return ""
    except (ValueError, TypeError):
        return '<p class="warnbar">抽選データの取得日時が確認できません</p>'


def _tcg_nav(current: str, has_ranking: bool = True) -> str:
    """TCG 内のナビ。1 段目 = ページの切り替え（商品と利益 / 抽選）、2 段目 = そのページの中の絞り込み・移動。"""
    def tab(key, label, href):
        cur = ' aria-current="page"' if key == current else ""
        return f'<a href="{href}"{cur}>{label}</a>'
    tabs = tab("products", "商品と利益", PAGE_PRODUCTS) + tab("lottery", "抽選", PAGE_LOTTERY)
    if current == "products":
        sub = (('#cat-pokemon', 'ポケモンカード'), ('#cat-onepiece', 'ONE PIECEカード')) + ((('#ranking', '利益ランキング'),) if has_ranking else ())
    else:
        sub = ()                                                    # 抽選のページは 1 段だけ（ページ内の移動は上の「商品から選ぶ」「方式から選ぶ」）
    subs = "".join(f'<a class="sub" href="{h}">{lb}</a>' for h, lb in sub)
    js = f'<div class="js">{subs}</div>' if subs else ""
    return f'<nav class="jump" aria-label="TCG のページ"><div class="jt">{tabs}</div>{js}</nav>'


def _foot(hub: dict, gen: str, credit: bool) -> str:
    ck = hub["checked_at"]
    data = (f'抽選データ {_e(_short(ck["lotteries_generated_at"]))}・商品一覧 {_e(_short(ck["registry_generated_at"]))}'
            f'・定価 {_e(_short(ck["msrp_generated_at"]))}・画面生成 {gen}')
    cr = f'<p id="img-credit">{_e(IMG_CREDIT)}</p>' if credit else ""
    return f'<footer class="foot" id="page-foot"><p>{_e(FOOT_NOTE)}</p>{cr}<p>{data}</p></footer>'


def _doc(title: str, hub: dict, body: str, script: str) -> str:
    ck = hub["checked_at"]
    legacy = _shared.legacy_css()
    nav = _shared.site_nav("tcg")
    sc = f"<script>{script}</script>" if script else ""
    return ('<!doctype html><html lang="ja" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="color-scheme" content="light"><title>{_e(title)} | プレ値速報</title><meta name="robots" content="index,follow">'
            f'<meta name="tcg-source-generated-at" content="{_e(ck["lotteries_generated_at"] or "")}"><style>{legacy}{CSS}</style></head>'
            f'<body>{nav}<main>{body}</main>{sc}</body></html>')


def _flags(hub: dict) -> dict:
    flagmap: dict = {}
    for v in hub["today_list"]:
        flagmap.setdefault(id(v), set()).add("today")
    for v in hub["deadline_today"]:
        flagmap.setdefault(id(v), set()).add("deadline")
    for v in hub["new"]:
        flagmap.setdefault(id(v), set()).add("new")
    return flagmap


def _ordered(hub: dict, flagmap: dict) -> list:
    def _rank(v):                                               # 今日締切 → 受付中・締切間近 → 近日開始 → その他（結果待ち等）
        if "deadline" in flagmap.get(id(v), ()):
            return 0
        return 1 if v["status"] in st.APPLYING else 2 if v["status"] == ls.L_UPCOMING else 3 + _ST_ORDER.get(v["status"], 99)
    return sorted(hub["events"], key=lambda v: (_rank(v), v["end"]["date"] or "9999", v["end"]["time"] or "99"))


def _pidx(hub: dict) -> dict:
    return {(p["tcg"], p["product_id"]): f"p{i}" for i, p in enumerate(hub["products"])}


def _confirmed(v: dict) -> bool:
    return bool(v["verified"]) and not v["ev"].get("conflict")


# ───────────────────────── tcg.html（商品と利益） ─────────────────────────
def _soon_band(hub: dict, ordered: list, flagmap: dict, pidx: dict, yr: str, cards: Optional[dict] = None) -> str:
    """締切が近い抽選の帯（受付中・締切間近で確認済み・食い違いなしだけ。最大 3 行）。無ければ出さない。
    行頭に画像（商品に紐付いた抽選は商品の画像、紐付いていない抽選は代わりの画像）。cards = (tcg, product_id) → 商品のカード。"""
    cand = [v for v in ordered if v["status"] in st.APPLYING and _confirmed(v)]
    rows = ([v for v in cand if not v.get("deadline_only")] + [v for v in cand if v.get("deadline_only")])[:3]   # 締切だけの行は受付中の行の後ろ
    if not rows:
        return ""
    lis = []
    for v in rows:
        ev = v["ev"]
        fl = flagmap.get(id(v), set())
        lab, tone = (("締切前", "warn") if v.get("deadline_only") else ("今日締切", "danger") if "deadline" in fl
                     else ("締切間近", "danger") if v["status"] == ls.L_ENDING_SOON else ("受付中", "info"))
        until, _m = _lot_until(v["status"], v["end"], v["purchase_end"])
        b0 = _badge(lab, tone)
        if v.get("deadline_only"):                                   # 帯では短く「締切前」。開始日未確認であることは title で補う
            b0 = b0.replace('<span class="sb', f'<span title="{_e(pv.DEADLINE_ONLY_LABEL)}" class="sb', 1)
        badge = _rb_wrap(b0, until, _badge(RB_EXPIRED_APPLY, "gray"))
        name = _e(ev.get("product_name") or "商品名不明")
        btn = _lot_buttons(v["status"], v["verified"], ev.get("conflict"), v["application_url"], v["announcement_url"], until, _md(v["end"], yr, True),
                           bool(v.get("deadline_only")))
        left = f'<small class="left" data-left-until="{_e(until)}"></small>' if (until and not v.get("deadline_only")) else ""
        rb = f' data-rb-card data-rb-until="{_e(until)}"' if until else ""
        card = (cards or {}).get((ev.get("tcg"), ev.get("product_id"))) if v.get("canonical") in (pv.C_MASTER, pv.C_DISCOVERED) else None
        img = _img_block(card) if card else _ev_img(ev)
        lis.append(f'<li class="sr" data-lot-state="{_e(v["status"])}" data-verified="1" data-retailer="{_e(ev.get("retailer") or "")}"'
                   f'{" data-deadline-only" if v.get("deadline_only") else ""}{rb}>{img}<div class="sr-t">{badge}'
                   f'<a class="nm" href="{PAGE_LOTTERY}#{_e(_lot_anchor(v.get("lottery_id")))}">{name}</a>'
                   f'<small>{_e(pv.retailer_label(ev))}・締切 {_md(v["end"], yr, True)}{left}</small></div>{btn}</li>')
    return (f'<section class="soon" id="soon" aria-label="締切が近い抽選"><div class="soon-h"><h2>締切が近い抽選</h2>'
            f'<a href="{PAGE_LOTTERY}#lottery">抽選をすべて見る</a></div><ul>{"".join(lis)}</ul>'
            '<p class="pnote" data-soon-expired hidden>締切を過ぎた抽選 <b>0</b>件</p>'
            f'<p class="pnote" data-soon-none hidden>受付中の抽選はありません・<a href="{PAGE_LOTTERY}#lottery">抽選ページへ</a></p></section>')


def short_name(name: str, names: list) -> str:
    """表示用の短い名前。ほかの商品と共通の長い接頭辞（「30th CELEBRATION カードセット 」など）を省き、違う部分だけにする（データは変えない）。"""
    name = str(name or "")
    best = 0
    for o in names:
        o = str(o or "")
        if o == name:
            continue
        k = 0
        while k < min(len(o), len(name)) and o[k] == name[k]:
            k += 1
        best = max(best, k)
    if best < 10:
        return name
    cut = max(name.rfind(" ", 0, best + 1), name.rfind("　", 0, best + 1))
    rest = name[cut + 1:].strip("「」 　") if cut > 0 else ""
    return rest if len(rest) >= 2 else name


def _thumbs(card_list: list, doms: list) -> str:
    """画像で選ぶ（横スクロールの帯）。各商品の行へのアンカー。金額は出さない。"""
    if not card_list:
        return ""
    names = [c["name"] for c in card_list]
    a = "".join(f'<a class="th" href="#{_e(d)}" data-pt title="{_e(c["name"])}">{_img_block(c)}<span>{_e(short_name(c["name"], names))}</span></a>'
                for c, d in zip(card_list, doms))
    return f'<nav class="thumbs" aria-label="画像で選ぶ">{a}</nav>'


def _stale_note(card_list: list) -> str:
    """表の上の 1 行（鮮度が切れた価格が 1 つでもあるときだけ JS_STALE_NOTE が出す。最初は隠す）。取得時刻は最も古い買取の取得時刻（新しく見せない）。"""
    obs = []
    for c in card_list:
        ex = ((c.get("buyback") or {}).get("highest_executable") or {})
        for v in (ex.get("checked_at"), (c.get("profit") or {}).get("sell_observed_at")):
            if v and rf.parse_aware(v):
                obs.append(rf.parse_aware(v))
    txt = f"買取価格は {_vshort(min(obs).isoformat())} の取得のため再確認待ち" if obs else "買取価格は再確認待ち"
    return f'<p class="stale-note" data-stale-note hidden>{txt}</p>'


def _list_head() -> str:
    return ('<div class="pl-head" aria-hidden="true"><span></span><span>商品</span><span>公式定価</span><span>最高買取（受付確認済み）</span>'
            '<span>純利益</span></div>')


def _no_info(c: dict) -> bool:
    """初期表示にしない商品（「ほかの商品」の折りたたみへ）: 利益が出ない（買取なし・単位違い・受付停止だけ・算出前・赤字）かつ、受付中・締切間近の抽選が無い。"""
    cn = c.get("counts") or {}
    net = (c.get("profit") or {}).get("net_profit")
    # 締切だけ分かる抽選（締切前）も、確認済みで締切が分かるので初期表示に残す（受付中とは数えないが隠さない）
    return not (isinstance(net, (int, float)) and net > 0) and not (cn.get("open") or cn.get("ending_soon") or cn.get("deadline_only"))


def _ranking(card_list: list, doms: list, cfg: dict) -> str:
    """利益ランキング（純利益が正の商品だけ。並びは商品の行と同じ = 利益の大きい順）。金額は鮮度の判定の中だけ。
    全行の鮮度が切れたら、節ごと隠す（JS_STALE_NOTE）。"""
    rows = []
    for c, dom in zip(card_list, doms):
        pr, m = c["profit"], c.get("msrp")
        net = pr.get("net_profit")
        if net is None or net <= 0 or not m:
            continue
        g = f"rk-{dom}"
        obs = pr.get("sell_observed_at")
        prof = (_live(g, obs, cfg, f'<b class="{"pos" if c.get("state") == pv.O_PROFIT else "wt"}">{_e(pr["label"])}</b><small>ROI {_roi_pr(pr)}・{_e(pr.get("sell_shop_name") or "")} {_yen(pr["sell_price"])}</small>')
                + _stale(g, cfg, "再確認待ち"))
        lab = c.get("state_label") or ""
        state = _live(g, obs, cfg, f'<b class="sb {"pf" if c.get("state") == pv.O_PROFIT else "warn"}">{_e(lab)}</b>') + _stale(g, cfg, "—")
        unit = _unit(c)
        rows.append(f'<tr><td class="nm"><a href="#{_e(dom)}">{_e(c["name"])}</a></td><td class="n" data-label="定価">{_e(unit + " ") if unit else ""}{_yen(m["retail_price"])}</td>'
                    f'<td class="n" data-label="純利益">{prof}</td><td class="st">{state}</td></tr>')
    if not rows:
        return ""
    return ('<section class="rk-sec" data-rk><h2 id="ranking">利益ランキング</h2><table class="rk"><thead><tr><th>商品</th><th>公式定価</th><th>純利益</th><th>状態</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></section>')


def _unbound_untils(hub: dict, tcg: str) -> list:
    """商品ページの無い（商品未特定の）受付中の抽選の締切（その TCG のもの。TCG が読めない告知は全 TCG に数える）。締切が無い抽選は "-"。"""
    out = []
    for v in hub.get("events") or []:
        ev = v.get("ev") or {}
        if v.get("canonical") in (pv.C_MASTER, pv.C_DISCOVERED) and ev.get("product_id"):
            continue
        if v.get("status") not in st.APPLYING or not _confirmed(v) or v.get("deadline_only"):   # 締切だけの行は受付中に数えない
            continue
        if (ev.get("tcg") or "") not in (tcg, ""):
            continue
        out.append(_until_iso(v["end"]) or "-")
    return out


def _cnt(untils: list, hide: str = "") -> str:
    """件数（期限を過ぎたものは表示時に JS が数えから外す。JS が無ければ生成時点の件数）。hide = 0 件で隠す祖先のセレクタ。"""
    h = f' data-cnt-hide="{_e(hide)}"' if hide else ""
    return f'<span data-cnt-untils="{_e(" ".join(untils))}"{h}>{len(untils)}</span>'


def render(hub: dict, *, generated_label: Optional[str] = None) -> str:
    """docs/tcg.html（商品と利益）。hub は build_hub の結果。壊れた hub でも例外にしない（空のページを返す）。"""
    hub = hub if isinstance(hub, dict) else build_hub(None, None, None)
    products = hub["products"]
    yr = str(hub["today"])[:4]
    pidx = _pidx(hub)
    flagmap = _flags(hub)
    ordered = _ordered(hub, flagmap)
    gen = _e(generated_label or hub["now"])

    opps = hub.get("opportunities") or []
    card_list = hub.get("cards")
    if card_list is None:                                       # build_hub 以外で作った hub でも落とさない（同じ統合規則で作り直す）
        card_list = pv.build_cards(products, opps)
    cfg = _CFG()
    hs = hub.get("stats") or {}
    by_tcg = hs.get("unbound_applying_by_tcg")
    unbound_total = int(hs.get("unbound_applying") or 0)
    rbs = hub.get("retailer_opportunities") or []
    box_keys = {(o.get("tcg"), o.get("product_id")) for o in rbs if isinstance(o, dict)}
    rb_open_by: dict = {}                    # (tcg, product_id) → 応募受付中（OPEN）の販売店行（台帳＋collector 由来。不採用の行は除く）
    for r in [o.get("retailer") for o in rbs if isinstance(o, dict)] + [r for r in (hub.get("retailer_references") or []) if isinstance(r, dict) and r.get("kind") != "REJECTED"]:
        if isinstance(r, dict) and r.get("accept_state") == "OPEN" and r.get("product_id"):
            rb_open_by.setdefault((r.get("tcg"), r["product_id"]), []).append(r)
    ann = _announce_index(hub.get("events"))
    doms, html_of = [], {}
    for n, c in enumerate(card_list):
        pk = pidx.get(c["key"])
        dom = pk or f"c{n}"
        doms.append(dom)
        # 未紐付けの受付中は、そのカードの TCG のものだけ数える（TCG が読めない告知は全 TCG に数える）。集計が無い hub は全体の件数
        ub = unbound_total if not isinstance(by_tcg, dict) else int(by_tcg.get(c["tcg"], 0)) + int(by_tcg.get("", 0))
        html_of[dom] = _card(c, dom, pk, yr, cfg, ub, rb_open_by.get(c["key"]), ann, box=c["key"] in box_keys)

    lists = ""
    for tcg, aid in (("POKEMON", "cat-pokemon"), ("ONE_PIECE", "cat-onepiece")):
        main_rows = [html_of[d] for c, d in zip(card_list, doms) if c["tcg"] == tcg and not _no_info(c)]
        rest = [html_of[d] for c, d in zip(card_list, doms) if c["tcg"] == tcg and _no_info(c)]
        ul = _unbound_untils(hub, tcg)
        ub_html = (f'<p class="pnote unb"><a href="{PAGE_LOTTERY}#lt-open">このほかの受付中の抽選 {_cnt(ul, ".unb")}件</a></p>' if ul else "")
        lists += (f'<h3 class="cat-h" id="{aid}">{_e(TCG_LABEL[tcg])}<small>{len(main_rows) + len(rest)}</small></h3>{ub_html}'
                  + (f'<div class="plist">{_list_head()}{"".join(main_rows)}</div>' if main_rows else "")
                  + (f'<details class="note nobb"><summary>ほかの商品（{len(rest)}件）</summary><div class="plist">{"".join(rest)}</div></details>' if rest else ""))

    # 0 件なら節ごと出さない。参考情報（_rb_refs）・台帳との食い違い（_rb_mismatch）は運用者向けの診断なので公開ページには出さない
    rb_html = ((f'<h2 id="retailer-box">販売店の BOX 価格（条件付き）（{len(rbs)}）</h2>'
                f'<div class="pgrid">{"".join(_rb_card(o, i, ann) for i, o in enumerate(rbs))}</div>') if rbs else "")

    ranking = _ranking(card_list, doms, cfg)
    body = (
        f'<header class="ph"><h1>ポケカ・ワンピの抽選と利益</h1><p class="upd">{_gen_line(hub, gen)}</p></header>'
        f'{_stale_banner(hub)}{_tcg_nav("products", has_ranking=bool(ranking))}'
        f'{_soon_band(hub, ordered, flagmap, pidx, yr, {c["key"]: c for c in card_list})}'
        f'{_thumbs(card_list, doms)}'
        f'{ranking}'
        f'<h2 id="opportunities">商品と利益（{len(card_list)}）</h2>{_stale_note(card_list)}'
        + (lists if card_list else '<p class="empty">商品はまだありません</p>')
        + rb_html)
    body += _foot(hub, gen, credit="<img " in body)               # 出典表記は公式画像を実際に出しているときだけ（代わりの画像だけなら出さない）
    return _doc("ポケカ・ワンピの抽選と利益", hub, body, rf.JS_FRESHNESS + JS_RB + JS_LEFT + JS_STALE_NOTE)


# ───────────────────────── tcg-lottery.html（抽選: カレンダー＋一覧） ─────────────────────────
_GROUPS = (("ending", "締切間近"), ("open", "受付中"), ("deadline_only", "締切前（開始日未確認）"), ("upcoming", "開始予定"),
           ("unknown", "未確認"), ("after", "結果待ち・当選者のみ"))
_OPEN_GROUPS = ("ending", "open", "deadline_only", "upcoming")
_TAB_GROUPS = ("ending", "open")
_SEP_HEAD = {"deadline_only": "締切前・開始日未確認の抽選", "upcoming": "開始前の抽選"}   # 受付中の抽選と分けて出す段の見出し                        # タブにする段（ほかは「すべて」の中か、閉じた折りたたみ）


def _group_of(v: dict) -> str:
    s = v["status"]
    if s in (ls.L_OPEN, ls.L_ENDING_SOON, ls.L_UPCOMING, ls.L_UNKNOWN) and not _confirmed(v):
        return "unknown"
    if s == ls.L_UNKNOWN:
        return "unknown"
    if v.get("deadline_only"):
        return "deadline_only"                              # 締切だけ分かる行は受付中の段に入れない
    return {ls.L_ENDING_SOON: "ending", ls.L_OPEN: "open", ls.L_UPCOMING: "upcoming"}.get(s, "after")


def render_lottery(hub: dict, *, generated_label: Optional[str] = None) -> str:
    """docs/tcg-lottery.html（抽選）。商品から選ぶ・方式から選ぶ・抽選カレンダー（折りたたみ）・「受付中の抽選」のカード一覧・
    別の見出しの「締切前・開始日未確認の抽選」「開始前の抽選」。
    初期表示は 締切間近・受付中・開始予定 だけ。未確認・結果待ち・当選者のみ・終了は閉じた折りたたみ。
    件数（見出し・タブ）は生成時点の件数から、締切を過ぎた抽選を表示時に JS が外す。"""
    hub = hub if isinstance(hub, dict) else build_hub(None, None, None)
    products = hub["products"]
    yr = str(hub["today"])[:4]
    pidx = _pidx(hub)
    flagmap = _flags(hub)
    ordered = _ordered(hub, flagmap)
    gen = _e(generated_label or hub["now"])
    live = [v for v in ordered if v["status"] != ls.L_ENDED]
    ended = [v for v in ordered if v["status"] == ls.L_ENDED]
    cards = {}                                                 # p{n} → 商品（画像を出すため）
    for c in (hub.get("cards") or []) + list(products):
        k = pidx.get((c.get("tcg"), c.get("product_id")))
        if k and k not in cards:
            cards[k] = c
    _evs = [v["ev"] for v in hub["events"]]
    retailers = sorted({k: pv.retailer_filter_label(k, _evs) for k in {(e.get("retailer") or "") for e in _evs} if k}.items())   # 同じ小売は 1 つ（代表ラベルを日本語名に固定）
    regions = sorted({v["ev"].get("prefecture") for v in hub["events"] if v["ev"].get("prefecture")})
    opt = lambda items: "".join(f'<option value="{_e(k)}">{_e(lbl)}</option>' for k, lbl in items)   # noqa: E731

    filters = (
        '<details class="flt" data-js-only hidden><summary>絞り込み</summary>'
        '<form id="flt" class="filters" onsubmit="return false">'
        f'<label>TCG<select name="tcg"><option value="">すべて</option>{opt(TCG_LABEL.items())}</select></label>'
        f'<label>商品<select name="product"><option value="">すべて</option>{opt((f"p{i}", p["name"]) for i, p in enumerate(products))}'
        f'<option value="none">その他（商品ページなし）</option></select></label>'
        f'<label>店舗<select name="retailer"><option value="">すべて</option>{opt(retailers)}</select></label>'
        f'<label>地域<select name="region"><option value="">すべて</option>{opt((r, r) for r in regions)}<option value="unknown">地域の記載なし</option></select></label>'
        '<label>状態<select name="state"><option value="">すべて</option><option value="open">受付中</option>'
        '<option value="ending">締切間近</option><option value="upcoming">近日開始</option>'
        '<option value="today">今日応募可能</option><option value="deadline">今日締切</option><option value="new">新着</option></select></label></form></details>')

    groups: dict = {k: [] for k, _ in _GROUPS}
    for v in live:
        groups[_group_of(v)].append(v)
    unt = {k: [_lot_until(v["status"], v["end"], v["purchase_end"])[0] or "-" for v in groups[k]] for k in groups}
    shown = [u for k in _OPEN_GROUPS for u in unt[k]]
    applying = [u for k in _TAB_GROUPS for u in unt[k]]            # 受付中の段（締切間近・受付中）の締切。見出し・方式・商品の件数はこれだけを数える
    tabs = ['<a href="#lottery" data-tab="all" aria-current="true">すべて</a>']
    secs, folds = [], []
    for key, label in _GROUPS:
        vs = groups[key]
        n = len(vs)
        if not n:                                                    # 件数 0 の段は出さない
            continue
        if key in _TAB_GROUPS:                                      # タブは 締切間近・受付中 だけ。締切を過ぎた抽選は表示時に件数から外し、0 件のタブは隠す
            tabs.append(f'<a href="#lt-{key}" data-tab="{key}" aria-current="false">{label} <b>{_cnt(unt[key], "a")}</b></a>')
        tbl = _table(vs, pidx, yr, flagmap, None, cards)
        if key in _OPEN_GROUPS:
            # 締切間近・受付中は「受付中の抽選」の下の小見出し。締切前（開始日未確認）・開始予定は受付中ではないので、別の見出し
            hd = (f'<h3 id="lt-{key}">{label}</h3>' if key in _TAB_GROUPS else f'<h2 class="lt-h" id="lt-{key}">{_SEP_HEAD[key]}</h2>')
            secs.append(f'<section class="lt-sec" data-lt-group="{key}">{hd}{tbl}</section>')
        else:
            folds.append(f'<details class="note lt-more" data-lt-group="{key}" id="lt-{key}"><summary>{label}（{n}件）</summary>{tbl}</details>')
    open_vs = [v for k in _OPEN_GROUPS for v in groups[k]]
    # 商品から選ぶ（受付中・締切前・開始前の抽選がある商品。件数は受付中の段だけ。受付中が無ければ段の名前）
    per: dict = {}
    for v in open_vs:
        ev = v["ev"]
        k = pidx.get((ev.get("tcg"), ev.get("product_id"))) if v.get("canonical") in (pv.C_MASTER, pv.C_DISCOVERED) else None
        if k and k in cards:
            g = _group_of(v)
            us, other = per.get(k, ([], ""))
            per[k] = (us + [_lot_until(v["status"], v["end"], v["purchase_end"])[0] or "-"], other) if g in _TAB_GROUPS else (us, other or g)
    pnames = [cards[k].get("name") or "" for k in per]

    def _pk_count(us, other):
        return f"受付中 {_cnt(us)}件" if us else {"deadline_only": "開始日未確認", "upcoming": "開始前"}.get(other, "")
    picks = "".join(f'<a class="pk" href="#prod-{_e(k)}" data-pk="{_e(k)}" data-pk-open="{len(us)}" aria-current="false" title="{_e(cards[k].get("name") or "")}">'
                    f'{_img_block(cards[k])}<span>{_e(short_name(cards[k].get("name") or "", pnames))}</span><small>{_pk_count(us, o)}</small></a>'
                    for k, (us, o) in sorted(per.items(), key=lambda kv: -len(kv[1][0])))
    pick_html = (f'<section class="pick" data-js-only hidden><h2>商品から選ぶ</h2><nav class="pick-row" aria-label="商品から選ぶ">{picks}</nav></section>'
                 if picks else "")
    applying_vs = [v for k in _TAB_GROUPS for v in groups[k]]
    def _ch_untils(key):
        return [_lot_until(v["status"], v["end"], v["purchase_end"])[0] or "-" for v in applying_vs if _ch_key(v["channel"]) == key]
    n_on, n_st = _cnt(_ch_untils("online")), _cnt(_ch_untils("store"))
    chips = ('<section class="pick" data-js-only hidden><h2>方式から選ぶ</h2><div class="mtiles" role="group" aria-label="応募方式">'
             f'<button type="button" data-ch-btn="online" aria-pressed="false"><i class="ic-online" aria-hidden="true">◎</i><span><b>オンライン抽選</b><small>受付中 <span data-ch-count="online">{n_on}</span>件・自宅から応募</small></span></button>'
             f'<button type="button" data-ch-btn="store" aria-pressed="false"><i class="ic-store" aria-hidden="true">▣</i><span><b>店頭抽選</b><small>受付中 <span data-ch-count="store">{n_st}</span>件・店舗で応募</small></span></button>'
             '</div></section>')
    until_all = _earliest_until(u for u in shown if u != "-")
    exp_note = (f'<p class="pnote expn" data-rb-card data-rb-until="{_e(until_all)}"><span data-rb-expired hidden>締切を過ぎた抽選は除いています</span></p>'
                if until_all else "")
    if secs:
        live_html = f'<div id="lt-live">{exp_note}{"".join(secs)}</div><!--/lt-live-->'
    else:
        live_html = '<p class="empty">受付中・開始前の抽選はありません</p><div id="lt-live"></div><!--/lt-live-->'
    ended_html = (f'<details class="note lt-more" data-lt-group="ended"><summary>終了（{len(ended)}件）</summary>{_table(ended, pidx, yr, flagmap, "lt-ended", cards)}</details>'
                  if ended else "")
    body = (
        f'<header class="ph"><h1>ポケカ・ワンピの抽選販売</h1></header>'
        f'{_stale_banner(hub)}{_tcg_nav("lottery")}{pick_html}{chips}'
        f'<details class="calx" id="calendar"><summary>抽選カレンダー</summary>{_calendar(hub["calendar"], hub["today"])}</details>'
        f'<h2 id="lottery" class="lt-h">受付中の抽選</h2>'
        f'<div class="lt-bar"><span>全{_cnt(applying)}件</span><span class="u">{_gen_line(hub, gen)}</span></div>'
        f'<nav class="lt-tabs" aria-label="抽選の状態">{"".join(tabs)}</nav>{filters}'
        '<p class="mut" id="cnt" aria-live="polite"></p>'
        '<p class="empty" id="none" hidden>受付中・開始前に該当する抽選はありません</p>'
        f'{live_html}{"".join(folds)}{ended_html}' + _foot(hub, gen, credit="<img " in f"{live_html}{ended_html}{''.join(folds)}"))
    return _doc("ポケカ・ワンピの抽選販売一覧", hub, body, JS + JS_RB + JS_LEFT)


def render_pages(hub: dict, *, generated_label: Optional[str] = None) -> dict:
    """{ファイル名: HTML}。docs/ に書く 2 ページ。"""
    return {PAGE_PRODUCTS: render(hub, generated_label=generated_label),
            PAGE_LOTTERY: render_lottery(hub, generated_label=generated_label)}


def render_from_json(lotteries, registry, msrp, now: Optional[datetime] = None, buyback=None) -> str:
    """公開済み JSON の辞書から直接 tcg.html（商品と利益）を作る。"""
    return render_pages_from_json(lotteries, registry, msrp, now, buyback)[PAGE_PRODUCTS]


def render_pages_from_json(lotteries, registry, msrp, now: Optional[datetime] = None, buyback=None) -> dict:
    """公開済み JSON の辞書から 2 ページを作る。"""
    now = (now or now_jst()).astimezone(JST)
    if isinstance(lotteries, dict) and isinstance(lotteries.get("items"), list):
        # 公開の出口（古い書き出し・手で作った入力でも、自由文・根拠の原文をページに出さない）
        from src.tcg.lottery.public import public_events
        lotteries = {**lotteries, "items": public_events(lotteries["items"])}
    return render_pages(build_hub(lotteries, registry, msrp, now, buyback), generated_label=now.strftime("%Y-%m-%d %H:%M JST"))
