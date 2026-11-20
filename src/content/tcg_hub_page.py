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
--tcg-pokemon:#6d28d9;--tcg-onepiece:#155e75;--k-result:#a21caf}
@media(prefers-color-scheme:dark){:root{--bg:#10141b;--fg:#e6e9ef;--mut:#a3adbb;--card:#181e28;--line:#2b3442;--acc:#7fb0ff;--warn:#e0a24a;
--t-info-fg:#93c5fd;--t-info-bg:#10223f;--t-info-bd:#1e3a8a;--t-danger-fg:#fca5a5;--t-danger-bg:#3b1212;--t-danger-bd:#7f1d1d;
--t-warn-fg:#fcd34d;--t-warn-bg:#3a2a08;--t-warn-bd:#78350f;--t-gray-fg:#cbd5e1;--t-gray-bg:#1e293b;--t-gray-bd:#334155;--k-result:#e879f9}}
*{box-sizing:border-box}body{overflow-wrap:anywhere;margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,"Hiragino Sans",sans-serif}
main{max-width:1240px;margin:0 auto;padding:16px}h1{font-size:24px;margin:.2em 0}
h2{font-size:18px;margin:1.6em 0 .5em;padding:0 0 .2em .6em;border-left:4px solid var(--acc);scroll-margin-top:56px}
h3{font-size:15px;margin:.2em 0}a{color:var(--acc)}.mut{color:var(--mut);font-size:13px}
.head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}.snap{margin:.2em 0;color:var(--mut)}
details.note{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 12px;margin:8px 0}
details summary{cursor:pointer;color:var(--mut);min-height:44px;min-width:44px}details.note>*:not(summary){margin:.5em 0}
nav.jump{position:sticky;top:0;z-index:5;display:flex;gap:6px;overflow-x:auto;padding:6px 0;margin:.6em 0;background:var(--bg)}
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
.sb.warn{color:var(--t-warn-fg);background:var(--t-warn-bg);border-color:var(--t-warn-bd)}
.sb.gray{color:var(--t-gray-fg);background:var(--t-gray-bg);border-color:var(--t-gray-bd)}
.sb.out{color:var(--mut);background:transparent}
.tcgtag{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:20px;padding:0 4px;border-radius:4px;color:#fff;font-size:12px;font-weight:700;margin-right:4px;vertical-align:middle}
.tcgtag.pokemon,.pimg.ph.pokemon{background:var(--tcg-pokemon)}.tcgtag.onepiece,.pimg.ph.onepiece{background:var(--tcg-onepiece)}
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}
.pcard{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:grid;grid-template-columns:72px minmax(0,1fr);gap:4px 10px;padding:8px 10px;align-content:start;scroll-margin-top:56px}
.pimg{grid-row:1;grid-column:1;width:72px;height:72px;display:flex;align-items:center;justify-content:center;background:var(--t-gray-bg);color:#fff;font-size:28px;font-weight:700;border-radius:8px;overflow:hidden}
.pimg img{width:100%;height:100%;object-fit:contain;display:block}.pimg.ph{background-image:none}
.phead{grid-row:1;grid-column:2;min-width:0;display:flex;flex-direction:column;gap:2px}.phead h3{font-size:15px;line-height:1.35;margin:0}
.pcard>.pmeta,.pcard>.chips,.pcard>.pfoot,.pcard>.pnote{grid-column:1/-1}.pnote.nw{white-space:nowrap}
.pmeta{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 12px;margin:0}.pmeta dl{display:contents;margin:0}.pmeta dl>div{min-width:0;display:flex;gap:4px;align-items:baseline}
.pmeta dt{color:var(--mut);font-size:12px;line-height:1.4}.pmeta dd{margin:0;font-weight:700;font-size:15px;line-height:1.4;overflow-wrap:anywhere}
.pnote,.pcard>p.pnote{margin:0;color:var(--mut);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:4px}.chip{border:1px solid var(--line);border-radius:8px;padding:0 8px;font-size:12px;line-height:1.6;color:var(--mut)}
.chip b{font-size:14px;color:var(--fg);margin-right:3px}
.chip.info{border-color:var(--t-info-bd);background:var(--t-info-bg)}.chip.danger{border-color:var(--t-danger-bd);background:var(--t-danger-bg)}
.pfoot{display:flex;flex-wrap:wrap;align-items:center;gap:0 12px;font-size:14px}
.pfoot details{flex:1 1 auto}.pfoot details[open]{flex-basis:100%}.pfoot details summary{display:inline-flex;align-items:center;min-height:44px;min-width:44px;font-size:13px}
.pfoot details>div{display:flex;flex-direction:column;gap:2px;padding-bottom:6px}
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
.pgrid{gap:8px}.pcard{grid-template-columns:48px minmax(0,1fr);padding:6px 8px;gap:2px 8px}.pimg{width:48px;height:48px;font-size:20px}
.pfoot details[open]{flex-basis:100%}.lt tr.ev{margin:6px 0;padding:4px 10px}.box{margin:6px 0}}
@media(min-width:901px){.dot{display:none!important}}
"""

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
    shop = ev.get("store_name") or ev.get("retailer_name") or ev.get("retailer") or "店舗不明"
    sub = ev.get("retailer_name") or ""
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
    links = [_link(v["application_url"], "応募ページ"), _link(v["announcement_url"], "公式の告知")]
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
    st_cell = f'{_status_badge(v["status"], v["status_label"])}{aux}'
    ok = v["verified"]
    no_res = not v["result"].get("date")
    return (f'<tr class="ev t-{_tone(v["status"])}" {attrs}>'
            f'<td data-label="状態">{st_cell}</td>'
            f'<td data-label="店舗"><b>{_e(shop)}</b>{"<small>" + _e(sub) + "</small>" if sub and sub != shop else ""}</td>'
            f'<td data-label="商品">{product}</td>'
            f'<td data-label="締切"{' class="w2"' if no_res else ""}>{_md(v["end"], yr, ok)}<small>開始 {_md(v["start"], yr, ok)}</small></td>'
            f'<td data-label="応募方法" class="how"><span title="{_e(CHANNEL_LABEL.get(ch, ch))}">{_e(CHANNEL_SHORT.get(ch, ch))}</span>・{_e(kind)}'
            f'{"<small>" + links + "</small>" if links else ""}{nolink}{cond}</td>'
            f'<td data-label="地域"{"" if region else NA}>{_e(region) if region else "—"}</td>'
            f'<td data-label="当選日"{"" if v["result"].get("date") else NA}>{_md(v["result"], yr, ok)}</td>'
            f'<td data-label="購入期間"{"" if (v["purchase_start"].get("date") or v["purchase_end"].get("date")) else NA}>{_range(v["purchase_start"], v["purchase_end"], yr, ok)}</td>'
            f'<td data-label="確認">{verify}<small title="{_e(ver_raw)}">確認 {_vshort(ver_raw)}</small>{nolink_m}</td></tr>')


NA = ' class="na"'                                      # 値が無いセル（モバイルのカードでは出さない）
_HEAD = ("<tr><th>状態</th><th>店舗</th><th>商品</th><th>締切</th><th>応募方法</th><th>地域</th>"
         "<th>当選日</th><th>購入期間</th><th>確認</th></tr>")


def _table(views, pidx, yr, flagmap, tid) -> str:
    rows = "".join(_ev_row(v, pidx, yr, flagmap.get(id(v), set())) for v in views)
    return f'<div class="lt-wrap" id="{tid}"><table class="lt"><thead>{_HEAD}</thead><tbody>{rows}</tbody></table></div>'


def _img_block(p: dict) -> str:
    ini, cls = TCG_INITIAL.get(p["tcg"], ("?", ""))
    src = _image_src(p.get("image_url")) if p["tcg"] == "POKEMON" and p["canonical"] == pv.C_MASTER else None
    if src:
        return (f'<div class="pimg {cls}"><img src="{_e(src)}" alt="" loading="lazy" decoding="async" '
                f'referrerpolicy="no-referrer" width="{IMG_W}" height="{IMG_H}"></div>')
    return f'<div class="pimg ph {cls}" role="img" aria-label="画像なし（{_e(TCG_LABEL.get(p["tcg"], p["tcg"]))}）">{_e(ini)}</div>'


def _product_card(p: dict, i: int, yr: str) -> str:
    pr = p["profit"]
    m = pr["msrp"]
    c = p["counts"]
    rel = (_md({"date": p["release_date"], "time": None}, yr) if p["release_date"]
           else ("未取得" if p["canonical"] == pv.C_DISCOVERED else "未公表"))
    ptype = PTYPE_LABEL.get(p["product_type"], p["product_type"]) if p["product_type"] else ""
    meta, unknown = "", []                                     # 値のある項目だけ並べ、無い項目は 1 行の淡い文にまとめる（金額・ROI は作らない）
    if p["release_date"]:
        meta += f'<div><dt>発売</dt><dd>{rel}</dd></div>'
    else:
        unknown.append("発売日")
    if m:
        meta += f'<div><dt>定価</dt><dd title="確認 {_e(m["checked_at"] or "不明")}">{_yen(m["retail_price"])}</dd></div>'
    else:
        unknown.append("定価")
    if pr.get("net_profit") is not None:
        meta += f'<div><dt>利益</dt><dd title="{_e(pr["reason"])}">{_e(pr["label"])}</dd></div>'
    else:
        unknown.append("利益")
    unk = (f'<span class="pnote" title="{_e(pr["reason"])}（利益: {_e(pr["label"])}）">未確認の項目: {_e("・".join(unknown))}</span>'
           if unknown else "")
    meta = f'<div class="pmeta">{"<dl>" + meta + "</dl>" if meta else ""}{unk}</div>' if (meta or unk) else ""
    chip = lambda n, lbl, tone: f'<span class="chip {tone}"><b>{n}</b>{lbl}</span>' if n else ""
    chips = chip(c["open"], "受付中", "info") + chip(c["ending_soon"], "締切間近", "danger") + chip(c["upcoming"], "近日開始", "info")
    chips = f'<div class="chips">{chips}</div>' if chips else '<p class="pnote nw">受付中・開始前なし</p>'
    off = _product_link(p["official_url"]) or '<span class="mut">公式ページ未確認</span>'
    more = (f'<details><summary>補足</summary><div><span class="pnote">{_e(ptype) + "・" if ptype else ""}'
            f'{"" if m else "定価 未確認・"}利益 {_e(pr["label"])}（{_e(pr["reason"])}）</span>{off}</div></details>')
    lot_link = (f'<a href="#lottery" data-pf="p{i}">この商品の抽選 {c["live"]} 件を表で見る</a>' if c["live"]
                else '<span class="pnote">この商品の抽選 0 件</span>')
    return (f'<section class="pcard" id="p{i}">{_img_block(p)}<div class="phead">'
            f'<div>{_tcgtag(p["tcg"])}{_status_badge(p["status"], st.STATUS_LABEL[p["status"]])}{_prio_badge(p["priority"])}</div>'
            f'<h3>{_e(p["name"])}</h3></div>'
            f'{meta}{chips}'
            f'<div class="pfoot">{lot_link}{more}</div>'
            f'</section>')


def _cal_item(c: dict) -> str:
    t0 = show_time(c["time"], c["verified"])                    # 00:00 は日付のみ（未確認行・補完の 0 時を時刻に見せない）
    if t0:
        t = f'<span title="{_e(c["time"])}">{_e(t0)}</span> '
    else:                                                       # 時刻が無い項目は「日付のみ」と分かるよう日付を出す
        t = ''                                                  # 日付は日付見出し・日の枠が示す。行ごとに「日付のみ」を繰り返さない（注記は一覧の先頭に 1 回）
    where = " ".join(x for x in (c["retailer"], c["store"]) if x)
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
    retailers = sorted({(v["ev"].get("retailer") or "", v["ev"].get("retailer_name") or v["ev"].get("retailer") or "") for v in hub["events"] if v["ev"].get("retailer")})
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

    sum_cards = "".join(f'<div class="c {tone}"><b>{_e(val)}</b>{_e(lbl)}</div>' for lbl, val, tone in (
        ("受付中（締切間近・未確認を含む）", s["applying"], "info"), ("今日締切", s["deadline_today"], "danger" if s["deadline_today"] else ""),
        ("近日開始", s["upcoming"], "info"), ("商品数", s["products"], "")))
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
        '<p class="mut">利益: TCG の買取・二次流通・eBay の根拠が無いため、純利益や順位は<b>算出前</b>です。出せるのは公式の定価だけです。'
        '日付が「日付のみ」のものは、公式が時刻を出していません（時刻を補っていません）。</p></details>')

    if live:
        live_html = _table(live, pidx, yr, flagmap, "lt-live")
    else:
        live_html = ('<p class="empty">いま受付中・開始前・結果待ちの抽選・予約は確認できていません。'
                     '近日の予定は<a href="#calendar">カレンダー</a>、終了した抽選は下の「終了した抽選」を見てください。</p><div id="lt-live"></div>')
    ended_html = (f'<details class="note"><summary>終了した抽選（{len(ended)} 件）</summary>{_table(ended, pidx, yr, flagmap, "lt-ended")}</details>'
                  if ended else "")
    cards = "".join(_product_card(p, i, yr) for i, p in enumerate(products))
    prod_html = (f'<div class="pgrid">{cards}</div>' if cards else
                 '<p class="empty">商品に束ねられた抽選はまだありません。公式の商品名と一致した抽選が出ると、ここに商品カードが並びます。</p>')

    body = (
        f'<div class="head"><h1>TCG 抽選ハブ</h1><span class="snap">状態は {gen} の画面生成時点のものです（情報の確認日は下の「確認日」）。応募前に必ず公式ページで確認してください。</span></div>'
        '<p class="mut">ポケモンカード・ONE PIECE カードの公式の抽選・予約をまとめています。自動応募はしません。</p>'
        f'{notes}{stale_banner}<div class="sum">{sum_cards}</div>{count_note}'
        '<nav class="jump" aria-label="ページ内の移動"><a href="#products">商品</a><a href="#lottery">抽選一覧</a>'
        '<a href="#calendar">カレンダー</a><a href="#checked">確認日</a></nav>'
        f'{low}<h2 id="products">商品（{s["products"]}）</h2>'
        '<details class="note"><summary>商品の束ね方</summary><p class="mut">商品に束ねたのは、商品 ID まで一致（exact）した抽選だけです。ポケモンカードは公式の商品一覧と照合しています。'
        'ONE PIECE は商品一覧が無いため、イベントの商品名だけで表示します（発売日・定価・画像は出しません）。</p></details>'
        f'{prod_html}'
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
            f'<title>TCG 抽選ハブ | プレ値速報</title><meta name="robots" content="index,follow"><style>{legacy}{CSS}</style></head>'
            f'<body>{nav}<main>{body}</main><script>{JS}</script></body></html>')


def render_from_json(lotteries, registry, msrp, now: Optional[datetime] = None) -> str:
    """公開済み JSON の辞書から直接ページを作る。"""
    now = (now or now_jst()).astimezone(JST)
    return render(build_hub(lotteries, registry, msrp, now), generated_label=now.strftime("%Y-%m-%d %H:%M JST"))
