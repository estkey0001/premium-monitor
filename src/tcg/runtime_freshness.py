# -*- coding: utf-8 -*-
"""買取価格の「取得からの経過時間」の判定（生成時 = Python と、ページ表示時 = JavaScript の共通の定義）。

- しきい値（observed_max_hours・future_tolerance_minutes）の唯一の定義は config/tcg_buyback.yaml。
  Python（buyback.classify_freshness）も、ページに出す data-fb-* 属性も、ここを通して同じ値を使う（JS に数値を書かない）。
- 取得時刻は、タイムゾーン（+09:00 など）付きの ISO 8601 だけを受け付ける。オフセットが無い・読めない・未来は UNKNOWN。
  端末のローカルタイムゾーンに依存しない（オフセット付きの時刻は絶対時刻として比較する）。
- 境界: 経過がちょうど max 時間のときは FRESH（max 時間を超えたら STALE）。
- ページ表示時は JS_FRESHNESS が同じ規則で判定し直し、FRESH でない価格を「最高買取・利益・ROI・利益根拠」として見せない。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

FRESH, STALE, UNKNOWN = "FRESH", "STALE", "UNKNOWN_FRESHNESS"

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")


def thresholds(cfg: dict) -> tuple:
    fr = (cfg or {}).get("freshness") or {}
    return float(fr.get("observed_max_hours", 8)), float(fr.get("future_tolerance_minutes", 5))


def parse_aware(v) -> Optional[datetime]:
    """オフセット付きの ISO 8601 だけ読む。それ以外は None（ローカル時刻・日本時間などを推測しない）。"""
    if not isinstance(v, str) or not _ISO.match(v.strip()):
        return None
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def evaluate(observed_iso, now: datetime, max_hours: float, future_min: float) -> str:
    """FRESH / STALE / UNKNOWN_FRESHNESS。now は tz 付き。"""
    obs = parse_aware(observed_iso)
    if obs is None or now.tzinfo is None:
        return UNKNOWN
    if obs > now + timedelta(minutes=future_min):
        return UNKNOWN
    return STALE if now - obs > timedelta(hours=max_hours) else FRESH


def attrs(observed_iso, cfg: dict) -> str:
    """ページに出す属性（JS はこれだけを読む。数値は設定から）。秒までに丸める（切り捨て = 古い側。JS の Date が読める形）。"""
    mx, fut = thresholds(cfg)
    d = parse_aware(observed_iso)
    obs = d.replace(microsecond=0).isoformat() if d else ""
    return f'data-fb-obs="{obs}" data-fb-max="{mx:g}" data-fb-fut="{fut:g}"'


# ページ表示時の判定（TCG ページと HOME が同じものを埋め込む）。数値は持たず、属性から読む。
# [data-fb-live]: 鮮度が FRESH のときだけ見せる要素（最初は hidden。JS が確認できたときだけ出す = JS が動かなければ出さない）
# [data-fb-stale][data-fb-group=g]: 同じ group の live が 1 つでも FRESH でないときに見せる「価格再確認待ち」（最初は表示）
JS_FRESHNESS = r"""
(function(){
function fresh(iso,nowMs,maxH,futMin){
if(typeof iso!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/.test(iso))return 'UNKNOWN_FRESHNESS';
var t=Date.parse(iso.replace(/(\.\d{3})\d+/,'$1'));
if(!isFinite(t)||!isFinite(maxH)||!isFinite(futMin))return 'UNKNOWN_FRESHNESS';
if(t>nowMs+futMin*60000)return 'UNKNOWN_FRESHNESS';
return (nowMs-t>maxH*3600000)?'STALE':'FRESH';}
function apply(nowMs){
if(nowMs===undefined)nowMs=Date.now();
var bad=Object.create(null),why=Object.create(null),lives=document.querySelectorAll('[data-fb-live]'),i,e,g,s;
for(i=0;i<lives.length;i++){e=lives[i];g=e.getAttribute('data-fb-group')||'';
s=fresh(e.getAttribute('data-fb-obs'),nowMs,parseFloat(e.getAttribute('data-fb-max')),parseFloat(e.getAttribute('data-fb-fut')));
e.hidden=(s!=='FRESH');
if(s!=='FRESH'){bad[g]=true;if(why[g]!=='STALE')why[g]=s;e.setAttribute('data-fb-state',s);}else{e.setAttribute('data-fb-state',s);}}
var sts=document.querySelectorAll('[data-fb-stale]');
for(i=0;i<sts.length;i++){e=sts[i];g=e.getAttribute('data-fb-group')||'';e.hidden=!bad[g];
var w=e.querySelector&&e.querySelector('[data-fb-why]');
if(w&&bad[g]){w.textContent=(why[g]==='STALE')?('取得から'+(e.getAttribute('data-fb-max')||'')+'時間以上経過'):'取得時刻を確認できません';}}}
window.tcgFresh=fresh;window.tcgFreshApply=apply;
try{apply();setInterval(apply,60000);
document.addEventListener('visibilitychange',function(){apply();});
window.addEventListener('pageshow',function(){apply();});}catch(x){}
})();
"""
