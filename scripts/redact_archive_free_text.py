#!/usr/bin/env python3
"""過去の LP（docs/archive/*.html）から、応募条件・支払い方法・発送時期の原文の欄だけを外す（部分修正の案）。

既定は確認だけ（何も書かない）。--apply を付けたときだけ書き換える。**実行は人の承認の後**（過去の公開ファイルの書き換え）。
- ファイル名（公開 URL）は変えない・ファイルを消さない。git の履歴は残る（書き換えは 1 つのコミットにまとめる想定）
- 外す: <dt>条件の詳細（公式の告知より）</dt><dd>…</dd> の組／「応募条件」の欄の中の「支払い: …」から欄の末尾まで（欄が空になれば組ごと。
  後ろに別の条件があれば一緒に消える＝外しすぎる側）／旧デザインの <details class="tcg-elig">（応募条件の原文）と
  <div class="tcg-row"><span>お届け</span><b>…</b></div> の行・<div class="tcg-verify">支払方法: …</div> の行
- 書き換えた後に原文の目印（RESIDUAL_MARKERS）が残れば、終了コード 1（不完全）を返す
- 残す: 構造化した要約（「会員登録が必要・本人確認あり」等）・日程・リンク・ページのほかの部分

  python scripts/redact_archive_free_text.py            # 確認だけ（ファイルごとの件数）
  python scripts/redact_archive_free_text.py --apply    # 書き換える（承認後）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs" / "archive"

_DETAIL = re.compile(r"<dt>条件の詳細（公式の告知より）</dt><dd>.*?</dd>", re.S)
_PAY_IN_REQ = re.compile(r"(<dt>応募条件</dt><dd>)(.*?)(</dd>)", re.S)
_PAY_PART = re.compile(r"(?:^|\s*[・/]\s*)支払い[:：].*$", re.S)
_DELIVERY_ROW = re.compile(r'<div class="tcg-row"><span>お届け</span><b>.*?</b></div>', re.S)
_OLD_PAY = re.compile(r'<div class="tcg-verify">支払方法[:：].*?</div>', re.S)                             # 旧デザインの支払方法の行
_OLD_ELIG = re.compile(r'<details class="tcg-elig"><summary>応募条件の原文</summary>.*?</details>', re.S)   # 旧デザインの原文の欄
# 書き換えた後に残ってはいけない目印（残っていれば --apply の結果は不完全として失敗にする）
RESIDUAL_MARKERS = ("条件の詳細（公式の告知より）", "応募条件の原文", "支払い:", "支払い：", "支払方法:", "支払方法：", "発送予定",
                    "本人認証済み枠")


def redact(html: str) -> tuple[str, dict]:
    counts = {"condition_detail": 0, "payment": 0, "delivery": 0, "old_eligibility": 0}
    html, counts["condition_detail"] = _DETAIL.subn("", html)
    html, counts["old_eligibility"] = _OLD_ELIG.subn("", html)
    html, n_old_pay = _OLD_PAY.subn("", html)
    counts["payment"] += n_old_pay

    def pay(m):
        body = m.group(2)
        new = _PAY_PART.sub("", body).strip()
        if new == body.strip():
            return m.group(0)
        counts["payment"] += 1
        return "" if not new else m.group(1) + new + m.group(3)
    html = _PAY_IN_REQ.sub(pay, html)
    html, counts["delivery"] = _DELIVERY_ROW.subn("", html)
    return html, counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="書き換える（人の承認の後だけ）")
    ap.add_argument("--dir", type=Path, default=ARCHIVE, help="対象のフォルダ（既定 docs/archive。コピーで試すときに指定）")
    a = ap.parse_args()
    target = Path(a.dir).resolve()
    # 書き込みは docs/archive か、名前に archive_copy を含むコピー（試し用）だけ。ほかのフォルダの HTML は書き換えない
    if a.apply and not (target == ARCHIVE.resolve() or "archive_copy" in target.name):
        print(f"--apply は docs/archive か、名前に archive_copy を含むコピーだけ: {target}")
        return 2
    total, changed = {"condition_detail": 0, "payment": 0, "delivery": 0, "old_eligibility": 0}, 0
    residual: dict = {}
    planned: list = []
    for f in sorted(Path(a.dir).glob("*.html")):
        src = f.read_text(encoding="utf-8")
        new, c = redact(src)
        if new == src:
            continue
        changed += 1
        for k in total:
            total[k] += c[k]
        print(f"{f.name}: {c}")
        for mk in RESIDUAL_MARKERS:
            if mk in new:
                residual[mk] = residual.get(mk, 0) + new.count(mk)
        planned.append((f, new))
    print(f"書き換えた後に残る目印: {residual or 'なし'}")
    if residual:
        print("目印が残るので書き換えない（規則を直してからやり直す）")
        return 1
    if a.apply:                                        # 全ファイルで目印が残らないことを確かめてから書く
        for f, new in planned:
            f.write_text(new, encoding="utf-8")
    print(f"対象 {changed} ファイル・合計 {total}" + ("（書き換えた）" if a.apply else "（確認だけ。書き換えていない）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
