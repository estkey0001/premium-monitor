#!/usr/bin/env python3
"""docs/ ディレクトリにLP公開用ファイルをビルドする。

exports/lp/daily/ → docs/ へコピーし、
exports/collector_report/latest.json → docs/collector_report.html を生成し、
sitemap.xml・robots.txt を生成する。
"""

import html as _html
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports" / "lp" / "daily"
PUBLIC_DIR = PROJECT_ROOT / "docs"
ARCHIVE_DIR = PUBLIC_DIR / "archive"


def _load_settings() -> dict:
    path = PROJECT_ROOT / "config" / "lp_settings.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build():
    """公開ファイルをビルドする。"""
    settings = _load_settings()
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    # index.html
    src_index = EXPORTS_DIR / "index.html"
    if not src_index.exists():
        print("ERROR: exports/lp/daily/index.html not found.")
        print("Run: python -m src.cli generate-daily-lp")
        sys.exit(1)

    dst_index = PUBLIC_DIR / "index.html"
    shutil.copy2(src_index, dst_index)
    print(f"  ✅ {dst_index}")

    # latest.md
    src_md = EXPORTS_DIR / "latest.md"
    if src_md.exists():
        shutil.copy2(src_md, PUBLIC_DIR / "latest.md")
        print(f"  ✅ {PUBLIC_DIR / 'latest.md'}")

    # archive/*.html
    for html_file in EXPORTS_DIR.glob("2*.html"):
        dst = ARCHIVE_DIR / html_file.name
        shutil.copy2(html_file, dst)
        print(f"  ✅ {dst}")

    # sitemap.xml
    site_url = settings.get("site_url", "").rstrip("/")
    now = datetime.now().strftime("%Y-%m-%d")

    urls = [("", now, "daily", "1.0")]
    for html_file in sorted(ARCHIVE_DIR.glob("*.html"), reverse=True)[:30]:
        urls.append((f"archive/{html_file.name}", html_file.stem, "never", "0.5"))

    sitemap_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, lastmod, freq, priority in urls:
        loc = f"{site_url}/{path}" if site_url else path
        sitemap_lines.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod>"
                             f"<changefreq>{freq}</changefreq><priority>{priority}</priority></url>")
    sitemap_lines.append("</urlset>")

    sitemap_path = PUBLIC_DIR / "sitemap.xml"
    sitemap_path.write_text("\n".join(sitemap_lines), encoding="utf-8")
    print(f"  ✅ {sitemap_path}")

    # robots.txt
    robots_path = PUBLIC_DIR / "robots.txt"
    robots_content = "User-agent: *\nAllow: /\n"
    if site_url:
        robots_content += f"Sitemap: {site_url}/sitemap.xml\n"
    else:
        robots_content += "Sitemap: sitemap.xml\n"
    robots_path.write_text(robots_content, encoding="utf-8")
    print(f"  ✅ {robots_path}")

    # collector_report.html
    _build_collector_report_html(PUBLIC_DIR)

    # ファイル数カウント
    total = sum(1 for _ in PUBLIC_DIR.rglob("*") if _.is_file())
    print(f"\n  Build complete: {total} files in docs/")


