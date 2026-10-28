#!/usr/bin/env python3
"""Coverage Wave 3 の変異テスト: 安全の規則を1つずつ壊して、テストが検知することを確かめる（リポジトリのルートで実行: python3 scripts/mutation_wave3.py）。

各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストの穴。
"""
# ruff: noqa
import subprocess, sys
C="src/research/candidates.py"; R="src/research/retail_lookup.py"; E="src/tcg/event_quality.py"; K="src/collectors/tcg/lottery/kidsrepublic.py"; F="src/collectors/tcg/lottery/fukufuku.py"; CL="src/collectors/tcg/lottery/clabo.py"
TESTS="tests/test_coverage_wave3.py tests/test_coverage_wave2.py tests/test_more_tcg_sources.py tests/test_clabo_lottery.py tests/test_hbst_lottery.py tests/test_market_research.py".split()
M=[
("ポイントを現金から引く",R,'basis, eff = BASIS_UNCONDITIONAL, (listed - imm if listed else None)','basis, eff = BASIS_UNCONDITIONAL, (listed - imm - (_int(e.get("points")) or 0) if listed else None)'),
("キャッシュバックを現金から引く",R,'basis, eff = BASIS_UNCONDITIONAL, (listed - imm if listed else None)','basis, eff = BASIS_UNCONDITIONAL, (listed - imm - (_int(e.get("cashback")) or 0) if listed else None)'),
("クーポン値引きを仕入れ値に使う",R,'    elif regular:\n        basis, eff = BASIS_REGULAR, regular','    elif False:\n        basis, eff = BASIS_REGULAR, regular'),
("キャンペーン価格を通常価格として扱う",R,'    if not conds:\n        basis, eff = BASIS_UNCONDITIONAL','    if True:\n        basis, eff = BASIS_UNCONDITIONAL'),
("条件つきを高優先にする",C,'or r.get("retail_caveat") or conditional or not buy_fresh','or r.get("retail_caveat") or not buy_fresh'),
("ポイントを参考の差にせず差に足す",C,'        spread = sell - retail\n','        spread = sell - retail + int(r.get("retail_points") or 0)\n'),
("古い照会を新しい扱い（結果の取得時刻）",C,'            if at is not None and timedelta(hours=-1) <= now - at <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS):','            if True:'),
("調査候補を確定にする",C,'r.update({"status": RESEARCH_CANDIDATE, "missing_requirements": list(dict.fromkeys(req)),','r.update({"status": VERIFIED, "missing_requirements": list(dict.fromkeys(req)),'),
("別の型番の小売を一致にする（Canon の表を使わない・コードの前方一致）",R,'        row = self.table().get(str(identity.get("value") or ""))','        row = next((r for j, r in self.table().items() if j[:9] == str(identity.get("value") or "")[:9]), None)'),
("Canon: JAN 以外でも引く",R,'        if identity.get("basis") != "JAN":\n            return ""\n        row = self.table()','        row = self.table()'),
("Apple: 部品番号の前方一致",R,'            return [e for e in entries if _norm_code(e.get("model")) == part], "part_exact"','            return [e for e in entries if _norm_code(e.get("model"))[:4] == part[:4]], "part_exact"'),
("複数の取得元から高い価格を選ぶ",R,'_basis.get(r.get("price_basis"), 3), r["price"] if r["price"] is not None else 10**12))','_basis.get(r.get("price_basis"), 3), -(r["price"] if r["price"] is not None else 10**12)))'),
("条件つきの安い価格を条件なしより優先する",R,'_basis.get(r.get("price_basis"), 3), r["price"]','0, r["price"]'),
("部品番号だけの引き当てを部分的な識別にしない",C,'or (r.get("retail_identity_evidence") or {}).get("method") == "part_exact"','or False'),
("福福: 公開日に応募締切を入れる",F,'published_at=None,','published_at=_date(*c["end_ymd"]).isoformat(),'),
("福福: 応募期間の欄から離れた購入期限も拾う",F,'    detail_text = full[i:i + 250] if i >= 0 else ""','    detail_text = full'),
("Canon: 販売終了のページの価格を使う",R,'            return []                                   # 販売終了のページの価格は、仕入れ値にしない','            pass'),
("TCG 質: 当選発表の有無を数えない",E,'                 "with_winner_announcement": bool(win),','                 "with_winner_announcement": True,'),
("TCG: 年またぎ以外の優先順位（期限間近を先にしない）",E,'    if status == "ENDING_SOON" or (end is not None','    if False or (end is not None'),
("TCG: 初めて見た時刻を測れると言う",E,'    return {"first_seen_available": False,','    return {"first_seen_available": True,'),
("キッズリパブリック: 遮断後も取得を続ける",K,'        if self.health.get("blocked"):\n            self.funnel.notes.append','        if False:\n            self.funnel.notes.append'),
("キッズリパブリック: main が無いページ全体を読む",K,'    return {"body": _text(m.group(0)) if m else ""}','    return {"body": _text(m.group(0) if m else html)}'),
("キッズリパブリック: 遊戯王も候補にする",K,'                if not _tcg_of(c["title"]):','                if False:'),
("福福: 遮断後も取得を続ける",F,'        if self.health.get("blocked"):\n            self.funnel.notes.append','        if False:\n            self.funnel.notes.append'),
("福福: 終了日が違う応募期間も使う",F,'and (em, ed) == card["end_ymd"][1:]:','and True:'),
("福福: 構造変化を数えない",F,'                self.funnel.structure_changed_pages += 1\n                self.health["error_messages"].append("一覧は取得できたがカードを読めなかった','                self.health["error_messages"].append("一覧は取得できたがカードを読めなかった'),
("取りこぼしを数えない（カードラボ）",CL,'        skipped_open = max(0, n_open - self.max_detail_fetch)','        skipped_open = 0'),
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
