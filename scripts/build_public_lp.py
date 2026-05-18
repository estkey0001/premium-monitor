#!/usr/bin/env python3
"""public/ ディレクトリにLP公開用ファイルをビルドする。

exports/lp/daily/ → public/ へコピーし、
sitemap.xml・robots.txt を生成する。
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports" / "lp" / "daily"
PUBLIC_DIR = PROJECT_ROOT / "public"
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

    # ファイル数カウント
    total = sum(1 for _ in PUBLIC_DIR.rglob("*") if _.is_file())
    print(f"\n  Build complete: {total} files in public/")


if __name__ == "__main__":
    build()
