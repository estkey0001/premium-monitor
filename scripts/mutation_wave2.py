#!/usr/bin/env python3
"""Coverage Wave 2 の変異テスト: 安全の規則を1つずつ壊して、テストが検知することを確かめる（リポジトリのルートで実行: python3 scripts/mutation_wave2.py）。

各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストの穴。
"""
# ruff: noqa
import subprocess, sys
C="src/research/candidates.py"; R="src/research/retail_lookup.py"; T="src/research/triage.py"; H="src/collectors/tcg/lottery/hbst.py"; F="src/tcg/funnel.py"
TESTS="tests/test_coverage_wave2.py tests/test_hbst_lottery.py tests/test_market_research.py tests/test_clabo_lottery.py".split()
M=[
("名前だけの行を選別で通す",T,'    if ident_basis not in IDENTITY_POINTS:\n','    if False:\n'),
("付属品を除外しない",T,'    if cat in (CAT_ACCESSORY, CAT_BUNDLE):\n','    if False:\n'),
("古い買取を新しい扱い（取得日の判定）",T,'    if age <= timedelta(days=3):\n        return 20, "fresh"','    if True:\n        return 20, "fresh"'),
("取得日が読めない行を通す",T,'    if cur in ("stale", "unknown", "future"):','    if False:'),
("照会の古い結果を使う（記録の鮮度を見ない）",C,'usable = bool(lookups) and gen is not None and timedelta(hours=-1) <= now - gen <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS)','usable = bool(lookups)'),
("照会結果の取得時刻を見ない",C,'            if at is not None and timedelta(hours=-1) <= now - at <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS):','            if True:'),
("調査候補を確定に昇格",C,'r.update({"status": RESEARCH_CANDIDATE, "missing_requirements": list(dict.fromkeys(req)),','r.update({"status": VERIFIED, "missing_requirements": list(dict.fromkeys(req)),'),
("価格差の無い候補も調査候補にする",C,'        if spread <= 0:\n            r.update({"status": REJECTED,','        if False:\n            r.update({"status": REJECTED,'),
("異常な価格差を高優先にする",C,'        anomaly = spread > retail * ANOMALY_RATIO','        anomaly = False'),
("別の商品を一致にする（JAN を前方一致）",R,'hits = [e for e in entries if e.get("jan") == v]','hits = [e for e in entries if str(e.get("jan") or "").startswith(v[:8])]'),
("名前の一致で一致にする",R,'    if basis == "JAN":\n        v = str(value or "").strip()','    if True:\n        return [e for e in entries if str(identity.get("name") or "")[:6] and str(identity.get("name"))[:6] in str(e.get("name"))], "name"\n    if basis == "JAN":\n        v = str(value or "").strip()'),
("価格の違う複数の一致から選ぶ",R,'    if len({(h.get("url"), h.get("price")) for h in hits}) != 1:','    if False:'),
("ブランド違いの一致を通す",R,'    if brand_of(h.get("name", "")) not in ("", *ad.brands):','    if False:'),
("販売終了の価格を仕入れ値にする",R,'if res["availability_state"] == AVAIL_OUT or not pe["effective_price"]:','if False or not pe["effective_price"]:'),
("取っていない型番を未取得にしない",R,'        if not key or key not in (idx.get("covered") or ()):','        if not key:'),
("遮断後も取得を続ける（商品ごと）",R,'            if err in _cutoff_reasons():\n                break','            if False:\n                break'),
("取得数の上限を外す",R,'[:getattr(ad, "MAX_ITEMS", 4)]','[:1000]'),
("途中の一覧が失敗しても引く",R,'            if not html:\n                ok = False\n                break','            if not html:\n                continue'),
("個別の小売価格を公開してよい項目にする",C,'"identity_value", "identity_basis", "retail_price", "retail_url",','"identity_value", "identity_basis", "retail_url",'),
("公開の集計に個別の候補を混ぜる",C,'        "retail_lookup_matched": int(m.get("retail_lookup_matched") or 0),','        "retail_lookup_matched": int(m.get("retail_lookup_matched") or 0),\n        "product_candidates": report.get("product_candidates"),'),
("ホビーステーション: 遮断後も詳細を取る",H,'        if self.health.get("blocked"):\n            self.funnel.notes.append','        if False:\n            self.funnel.notes.append'),
("ホビーステーション: 本文が無いページ全体の日程を読む",H,'    body = re.sub(r"\\s+", " ", re.sub(r"<[^>]+>", " ", unescape(a.group(0)))).strip() if a else ""','    body = re.sub(r"\\s+", " ", re.sub(r"<[^>]+>", " ", unescape(a.group(0) if a else (html or "")))).strip()'),
("ホビーステーション: 応募ページの URL を作る",H,'entry_url=None, result_url=None, tcg_hint=_tcg_of(title), targets=targets))','entry_url="https://livepocket.jp/e/x", result_url=None, tcg_hint=_tcg_of(title), targets=targets))'),
("ホビーステーション: 価格を定価にする",H,'[{"product_name": prod, "retail_price": None}]','[{"product_name": prod, "retail_price": 7200}]'),
("一覧の構造変化を劣化にしない",F,'        if self.structure_changed_pages > 0:\n            return HEALTH_DEGRADED','        if False:\n            return HEALTH_DEGRADED'),
("引ける見込みに一覧が無い取得器の商品ごとの取得を数える",R,'    return ad is not None and not getattr(ad, "per_item", False)','    return ad is not None'),
("価格差なしの行を待ち行列に入れる",T,'        if c.get("status") == "REJECTED":','        if False:'),
("買取側が古くても高優先にする",C,'or r.get("retail_caveat") or conditional or not buy_fresh','or r.get("retail_caveat") or conditional'),
("割引込みの価格を高優先にする",C,'or basis_note != "retail_lookup" or r.get("retail_caveat")','or basis_note != "retail_lookup"'),
("429 の後も取得を続ける",R,'    return CUTOFF_IMMEDIATE | {"blocked"}','    return frozenset({"blocked"})'),
("ホビーステーションの詳細の構造変化を数えない",H,'            if not d["body"]:','            if False:'),
("ニコンの一眼レフを引ける扱いにする",R,'and bool(self._MIRRORLESS.search(str(name)))','and True'),
("ソニーの型番なしを引ける扱いにする",R,'        return super().supports(identity) and bool(self.item_key(identity))','        return super().supports(identity)'),
("カードラボ: 終了した告知を先に取る",'src/collectors/tcg/lottery/clabo.py','cands.sort(key=lambda tc: (not _title_ended(','cands.sort(key=lambda tc: ((_title_ended('),
]
bad=0
for desc,f,old,new in M:
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
