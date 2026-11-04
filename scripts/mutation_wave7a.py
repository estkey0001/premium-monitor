#!/usr/bin/env python3
"""Coverage Wave 7a の変異テスト: 応募先・経路・要件・完成度・定価との結び付きの規則を1つずつ壊して、テストが検知することを確かめる。

リポジトリのルートで実行: python3 scripts/mutation_wave7a.py
各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストを足す。
注意: 追跡対象のソースをその場で書き換える。他のセッションが同じファイルを編集していないときに実行する（強制終了すると変異が残る）。
"""
# ruff: noqa
import subprocess, sys
AU = "src/tcg/action_url.py"; PD = "src/tcg/profit_dense.py"
TESTS = "tests/test_coverage_wave7a.py tests/test_coverage_wave6.py".split()
M = [
    ("公式ドメインでなくても応募の URL にする（外部フォーム・他社ドメイン）", AU,
     'official_source and _is_official(entry, retailer)', 'official_source'),
    ("http の応募ページも認める（https に書き換えて通す）", AU, 'or not raw.startswith("https://"):', 'or not raw.startswith("http"):'),
    ("認証情報つきの URL を認める", AU, 'if "@" in netloc or ":" in netloc or not _AUTHORITY.match(netloc):', 'if ":" in netloc or not _AUTHORITY.match(netloc.split("@")[-1]):'),
    ("末尾が似ているだけのドメインを公式とみなす", AU, 'host == h or host.endswith("." + h)', 'host == h or host.endswith(h)'),
    ("公式ドメインを前に置いた別ドメインを公式とみなす", AU, 'host == h or host.endswith("." + h)', 'h in host'),
    ("登録簿に無い取得元の応募の URL を認める", AU, '    if not src:\n        return frozenset()', '    if not src:\n        return frozenset({"unknown.example"})'),
    ("外部フォームを公式の応募ページの経路にする", AU, '    elif external:\n        channel = CH_EXTERNAL_FORM', '    elif external:\n        channel = CH_WEB_OFFICIAL'),
    ("告知の URL だけで応募の URL が確認できたことにする", PD,
     '"application_url_confirmed": c["application_url"] is not None,', '"application_url_confirmed": c["application_url"] is not None or c["announcement_url"] is not None,'),
    ("調査していない取得元の経路を推測で SNS にする", AU, 'SOURCE_CHANNEL.get(retailer, CH_UNKNOWN)', 'SOURCE_CHANNEL.get(retailer, CH_SNS)'),
    ("False・不明の要件も要件として並べる", AU, 'if i.get(key) is True]', 'if i.get(key) is not None]'),
    ("SNS の要件を落とす", AU, '    if channel == CH_SNS:\n        reqs.append(R_SNS)', '    if False:\n        reqs.append(R_SNS)'),
    ("経路が分かっている取得元を店頭で上書きする", AU, 'if channel == CH_UNKNOWN and official_source and i.get("store_pickup_required") is True:', 'if official_source and i.get("store_pickup_required") is True:'),
    ("日程の矛盾を review_required にしない", AU, 'quality = Q_REVIEW if review else (Q_COMPLETE if not missing else Q_PARTIAL)',
     'quality = (Q_COMPLETE if not missing else Q_PARTIAL)'),
    ("同じ日の当選発表を矛盾にする（補った時刻で比べる）", AU, 'b.date() < a.date()', 'b < a'),
    ("商品の同一性が曖昧でも確認済みにする", AU, '(bool(i.get("product_id")) and str(i.get("product_match") or "") == "ambiguous")', 'False'),
    ("1 項目欠けても complete にする", AU, 'Q_COMPLETE if not missing else Q_PARTIAL', 'Q_COMPLETE if len(missing) <= 1 else Q_PARTIAL'),
    ("商品の一致が exact でなくても商品を確認済みにする", AU, '== "exact" and not i.get("provisional_product"),', '!= "none" and not i.get("provisional_product"),'),
    ("complete 以外を actionable にする", AU, '"actionable_event": quality == Q_COMPLETE', '"actionable_event": quality != Q_REVIEW'),
    ("完成度の件数を partial に寄せる", PD, 'counts["tcg_quality_" + c["quality"]] += 1', 'counts["tcg_quality_partial"] += 1'),
    ("actionable の件数を完成度 6/7 で数える", PD, 'counts["tcg_actionable_events"] += int(c["actionable_event"])', 'counts["tcg_actionable_events"] += int(c["completeness"] >= 6)'),
    ("定価との結び付きで TCG の種類の一致を見ない", PD, 'and str(m.get("tcg")) != str(i.get("tcg")):', 'and False:'),
    ("仮の商品（登録簿に無い）を定価に結ぶ", PD, '== "exact" and not i.get("provisional_product") else None', '== "exact" else None'),
    ("商品の一致が exact でなくても定価に結ぶ（名前の近さ）", PD, 'm = idx.get(pid) if pid and str(i.get("product_match") or "") == "exact"', 'm = idx.get(pid) if pid'),
    ("バックスラッシュ・空白などの制御文字を拒否しない", AU, 'or _BAD_CHARS.search(raw) or', 'or'),
    ("ホストの許可リスト（ASCII のラベルだけ）を外す", AU, 'if "@" in netloc or ":" in netloc or not _AUTHORITY.match(netloc):', 'if False:'),
    ("443 以外のポートを認める", AU, '    if "@" in netloc or ":" in netloc or not _AUTHORITY.match(netloc):\n        return None', '    if "@" in netloc or not _AUTHORITY.match(netloc.split(":")[0]):\n        return None'),
    ("空の認証情報（@）を認める", AU, '    if "@" in netloc or ":" in netloc or not _AUTHORITY.match(netloc):', '    if ":" in netloc or not _AUTHORITY.match(netloc.lstrip("@")):'),
    ("スキームの大文字を認める", AU, 'or not raw.startswith("https://"):', 'or not raw.lower().startswith("https://"):'),
    ("返す URL を正規化しない（元の文字列を返す）", AU, '_no_query(safe[1]) if (safe and official_source and _is_official', 'entry if (safe and official_source and _is_official'),
    ("告知の URL と同じ（query・大文字小文字・index.html を足した）URL を応募の URL にする", AU, 'and (not is_ann or self_ok)', 'and True'),
    ("告知の比較で query を区別する（query を足すだけで別の URL になる）", AU, 'return _base(sp.netloc) + "/" + "/".join(segs)', 'return _base(sp.netloc) + "/" + "/".join(segs) + sp.query'),
    ("告知の比較でパスの大文字小文字を区別する", AU, 'segs = [x.lower() for x in sp.path.split("/") if x]\n    if segs and segs[-1] in _INDEX_FILES:', 'segs = [x for x in sp.path.split("/") if x]\n    if segs and segs[-1] in _INDEX_FILES:'),
    ("告知の比較で index.html を区別する", AU, '    if segs and segs[-1] in _INDEX_FILES:\n        segs.pop()', '    if False:\n        segs.pop()'),
    ("dot segment（.）を解決しない", AU, '        if seg in ("", "."):\n            continue', '        if seg == "":\n            continue'),
    ("ルートより上へ出る .. を通す", AU, '            if not out:\n                return None\n            out.pop()', '            if not out:\n                continue\n            out.pop()'),
    ("返す URL の末尾のスラッシュを落とす", AU, '("/" if out and path.endswith("/") else "")', '""'),
    ("符号化されたドット・スラッシュ・制御文字を通す", AU, '    if _BAD_ENCODED.search(p.path) or _BAD_ENCODED.search(p.query) or _BAD_ENCODED.search(p.netloc):', '    if False:'),
    ("ホストの形式（IP リテラル・punycode・不正なラベル）を検査しない", AU, '    if not _host_ok(host):\n        return None', '    if False:\n        return None'),
    ("IP リテラル（最後のラベルが数字）を認める", AU, 'return not labels[-1].isdigit() and any(c.isalpha() for c in labels[-1])', 'return any(c.isalpha() for c in host)'),
    ("punycode のホストを認める", AU, 'or lb.lower().startswith("xn--"):', ':'),
    ("出来事固有でない URL（入口・一覧）を応募の URL にする", AU, 'and _is_official(entry, retailer) and specific and', 'and _is_official(entry, retailer) and'),
    ("お知らせ・キャンペーンなどのパスを応募の URL にする", AU, '    return not (segs & _NEWS_SEGMENTS)\n\n\ndef _event_specific'[:0] + '    segs = {x.lower() for x in urlsplit(r[1]).path.split("/") if x}\n    return not (segs & _NEWS_SEGMENTS)', '    return True'),
    ("外部フォームを許可ホストでなくても認める（一般のフォーム）", AU, 'return any(r[0] == h and pat.fullmatch(path) for h, pat in rules)', 'return any(pat.fullmatch(path) for h, pat in rules)'),
    ("外部フォームを別の取得元の許可ホストでも認める（横流用）", AU, 'EXTERNAL_FORM_RULES.get(retailer, ())', 'tuple(x for v in EXTERNAL_FORM_RULES.values() for x in v)'),
    ("公式でない情報元の外部フォームを認める", AU, 'application is None and official_source and not is_ann and not source_unreadable', 'application is None and not is_ann and not source_unreadable'),
    ("外部フォーム・応募のパスの形を見ない（/login・主催者ページ・入口）", AU, 'return any(r[0] == h and pat.fullmatch(path) for h, pat in rules)', 'return any(r[0] == h for h, pat in rules)'),
    ("告知と同じ URL を、確認していない取得元でも応募の URL にする", AU, 'self_ok = is_ann and retailer in SELF_APPLICATION_SOURCES and', 'self_ok = is_ann and'),
    ("情報元が公式でなくても応募の URL にする", AU, 'official_source = str(i.get("source_type") or "") in OFFICIAL_LOTTERY_SOURCES', 'official_source = True'),
    ("告知の一覧のホストを公式の応募先に含める", AU, 'for k in ("official_url", "lottery_url")}', 'for k in ("official_url", "lottery_url", "news_url")}'),
    ("読めない当選発表（TBD）を「ある」にする", AU, '"winner_announcement": wa is not None,', '"winner_announcement": bool(i.get("winner_announcement_at") or i.get("winner_announcement_date")),'),
    ("読めない購入期間を「ある」にする", AU, '"purchase_window": ps is not None and pe is not None,', '"purchase_window": bool((i.get("purchase_start") or i.get("purchase_start_date")) and (i.get("purchase_end") or i.get("purchase_end_date"))),'),
    ("経路が不明でも channel_ready にする", AU, 'and channel in CHANNEL_READY', ''),
    ("review_required でも channel_ready にする", AU, 'channel_ready = (quality != Q_REVIEW and', 'channel_ready = (True and'),
    ("channel_ready を actionable にする", AU, '"actionable_event": quality == Q_COMPLETE, "channel_ready"', '"actionable_event": quality == Q_COMPLETE or channel_ready, "channel_ready"'),
    ("応募の許可パス表を見ない（公式ドメインの商品ページ・記事も応募にする）", AU, 'and specific and allowed_path\n', 'and specific\n'),
    ("取得元の大文字小文字・空白を正規化しない", AU, 'retailer = str(i.get("retailer") or "").strip().upper()', 'retailer = str(i.get("retailer") or "")'),
    ("パスのパラメータ（;）を許す", AU, 'if ";" in p.path or "//" in p.path or "//" in p.query:', 'if "//" in p.path or "//" in p.query:'),
    ("query の埋め込み URL・リダイレクト（//）を許す", AU, 'if ";" in p.path or "//" in p.path or "//" in p.query:', 'if ";" in p.path or "//" in p.path:'),
    ("符号化の正規化をしない（%61 と a が別の URL になる）", AU, 'path = _resolve_path(_norm_pct(p.path))', 'path = _resolve_path(p.path)'),
    ("二重符号化（%25）を許す", AU, '%(?:2e|2f|5c|25|[01][0-9a-f]|7f)', '%(?:2e|2f|5c|[01][0-9a-f]|7f)'),
    ("告知の比較で www. の有無を区別する", AU, 'return _base(sp.netloc) + "/" + "/".join(segs)', 'return sp.netloc + "/" + "/".join(segs)'),
    ("行動の URL の件数に購入の URL・告知の URL を数える", "src/tcg/event_quality.py", 'url = _au.classify(i, now)["application_url"] is not None', 'url = bool(i.get("entry_url") or i.get("purchase_url"))'),
    ("告知の URL が読めなくても応募の URL を確定する", AU, 'and not source_unreadable and (not is_ann or self_ok)', 'and (not is_ann or self_ok)'),
    ("外部フォームは告知が読めなくても確定する", AU, 'and not is_ann and not source_unreadable\n', 'and not is_ann\n'),
    ("応募の URL に query を残す", AU, 'application = (_no_query(safe[1]) if', 'application = (safe[1] if'),
    ("外部フォームの URL に query を残す", AU, 'external = (_no_query(safe[1]) if', 'external = (safe[1] if'),
    ("非 ASCII（全角・結合文字・不可視文字）を拒否しない", AU, 'if not raw.isascii():\n        return None', 'if False:\n        return None'),
    ("許可パスの数字を Unicode にする（全角数字に一致）", AU, '"GEO": (("draw.geo-online.co.jp", re.compile(r"^/lottery/[0-9]+/?$", re.ASCII)),),', '"GEO": (("draw.geo-online.co.jp", re.compile(r"^/lottery/\\d+/?$")),),'),
    ("パスの連続スラッシュを許す", AU, 'if ";" in p.path or "//" in p.path or "//" in p.query:', 'if ";" in p.path or "//" in p.query:'),
    ("許可表のホストをサブドメインまで許す", AU, 'return any(r[0] == h and pat.fullmatch(path) for h, pat in rules)', 'return any((r[0] == h or r[0].endswith("." + h)) and pat.fullmatch(path) for h, pat in rules)'),
    ("会員ログインの取得元（福福トレカ）を応募の許可表に入れる", AU, '    "GEO": (("draw.geo-online.co.jp"', '    "FUKUFUKU_TOREKA": (("pokemon.fukufukutoreka.com", re.compile(r"^/lottery/[0-9]+/?$", re.ASCII)),),\n    "GEO": (("draw.geo-online.co.jp"'),
    ("旧通知経路が未検証の応募フォーム URL をそのまま使う", "scripts/update_alerts.py", 'return _safe_link(ev.get("entry_form_url"))', 'return str(ev.get("entry_form_url") or "")'),
    ("告知の URL が無くても応募の URL を確定する", AU, 'source_unreadable = (ann is None or not _source_host_ok(ann[0], retailer) or any(', 'source_unreadable = (ann is not None and not _source_host_ok(ann[0], retailer) or any('),
    ("文字列でない source_urls の要素を無視する", AU, 'any(not isinstance(u, str) or (u.strip() and safe_https(u) is None) for u in extra))', 'any(isinstance(u, str) and (u.strip() and safe_https(u) is None) for u in extra))'),
    ("不正な符号化（孤立した %）を許す", AU, '    if re.search(r"%(?![0-9A-Fa-f]{2})", p.path + "?" + p.query):\n        return None', '    if False:\n        return None'),
    ("LivePocket の予約語（login など）を許す", AU, '(?!(?i:login|logout|mypage|signup|register|search|help|terms|top)/?$)', ''),
    ("旧通知経路が応募フォームを「未照合」と明示せず断定する", "scripts/update_alerts.py", '"応募先の候補を確認（公式ドメイン未照合）"', '"抽選フォームを確認"'),
    ("旧通知経路が読めない URL を告知にも使う", "scripts/update_alerts.py", '    ann, form = _safe_link(ev.get("url")), _entry_form_url(ev)', '    ann, form = str(ev.get("url") or ""), _entry_form_url(ev)'),
    ("旧通知経路が商品を特定する query を捨てる", "scripts/update_alerts.py", '    return r[1] if r else ""', '    return r[1].split("?", 1)[0] if r else ""'),
    ("非公式の情報元でも登録簿の経路を使う", AU, 'if official_source else CH_UNKNOWN', ''),
    ("告知の取得元ドメインを見ない", AU, 'or not _source_host_ok(ann[0], retailer)', ''),
    ("HTML・引用符の文字を拒否しない", AU, '    if re.search(r"[<>\\"\'`|^{}]", raw):\n        return None', '    if False:\n        return None'),
    ("LivePocket の予約語の大文字小文字を区別する", AU, '(?!(?i:login', '(?!(?:login'),
    ("source_urls の文字列を 1 文字ずつ回す（告知との同一性の迂回）", AU, '| {_ident(u) for u in _extra_urls(i) if isinstance(u, str)}', '| {_ident(u) for u in list(i.get("source_urls") or []) if isinstance(u, str)}'),
    ("非公式の情報元でも app_required で APP 経路にする", AU, '    elif official_source and (i.get("app_required") is True', '    elif (i.get("app_required") is True'),
    ("非公式の情報元でも店頭の明記で経路にする", AU, 'if channel == CH_UNKNOWN and official_source and i.get("store_pickup_required") is True:', 'if channel == CH_UNKNOWN and i.get("store_pickup_required") is True:'),
    ("拒否された応募先が渡されたのに channel_ready を立てる", AU, 'and not source_unreadable and entry_ok)', 'and not source_unreadable)'),
    ("告知が読めないのに channel_ready を立てる", AU, 'and not source_unreadable and entry_ok)', 'and entry_ok)'),
    ("旧通知経路が末尾スラッシュだけの差を別のフォームにする", "scripts/update_alerts.py", '    if form and form.rstrip("/") != ann.rstrip("/"):', '    if form and form != ann:'),
    ("旧通知経路が告知と同じ URL を応募先の候補にする", "scripts/update_alerts.py", '    if form and form.rstrip("/") != ann.rstrip("/"):', '    if form:'),
]
bad = 0
for desc, f, old, new in M:
    s = open(f).read()
    if old not in s:
        print("無効（置換元なし）", desc); bad += 1; continue
    open(f, "w").write(s.replace(old, new, 1))
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS], capture_output=True, text=True, timeout=180)
        ok = r.returncode != 0
    except subprocess.TimeoutExpired:
        ok = True
    finally:
        open(f, "w").write(s)
    print("検出" if ok else "★見逃し", desc)
    bad += (not ok)
print("見逃し/無効:", bad, "/", len(M))
