#!/usr/bin/env python3
"""Wave 7e-1 の変異テスト: 公式の状態・期限の正本・確認日時・最終状態・実行の記録・台帳の公開集計の規則を 1 つずつ壊して、テストが検知することを確かめる。

リポジトリのルートで実行: python3 scripts/mutation_wave7e1.py
各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストの穴。
注意: 追跡対象のソースをその場で書き換える。他のセッションが同じファイルを編集していないときに実行する（強制終了すると変異が残る）。
"""
# ruff: noqa
import subprocess, sys
OS = "src/research/official_state.py"; REG = "src/market/official_registry.py"; HA = "src/ops/health_alert.py"
AU = "scripts/audit_official_sources.py"; C = "src/research/candidates.py"; RO = "scripts/run_observability.py"
TESTS = ("tests/test_wave7e1_observability.py tests/test_wave7e1_long_horizon.py tests/test_wave7e1_conditional_points.py tests/test_wave7e1_registry_timestamp_audit.py "
         "tests/test_integrity_remediation.py tests/test_phase16_official_direct.py tests/test_market_research.py").split()
M = [
    ("確認済みを最初に判定しない（確認済みの数が別の旗で変わる）", OS, '    if str(evidence or "") in (_EV_CURRENT, _EV_DATED):\n        return str(evidence)', '    if False:\n        return str(evidence)'),
    ("状態の合計と商品数の一致を検査しない", OS, '    if canonical_count is not None and sum(counts.values()) != int(canonical_count):', '    if False:'),
    ("空・壊れた商品 ID も 1 件として数える", OS, '        if not pid or pid in out:\n            continue', '        if pid in out:\n            continue'),
    ("確認済みの状態の合計に VERIFIED_DATED を入れない", OS, 'VERIFIED_STATES = frozenset({VERIFIED_CURRENT, VERIFIED_DATED})', 'VERIFIED_STATES = frozenset({VERIFIED_CURRENT})'),
    ("販売終了を UNKNOWN にする", OS, '    eg.SALE_ENDED: SALE_ENDED,', '    eg.SALE_ENDED: UNKNOWN,'),
    ("未来の確認日を有効にする", REG, '    return d.isoformat() if d <= today else ""', '    return d.isoformat()'),
    # 価格の変化（changed）は無効化の分岐で先に処理される（確認日を進める分岐に届かない）。無効化を外す変異（下）で検知する
    ("再確認の連続失敗の日数を数えない", REG, '            if e.get("last_failure_day") != day:', '            if False:'),
    ("希望小売価格だけの確認（msrp_lineup）でも確認日を進める", REG, 'and extends_verification(r) and day >= str(e.get("last_verified_at") or "") \\\n                and recheck_identity_ok', 'and day >= str(e.get("last_verified_at") or "") \\\n                and recheck_identity_ok'),
    ("登録簿が変わっても前回の最終状態を引き継ぐ", REG, '        if isinstance(e, dict) and isinstance(v, dict) and e.get("url") == v.get("url") and e.get("price") == v.get("price"):', '        if isinstance(e, dict) and isinstance(v, dict):'),
    ("確認の期限を公式直販の 14 日に固定する（正本を使わない）", REG, '        stale_days = official_stale_days(pid)\n        original', '        stale_days = 14\n        original'),
    ("履歴から導出した最終状態を確認日に使わない（確認日が戻る）", REG, '        if day and day >= last:\n            last, verified_by = day, str(e.get("last_verified_by")', '        if False:\n            last, verified_by = day, str(e.get("last_verified_by")'),
    # 履歴の未来の日付は、日付の検査（_valid_day）を 2 か所で通す二重の防御。両方を壊す変異（上の「未来の確認日を有効にする」）で検知する
    ("アラートの期限切れの文言を 14 日に固定する", HA, "（期限 {int(r.get('stale_days') or 14)} 日）\", days_left", "（期限 14 日）\", days_left"),
    ("アラートの残り日数の文言を 14 日に固定する", HA, "（期限 {int(r.get('stale_days') or 14)} 日。実際に", "（期限 14 日。実際に"),
    ("販売終了・価格の変化を観測しても、それまでの確認日を無効にしない", REG, '        if st in ("changed", "sale_ended"):\n            # 確認済みを外す側の観測', '        if False:\n            # 確認済みを外す側の観測'),
    ("履歴から最終状態を導出しない", REG, '    return advance_last_state({}, history, today, verified_urls=verified_urls, products=products)', '    return {}'),
    ("同一性を確かめない再確認でも確認日を進める", REG, 'day >= str(e.get("last_verified_at") or "") \\\n                and recheck_identity_ok(pid, r, prods.get(pid)):', 'day >= str(e.get("last_verified_at") or ""):'),
    ("結果の型番が正本と違っても同一とみなす", REG, '        return str(result.get("model") or "").strip() == model', '        return True'),
    ("公式の証拠で確認済みでなくても同一とみなす（商品名だけ）", REG, '    if identity_state(p)[0] != "IDENTITY_CONFIRMED":\n        return False\n    match', '    if False:\n        return False\n    match'),
    ("照合の値が無い結果でも同一とみなす", REG, '    if not match:\n        return False\n    if model:', '    if False:\n        return False\n    if model:'),
    ("JAN だけの商品で照合の値を確かめない", REG, '        return jan in match or bool(ev.get("edition") and str(ev["edition"]) in match)', '        return True'),
    ("色違いの部品番号の組を確かめない", REG, '        and match == ",".join(sorted(ev["variant_skus"]))', '        and True'),
    # 同一性を確かめた一致での invalidated_at の解除は、確認日（>= 無効化の日）が必ず上回るので、解除しなくても結果は同じ（同等の変異）
    ("無効化の後も登録簿の確認日を使う", REG, '        if inv and last < inv:', '        if False:'),
    # 履歴の保持（C-event）: 通常の行は 35 日・無効化（changed・sale_ended）の行は 195 日（Wave 7e-1 最終）
    ("保持: 無効化の行を 195 日でなく 35 日で捨てる", REG, 'cut_n, cut_i = now - timedelta(days=RECHECK_HISTORY_DAYS), now - timedelta(days=RECHECK_INVALIDATION_DAYS)', 'cut_n, cut_i = now - timedelta(days=RECHECK_HISTORY_DAYS), now - timedelta(days=RECHECK_HISTORY_DAYS)'),
    ("保持: 通常の行を 195 日残す", REG, 'r.get("status") not in INVALIDATING_STATUSES and ts >= cut_n]', 'r.get("status") not in INVALIDATING_STATUSES and ts >= cut_i]'),
    ("保持: 件数の上限が無効化の行を消す（通常の行と合わせて先頭を切る）", REG, '    return sorted(normal + [r for r in keep if id(r) not in in_normal], key=lambda r: _recheck_ts(r))', '    return sorted(normal + [r for r in keep if id(r) not in in_normal], key=lambda r: _recheck_ts(r))[-RECHECK_HISTORY_LIMIT:]'),
    ("保持: 無効化の行を残さない", REG, '        if r.get("status") in INVALIDATING_STATUSES and ts >= cut_i and current:', '        if False:'),
    ("保持: 商品ごとに最新でなく最古の無効化を残す", REG, '            latest[str(r.get("product_id") or "")] = (ts, r)               # 時刻の昇順なので、最後が最新', '            latest.setdefault(str(r.get("product_id") or ""), (ts, r))'),
    ("保持: 無効化の行も商品ごとに絞らず全部残す（公開が増える）", REG, '            latest[str(r.get("product_id") or "")] = (ts, r)               # 時刻の昇順なので、最後が最新', '            latest[str(r.get("product_id") or "") + str(ts)] = (ts, r)'),
    ("保持: 回復の行を残さない（古い無効化が回復済みの現在を無効にする）", REG, '        if rec:\n            keep.append(rec[-1])', '        if False:\n            keep.append(rec[-1])'),
    ("保持: 同一性を確かめない一致も回復の行として残す", REG, 'and extends_verification(r) and recheck_identity_ok(pid, r, prods.get(pid))]\n        if rec:', 'and extends_verification(r)]\n        if rec:'),
    ("保持: 未来の日付の行を捨てない", REG, '        if ts is not None and ts <= limit:', '        if ts is not None:'),
    ("無効化: 古い記録（別の URL・価格）に対する観測でも今の記録を無効にする", REG, '''        if st in ("changed", "sale_ended") and (r.get("url") != v.get("url") or r.get("recorded_price") not in (None, v.get("price"))):\n            continue''', '''        if False:\n            continue'''),
    ("保持: 取得の時刻が開始時刻より後の行を未来として捨てる（許容幅なし）", REG, '    limit = now + timedelta(hours=RECHECK_CLOCK_SKEW_HOURS)', '    limit = now'),
    ("保持: 整理の基準を取得の前の開始時刻にする（今回の行が消える）", "scripts/recheck_official.py", 'hist = trim_history(hist + results, datetime.now(tz=JST))', 'hist = trim_history(hist + results, now)'),
    ("保持: 現行でない記録への無効化も最新として選ぶ", REG, 'and current:   # 古い記録', 'and True:   # 古い記録'),
    ("導出: 履歴を文字列の順で処理する（形式が混在すると順序がずれる）", REG, 'key=lambda x: (_recheck_ts(x) or _floor, str(x.get("observed_at") or "")))', 'key=lambda x: str(x.get("observed_at") or ""))'),
    ("保持: 無効化の保持日数の定数を 35 にする", REG, 'RECHECK_INVALIDATION_DAYS = 195', 'RECHECK_INVALIDATION_DAYS = 35'),
    ("保持: 履歴の整理が呼ばれない（日数で絞らない）", "scripts/recheck_official.py", '    return trim_recheck_history(hist, now)', '    return [r for r in hist if isinstance(r, dict)]'),
    ("DB: 履歴の無効化の持続を DB に反映しない（登録簿の古い確認日で確認済みに戻る）", AU, '        if inv and e.get("url") == v.get("url") and e.get("price") == v.get("price") and str(v.get("checked_on") or "") < inv:', '        if False:'),
    ("DB: 人の再確認の後も無効化を続ける（復帰できない）", AU, 'and str(v.get("checked_on") or "") < inv:', 'and True:'),
    # DB への引き継ぎの changed・sale_ended 除外と未来の日付の除外は、導出（advance_last_state の無効化・_valid_day）と二重の防御。導出側の変異で検知する
    ("DB への引き継ぎが履歴から導出しない", AU, '    ls = _derive_last_state(_hist, NOW.date(), products=products)', '    ls = {}'),
    ("引き継ぐ確認日が未来でも検証しない", REG, '            if not _valid_day(e.get("last_verified_at"), t):     # 引き継ぐ確認日が未来', '            if False:     # 引き継ぐ確認日が未来'),
    ("引き継いだ確認日を設定の行に書かない", AU, '                c.execute("UPDATE product_source_config SET extra_config = json_set(COALESCE(extra_config, \'{}\'), "\n                          "\'$.last_verified_at\', ?) WHERE product_id=? AND source_id=? "\n                          "AND COALESCE(json_extract(extra_config, \'$.verified\'), 0) = 1", (day, pid, v["source"]))\n                applied.append({"product_id": pid, "action": "price_reconfirmed_from_last_state"', '                applied.append({"product_id": pid, "action": "price_reconfirmed_from_last_state"'),
    ("今日の失敗で、前回の実際の確認日を引き継がない", AU, '    for pid, e in ls.items():\n        v = VERIFIED_URLS.get(pid)', '    for pid, e in []:\n        v = VERIFIED_URLS.get(pid)'),
    ("同じ実行の再生成が復元の結果を上書きする", C, '    if ledger_state != LEDGER_REUSED_WITHIN_RUN:\n        return ledger_state if ledger_state in ALLOWED_RESTORE else "UNKNOWN"', '    if True:\n        return ledger_state if ledger_state in ALLOWED_RESTORE else "UNKNOWN"'),
    ("別の実行の復元の結果を引き継ぐ", C, '    first = raw.get("first_ledger_state") if isinstance(raw, dict) and raw.get("run_id") == run_id else None', '    first = raw.get("first_ledger_state") if isinstance(raw, dict) else None'),
    ("商品ごとの公式の状態・台帳の個別の項目を非公開にしない", C, '    "official_states", "official_state", "first_ledger_state"})', '    })'),
    ("公開の復元の結果が語彙外を通す", C, '"ledger_restore_status": report.get("ledger_restore_status") if report.get("ledger_restore_status") in ALLOWED_RESTORE else "UNKNOWN",', '"ledger_restore_status": report.get("ledger_restore_status"),'),
    ("最初の復元の結果を台帳に保存しない", C, '"first_ledger_state": report.get("ledger_restore_status")}, ensure_ascii', '"first_ledger_state": None}, ensure_ascii'),
    ("商品ごとの公式の状態を非公開に書かない", C, '(priv / "official_state.json").write_text(', '(priv / "official_state.tmp").write_text('),
    ("測れなかった件数に前の run で処理済みを混ぜる", C, 'for k in ("unknown_published_at", "source_gap_excluded", "previously_observable_excluded")),', 'for k in ("unknown_published_at", "source_gap_excluded", "previously_observable_excluded", "already_processed")),'),
    ("再実行（run_attempt が 2 以上）の遅れも計算する", RO, '    if trigger != "schedule" or run_attempt != 1 or scheduled_for_ is None or started_at is None:', '    if scheduled_for_ is None or started_at is None:'),
    ("公開の記録に許可リスト外の項目を足す", RO, '    return {k: out[k] for k in PUBLIC_KEYS}', '    return dict(out, secret="x")'),
    ("開始が予定より前の日の予定を使わない", RO, '    return cand - timedelta(days=1) if cand > s else cand', '    return cand'),
    ("異常な所要時間を捨てない", RO, '    if runtime is not None and not (0 <= runtime <= MAX_RUNTIME_SECONDS):', '    if False:'),
]
bad = 0
for desc, f, old, new in M:
    s = open(f).read()
    if old not in s:
        print("無効（置換元なし）", desc); bad += 1; continue
    open(f, "w").write(s.replace(old, new, 1))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS], capture_output=True, text=True, timeout=300)
        ok = r.returncode != 0
    except subprocess.TimeoutExpired:
        ok = True
    finally:
        open(f, "w").write(s)
    print("検出" if ok else "★見逃し", desc)
    bad += (not ok)
print("見逃し/無効:", bad, "/", len(M))
