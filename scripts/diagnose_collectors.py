#!/usr/bin/env python3
"""
各買取サイトのHTMLを実際に取得し、価格パターンを調査するスクリプト。
結果は exports/debug/ に保存する。

使い方:
  python scripts/diagnose_collectors.py [--shops iosys geo_mobile sofmap surugaya bookoff janpara]
"""
import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEBUG_DIR = PROJECT_ROOT / "exports" / "debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

TODAY = datetime.now().strftime("%Y%m%d")

# ── User-Agent ──
UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)


def _save(name: str, content: str, ext: str = "html") -> Path:
    path = DEBUG_DIR / f"{name}_{TODAY}.{ext}"
    path.write_text(content, encoding="utf-8")
    print(f"    💾 saved: {path}")
    return path


def _extract_context(text: str, keywords: list, window: int = 500) -> str:
    """キーワード周辺のテキストを抽出。"""
    parts = []
    for kw in keywords:
        idx = text.lower().find(kw.lower())
        if idx >= 0:
            start = max(0, idx - 50)
            end = min(len(text), idx + window)
            excerpt = text[start:end].strip()
            parts.append(f"  [keyword='{kw}' @ pos={idx}]\n  {excerpt[:300]}\n")
    return "\n".join(parts) if parts else "  (キーワード未発見)"


def _try_requests(url: str, ua: str = UA_DESKTOP, verify_ssl: bool = True) -> tuple[int, str]:
    """requests で取得。(status_code, text) を返す。"""
    import requests
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": ua,
        "Accept-Language": "ja,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        resp = sess.get(url, timeout=15, verify=verify_ssl, allow_redirects=True)
        return resp.status_code, resp.text
    except Exception as e:
        return 0, str(e)


