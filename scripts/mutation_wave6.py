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
("応募期間を含む lottery_id をイベントの鍵にする（期間が入ると新規扱い）",DD,'    from src.tcg.lottery.schema import product_key\n','    from src.tcg.lottery.schema import product_key\n    if i.get("lottery_id"):\n        return str(i["lottery_id"])\n'),
("日本語の隣の英語の限定語を見逃す（isalpha）",SG,'    return bool(ch) and ch.isascii() and ch.isalpha()','    return bool(ch) and ch.isalpha()'),
("旧鍵の台帳（版が違う）を引き継ぐ",DD,'    if prev.get("event_key_version") != EVENT_KEY_VERSION:','    if False:'),
("同じ鍵に潰れた複数のアイテムを何度も測る",DD,'        if k in done_keys:\n            continue\n','        if False:\n            continue\n'),
("古い入力を新しい入力として受け入れる",DD,'    if not input_fresh:','    if False:'),
("古い生成物を鮮度の確認で通す",DD,'        if age < -5 / 60 or age > INPUT_MAX_AGE_HOURS:','        if age < -5 / 60:'),
("古い入力の日に取得元の最終確認（sources）を今に更新する",DD,'        return (dict(p) if p else {}), zero, []','        return ({**p, "sources": {r: stamp for r in (p.get("sources") or {})}} if p else {}), zero, []'),
("古い入力の日に台帳を新しく作る（既存イベントを新規として測る）",DD,'        return (dict(p) if p else {}), zero, []','        return (dict(p) if p else {"started_at": stamp, "events": {}, "sources": {}, "sources_base": {}, "run_id": run_id, "trusted": True, "event_key_version": EVENT_KEY_VERSION}), zero, []'),
("商品名を出来事の URL より先に鍵にする",DD,'    if u:\n        k = "|".join(("u", u, store, etype))','    if u and not i.get("lottery_id"):\n        k = "|".join(("u", u, store, etype))'),
("product_id を鍵に入れる（後から付くと別イベント）",DD,'k = "|".join(("u", u, store, etype))','k = "|".join(("u", u, store, etype, str(i.get("product_id") or "")))'),
("応募期間を鍵に入れる（後から入ると別イベント）",DD,'k = "|".join(("u", u, store, etype))','k = "|".join(("u", u, store, etype, str(i.get("application_start") or "")))'),
("一般的な URL（一覧・入口）を出来事の識別に使う",DD,'    if not has_id and (not segs or last.lower() in _GENERIC_SEGMENTS or not any(c.isdigit() for c in last)):\n        return ""','    if False:\n        return ""'),
("店舗の違うイベントを 1 つにする",DD,'k = "|".join(("u", u, store, etype))','k = "|".join(("u", u, "", etype))'),
("1 つの URL の別の商品を 1 つに潰す",DD,'return ((k + "|" + _name_key(i)) if u in multi_urls else k)[:400]','return k[:400]'),
("共有 URL で台帳に無い名前を新規として測る",DD,'        if is_new and seen.get("ambiguous"):','        if False:'),
("URL の無いイベントの新しい鍵を新規として測る",DD,'            if u in multi_urls or not u:','            if u in multi_urls:'),
("http と https を別のイベントにする",DD,'return f"https://{sp.netloc.lower()}/','return f"{sp.scheme}://{sp.netloc.lower()}/'),
("後から URL が付いたイベントを引き継がず新規にする",DD,'            if alt in events and not events[alt].get("url"):','            if False:'),
("前回の観測より前に公開されたイベントも新規として測る",DD,'        if last_src is not None and pub < last_src:','        if False:'),
("手動のイベントで取得元が見えていたことにする",DD,'                    and not str(i.get("collection_method") or "").upper().startswith("MANUAL")):','                    ):'),
("正常取得の取得元が渡されていても受付中のイベントで取得元を更新する",DD,'    if healthy_sources is None:','    if True:'),
("00:00:00 の公開日時を時刻つきとして測る",DD,'    return bool(re.search(','    return False and bool(re.search('),
("手動イベントの遅れを測る",DD,'        if str(i.get("collection_method") or "").upper().startswith("MANUAL"):\n            counts["unknown_published_at"] += 1','        if False:\n            counts["unknown_published_at"] += 1'),
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
