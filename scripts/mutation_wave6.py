#!/usr/bin/env python3
"""Coverage Wave 6 の変異テスト: 安全の規則を1つずつ壊して、テストが検知することを確かめる（リポジトリのルートで実行: python3 scripts/mutation_wave6.py）。

各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストの穴。
注意: 追跡対象のソースをその場で書き換える。他のセッションが同じファイルを編集していないときに実行する（強制終了すると変異が残る）。
"""
# ruff: noqa
import subprocess, sys
SG="src/research/signals.py"; C="src/research/candidates.py"; PD="src/tcg/profit_dense.py"; DD="src/tcg/detection_delay.py"
RC="src/collectors/tcg/runcache.py"; B="src/collectors/tcg/base.py"; CM="src/tcg/collection_metrics.py"; PL="src/tcg/lottery/pipeline.py"
TESTS="tests/test_coverage_wave6.py tests/test_coverage_wave5.py tests/test_coverage_wave4.py".split()
M=[
("first_seen を毎回リセットする",DD,'        else:\n            seen["last_seen"] = stamp\n','        else:\n            seen["last_seen"] = stamp\n            seen["first_seen"] = stamp\n'),
("古い前回の価格（基準）を受け入れる",SG,'    if prev.get("stale"):','    if False:'),
("隔離された価格の勢いを使う（確定へ近づく）",SG,'out["momentum_usable"] = out["momentum_state"] == MOM_RISING and not quarantined','out["momentum_usable"] = out["momentum_state"] == MOM_RISING'),
("同じ URL を何度も取る（キャッシュが効かない）",RC,'                if key in self._entries:','                if False:'),
("ドメインごとの直列化をやめる（同じドメインへ同時に取る）",RC,'        lock = _DOMAIN_LOCKS.get(d)\n        if lock is None:\n            lock = _DOMAIN_LOCKS[d] = threading.Lock()\n        return lock','        return threading.Lock()'),
("ドメインごとの間隔の下限をなくす",B,'MIN_INTERVAL_SEC = 60','MIN_INTERVAL_SEC = 0'),
("ブロックされた取得元を取り直す（失敗をキャッシュしない）",RC,'                if entry is not None:\n                    self._entries[key] = entry','                if entry is not None and entry.get("html") is not None:\n                    self._entries[key] = entry'),
("終了済みのイベントを優先する",PD,'        if status not in ACTIVE:\n            continue','        if False:\n            continue'),
("Special・特別だけで限定にする（語の推測）",SG,'            if structured_limited:\n                return {"limited": True','            if True:\n                return {"limited": True'),
("勢い・first_seen を公開してよい項目にする",C,'    "momentum", "tcg_first_seen", "tcg_detection_events", "buyback_prices_prev"})','    "buyback_prices_prev"})'),
("初めて見た候補を上がったことにする（NEW_OBSERVATION を RISING）",SG,'        out["momentum_state"] = MOM_NEW_OBSERVATION\n        return out\n    pp =','        out["momentum_state"] = MOM_RISING\n        out["momentum_usable"] = True\n        return out\n    pp ='),
("同じ観測を新しい値として勢いに数える",SG,'    if out["previous_observed_at"] and out["previous_observed_at"] == out["current_observed_at"]:','    if False:'),
("公開日時が無いのに検知の遅れを作る（推測）",DD,'        if pub is None or _date_only(i.get("published_at")) or fs < pub:','        if fs is None:'),
("隔離された価格を次回の基準にする",C,'        if _sg.is_quarantined(r) or (r.get("momentum") or {}).get("momentum_quarantined"):','        if False:'),
("取得元を並列に動かさない",RC,'n = max(1, min(int(max_workers or len(tasks) or 1), MAX_TASK_THREADS))','n = 1'),
("全体の並列の上限を外す",RC,'GLOBAL_CAP = 12 ','GLOBAL_CAP = 1000 '),
("応募の URL でない（購入の URL・告知の URL）を応募の URL にする",PD,'"official_url": bool(i.get("entry_url")),','"official_url": bool(i.get("entry_url") or i.get("purchase_url") or i.get("source_url")),'),
("不明な取得元の状態を healthy にする",CM,'    return FAILED if not f.get("pages_loaded") else PARSER_DEGRADED','    return HEALTHY'),
("台帳を引き継げていない日に前回と比べる",SG,'    comparable = bool(comparable) and prev_obs_of is not None','    comparable = prev_obs_of is not None'),
("同じ run の再生成で first_seen を捨てる",C,'comparable=(ledger_state in (LEDGER_RESTORED_FROM_PREVIOUS_RUN, LEDGER_REUSED_WITHIN_RUN)), now=now,','comparable=(ledger_state == LEDGER_RESTORED_FROM_PREVIOUS_RUN), now=now,'),
("引き継いでいない台帳の前回の価格を使う",C,'    if ledger_state != LEDGER_RESTORED_FROM_PREVIOUS_RUN or not isinstance(prices, dict):\n        return None\n\n    def _prev(row: dict):\n        e = prices.get(row.get("candidate_id"))\n        if not isinstance(e, dict) or not isinstance(e.get("price"), int) or isinstance(e.get("price"), bool) or e["price"] <= 0:','    if not isinstance(prices, dict):\n        return None\n\n    def _prev(row: dict):\n        e = prices.get(row.get("candidate_id"))\n        if not isinstance(e, dict) or not isinstance(e.get("price"), int) or isinstance(e.get("price"), bool) or e["price"] <= 0:'),
("抽選の取得元を並列に取らない（登録簿の順に直列）",PL,'    done = runcache.run_parallel([(s["source_id"], (lambda s=s: _one(s))) for s in start_order])','    done = {s["source_id"]: runcache.run_parallel([(s["source_id"], (lambda s=s: _one(s)))])[s["source_id"]] for s in start_order}'),
("数百円のぶれを勢いにする",SG,'MOMENTUM_MIN_YEN = 500','MOMENTUM_MIN_YEN = 0'),
("同じ run の再生成で今回の値と比べる（基準を上書きする）",C,'        prices = raw_state.get("buyback_prices_prev")','        prices = raw_state.get("buyback_prices")'),
("JS 描画と静的な応答を混ぜる",RC,'key = normalize_url(url) + ("#" + variant if variant else "")','key = normalize_url(url)'),
("キャッシュで受け取った時刻を観測時刻にする",B,'self._fetched_at = entry.get("fetched_at") or now_jst().isoformat()','self._fetched_at = now_jst().isoformat()'),
("取得元の停止の復旧日を遅れとして測る",DD,'        if last_src is None or now - last_src > timedelta(hours=SOURCE_GAP_HOURS):','        if False:'),
("1 件だけの遅れの値を公開する",DD,'MIN_SAMPLES_FOR_VALUES = 3','MIN_SAMPLES_FOR_VALUES = 1'),
("日付だけの公開日で遅れを作る",DD,'if pub is None or _date_only(i.get("published_at")) or fs < pub:','if pub is None or fs < pub:'),
("限定の語を否定・別の語の一部でも一致させる",SG,'        if before[-1:] in _NEG_BEFORE or after.startswith(_NEG_AFTER):','        if False:'),
("勢いの対象外の行の誤価格を基準にする",C,'        if _sg.is_quarantined(r) or (r.get("momentum") or {}).get("momentum_quarantined"):','        if (r.get("momentum") or {}).get("momentum_quarantined"):'),
("翌日の run で同じイベントの遅れをまた数える",DD,'        if mr is not None and mr != run_id:','        if False:'),
("同じ run の再生成で取得元の停止の判定が外れる",DD,'prev_sources = (p.get("sources_base") if same_run else p.get("sources")) or {}','prev_sources = p.get("sources") or {}'),
("最初の生成が信頼できなくても再生成が測る",DD,'trusted = bool(p) and (p.get("trusted") is True if same_run else True)','trusted = bool(p)'),
("中断で待機側を解放しない",RC,'                self._inflight.pop(key).set()','                pass'),
]
bad=0
for desc,f,old,new in M:
    s=open(f).read()
    if old not in s: print("無効（置換元なし）",desc); bad+=1; continue
    open(f,"w").write(s.replace(old,new,1))
    try:
        r=subprocess.run([sys.executable,"-m","pytest","-q","-x","-p","no:cacheprovider",*TESTS],capture_output=True,text=True,timeout=180)
        ok=r.returncode!=0
    except subprocess.TimeoutExpired:
        ok=True                                       # ハング（待機側が解放されない等）もテストが変異を検知した扱い
    finally:
        open(f,"w").write(s)
    print("検出" if ok else "★見逃し",desc)
    bad+=(not ok)
print("見逃し/無効:",bad,"/",len(M))
