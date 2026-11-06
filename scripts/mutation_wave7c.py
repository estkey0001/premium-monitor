#!/usr/bin/env python3
"""Coverage Wave 7c の変異テスト: 価格の種類・公式が確認できない原因・作業キューの次の行動の規則を 1 つずつ壊して、テストが検知することを確かめる。

リポジトリのルートで実行: python3 scripts/mutation_wave7c.py
各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストを足す。
注意: 追跡対象のソースをその場で書き換える。他のセッションが同じファイルを編集していないときに実行する（強制終了すると変異が残る）。
"""
# ruff: noqa
import subprocess, sys
EG = "src/research/evidence_gap.py"; R = "src/research/retail_lookup.py"; C = "src/research/candidates.py"; Q = "src/research/operator_queue.py"
TESTS = "tests/test_coverage_wave7c.py tests/test_coverage_wave7b.py tests/test_market_research.py tests/test_coverage_wave3.py".split()
M = [
    ("ポイントを現金から引く（現金の仕入れ値にする）", R, '        basis, eff = BASIS_UNCONDITIONAL, (listed - imm if listed else None)', '        basis, eff = BASIS_UNCONDITIONAL, (listed - imm - (_int(e.get("points")) or 0) if listed else None)'),
    ("キャッシュバックを現金から引く", R, '        basis, eff = BASIS_UNCONDITIONAL, (listed - imm if listed else None)', '        basis, eff = BASIS_UNCONDITIONAL, (listed - imm - (_int(e.get("cashback")) or 0) if listed else None)'),
    ("クーポンの価格を確定に使えることにする", EG, 'CONFIRMABLE_TYPES = frozenset({REGULAR, SALE})', 'CONFIRMABLE_TYPES = frozenset({REGULAR, SALE, COUPON})'),
    ("会員限定の価格を確定に使えることにする", EG, 'CONFIRMABLE_TYPES = frozenset({REGULAR, SALE})', 'CONFIRMABLE_TYPES = frozenset({REGULAR, SALE, MEMBERSHIP})'),
    ("条件つきの価格を確定に使えることにする", EG, 'CONFIRMABLE_TYPES = frozenset({REGULAR, SALE})', 'CONFIRMABLE_TYPES = frozenset({REGULAR, SALE, CONDITIONAL})'),
    ("クーポンを通常価格に分類する", EG, '    elif _COND_COUPON in conds:\n        ptype = COUPON', '    elif False:\n        ptype = COUPON'),
    ("会員限定を通常価格に分類する", EG, '    elif _COND_MEMBER in conds:\n        ptype = MEMBERSHIP', '    elif False:\n        ptype = MEMBERSHIP'),
    ("キャンペーン・数量限定を通常価格に分類する", EG, '    elif conds:\n        ptype = CONDITIONAL', '    elif False:\n        ptype = CONDITIONAL'),
    ("条件なしの即時値引きを SALE と認めない", EG, '    elif _n(ev.get("immediate_discount")) > 0:\n        ptype = SALE', '    elif False:\n        ptype = SALE'),
    ("ポイント・キャッシュバックの参考を残さない", EG, '    refs = [t for t, k in ((POINTS, "points"), (CASHBACK, "cashback")) if _n(ev.get(k)) > 0]', '    refs = []'),
    ("価格が読めなくても REGULAR にする", EG, '    if not _n(ev.get("listed_price")) and not _n(ev.get("effective_price")):\n        ptype = UNKNOWN', '    if False:\n        ptype = UNKNOWN'),
    ("価格の種類を照会の結果に付けない", R, '    out.update(_eg.price_type_of(out))', '    pass'),
    ("価格の種類だけの条件つきを確定に使う", C, '                       or r.get("retail_price_type") in ("COUPON", "MEMBERSHIP", "CONDITIONAL"))', '                       )'),
    ("価格の種類を候補の行に残さない", C, '                          "retail_price_type": str(lk.get("price_type") or "UNKNOWN"),', '                          "retail_price_type": "UNKNOWN",'),
    ("条件つきで確定に使わなかった価格を数え間違える", EG, '        out["rejected_conditional"] += int(t in (COUPON, MEMBERSHIP, CONDITIONAL))', '        out["rejected_conditional"] += int(t in (COUPON,))'),
    ("販売終了を原因として扱わない", EG, '    if official_not_sold or meta.get("official_not_sold") or meta.get("recheck_sale_ended") or meta.get("registry_sale_ended"):\n        return SALE_ENDED', '    if False:\n        return SALE_ENDED'),
    ("商品の不一致を原因として扱わない", EG, '    if meta.get("identity_mismatch"):\n        return IDENTITY_NOT_MATCHED', '    if False:\n        return IDENTITY_NOT_MATCHED'),
    ("取得元が未登録を原因として扱わない", EG, '    if not has_url:\n        return SOURCE_NOT_IMPLEMENTED', '    if False:\n        return SOURCE_NOT_IMPLEMENTED'),
    ("遮断を原因として扱わない", EG, '    if source_blocked or meta.get("source_blocked"):\n        return SOURCE_BLOCKED', '    if False:\n        return SOURCE_BLOCKED'),
    ("確認が古いことを設定値だけと取り違える", EG, '    if ev == _EV_STALE:\n        return VERIFICATION_STALE', '    if ev == _EV_STALE:\n        return CONFIGURED_PRICE_ONLY'),
    ("設定値だけを確認が古いと取り違える", EG, '    if ev == _EV_CONFIGURED:\n        return CONFIGURED_PRICE_ONLY', '    if ev == _EV_CONFIGURED:\n        return VERIFICATION_STALE'),
    ("価格を読めていないことを原因不明にする", EG, '    if ev == _EV_UNKNOWN:\n        return PRICE_NOT_FOUND', '    if ev == _EV_UNKNOWN:\n        return UNKNOWN_CAUSE'),
    ("原因を候補の行に付けない", C, '        if OFFICIAL_UNVERIFIED in row["exclusion_reasons"] or OFFICIAL_NOT_SOLD in row["exclusion_reasons"]:', '        if False:'),
    ("原因の件数に含まれない候補を数える", EG, '        if isinstance(c, str) and c in out:\n            out[c] += 1', '        if True:\n            out[c] = out.get(c, 0) + 1'),
    ("販売終了でも公式の確認を次の行動にする", Q, '    _gap_action = {"SALE_ENDED": VERIFY_RETAIL_PRICE, ', '    _gap_action = {"SALE_ENDED": VERIFY_OFFICIAL_PRICE, '),
    ("公式が売っていない商品に公式の価格の確認を付ける", Q, '    (frozenset({C.OFFICIAL_NOT_SOLD}), VERIFY_RETAIL_PRICE),', '    (frozenset({C.OFFICIAL_NOT_SOLD}), VERIFY_OFFICIAL_PRICE),'),
    ("公式の未確認に小売の価格の確認を付ける", Q, '    (frozenset({C.OFFICIAL_UNVERIFIED}), VERIFY_OFFICIAL_PRICE),', '    (frozenset({C.OFFICIAL_UNVERIFIED}), VERIFY_RETAIL_PRICE),'),
    ("公開の集計に原因の個別の項目が混ざる", C, '        "official_gap_counts": _count_dict(m.get("official_gap_counts"), COVERAGE_KEYS["official_gap_counts"]),', '        "official_gap_counts": m.get("official_gap_counts"),'),
    ("公開の集計に価格の種類の個別の項目が混ざる", C, '        "price_type_counts": _count_dict(m.get("price_type_counts"), COVERAGE_KEYS["price_type_counts"]),', '        "price_type_counts": m.get("price_type_counts"),'),
    ("原因・価格の種類の項目が非公開の一覧から外れる", C, '    "official_gap", "retail_price_type", "retail_confirmable", "retail_reference_types", "price_type", "confirmable", "reference_types",', ''),
    ("同一性が確認できない商品を原因として扱わない", EG, '    if meta.get("identity_mismatch"):\n        return IDENTITY_NOT_MATCHED', '    if False:\n        return IDENTITY_NOT_MATCHED'),
    ("確認済みでも遮断を原因にする", EG, '    if ev in _EV_VERIFIED:\n        return UNKNOWN_CAUSE                          # 確認済みなら不足ではない（遮断・ページの変更より先に判定）', '    if False:\n        return UNKNOWN_CAUSE'),
    ("ページの変更（価格を読めない）を原因にしない", EG, '    if meta.get("recheck_failed"):\n        return PAGE_CHANGED', '    if False:\n        return PAGE_CHANGED'),
    ("古い遮断の記録を今日のものとして使う", EG, '        if age < timedelta(hours=-1) or age > timedelta(hours=max_age_hours):\n            continue', '        if False:\n            continue'),
    ("未来の時刻の記録を使う", EG, '        if age < timedelta(hours=-1) or age > timedelta(hours=max_age_hours):\n            continue', '        if age > timedelta(hours=max_age_hours):\n            continue'),
    ("確認済み・販売終了の同一性も不一致の旗にする", EG, '        elif state == "PARTIAL_IDENTITY":', '        elif state in ("PARTIAL_IDENTITY", "IDENTITY_CONFIRMED", "DISCONTINUED"):'),
    ("同一性の判断ができない商品に旗を立てる", EG, '        except Exception:  # noqa: BLE001 - 判断できない商品は旗を立てない（推測しない）\n            continue', '        except Exception:  # noqa: BLE001\n            state = "AMBIGUOUS"'),
    ("取得元が未登録の次の行動を公式の確認のままにする", Q, '                   "SOURCE_NOT_IMPLEMENTED": REGISTER_OFFICIAL_SOURCE,', '                   "SOURCE_NOT_IMPLEMENTED": VERIFY_OFFICIAL_PRICE,'),
    ("同一性が確認できないときの次の行動を公式の確認のままにする", Q, '                   "IDENTITY_NOT_MATCHED": VERIFY_IDENTITY}', '                   "IDENTITY_NOT_MATCHED": VERIFY_OFFICIAL_PRICE}'),
    ("現金の価格が確定できなくても確定に使える", EG, '    elif "effective_price" in ev and not _n(ev.get("effective_price")):\n        ptype = UNKNOWN', '    elif False:\n        ptype = UNKNOWN'),
    ("壊れた条件を条件なしと読む", EG, '        conds = {"UNREADABLE"} ', '        conds = set() '),
    ("生成側が再確認の記録を使わない", "src/content/daily_lp_generator.py", '                _eg.merge_signals(_official_meta, _eg.official_signals(', '                (lambda *a: None)(_official_meta, _eg.official_signals('),
    ("遮断・到達不能の理由を価格を読めないと取り違える", EG, 'failed_key = "source_blocked" if (why in _BLOCKED_REASONS or why in _UNREACHABLE_REASONS) else "recheck_failed"', 'failed_key = "recheck_failed"'),
    ("ページ側・未知の理由を遮断と断定する", EG, 'failed_key = "source_blocked" if (why in _BLOCKED_REASONS or why in _UNREACHABLE_REASONS) else "recheck_failed"', 'failed_key = "source_blocked"'),
    ("再確認の販売終了を使わない", EG, '"failed": failed_key, "sale_ended": "recheck_sale_ended", "changed": "price_changed",', '"failed": failed_key, "changed": "price_changed",'),
    ("再確認の価格の変化を使わない", EG, '"sale_ended": "recheck_sale_ended", "changed": "price_changed",', '"sale_ended": "recheck_sale_ended",'),
    ("価格の変化を原因として扱わない", EG, '    if meta.get("price_changed"):\n        return PRICE_CHANGED', '    if False:\n        return PRICE_CHANGED'),
    ("再確認の URL を補わない", EG, '        if pid and _https_url_ok(url):', '        if False:'),
    ("分類専用の URL が買い側の url を上書きする", EG, '            if k in SIGNAL_KEYS:                             # 許可した旗だけ', '            if k == "gap_url":\n                m["url"] = v\n            if k in SIGNAL_KEYS:                             # 許可した旗だけ'),
    ("https 以外の URL を根拠にする", EG, 'url[:8].lower() != "https://" or not url.isprintable()', 'not url.isprintable()'),
    ("タイムゾーンなしの現在時刻で落とす", EG, '    if getattr(now, "tzinfo", None) is None:\n        now = now.replace(tzinfo=timezone(timedelta(hours=9)))', '    if False:\n        pass'),
    ("信号の組み立ての失敗が調査レポートを止める", "src/content/daily_lp_generator.py", '            except Exception as _exc:  # noqa: BLE001\n                logger.warning("公式の確認の信号の組み立てに失敗（旗なしで続ける）', '            except KeyError as _exc:  # noqa: BLE001\n                logger.warning("公式の確認の信号の組み立てに失敗（旗なしで続ける）'),
    ("買取店の遮断を公式の遮断として扱う", C, '                source_blocked=False)       # 公式の取得元の遮断は', '                source_blocked=str(meta.get("source_id") or "") in blocked_sources)       # 公式の取得元の遮断は'),
    ("再確認の販売終了を、候補の買い側の経路を切り替える旗にする", EG, '"sale_ended": "recheck_sale_ended"', '"sale_ended": "official_not_sold"'),
    ("再確認の販売終了を原因として扱わない", EG, ' or meta.get("recheck_sale_ended") or meta.get("registry_sale_ended"):', ' or meta.get("registry_sale_ended"):'),
    ("同一性が未決を原因として扱わない", EG, '    if meta.get("identity_undecided"):\n        return IDENTITY_NOT_MATCHED', '    if False:\n        return IDENTITY_NOT_MATCHED'),
    ("同一性が未決の商品に旗を立てない", EG, '        if state in ("AMBIGUOUS", "NEEDS_USER_DECISION"):', '        if False:'),
    ("型番・JAN の登録だけある商品を未決にする", EG, '        elif state == "PARTIAL_IDENTITY":\n            _flag(p.get("id") or p.get("product_id"), "identity_mismatch")', '        elif state == "PARTIAL_IDENTITY":\n            _flag(p.get("id") or p.get("product_id"), "identity_undecided")'),
    ("ホストのラベルの空（連続ドット）を認める", EG, 'all(lb and not lb.startswith("-") and not lb.endswith("-") for lb in labels)', 'all(not lb.startswith("-") and not lb.endswith("-") for lb in labels)'),
    ("空白・バックスラッシュを含む URL を根拠にする", EG, ' or not url.isprintable() or any(ch.isspace() or ch == "\\\\" for ch in url)):', ' or not url.isprintable()):'),
    ("価格の条件の元の項目を読まない（クーポン）", EG, '    if str(ev.get("required_coupon") or "").strip():\n        conds = set(conds) | {_COND_COUPON}', '    if False:\n        conds = set(conds) | {_COND_COUPON}'),
    ("価格の条件の元の項目を読まない（会員限定）", EG, '    if ev.get("member_only"):\n        conds = set(conds) | {_COND_MEMBER}', '    if False:\n        conds = set(conds) | {_COND_MEMBER}'),
    ("価格の条件の元の項目を読まない（キャンペーン・数量限定）", EG, '    if str(ev.get("campaign_conditions") or "").strip() or _n(ev.get("campaign_price")) or ev.get("limited_quantity"):', '    if False:'),
    ("壊れたメタで落ちる", EG, '        if not isinstance(m, dict):\n            m = meta_by_pid[pid] = {}', '        if False:\n            pass'),
    ("件数に型の違う値が混ざると落ちる", EG, '        if isinstance(c, str) and c in out:', '        if c in out:'),
    ("登録簿の販売終了を原因として扱わない", EG, ' or meta.get("recheck_sale_ended") or meta.get("registry_sale_ended"):', ' or meta.get("recheck_sale_ended"):'),
    ("登録簿の販売終了に旗を立てない", EG, '        elif state == "DISCONTINUED":\n            _flag(p.get("id") or p.get("product_id"), "registry_sale_ended")', '        elif False:\n            pass'),
    ("登録簿の販売終了を、買い側の経路を切り替える旗にする", EG, '            _flag(p.get("id") or p.get("product_id"), "registry_sale_ended")', '            _flag(p.get("id") or p.get("product_id"), "official_not_sold")'),
    ("根拠のページの有無に分類専用の URL を読まない", EG, '    has_url = bool(str(meta.get("url") or "").strip()) or bool(str(meta.get("gap_url") or "").strip())', '    has_url = bool(str(meta.get("url") or "").strip())'),
    ("分類専用の URL を買い側の URL に補う", EG, '            if k in SIGNAL_KEYS:                             # 許可した旗だけ', '            if k == "gap_url" and not str(m.get("url") or "").strip():\n                m["url"] = v\n            if k in SIGNAL_KEYS:                             # 許可した旗だけ'),
    ("不可視文字・DEL を含む URL を根拠にする", EG, ' or not url.isprintable() or any(', ' or any('),
    ("生の IDN のホストを根拠にする", EG, 'set(host) <= _HOST_CHARS and len(labels) >= 2', 'len(labels) >= 2'),
    ("IP リテラル風のホストを根拠にする", EG, '    if all(lb.isdigit() or lb.lower().startswith("0x") for lb in labels) or labels[-1].isdigit():\n        return False', '    if False:\n        return False'),
    ("販売終了でも価格差を優先度に使う", Q, '    if gap == "SALE_ENDED" and str(row.get("route_type") or "") != C.SECONDARY_TO_BUYBACK:', '    if False:'),
    ("SECONDARY_TO_BUYBACK でも価格差を消す", Q, ' and str(row.get("route_type") or "") != C.SECONDARY_TO_BUYBACK:', ':'),
    ("ポートの ASCII 限定を外す", EG, '(port.isascii() and port.isdigit() and len(port) <= 5 and 1 <=', '(port.isdigit() and len(port) <= 5 and 1 <='),
    ("ポートの範囲を検査しない", EG, '    return not _sep or (port.isascii() and port.isdigit() and len(port) <= 5 and 1 <= int(port) <= 65535)', '    return not _sep or (port.isascii() and port.isdigit() and len(port) <= 5)'),
    ("再確認の一致を原因として扱わない", EG, '    if meta.get("recheck_matched"):\n        return RECHECK_MATCHED', '    if False:\n        return RECHECK_MATCHED'),
    ("再確認の一致が、失敗・価格の変化・遮断より先になる", EG, '    if source_blocked or meta.get("source_blocked"):\n        return SOURCE_BLOCKED', '    if meta.get("recheck_matched"):\n        return RECHECK_MATCHED\n    if source_blocked or meta.get("source_blocked"):\n        return SOURCE_BLOCKED'),
    ("再確認の一致に旗を立てない", EG, '               "unchanged": "recheck_matched"}.get(st)', '               }.get(st)'),
    ("登録簿の確認済み URL を使わない", EG, '        if isinstance(pid, str) and _https_url_ok(u):\n            out.setdefault(pid, {}).setdefault("gap_url", u)', '        if False:\n            pass'),
    ("登録簿の URL が再確認の記録の URL を上書きする", EG, '            out.setdefault(pid, {}).setdefault("gap_url", u)', '            out.setdefault(pid, {})["gap_url"] = u'),
    ("旗の許可リストを外す（買い側の経路を決めるキーも書く）", EG, '            if k in SIGNAL_KEYS:', '            if True:'),
    ("results が壊れていると登録簿の旗まで失う", EG, '    for r in (results if isinstance(results, (list, tuple)) else []):', '    for r in results:'),
    ("商品 ID が文字列でない記録を使う", EG, '        pid = r.get("product_id") if isinstance(r.get("product_id"), str) else None', '        pid = r.get("product_id")'),
    ("末尾のドットを複数許す", EG, 'host = host[:-1] if host.endswith(".") and not host.endswith("..") else host', 'host = host.rstrip(".")'),
    ("生成側が登録簿の URL を渡さない", "src/content/daily_lp_generator.py", ', verified_urls=_reg.VERIFIED_URLS))', '))'),
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
