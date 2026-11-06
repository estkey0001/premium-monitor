#!/usr/bin/env python3
"""Coverage Wave 7b の変異テスト: 作業キューの規則を 1 つずつ壊して、テストが検知することを確かめる。

リポジトリのルートで実行: python3 scripts/mutation_wave7b.py
各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストを足す。
注意: 追跡対象のソースをその場で書き換える。他のセッションが同じファイルを編集していないときに実行する（強制終了すると変異が残る）。
"""
# ruff: noqa
import subprocess, sys
Q = "src/research/operator_queue.py"; C = "src/research/candidates.py"; PD = "src/tcg/profit_dense.py"
TESTS = "tests/test_coverage_wave7b.py tests/test_market_research.py".split()
M = [
    ("古い候補が URGENT のまま残る", Q, '    if stale or missing & LOW_CONF or missing & WEAK_IDENTITY or C.GENERIC_SELL_URL in missing:\n        return LOW',
     '    if missing & LOW_CONF or missing & WEAK_IDENTITY or C.GENERIC_SELL_URL in missing:\n        return LOW'),
    ("誤価格の疑いが URGENT / HIGH になる", Q, 'if stale or missing & LOW_CONF or', 'if stale or'),
    ("同一性が弱い候補が上位になる", Q, ' or missing & WEAK_IDENTITY or C.GENERIC_SELL_URL in missing:', ' or C.GENERIC_SELL_URL in missing:'),
    ("同一性が一部でも URGENT になる", Q, '    positive = isinstance(spread, int) and spread >= MIN_SPREAD_YEN\n', '    positive = isinstance(spread, int) and spread >= MIN_SPREAD_YEN\n    identity_ok = True\n'),
    ("価格差が正でなくても URGENT になる", Q, 'if positive and identity_ok and missing and missing <= URGENT_MISSING_OK', 'if identity_ok and missing and missing <= URGENT_MISSING_OK'),
    ("不足が 3 個以上でも URGENT になる", Q, 'and len(missing) <= URGENT_MAX_MISSING:', ':'),
    ("許していない種類の不足があっても URGENT になる", Q, 'and missing <= URGENT_MISSING_OK and', 'and'),
    ("公式の未確認が残っても URGENT になる", Q, 'URGENT_MISSING_OK = frozenset({C.PURCHASE_SHIPPING_UNKNOWN, C.STOCK_UNKNOWN, C.NEEDS_CORROBORATION})',
     'URGENT_MISSING_OK = frozenset({C.PURCHASE_SHIPPING_UNKNOWN, C.STOCK_UNKNOWN, C.NEEDS_CORROBORATION, C.OFFICIAL_UNVERIFIED})'),
    ("誤価格の疑いでも価格差を加点する", Q, 'if isinstance(spread, int) and spread > 0 and not (missing & LOW_CONF):', 'if isinstance(spread, int) and spread > 0:'),
    ("隔離された価格の急騰を加点する", Q, 'if momentum["usable"] and not momentum["quarantined"] and not stale and identity_ok and not (missing & QUARANTINE):', 'if momentum["state"] == "RISING":'),
    ("条件を満たさない急騰も加点する", Q, 'if momentum["usable"] and not momentum["quarantined"] and not stale and identity_ok and not (missing & QUARANTINE):', 'if momentum["delta_yen"]:'),
    ("古い候補にも急騰を加点する", Q, 'if momentum["usable"] and not momentum["quarantined"] and not stale and identity_ok and not (missing & QUARANTINE):', 'if momentum["usable"] and not momentum["quarantined"] and identity_ok and not (missing & QUARANTINE):'),
    ("古い候補の減点をしない", Q, '    if stale:\n        score -= 30', '    if False:\n        score -= 30'),
    ("不足している証拠の減点をしない", Q, '    if miss:\n        score -= 4 * miss', '    if False:\n        score -= 4 * miss'),
    ("次の行動を取り違える（公式の価格 → 送料）", Q, '(frozenset({C.OFFICIAL_UNVERIFIED}), VERIFY_OFFICIAL_PRICE)', '(frozenset({C.OFFICIAL_UNVERIFIED}), VERIFY_SHIPPING)'),
    ("次の行動を取り違える（送料 → 在庫）", Q, '(frozenset({C.PURCHASE_SHIPPING_UNKNOWN}), VERIFY_SHIPPING)', '(frozenset({C.PURCHASE_SHIPPING_UNKNOWN}), VERIFY_STOCK)'),
    ("次の行動を取り違える（在庫 → 送料）", Q, '(frozenset({C.STOCK_UNKNOWN}), VERIFY_STOCK)', '(frozenset({C.STOCK_UNKNOWN}), VERIFY_SHIPPING)'),
    ("次の行動を取り違える（同一性）", Q, '(frozenset({C.IDENTITY_UNCONFIRMED, C.IDENTITY_PARTIAL}), VERIFY_IDENTITY)', '(frozenset({C.IDENTITY_UNCONFIRMED, C.IDENTITY_PARTIAL}), VERIFY_OFFICIAL_PRICE)'),
    ("古い価格に新しい価格を待つ行動を付けない", Q, '    (STALE_REASONS, WAIT_FOR_FRESH_PRICE),\n', ''),
    ("次の行動の優先順を入れ替える（送料が公式より先）", Q, '    (frozenset({C.OFFICIAL_UNVERIFIED}), VERIFY_OFFICIAL_PRICE),\n', '    (frozenset({C.PURCHASE_SHIPPING_UNKNOWN}), VERIFY_SHIPPING),\n    (frozenset({C.OFFICIAL_UNVERIFIED}), VERIFY_OFFICIAL_PRICE),\n'),
    ("TCG の応募の URL が無くても確認の行動にしない", Q, 'if not app_urls and not no_url_channel:', 'if False:'),
    ("SNS・アプリの経路でも応募の URL の確認にする", Q, 'if not app_urls and not no_url_channel:', 'if not app_urls:'),
    ("日付だけの締切を時刻つきとして加点する", Q, '    precise = r.get("application_end_precision") == "datetime"', '    precise = True'),
    ("締切の加点をしない", Q, 'boost = (20 + int((24 - hours) / 2)) if hours <= 24 else (10 if hours <= 72 else 0)', 'boost = 0'),
    ("日付だけの締切に大きく加点する", Q, 'boost = 3 if hours <= 72 else 0', 'boost = 20 if hours <= 72 else 0'),
    ("締切不明でも加点する", Q, 'if status in TCG_ACTIVE and hours is not None and hours >= 0:', 'if status in TCG_ACTIVE:\n            hours = hours or 0'),
    ("締切が近い TCG を URGENT にしない", Q, 'elif status in TCG_ACTIVE and precise and hours is not None and 0 <= hours <= 24 and rep_identity_ok:', 'elif False:'),
    ("日付だけの締切を URGENT にする", Q, 'elif status in TCG_ACTIVE and precise and hours is not None and 0 <= hours <= 24 and rep_identity_ok:', 'elif status in TCG_ACTIVE and hours is not None and 0 <= hours <= 24 and rep_identity_ok:'),
    ("応募の対象でない TCG の状態もキューに入れる", Q, 'if isinstance(r, dict) and str(r.get("status") or "") in (TCG_ACTIVE | {"UPCOMING"}):', 'if isinstance(r, dict):'),
    ("同じ小売・商品の TCG を 1 件にまとめない", Q, '    raw = f"{r.get(\'retailer\')}|{ident}|{r.get(\'event_type\')}"', '    raw = f"{id(r)}"'),
    ("今回見えなかった候補（STALE）をキューに入れる", Q, '        if str(c.get("status")) == C.STALE:\n            not_seen += 1\n        elif', '        if str(c.get("status")) == C.STALE:\n            not_seen += 1\n            items.append(_product_item(c, G_PRODUCT, now))\n        elif'),
    ("研究候補でない未登録商品を入れる", Q, 'if isinstance(r, dict) and str(r.get("status")) == C.RESEARCH_CANDIDATE:', 'if isinstance(r, dict):'),
    ("キューの上限を外す", Q, 'limit = max(0, _int(max_queue, MAX_QUEUE))', 'limit = 10**6'),
    ("同点で並びが不安定（ID で決めない）", Q, '"_sort": (_CLASS_ORDER[cls], -score, -(spread or 0), -(_ts_key(last, now)), str(row.get("candidate_id") or "")),', '"_sort": (_CLASS_ORDER[cls], -score, -(spread or 0), -(_ts_key(last, now)), 0),'),
    ("区分より点を先に並べる", Q, '"_sort": (_CLASS_ORDER[cls], -score,', '"_sort": (-score, _CLASS_ORDER[cls],'),
    ("鮮度で並べない", Q, '-(spread or 0), -(_ts_key(last, now)), str(row.get("candidate_id") or "")),', '-(spread or 0), 0.0, str(row.get("candidate_id") or "")),'),
    ("入力の候補を書き換える", Q, '    items.sort(key=lambda x: x["_sort"])', '    items.sort(key=lambda x: x["_sort"])\n    for _c in candidates or []:\n        if isinstance(_c, dict):\n            _c["status"] = "VERIFIED"'),
    ("公開の集計に個別のキューが混ざる", C, '        "operator_queue_counts": _count_dict(m.get("operator_queue"), COVERAGE_KEYS["operator_queue_counts"]),', '        "operator_queue_counts": m.get("operator_queue"),'),
    ("作業キューを公開側のディレクトリへ書く", C, '    (priv / "operator_queue.json").write_text(', '    (pub / "operator_queue.json").write_text('),
    ("個別のキューが非公開の項目の一覧から外れる", C, '    "operator_queue", "queue", "next_action", "next_actions", "missing_evidence", "score_parts", "score",', ''),
    ("キューを作らずに build する", C, '        oq = _oq.build(candidates=cands, product_candidates=tri["rows"], tcg_events=pd["events"], now=now,', '        oq = _oq.build(candidates=[], product_candidates=[], tcg_events=[], now=now,'),
    ("TCG のキューに締切の項目が渡らない", PD, '"hours_to_deadline": round((en - now).total_seconds() / 3600, 1) if en is not None else None, **c})', '"hours_to_deadline": None, **c})'),
    ("TCG の締切の精度を落とす（日付だけが時刻つきに見える）", PD, '"application_end_precision": en_prec if en is not None else "",', '"application_end_precision": "datetime",'),
    ("同一性が未確認の TCG を URGENT にする", Q, 'and 0 <= hours <= 24 and rep_identity_ok:', 'and 0 <= hours <= 24:'),
    ("価格差の下限（500 円）を外す", Q, 'MIN_SPREAD_YEN = 500 ', 'MIN_SPREAD_YEN = 0 '),
    ("TCG の枠の上限を外す", Q, 'TCG_MAX_IN_QUEUE = 4 ', 'TCG_MAX_IN_QUEUE = 100 '),
    ("観測時刻が読めない・未来でも新しいと扱う", Q, 'or unreadable_time or age > STALE_HOURS', 'or (age is not None and age > STALE_HOURS)'),
    ("未来の観測時刻が並びで有利になる", Q, 'return 0.0 if t is None or t > now + timedelta(hours=FUTURE_TOLERANCE_HOURS) else t.timestamp()', 'return 0.0 if t is None else t.timestamp()'),
    ("価格差があっても HIGH にしない", Q, '        return HIGH if len(missing - C.ADVISORY) <= 4 else MEDIUM', '        return MEDIUM'),
    ("足りない証拠が多くても HIGH にする", Q, '        return HIGH if len(missing - C.ADVISORY) <= 4 else MEDIUM', '        return HIGH'),
    ("TCG の同一性を最も近い店舗だけで見る（全店舗を見ない）", Q, 'identity_ok = any(', 'identity_ok = all('),
    ("TCG の応募の URL を最も近い店舗だけで見る", Q, 'for x in rows if x.get("application_url")})', 'for x in rows[:1] if x.get("application_url")})'),
    ("小数の価格差を読まない", Q, 'if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf"):', 'if isinstance(v, int) and not isinstance(v, bool):'),
    ("作業キューの失敗が調査レポートを止める", C, '    except Exception as exc:  # noqa: BLE001 - 作業キューは', '    except KeyError as exc:  # noqa: BLE001 - 作業キューは'),
    ("失敗時の空のキューが、壊れた部品をもう一度呼ぶ", C, '        oq = _oq.empty(now)\n', '        oq = _oq.build(candidates=[], product_candidates=[], tcg_events=[], now=now)\n'),
    ("隔離された価格差の加点に上限をかけない", Q, '            pts = min(pts, QUARANTINE_SPREAD_CAP) ', '            pts = pts  '),
    ("失敗の件数を公開に出さない（0 件と区別できない）", Q, '    counts["queue_build_failed"] = 1 ', '    counts["queue_build_failed"] = 0 '),
    ("例外のメッセージ（入力の値）をログに出す", C, 'logging.getLogger(__name__).warning("operator_queue の組み立てに失敗（空のキューにする）: %s", type(exc).__name__)', 'logging.getLogger(__name__).warning("operator_queue の組み立てに失敗（空のキューにする）: %s: %s", type(exc).__name__, exc)'),
    ("信号だけで同一性が弱い候補を MEDIUM にする", Q, ' and identity_ok and not (missing & QUARANTINE)', ''),
    ("隔離された急騰で MEDIUM にする", Q, '(mom["usable"] and not mom["quarantined"])', 'mom["usable"]'),
    ("締切を過ぎた TCG を優先する", Q, '        if expired or stale:\n            cls = LOW\n', '        if False:\n            cls = LOW\n'),
    ("真偽値・文字列を締切までの時間として読む", Q, '    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        return None', '    if not isinstance(value, (int, float, str, bool)):\n        return None\n    if isinstance(value, str):\n        return float(value) if value.replace(".", "").isdigit() else None'),
    ("足りない証拠の文字列を 1 文字ずつの集合にする", Q, '    if isinstance(value, str):\n        return {value} if value else set()', '    if isinstance(value, str):\n        return set(value)'),
    ("次の行動が無い候補に既定の行動を付けない", Q, '    if not acts and cls != LOW:', '    if False:'),
    ("収集が失敗した日の TCG を新しい情報として扱う", Q, '        stale = (not fresh) or (not source_ok) ', '        stale = False '),
    ("健全でない取得元の TCG を新しい情報として扱う", Q, '        stale = (not fresh) or (not source_ok) ', '        stale = (not fresh) '),
    ("鮮度が candidates から渡らない", C, '                       tcg_fresh=tcg_input_fresh, tcg_healthy_sources=tcg_healthy_sources)', '                       )'),
    ("締切の加点を近さで段階づけない", Q, 'boost = (20 + int((24 - hours) / 2)) if hours <= 24 else (10 if hours <= 72 else 0)', 'boost = 20 if hours <= 24 else (10 if hours <= 72 else 0)'),
    ("TCG の並びの鍵に締切を使わない", Q, '"_sort": (_CLASS_ORDER[cls], -score, hours if hours is not None else 10**6, 0.0, gid),', '"_sort": (_CLASS_ORDER[cls], -score, 0, 0.0, gid),'),
    ("TCG の最低枠を確保しない", Q, 'if tcg_n >= min(TCG_MIN_IN_QUEUE, limit):', 'if True:'),
    ("LOW の行が期限つきの TCG を押し出す", Q, 'if worst is not None and worst["genre"] != G_TCG and worst["priority"] == LOW and it["priority"] != LOW:', 'if False:'),
    ("HIGH の商品まで URGENT の TCG に入れ替える", Q, 'if worst is not None and worst["genre"] != G_TCG and worst["priority"] == LOW and it["priority"] != LOW:', 'if worst is not None and worst["genre"] != G_TCG and it["_sort"][0] < worst["_sort"][0]:'),
    ("期限切れの行が代表になる", Q, "        live = [x for x in rows if _h(x) is None or _h(x) >= 0] or rows", "        live = rows"),
    ("URGENT が代表でない店舗の同一性で決まる", Q, 'and 0 <= hours <= 24 and rep_identity_ok:', 'and 0 <= hours <= 24 and identity_ok:'),
    ("TCG の条件の型の揺れで例外になる", Q, "        requirements = sorted({q for x in rows for q in _reasons(x.get(\"requirements\"))})", "        requirements = sorted({str(q) for x in rows for q in (x.get(\"requirements\") or [])})"),
    ("隔離された行に急騰の加点をする", Q, ' and identity_ok and not (missing & QUARANTINE):\n        score += 10', ' and identity_ok:\n        score += 10'),
    ("信号だけの MEDIUM に次の行動を付けない", Q, '    if not acts and cls != LOW:', '    if False:'),
    ("古さの境界（72 時間）を延ばす", Q, 'STALE_HOURS = 72 ', 'STALE_HOURS = 96 '),
    ("TCG の URGENT の窓（24 時間）を延ばす", Q, 'and 0 <= hours <= 24 and rep_identity_ok:', 'and 0 <= hours <= 48 and rep_identity_ok:'),
]
bad = 0
for desc, f, old, new in M:
    s = open(f).read()
    if old not in s:
        print("無効（置換元なし）", desc); bad += 1; continue
    open(f, "w").write(s.replace(old, new, 1))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS], capture_output=True, text=True, timeout=240)
        ok = r.returncode != 0
    except subprocess.TimeoutExpired:
        ok = True
    finally:
        open(f, "w").write(s)
    print("検出" if ok else "★見逃し", desc)
    bad += (not ok)
print("見逃し/無効:", bad, "/", len(M))