def _try_playwright(url: str, ua: str = UA_DESKTOP, wait_ms: int = 4000) -> tuple[str, str]:
    """Playwright で取得。(html_content, inner_text) を返す。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=ua,
                extra_http_headers={"Accept-Language": "ja,en;q=0.9"},
            )
            page = ctx.new_page()
            resp = page.goto(url, timeout=30000, wait_until="domcontentloaded")
            status = resp.status if resp else 0
            page.wait_for_timeout(wait_ms)
            html = page.content()
            text = page.inner_text("body")
            browser.close()
            return html, text, status
    except Exception as e:
        return "", str(e), 0


# ═══════════════════════════════════════════════════════
# イオシス
# ═══════════════════════════════════════════════════════
def diagnose_iosys():
    print("\n" + "="*60)
    print("📋 イオシス (k-tai-iosys.com)")
    print("="*60)
    urls = {
        "smartphone": "https://k-tai-iosys.com/pricelist/",
        "game":       "https://k-tai-iosys.com/pricelist/game/",
    }
    keywords_phone = ["iPhone 17 Pro", "iPhone17", "17 Pro 256", "17 Pro 512"]
    keywords_game  = ["Switch 2", "Nintendo Switch", "PS5 Pro", "PlayStation 5 Pro"]

    for page_name, url in urls.items():
        print(f"\n  → {page_name}: {url}")
        status, html = _try_requests(url)
        print(f"    HTTP status: {status}  HTML size: {len(html)} bytes")

        if status == 200 and len(html) > 500:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(" ", strip=True)
            _save(f"iosys_{page_name}", html, "html")
            _save(f"iosys_{page_name}", text, "txt")

            kws = keywords_phone if page_name == "smartphone" else keywords_game
            print("  🔍 商品名周辺テキスト:")
            print(_extract_context(text, kws, window=600))

            # CSS クラス調査
            prices_spans = soup.find_all("span", class_=re.compile(r'price', re.I))
            print(f"  📌 price系spanクラス一覧: {list(set(s.get('class',[''])[0] for s in prices_spans[:20]))}")

            # <tr> テーブル行チェック
            trs = soup.find_all("tr")
            print(f"  📌 <tr> 行数: {len(trs)}")
            for tr in trs[:5]:
                row_text = tr.get_text(" ", strip=True)
                if any(kw.lower() in row_text.lower() for kw in kws):
                    print(f"  ✅ 商品行発見: {row_text[:200]}")
        else:
            print(f"    ❌ 取得失敗 ({status}): {html[:200]}")


# ═══════════════════════════════════════════════════════
# ゲオモバイル
# ═══════════════════════════════════════════════════════
def diagnose_geo_mobile():
    import urllib.parse
    print("\n" + "="*60)
    print("📋 ゲオモバイル (geomobile.jp)")
    print("="*60)

    base_url = "https://geomobile.jp/purchase/"
    search_url = f"https://geomobile.jp/purchase/search/?q={urllib.parse.quote('iPhone 17 Pro 256GB')}"

    for label, url in [("top", base_url), ("search", search_url)]:
        for ua_label, ua in [("desktop_UA", UA_DESKTOP), ("mobile_UA", UA_MOBILE)]:
            print(f"\n  → {label} / {ua_label}: {url}")
            time.sleep(1)
            status, html = _try_requests(url, ua=ua, verify_ssl=True)
            print(f"    requests SSL=True: status={status}, size={len(html)}")
            if status == 200 and len(html) > 500:
                _save(f"geo_mobile_{label}_{ua_label}_req", html, "html")
                from bs4 import BeautifulSoup
                text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
                _save(f"geo_mobile_{label}_{ua_label}_req", text, "txt")
                print(_extract_context(text, ["iPhone 17 Pro", "iPhone17"], 400))
                break
            # SSL verify=False 試行
            if status == 0:
                time.sleep(1)
                status2, html2 = _try_requests(url, ua=ua, verify_ssl=False)
                print(f"    requests SSL=False: status={status2}, size={len(html2)}")
                if status2 == 200 and len(html2) > 500:
                    _save(f"geo_mobile_{label}_{ua_label}_nossl", html2, "html")
                    break

    # Playwright 試行
    print("\n  → Playwright試行 (desktop UA):")
    time.sleep(2)
    html, text, pw_status = _try_playwright(search_url, ua=UA_DESKTOP, wait_ms=4000)
    print(f"    Playwright status={pw_status}, html={len(html)} bytes, text={len(text)} chars")
    if len(html) > 500:
        _save("geo_mobile_search_playwright", html, "html")
        _save("geo_mobile_search_playwright", text, "txt")
        print(_extract_context(text, ["iPhone 17 Pro", "iPhone17"], 400))
    elif text:
        print(f"    エラー/テキスト: {text[:300]}")


# ═══════════════════════════════════════════════════════
# ソフマップ
# ═══════════════════════════════════════════════════════
def diagnose_sofmap():
    import urllib.parse
    print("\n" + "="*60)
    print("📋 ソフマップ (sofmap.com)")
    print("="*60)

    # 現行URL確認
    urls = {
        "buy_list_switch2": f"https://www.sofmap.com/buy_list.aspx?keyword={urllib.parse.quote('Nintendo Switch 2')}",
        "buy_list_ps5":     f"https://www.sofmap.com/buy_list.aspx?keyword={urllib.parse.quote('PlayStation 5 Pro')}",
        "buy_top":          "https://www.sofmap.com/buy_list.aspx",
    }

    for label, url in urls.items():
        print(f"\n  → {label}: {url}")
        time.sleep(1.5)
        status, html = _try_requests(url, ua=UA_DESKTOP)
        print(f"    requests: status={status}, size={len(html)}")

        if status == 200 and len(html) > 1000:
            _save(f"sofmap_{label}", html, "html")
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            _save(f"sofmap_{label}", text, "txt")
            kws = ["Switch 2", "Nintendo Switch 2", "PlayStation 5 Pro", "PS5 Pro", "買取価格"]
            print("  🔍 商品名周辺テキスト:")
            print(_extract_context(text, kws, 400))
        elif status >= 400:
            print(f"    ❌ HTTP {status} — Playwright試行")
            time.sleep(2)
            html_pw, text_pw, pw_status = _try_playwright(url, ua=UA_DESKTOP, wait_ms=4000)
            print(f"    Playwright: status={pw_status}, html={len(html_pw)}, text={len(text_pw)}")
            if len(html_pw) > 500:
                _save(f"sofmap_{label}_playwright", html_pw, "html")
                _save(f"sofmap_{label}_playwright", text_pw, "txt")
                kws = ["Switch 2", "PS5 Pro", "買取価格"]
                print(_extract_context(text_pw, kws, 400))


# ═══════════════════════════════════════════════════════
# 駿河屋
# ═══════════════════════════════════════════════════════
def diagnose_surugaya():
    import urllib.parse
    print("\n" + "="*60)
    print("📋 駿河屋 (suruga-ya.jp)")
    print("="*60)

    urls = {
        "switch2_kaitori": f"https://www.suruga-ya.jp/kaitori/kaitori_list.php?keyword={urllib.parse.quote('Nintendo Switch 2')}&category=&stock=2",
        "ps5_kaitori":     f"https://www.suruga-ya.jp/kaitori/kaitori_list.php?keyword={urllib.parse.quote('PlayStation 5 Pro')}&category=&stock=2",
        "kaitori_top":     "https://www.suruga-ya.jp/kaitori/",
    }

    for label, url in urls.items():
        print(f"\n  → {label}: {url}")
        time.sleep(1.5)
        status, html = _try_requests(url, ua=UA_DESKTOP)
        print(f"    requests: status={status}, size={len(html)}")

        if status == 200 and len(html) > 500:
            _save(f"surugaya_{label}", html, "html")
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            _save(f"surugaya_{label}", text, "txt")
            kws = ["Switch 2", "Nintendo Switch 2", "PlayStation", "買取価格", "買取"]
            print("  🔍 商品名周辺テキスト:")
            print(_extract_context(text, kws, 400))
        elif status == 403:
            print("    ❌ 403 Forbidden — ボット検知の可能性")
            # Playwright試行
            time.sleep(2)
            html_pw, text_pw, pw_status = _try_playwright(url, ua=UA_DESKTOP, wait_ms=4000)
            print(f"    Playwright: status={pw_status}, html={len(html_pw)}, text={len(text_pw)}")
            if len(html_pw) > 500:
                _save(f"surugaya_{label}_playwright", html_pw, "html")
                _save(f"surugaya_{label}_playwright", text_pw, "txt")
                kws = ["Switch 2", "買取価格"]
                print(_extract_context(text_pw, kws, 400))
            else:
                print(f"    Playwright結果: {text_pw[:200]}")


# ═══════════════════════════════════════════════════════
# ブックオフ
# ═══════════════════════════════════════════════════════
def diagnose_bookoff():
    import urllib.parse
    print("\n" + "="*60)
    print("📋 ブックオフ (bookoffonline.co.jp)")
    print("="*60)

    # ブックオフの買取価格ページを調査
    urls = {
        "kaitori_top":   "https://www.bookoffonline.co.jp/files/050kaitori.html",
        "search_switch": f"https://www.bookoffonline.co.jp/files/050kaitori.html?keyword={urllib.parse.quote('Nintendo Switch 2')}",
        "assess_iphone": "https://www.bookoffonline.co.jp/files/050kaitori.html?keyword=iPhone+17",
    }

    for label, url in urls.items():
        print(f"\n  → {label}: {url}")
        time.sleep(1.5)
        status, html = _try_requests(url, ua=UA_DESKTOP)
        print(f"    requests: status={status}, size={len(html)}")

        if status == 200 and len(html) > 500:
            _save(f"bookoff_{label}", html, "html")
            from bs4 import BeautifulSoup
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            _save(f"bookoff_{label}", text, "txt")
            kws = ["Switch 2", "iPhone", "買取価格", "査定"]
            print("  🔍 商品名周辺テキスト:")
            print(_extract_context(text, kws, 400))
        else:
            print(f"    ❌ HTTP {status}: {html[:200]}")


# ═══════════════════════════════════════════════════════
# じゃんぱら
# ═══════════════════════════════════════════════════════
def diagnose_janpara():
    print("\n" + "="*60)
    print("📋 じゃんぱら (buy.janpara.co.jp)")
    print("="*60)

    url = "https://buy.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+256GB"
    print(f"  → {url}")

    time.sleep(3)
    status, html = _try_requests(url, ua=UA_DESKTOP)
    print(f"    requests: status={status}, size={len(html)}")

    if status == 200 and len(html) > 500:
        _save("janpara_iphone17pro256", html, "html")
        from bs4 import BeautifulSoup
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        _save("janpara_iphone17pro256", text, "txt")
        kws = ["iPhone 17 Pro", "買取", "価格"]
        print(_extract_context(text, kws, 400))
    elif status == 429:
        print("    ❌ 429 Rate Limit — Playwright試行 (5秒スリープ後)")
        time.sleep(5)
        html_pw, text_pw, pw_status = _try_playwright(url, ua=UA_DESKTOP, wait_ms=4000)
        print(f"    Playwright: status={pw_status}, html={len(html_pw)}, text={len(text_pw)}")
        if len(text_pw) > 200:
            _save("janpara_iphone17pro256_playwright", html_pw, "html")
            _save("janpara_iphone17pro256_playwright", text_pw, "txt")
            kws = ["iPhone 17 Pro", "買取", "価格"]
            print(_extract_context(text_pw, kws, 400))
    else:
        print(f"    ❌ HTTP {status}: {html[:300]}")


# ═══════════════════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════════════════
SHOP_FUNCS = {
    "iosys":      diagnose_iosys,
    "geo_mobile": diagnose_geo_mobile,
    "sofmap":     diagnose_sofmap,
    "surugaya":   diagnose_surugaya,
    "bookoff":    diagnose_bookoff,
    "janpara":    diagnose_janpara,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="買取サイト診断スクリプト")
    parser.add_argument("--shops", nargs="+", choices=list(SHOP_FUNCS.keys()),
                        default=list(SHOP_FUNCS.keys()),
                        help="調査するショップ (デフォルト: 全て)")
    args = parser.parse_args()

    print(f"\n🔬 買取サイト診断 ({TODAY})")
    print(f"   対象: {args.shops}")
    print(f"   保存先: {DEBUG_DIR}")

    for shop in args.shops:
        SHOP_FUNCS[shop]()

    print(f"\n\n✅ 診断完了。結果は {DEBUG_DIR} に保存されました。")