def _build_collector_report_html(public_dir: Path) -> None:
    """exports/collector_report/latest.json → docs/collector_report.html を生成する。"""
    json_path = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
    if not json_path.exists():
        print(f"  ⚠️  collector_report/latest.json not found — skipping collector_report.html")
        return

    try:
        report = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠️  collector_report/latest.json parse error: {e}")
        return

    def _e(s) -> str:
        return _html.escape(str(s) if s is not None else "")

    generated_at = report.get("generated_at", "")
    summary      = report.get("summary", {})
    by_shop      = report.get("by_shop", {})
    by_product   = report.get("by_product", {})
    ff_list      = report.get("fetch_failed", [])
    pc_list      = report.get("price_changes", [])
    sp_list      = report.get("suspicious_prices", [])

    ok    = summary.get("ok", 0)
    fail  = summary.get("failed", 0)
    skip  = summary.get("skip", 0)
    total = summary.get("total", 0)

    # ── テーブルヘルパー ──
    def _tr(*cells, header=False):
        tag = "th" if header else "td"
        return "<tr>" + "".join(f"<{tag}>{_e(c)}</{tag}>" for c in cells) + "</tr>"

    def _table(headers, rows, cls=""):
        head = _tr(*headers, header=True)
        body = "".join(_tr(*r) for r in rows)
        return f'<table class="cr-table {cls}"><thead>{head}</thead><tbody>{body}</tbody></table>'

    # ── 店舗別テーブル ──
    shop_rows = [
        (shop, d["ok"], d["failed"], d["skip"])
        for shop, d in sorted(by_shop.items())
    ]
    shop_table = _table(["店舗", "OK", "失敗", "スキップ"], shop_rows)

    # ── 商品別テーブル ──
    product_rows = [
        (alias, d["ok"], d["failed"], d["skip"])
        for alias, d in sorted(by_product.items())
    ]
    product_table = _table(["商品", "OK", "失敗", "スキップ"], product_rows)

    # ── 取得失敗一覧 ──
    if ff_list:
        ff_rows = [(f["product_alias"], f["shop"], f["status"], f["reason"])
                   for f in ff_list]
        ff_table = _table(["商品", "店舗", "ステータス", "理由"], ff_rows, "cr-failed")
    else:
        ff_table = '<p class="cr-none">取得失敗なし</p>'

    # ── 価格変動一覧 ──
    if pc_list:
        pc_rows = [(c["product_alias"], c["shop"],
                    f"¥{c['prev_price']:,}", f"¥{c['new_price']:,}",
                    f"{'↑' if c['change_pct'] > 0 else '↓'}{abs(c['change_pct']):.1f}%")
                   for c in sorted(pc_list, key=lambda x: abs(x["change_pct"]), reverse=True)]
        pc_table = _table(["商品", "店舗", "前回", "今回", "変化率"], pc_rows, "cr-changes")
    else:
        pc_table = '<p class="cr-none">価格変動なし（前回比）</p>'

    # ── suspicious_price 一覧 ──
    if sp_list:
        sp_rows = [(s["product_alias"], s["shop"], f"¥{s['price']:,}", s["reason"], s["details"])
                   for s in sp_list]
        sp_table = _table(["商品", "店舗", "価格", "理由", "詳細"], sp_rows, "cr-suspicious")
        sp_badge = f'<span class="cr-badge cr-badge-warn">⚠️ {len(sp_list)}件</span>'
    else:
        sp_table = '<p class="cr-none">suspicious_price なし</p>'
        sp_badge = '<span class="cr-badge cr-badge-ok">✅ なし</span>'

    # ── 失敗バッジ ──
    fail_badge_cls = "cr-badge-warn" if fail > 0 else "cr-badge-ok"
    fail_badge = f'<span class="cr-badge {fail_badge_cls}">{"⚠️" if fail > 0 else "✅"} {fail}件失敗</span>'

    html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Collector Quality Report — プレ値速報</title>
