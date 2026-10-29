#!/usr/bin/env python3
"""Coverage Wave 5 の変異テスト: 安全の規則を1つずつ壊して、テストが検知することを確かめる（リポジトリのルートで実行: python3 scripts/mutation_wave5.py）。

各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストの穴。
"""
# ruff: noqa
import subprocess, sys
SG="src/research/signals.py"; C="src/research/candidates.py"; PD="src/tcg/profit_dense.py"; R="src/research/retail_lookup.py"
TESTS="tests/test_coverage_wave5.py tests/test_coverage_wave4.py tests/test_coverage_wave3.py tests/test_market_research.py".split()
M=[
("発売日が無いのに発売直後にする",SG,'        return {"release_state": REL_UNKNOWN, "days_since_release": None}\n    days','        return {"release_state": REL_NEW, "days_since_release": 0}\n    days'),
("発売前を発売直後にする",SG,'    if now < d:\n        return {"release_state": REL_UPCOMING','    if False:\n        return {"release_state": REL_UPCOMING'),
("限定を公式の根拠なしに付ける（名前だけで推測）",SG,'    if not (official and str(official_url or "").startswith("https://") and name):','    if not name:'),
("在庫が不明を供給の逼迫にする",SG,'    if official and availability == "OUT_OF_STOCK":','    if availability in ("OUT_OF_STOCK", "UNKNOWN", ""):'),
("公式でない 1 つの取得元の在庫なしを逼迫にする",SG,'    if official and availability == "OUT_OF_STOCK":','    if availability == "OUT_OF_STOCK":'),
("1 つの取得元の購入不可を複数と数える",SG,'    if unavailable_sources >= 2:','    if unavailable_sources >= 1:'),
("前回が無いのに買取が上がったことにする",SG,'    if isinstance(prev_sell, int) and isinstance(sell, int) and prev_sell > 0 and sell >= prev_sell * RISING_MIN_RATIO:','    if isinstance(sell, int) and sell >= (prev_sell or 0) * RISING_MIN_RATIO:'),
("誤価格の疑いの行にも買取の勢いを付ける",SG,'    if r.get("suspicious") or r.get("retail_conditions"):\n        return []','    if False:\n        return []'),
("誤価格の疑いの行にも点を付ける（疑わしい価格が確定へ近づく）",SG,'    if suspicious:\n        return {"signal_points": 0','    if False:\n        return {"signal_points": 0'),
("標本が 1 件でも品目の中央値を基準にする",SG,'MEDIAN_MIN_SAMPLES = 3','MEDIAN_MIN_SAMPLES = 1'),
("実行をまたいでいない台帳の前回の価格を使う",C,'    if ledger_state != LEDGER_RESTORED_FROM_PREVIOUS_RUN or not isinstance(prices, dict):','    if not isinstance(prices, dict):'),
("古い前回の価格（7 日超）を使う",C,'timedelta(hours=-1) <= now - at <= timedelta(days=PREV_BUYBACK_MAX_AGE_DAYS)','timedelta(hours=-1) <= now - at'),
("古い在庫なしを今日の供給の逼迫にする",C,'                    and timedelta(hours=-1) <= now - _at <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS)):','                    and True):'),
("不完全な TCG のイベントを actionable にする",PD,'"actionable_event": n == len(COMPLETENESS_FIELDS)','"actionable_event": n >= 4'),
("商品が特定できていない TCG のイベントを定価に結ぶ（完全一致でない）",PD,'m = idx.get(pid) if pid and str(i.get("product_match") or "") == "exact" else None','m = idx.get(pid) if pid else None'),
("公式でない定価の台帳から限定にする",PD,'official=bool(m and m.get("source") == "official_product_api")','official=bool(m)'),
("検知の間隔のシミュレーションが間隔を無視する",PD,'wait = latency_hours + h * k / SIM_PHASES','wait = 0'),
("個別の TCG イベントのシグナルを公開してよい項目にする",C,'"retail_unavailable_sources", "days_since_release", "tcg_priority_events", "buyback_prices",','"retail_unavailable_sources", "days_since_release",'),
("シグナルの個別の項目を公開してよい項目にする",C,'"release", "release_date", "limited_signal", "supply_signals", "buyback_signals", "signal_points", "signal_reasons",','"release_date",'),
("同一実行のキャッシュが同じ URL を何度も取る",R,'            if url in self._mem:','            if False:'),
("取得器の取得を並列にしない",R,'ThreadPoolExecutor(max_workers=len(tasks))','ThreadPoolExecutor(max_workers=1)'),
("1 つの取得器の失敗で全体が止まる",R,'            except Exception as exc:  # noqa: BLE001 - 1 つの取得器の失敗で他を止めない','            except ZeroDivisionError as exc:  # noqa: BLE001 - 1 つの取得器の失敗で他を止めない'),
("価格が読めないだけの行を在庫なしにする",C,'            if (lk.get("availability_state") == "OUT_OF_STOCK" and _at is not None','            if (True and _at is not None'),
("価格が読めないだけの代替の取得元を購入不可と数える",C,'x.get("status") == "NOT_PURCHASABLE" and x.get("availability", x.get("availability_state")) == "OUT_OF_STOCK"','x.get("status") == "NOT_PURCHASABLE"'),
("価格差が無い（REJECTED）行にもシグナルを付ける",SG,'        if r.get("status") == "REJECTED" or tri.get("tier") not in ("HIGH", "MEDIUM") or tri.get("currentness") != "fresh":','        if False:'),
("ヒント由来の価格差にも正の価格差の点を付ける",SG,'                        and r.get("retail_basis") == "retail_lookup" and not r.get("retail_conditions")','                        and not r.get("retail_conditions")'),
("条件つきの仕入れ値の行にも点を付ける",SG,'SUSPICIOUS_REASONS = frozenset({"PRICE_ANOMALY_SUSPECTED", "ACQUISITION_CONDITIONAL", "IDENTITY_PARTIAL",','SUSPICIOUS_REASONS = frozenset({"PRICE_ANOMALY_SUSPECTED", "IDENTITY_PARTIAL_X",'),
("応募の終了が過ぎた TCG のイベントも受付中に数える",PD,'        if _end is not None and _end < now:\n            continue','        if False:\n            continue'),
("抽選が開いているだけで高密度と数える",PD,'counts["active_tcg_priority"] += int(dense and pts >= HIGH_DENSITY_POINTS)','counts["active_tcg_priority"] += int(pts >= HIGH_DENSITY_POINTS)'),
]
bad=0
for desc,f,old,new in M:
    old=old.replace("\\\n","\n"); new=new.replace("\\\n","\n")
    s=open(f).read()
    if old not in s: print("無効（置換元なし）",desc); bad+=1; continue
    open(f,"w").write(s.replace(old,new,1))
    try:
        r=subprocess.run([sys.executable,"-m","pytest","-q","-x",*TESTS],capture_output=True,text=True)
    finally:
        open(f,"w").write(s)
    ok=r.returncode!=0
    print("検出" if ok else "★見逃し",desc)
    bad+=(not ok)
print("見逃し/無効:",bad,"/",len(M))
