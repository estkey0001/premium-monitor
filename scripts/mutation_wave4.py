#!/usr/bin/env python3
"""Coverage Wave 4 の変異テスト: 安全の規則を1つずつ壊して、テストが検知することを確かめる（リポジトリのルートで実行: python3 scripts/mutation_wave4.py）。

各変異は元のファイルを書き換えてテストを走らせ、必ず元に戻す（途中で止めたときは git diff を確認する）。「★見逃し」が 1 件でもあればテストの穴。
"""
# ruff: noqa
import subprocess, sys
R="src/research/retail_lookup.py"; C="src/research/candidates.py"; B="src/tcg/lottery/budget.py"; P="src/tcg/lottery/pipeline.py"; G="src/tcg/lottery/registry.py"; MG="src/collectors/tcg/lottery/mugiwara.py"; CL="src/collectors/tcg/lottery/clabo.py"
TESTS="tests/test_coverage_wave4.py tests/test_coverage_wave3.py tests/test_coverage_wave2.py tests/test_more_tcg_sources.py tests/test_clabo_lottery.py tests/test_market_research.py".split()
M=[
("Apple が全ての枠を取る（最低枠を渡さない）",R,'    for step in (1, None):','    for step in ():'),
("最低枠が 1 件も保証されない",R,'            if n > 0 and (step is None or have == 0):','            if False:'),
("総数の上限を無視する（余りを無制限に配る）",R,'        if left <= 0:\n            break\n        out[aid]["keys"].append(k)','        out[aid]["keys"].append(k)'),
("取得器ごとの上限（cap）を無視する",R,'for k, sc in p["keys"][len(out[p["adapter_id"]]["keys"]):int(p.get("cap") or 0)]','for k, sc in p["keys"][len(out[p["adapter_id"]]["keys"]):]'),
("一覧を全ページ取れなくても部分的に取る",R,'            if p["cost"] <= left:','            if True:'),
("待ち行列の上位だけから選ぶ（全候補から選ばない）",R,'    for r in sorted((x for x in tri["rows"] if x["triage"]["tier"] != tr.REJECTED),','    for r in sorted((x for x in tri["queue"] if x["triage"]["tier"] != tr.REJECTED),'),
("Apple: 容量違いを一致にする",R,'    same = a["line_key"] == b["line_key"] and a["capacity"] == b["capacity"]','    same = True'),
("Apple: 世代違いを一致にする",R,'    same = a["line_key"] == b["line_key"] and a["capacity"] == b["capacity"]','    same = a["capacity"] == b["capacity"]'),
("Apple: 属性を確かめずに確認済みにする",R,'        ev["attributes_verified"] = attrs["status"] == "MATCH"','        ev["attributes_verified"] = True'),
("Apple: 確認済みでも部分的な識別にする",C,'            ev.get("method") == "part_exact" and not ev.get("attributes_verified"))) else "IDENTITY_CONFIRMED"','            ev.get("method") == "part_exact")) else "IDENTITY_CONFIRMED"'),
("Sony: 色違いの JAN を同じ商品にする",R,'        hits = [e for e in entries if e.get("jan") == v]','        hits = [e for e in entries if e.get("jan", "")[:9] == v[:9]]'),
("Sony: 未知の在庫語を在庫ありと推測する",R,'        words = "|".join(self._STOCK_IN + self._STOCK_OUT)','        words = "|".join(self._STOCK_IN + self._STOCK_OUT + ("予約受付中",))'),
("ソフマップ: ページの JAN が違っても読む",R,'        if jans != {str(row["jan"])}:','        if False:'),
("ソフマップ: 中古を読む",R,'        if not offer or "中古" in name:','        if not offer:'),
("ソフマップ: 登録に無い JAN も引く",R,'        row = self.table().get(str(identity.get("value") or ""))\n        return str(row["sku"]) if row else ""','        return "18246893"'),
("API: 鍵が無くても READY にする",R,'"status": API_PENDING if not has_keys else','"status": API_READY if not has_keys else'),
("キャンペーン価格を確定の仕入れ値にする",R,'    if not conds:\n        basis, eff = BASIS_UNCONDITIONAL','    if True:\n        basis, eff = BASIS_UNCONDITIONAL'),
("TCG: 取得枠を使い切って後ろの取得元の最低枠を残さない",B,'    reserved = sum(min(min_quota, int(c)) for c in remaining_caps)','    reserved = 0'),
("TCG: 大きい取得元を先に動かす",B,'    return sorted(items, key=lambda x: (int(x[1]), x[0]))','    return sorted(items, key=lambda x: (-int(x[1]), x[0]))'),
("TCG: 遮断された取得元を LIST_OK のまま WORKING 扱いにする（遮断の印を落とす）",G,'    if row.get("blocked"):\n        flags.append(BLOCKED_FLAG)','    if False:\n        flags.append(BLOCKED_FLAG)'),
("TCG: 構造変化の印を落とす",G,'    if int(row.get("structure_changed_pages") or 0) > 0:','    if False:'),
("TCG: 期限が近い告知を優先しない（カードラボ）",CL,'_title_deadline_soon(card["title"], today),\n','False,\n'),
("麦わらストア: 遮断後も取得を続ける",MG,'        if self.health.get("blocked"):\n            self.funnel.notes.append','        if False:\n            self.funnel.notes.append'),
("麦わらストア: article が無いページ全体を読む",MG,'    m = _ARTICLE.search(html or "") or _MAIN.search(html or "")\n    body = _text(m.group(0)) if m else ""','    m = _ARTICLE.search(html or "") or _MAIN.search(html or "")\n    body = _text(m.group(0) if m else html)'),
("麦わらストア: カテゴリを件名にする",MG,'        title = max((t for a, t in ps if "date" not in a and "cat" not in a and t), key=len, default="")','        title = next((t for a, t in ps if t), "")'),
("公開: 取得器の件数に許可外の ID を通す",C,'if aid in ALLOWED_RETAIL_ADAPTERS and isinstance(v, dict)}','if isinstance(v, dict)}'),
("公開: 古い記録の取得器の件数を今日のものにする",C,'and timedelta(hours=-1) <= now - gen_ok <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS) else {})','and True else {})'),
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