<style>
  :root {{
    --bg: #0f1117; --surface: #1a1d27; --border: #2d3148;
    --text: #e2e8f0; --muted: #94a3b8;
    --ok: #22c55e; --warn: #f59e0b; --fail: #ef4444;
    --accent: #6366f1;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 14px; line-height: 1.6; }}
  .cr-wrap {{ max-width: 960px; margin: 0 auto; padding: 24px 16px 60px; }}
  .cr-topbar {{ display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--surface); border-bottom: 1px solid var(--border); margin-bottom: 24px; border-radius: 8px; }}
  .cr-topbar a {{ color: var(--accent); text-decoration: none; font-size: 13px; }}
  .cr-topbar a:hover {{ text-decoration: underline; }}
  .cr-topbar-title {{ font-size: 15px; font-weight: 600; flex: 1; }}
  h1 {{ font-size: 20px; font-weight: 700; margin-bottom: 4px; }}
  .cr-meta {{ color: var(--muted); font-size: 12px; margin-bottom: 24px; }}
  h2 {{ font-size: 14px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin: 28px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }}
  .cr-summary {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }}
  .cr-stat {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px 20px; min-width: 100px; text-align: center; }}
  .cr-stat-val {{ font-size: 26px; font-weight: 700; line-height: 1; }}
  .cr-stat-lbl {{ font-size: 11px; color: var(--muted); margin-top: 4px; }}
  .cr-stat-val.ok   {{ color: var(--ok); }}
  .cr-stat-val.fail {{ color: var(--fail); }}
  .cr-stat-val.skip {{ color: var(--muted); }}
  .cr-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  .cr-table th {{ background: var(--surface); padding: 8px 12px; text-align: left; color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--border); }}
  .cr-table td {{ padding: 7px 12px; border-bottom: 1px solid rgba(45,49,72,.5); }}
  .cr-table tr:last-child td {{ border-bottom: none; }}
  .cr-table tr:hover td {{ background: rgba(255,255,255,.03); }}
  .cr-failed td:nth-child(3), .cr-failed td:nth-child(4) {{ font-family: monospace; font-size: 12px; color: var(--warn); }}
  .cr-suspicious td:nth-child(4) {{ color: var(--warn); font-size: 12px; }}
  .cr-suspicious td:nth-child(5) {{ color: var(--muted); font-size: 12px; }}
  .cr-changes td:nth-child(5) {{ font-weight: 600; }}
  .cr-none {{ color: var(--muted); font-size: 13px; padding: 8px 0; }}
  .cr-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; margin-left: 8px; }}
  .cr-badge-ok   {{ background: rgba(34,197,94,.15); color: var(--ok); }}
  .cr-badge-warn {{ background: rgba(245,158,11,.15); color: var(--warn); }}
  @media (max-width: 600px) {{ .cr-summary {{ gap: 8px; }} .cr-stat {{ min-width: 80px; padding: 10px 14px; }} }}
</style>
</head>
<body>
<div class="cr-wrap">
  <div class="cr-topbar">
    <span class="cr-topbar-title">📊 Collector Quality Report</span>
    <a href="index.html">← LP トップに戻る</a>
  </div>
  <h1>買取価格 取得品質レポート</h1>
  <p class="cr-meta">生成日時: {_e(generated_at)}</p>

  <h2>サマリ</h2>
  <div class="cr-summary">
    <div class="cr-stat"><div class="cr-stat-val" style="color:var(--text)">{total}</div><div class="cr-stat-lbl">合計</div></div>
    <div class="cr-stat"><div class="cr-stat-val ok">{ok}</div><div class="cr-stat-lbl">OK</div></div>
    <div class="cr-stat"><div class="cr-stat-val fail">{fail}</div><div class="cr-stat-lbl">失敗 {fail_badge}</div></div>
    <div class="cr-stat"><div class="cr-stat-val skip">{skip}</div><div class="cr-stat-lbl">スキップ</div></div>
    <div class="cr-stat"><div class="cr-stat-val">{len(sp_list)}</div><div class="cr-stat-lbl">疑わしい価格 {sp_badge}</div></div>
  </div>

  <h2>店舗別 OK / 失敗 / スキップ</h2>
  {shop_table}

  <h2>商品別 OK / 失敗 / スキップ</h2>
  {product_table}

  <h2>取得失敗一覧 ({len(ff_list)} 件)</h2>
  {ff_table}

  <h2>価格変動一覧 ({len(pc_list)} 件)</h2>
  {pc_table}

  <h2>⚠️ suspicious_price 一覧 ({len(sp_list)} 件)</h2>
  {sp_table}
</div>
</body>
</html>"""

    dst = public_dir / "collector_report.html"
    dst.write_text(html_content, encoding="utf-8")
    print(f"  ✅ {dst}")


if __name__ == "__main__":
    build()
