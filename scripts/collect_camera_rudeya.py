# -*- coding: utf-8 -*-
"""カメラの買取ルデヤの価格を取得して、camera_refresh の入力（research_camera_<ブランド>_rudeya.json）を作る。

    python scripts/collect_camera_rudeya.py --dir .private/research/weekly/<YYYY-MM-DD>          # 書き込む（調査フォルダへ）
    python scripts/collect_camera_rudeya.py --dir <フォルダ> --dry-run                           # 書かない（結果の表示だけ）

- 取得は src/collectors/polite.py を通す（robots.txt・同じドメインの間隔・正直な User-Agent・打ち切り）。ブロックされたら別の手段で取り直さない。
- 対象は config/camera_rudeya.yaml（一覧 2 ページ + 商品ページ）。一覧と商品ページで価格・JAN・名前・受付中が一致した機種だけ行にする。
- 取れなかった・確認できなかった機種は行を作らない（取得元の結果に理由を残す）。古い価格を今日の確認にしない。
- 終了コード: 0＝設定の全機種を採用／2＝一部が不採用（理由を表示）／1＝採用できた機種が 0 件（取得できなかった場合と、全機種を意図して不採用にした場合の両方。理由を表示し、取得元の結果は出力ファイルに書く）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import yaml  # noqa: E402

from src.collectors import camera_rudeya as cru  # noqa: E402
from src.collectors import polite  # noqa: E402
from src.tcg import buyback as bb  # noqa: E402

CONFIG = PROJECT_ROOT / "config" / "camera_rudeya.yaml"
_LAST = {"reason": ""}


def fetch(url: str, timeout: int = 20):
    """HTML を取得する。失敗したら None（理由は _LAST["reason"]）。ブロックされたら別の手段で取り直さない。"""
    _LAST["reason"] = ""
    if not polite.robots_allowed(url):
        _LAST["reason"] = polite.robots_block_reason(url)
        return None
    polite.polite_wait(url)
    try:
        import requests
        resp = requests.get(url, headers={"User-Agent": polite.HONEST_UA, "Accept-Language": "ja,en;q=0.9"}, timeout=timeout, allow_redirects=False)
    except Exception as e:  # noqa: BLE001
        _LAST["reason"] = "timeout" if "timeout" in type(e).__name__.lower() else "connection_error"
        return None
    if resp.status_code != 200:
        _LAST["reason"] = polite.status_reason(resp.status_code)
        return None
    if len(resp.text) < 500:
        _LAST["reason"] = "empty_html"
        return None
    return resp.text


def collect(cfg: dict, now: datetime, fetcher=fetch) -> tuple[dict, list]:
    """(書き込む内容 {ファイル名: 内容}, 機種ごとの結果)。"""
    cutoff = polite.ShopCutoff()
    key = "kaitori-rudeya"
    list_rows: list = []
    pages_ok = 0
    for url in cfg.get("categories") or []:
        if cutoff.is_cut(key):
            break
        html = fetcher(url)
        if html is None:
            cutoff.record(key, False, _LAST["reason"] or "fetch_failed")
            continue
        got = cru.parse_list(html, url, now)
        if not got:
            cutoff.record(key, False, "no_rows")              # 200 で返ったが商品カードを 1 件も解析できない（構造の変更・メンテナンス）。取得できたことにしない
            continue
        cutoff.record(key, True)
        pages_ok += 1
        list_rows += got

    def fetch_item(url: str):
        if cutoff.is_cut(key):
            return None
        h = fetcher(url)
        cutoff.record(key, h is not None, None if h is not None else (_LAST["reason"] or "fetch_failed"))
        return h

    products, notes = cru.build_rows(cfg, list_rows, fetch_item, now.strftime("%Y-%m-%d"), lists_complete=(pages_ok == len(cfg.get("categories") or []))) if pages_ok else ([], [
        {"product": i["product"], "jan": str(i["jan"]), "ok": False, "withdraw": False, "reason": "一覧ページを取得できなかった"} for i in cfg.get("items") or []])
    docs = cru.build_docs(products, notes, now.strftime("%Y-%m-%d"), now, len(cfg.get("items") or []))
    return docs, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="買取ルデヤ（カメラ）の価格を取得して camera_refresh の入力を作る")
    ap.add_argument("--dir", required=True, help="調査フォルダ（.private/research/weekly/<YYYY-MM-DD>）")
    ap.add_argument("--dry-run", action="store_true", help="書かない")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    now = datetime.now(bb.JST)
    docs, notes = collect(cfg, now)
    for n in notes:
        print(("OK  " if n["ok"] else "NG  ") + f"{n['product']} {n['jan']} " + (f"{n['price']}円 {n['url']}" if n["ok"] else n["reason"]))
    ok = sum(1 for n in notes if n["ok"])
    if not a.dry_run:
        d = Path(a.dir)
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("research_camera_*_rudeya.json"):
            old.unlink()                             # 前回の出力を先に消す（今回採用しなかった機種の行・不採用の記録が前回の分で残らないように）
        for name, doc in docs.items():
            (d / name).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"書き込み: {', '.join(docs)}")
    if ok == 0:
        print("採用できた機種が 0 件")
        return 1
    return 0 if ok == len(notes) else 2


if __name__ == "__main__":
    raise SystemExit(main())
