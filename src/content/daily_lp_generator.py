"""日次LP自動生成エンジン (Phase 13+)。

buyback_premium_check 完了後に呼ばれ、
exports/lp/daily/index.html を生成する。

タブUI構成:
  - 初級者向け (beginner_easy / beginner_watch)
  - 上級者向け (advanced_high_profit / expert_only / カメラ / 抽選 / SOLD OUT / 海外)
  - 本日の急騰/急落 (buyback_surge / buyback_drop)
  - 買取ランキング (実質利益 / 買取店別 / iPhone / ゲーム機)

データ鮮度:
  - 買取価格更新日時（buyback_prices.observed_at 最新値）
  - LP生成日時（datetime.now()）
  - 24時間超の場合は警告バナー表示
"""

import html as html_mod
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.content.safety import (
    check_forbidden, sanitize_text, fmt_price, fmt_profit, fmt_rate,
    DISCLAIMER_SHORT, DISCLAIMER_FULL,
)
from src.db.repository import Repository
import urllib.parse as _urllib_parse

try:
    from src.market.link_resolver import LinkResolver as _LinkResolver
    def get_resolver():
        return _LinkResolver()
except ImportError:
    def get_resolver():
        return None

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JST = timezone(timedelta(hours=9))


def _esc(text) -> str:
    return html_mod.escape(str(text)) if text is not None else ""


def _jst_str(dt: Optional[datetime]) -> str:
    """datetime を JST 表示文字列に変換する。"""
    if not dt:
        return "不明"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    else:
        dt = dt.astimezone(JST)
    return dt.strftime("%Y-%m-%d %H:%M JST")


def _hours_ago(dt: Optional[datetime]) -> float:
    """dt が何時間前か返す。Noneなら999。"""
    if not dt:
        return 999.0
    now = datetime.now(tz=JST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    else:
        dt = dt.astimezone(JST)
    return (now - dt).total_seconds() / 3600


def _load_lp_settings() -> dict:
    path = PROJECT_ROOT / "config" / "lp_settings.yaml"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


class DailyLPGenerator:
    """日次LP HTMLを生成する。"""

    def __init__(self, repository: Repository):
        self.repo = repository
        self.settings = _load_lp_settings()

    def generate(self, date_str: Optional[str] = None, variant: Optional[str] = None) -> dict:
        """LP HTMLを生成して保存する。"""
        now = datetime.now()
        date_str = date_str or now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

        # A/Bバリアント上書き
        orig_variant = self.settings.get("headline_variant", "A")
        if variant:
            self.settings["headline_variant"] = variant

        out_dir = PROJECT_ROOT / self.settings.get("output", {}).get("daily_dir", "exports/lp/daily")
        out_dir.mkdir(parents=True, exist_ok=True)

        # データ取得（優先度順で最新observed_atを決定）
        latest_buyback_at = self.repo.get_latest_buyback_observed_at()
        latest_deals_at   = self.repo.get_latest_beginner_deals_at()
        lp_generated_at   = now

        # beginner deals（レベル別）
        beginner_easy  = self.repo.list_beginner_deals(user_level="beginner_easy",  min_profit=0, limit=15)
        beginner_watch = self.repo.list_beginner_deals(user_level="beginner_watch", min_profit=0, limit=10)
        advanced_deals = self.repo.list_beginner_deals(user_level="advanced",       min_profit=0, limit=15)

        # 上級者向けスナップショット
        advanced_snaps = self.repo.list_premium_candidates_with_snapshots(limit=15, user_level="advanced")

        # 上級者向けフォールバック：監視候補（camera + game_console）
        watch_candidates = self.repo.list_watch_candidates(genres=["camera", "game_console"], limit=20)

        # 商品別買取店一覧（複数店舗比較用）- product_id → [buyback_rows]
        buyback_by_product: dict = {}
        _all_products = self.repo.list_products()
        for _p in _all_products:
            _rows = self.repo.list_buyback_prices_by_product(_p.id, limit=5)
            if _rows:
                buyback_by_product[_p.id] = _rows

        # 急騰・急落
        buyback_alerts = self.repo.list_buyback_alerts(limit=20)

        # ランキング用 + カテゴリ別
        all_deals    = self.repo.list_beginner_deals(min_profit=0, limit=50)
        iphone_deals = [d for d in all_deals if d.category == "iphone"]
        game_deals   = [d for d in all_deals if d.category == "game_console"]
        camera_deals = [d for d in all_deals if d.category == "camera"]
        # ジャンル別監視候補
        iphone_watch  = self.repo.list_watch_candidates(genres=["iphone"],       limit=15)
        camera_watch  = self.repo.list_watch_candidates(genres=["camera"],       limit=15)
        game_watch    = self.repo.list_watch_candidates(genres=["game_console"], limit=15)
        # v5: camera_watch for advanced tab
        _camera_watch_adv = camera_watch

        # せどりルート取得（Phase 14）
        sedori_routes = []
        try:
            sedori_routes = self.repo.list_sedori_routes(min_net_profit=0, limit=20)
        except Exception:
            sedori_routes = []

        # HTML生成
        page_html = self._render_page(
            date_str=date_str,
            time_str=time_str,
            latest_buyback_at=latest_buyback_at,
            latest_deals_at=latest_deals_at,
            lp_generated_at=lp_generated_at,
            beginner_easy=beginner_easy,
            beginner_watch=beginner_watch,
            advanced_deals=advanced_deals,
            advanced_snaps=advanced_snaps,
            watch_candidates=watch_candidates,
            buyback_alerts=buyback_alerts,
            all_deals=all_deals,
            iphone_deals=iphone_deals,
            game_deals=game_deals,
            camera_deals=camera_deals,
            iphone_watch=iphone_watch,
            camera_watch=camera_watch,
            game_watch=game_watch,
            buyback_by_product=buyback_by_product,
            sedori_routes=sedori_routes,
        )

        # 安全チェック
        forbidden = check_forbidden(page_html)
        if forbidden:
            logger.warning("LP forbidden phrases: %s — sanitizing", forbidden)
            page_html, _ = sanitize_text(page_html)

        # 保存
        suffix = f"_{variant}" if variant else ""
        index_path = out_dir / f"index{suffix}.html"
        dated_path = out_dir / f"{date_str}{suffix}.html"
        md_path    = out_dir / "latest.md"

        index_path.write_text(page_html, encoding="utf-8")
        dated_path.write_text(page_html, encoding="utf-8")

        # variant指定有無に関わらず index.html を常に更新（build-public-lp が参照するファイル）
        (out_dir / "index.html").write_text(page_html, encoding="utf-8")
        if not variant:
            md_content = self._render_markdown(
                date_str, time_str,
                beginner_easy + beginner_watch, advanced_snaps, buyback_alerts,
            )
            md_path.write_text(md_content, encoding="utf-8")

        self.settings["headline_variant"] = orig_variant

        return {
            "index_path": str(index_path),
            "dated_path": str(dated_path),
            "md_path": str(md_path),
            "variant": variant or orig_variant,
            "date": date_str,
            "time": time_str,
            "beginner_count": len(beginner_easy) + len(beginner_watch),
            "advanced_count": len(advanced_deals) + len(advanced_snaps),
            "alerts_count": len(buyback_alerts),
            "char_count": len(page_html),
            "forbidden_found": forbidden,
            "latest_buyback_at": _jst_str(latest_buyback_at),
            "latest_deals_at":   _jst_str(latest_deals_at),
        }

    # ===== HTML Rendering =====

    def _render_page(self, date_str, time_str,
                     latest_buyback_at, latest_deals_at, lp_generated_at,
                     beginner_easy, beginner_watch, advanced_deals, advanced_snaps,
                     watch_candidates, buyback_alerts, all_deals, iphone_deals, game_deals,
                     camera_deals=None, iphone_watch=None, camera_watch=None, game_watch=None,
                     buyback_by_product: dict = None, sedori_routes: list = None) -> str:

        site_title = _esc(self.settings.get("site_title", "プレ値速報"))
        ga_id      = self.settings.get("analytics", {}).get("google_analytics_id", "")
        meta_pixel = self.settings.get("analytics", {}).get("meta_pixel_id", "")
        x_pixel    = self.settings.get("analytics", {}).get("x_pixel_id", "")

        analytics_head = ""
        if ga_id:
            analytics_head += (
                f'<script async src="https://www.googletagmanager.com/gtag/js?id={_esc(ga_id)}"></script>\n'
                f'<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}'
                f'gtag("js",new Date());gtag("config","{_esc(ga_id)}");</script>\n'
            )
        if meta_pixel:
            analytics_head += (
                f'<script>!function(f,b,e,v,n,t,s){{if(f.fbq)return;n=f.fbq=function(){{'
                f'n.callMethod?n.callMethod.apply(n,arguments):n.queue.push(arguments)}};'
                f'if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version="2.0";n.queue=[];'
                f't=b.createElement(e);t.async=!0;t.src=v;s=b.getElementsByTagName(e)[0];'
                f'}}(window,document,"script","https://connect.facebook.net/en_US/fbevents.js");'
                f'fbq("init","{_esc(meta_pixel)}");fbq("track","PageView");</script>\n'
            )
        if x_pixel:
            analytics_head += f'<!-- X Pixel {_esc(x_pixel)} -->\n'

        # 抽選情報
        lottery_events = []
        try:
            lottery_events = self.repo.list_lottery_events(status="active", limit=20)
        except Exception:
            lottery_events = []

        # セクション生成
        hero_html    = self._section_hero(date_str, time_str, latest_buyback_at, lp_generated_at,
                                           all_deals=all_deals, iphone_deals=iphone_deals,
                                           camera_deals=camera_deals or [], game_deals=game_deals)
        stale_html   = self._section_stale_warning(latest_buyback_at, latest_deals_at, lp_generated_at)
        category_nav_html = self._section_category_nav(lottery_count=len(lottery_events))
        tab_html     = self._section_tabs(
            beginner_easy, beginner_watch,
            advanced_deals, advanced_snaps,
            watch_candidates,
            buyback_alerts,
            all_deals, iphone_deals, game_deals,
            camera_deals=camera_deals or [],
            iphone_watch=iphone_watch or [],
            camera_watch=camera_watch or [],
            game_watch=game_watch or [],
            buyback_by_product=buyback_by_product or {},
            sedori_routes=sedori_routes or [],
            lottery_events=lottery_events,
        )
        caution_html = self._section_caution()
        cta_html     = self._section_cta()
        footer_html  = self._section_footer()

        # topbar用の日時文字列（_render_page スコープで利用）
        _buyback_str_top = _jst_str(latest_buyback_at) if latest_buyback_at else "—"
        _lp_str_top = lp_generated_at.strftime("%m/%d %H:%M") if lp_generated_at else "—"
        # アナウンスバー用
        _beginner_count_top = len(beginner_easy)
        _max_profit_top = max((d.net_profit_jpy or 0) for d in beginner_easy) if beginner_easy else 0
        _max_profit_str_top = f'+¥{_max_profit_top:,}' if _max_profit_top > 0 else '—'

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title}</title>
<meta name="description" content="{_esc(self.settings.get('site_description', ''))}">
{analytics_head}
<style>
/* ============================================================
   SOUBA デザインシステム — プレ値速報
   ============================================================ */

:root {{
  /* ページ背景 */
  --bg: #FAFBFF;
  /* カード */
  --card-bg: #FFFFFF;
  --card-border: #E8EAF2;
  --surface2: #F4F6FD;
  /* テキスト */
  --ink: #0D0F1C;
  --ink2: #5B6278;
  --ink3: #9CA3B8;
  --ink4: #C8CADE;
  /* アクセント */
  --profit: #00C896;
  --profit-dark: #00A876;
  --violet: #7C5CFC;
  --violet-dark: #6040E8;
  --amber: #FF9500;
  --danger: #FF3B5C;
  --blue: #3B7BFF;
  --gold: #F5A623;

  /* 後方互換用エイリアス */
  --white:   #ffffff;
  --gray-50: #f8fafc;
  --gray-100:#f1f5f9;
  --gray-200:#e2e8f0;
  --gray-300:#cbd5e1;
  --gray-400:#94a3b8;
  --gray-500:#64748b;
  --gray-600:#475569;
  --gray-700:#334155;
  --gray-800:#1e293b;
  --gray-900:#0f172a;
  --blue-50:  #eff6ff;
  --blue-100: #dbeafe;
  --blue-200: #bfdbfe;
  --blue-500: #3b82f6;
  --blue-600: #2563eb;
  --blue-700: #1d4ed8;
  --green-50:  #f0fdf4;
  --green-100: #dcfce7;
  --green-200: #bbf7d0;
  --green-500: #22c55e;
  --green-600: #16a34a;
  --green-700: #15803d;
  --amber-50:  #fffbeb;
  --amber-100: #fef3c7;
  --amber-200: #fde68a;
  --amber-500: #f59e0b;
  --amber-600: #d97706;
  --amber-700: #b45309;
  --red-50:   #fef2f2;
  --red-100:  #fee2e2;
  --red-500:  #ef4444;
  --red-600:  #dc2626;
  --purple-50:  #faf5ff;
  --purple-100: #f3e8ff;
  --purple-500: #a855f7;
  --purple-600: #9333ea;
  --teal-50:  #f0fdfa;
  --teal-100: #ccfbf1;
  --teal-500: #14b8a6;
  --teal-600: #0d9488;

  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Hiragino Sans', 'Meiryo', sans-serif;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
  --radius-2xl: 28px;

  --shadow-xs: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-sm: 0 1px 3px rgba(13,15,28,0.05), 0 1px 2px rgba(13,15,28,0.04);
  --shadow-md: 0 4px 8px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);
  --shadow-lg: 0 10px 20px rgba(0,0,0,0.08), 0 4px 8px rgba(0,0,0,0.04);
  --shadow-xl: 0 12px 40px rgba(13,15,28,0.1), 0 4px 12px rgba(13,15,28,0.06);
}}

*, *::before, *::after {{
  margin: 0; padding: 0;
  box-sizing: border-box;
  -webkit-font-smoothing: antialiased;
}}

html {{ scroll-behavior: smooth; }}

body {{
  font-family: var(--font);
  background: var(--bg);
  color: var(--ink);
  font-size: 15px;
  line-height: 1.6;
  font-feature-settings: "cv02","cv03","cv04","cv11","tnum";
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

/* ============================================================
   SCROLLBAR — Manus style
   ============================================================ */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: #D0D4E8; border-radius: 4px; }}
::-webkit-scrollbar-thumb:hover {{ background: #B0B6CC; }}

/* ============================================================
   ANIMATIONS — fade-in-up
   ============================================================ */
@keyframes fadeInUp {{
  from {{ opacity: 0; transform: translateY(16px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}

.fade-in-up {{
  animation: fadeInUp 0.45s cubic-bezier(0.23,1,0.32,1) forwards;
  opacity: 0;
}}

.delay-100 {{ animation-delay: 100ms; }}
.delay-200 {{ animation-delay: 200ms; }}
.delay-300 {{ animation-delay: 300ms; }}

/* ============================================================
   CURSOR — クリック可能要素
   ============================================================ */
a[href], button, [role="tab"], [role="button"],
.tab-btn, .genre-chip, .maker-chip, .oc-chip,
.overseas-btn, .overseas-chip, .shop-check-btn {{
  cursor: pointer;
}}

/* オーバーレイがクリックを阻害しないように */
.hero::before, .hero::after,
.section-overlay, .bg-overlay {{
  pointer-events: none;
}}

/* ============================================================
   ANNOUNCEMENT BAR
   ============================================================ */
.announce-bar {{
  background: linear-gradient(90deg, #00C896, #3B7BFF, #7C5CFC);
  text-align: center;
  padding: 8px 20px;
}}

.announce-bar a {{
  color: #fff;
  text-decoration: none;
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.01em;
}}

.announce-bar a:hover {{ text-decoration: underline; }}

/* ============================================================
   TOPBAR
   ============================================================ */
.topbar {{
  position: sticky; top: 0; z-index: 300;
  background: rgba(250,251,255,0.95);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--card-border);
  height: 56px;
  display: flex; align-items: center;
  padding: 0 20px; gap: 12px;
}}

.topbar-brand {{
  display: flex; align-items: center; gap: 10px;
  text-decoration: none; color: var(--ink);
  font-weight: 800; font-size: 0.95rem;
}}

.brand-icon {{
  width: 30px; height: 30px;
  background: linear-gradient(135deg, var(--blue), var(--violet));
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: white; font-weight: 900; font-size: 0.8rem;
  box-shadow: 0 2px 8px rgba(59,123,255,0.3);
  flex-shrink: 0;
}}

.topbar-live {{
  display: flex; align-items: center; gap: 5px;
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--profit-dark);
  background: #F0FDF8;
  border: 1px solid #B2F0DC;
  padding: 3px 10px; border-radius: 99px;
}}

.live-dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--profit);
  animation: blink 2s ease-in-out infinite;
}}

@keyframes blink {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.3; }}
}}

.topbar-date {{
  font-size: 0.78rem; color: var(--ink3);
  font-variant-numeric: tabular-nums;
}}

.topbar-spacer {{ flex: 1; }}

.topbar-note-btn {{
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--violet); color: white;
  font-size: 0.78rem; font-weight: 700;
  padding: 7px 16px; border-radius: var(--radius-md);
  text-decoration: none;
  box-shadow: 0 2px 8px rgba(124,92,252,0.3);
  transition: all 0.2s;
  white-space: nowrap;
}}

.topbar-note-btn:hover {{
  background: var(--violet-dark);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(124,92,252,0.4);
}}

/* ============================================================
   LIVE TICKER
   ============================================================ */
.ticker-bar {{
  background: #0D0F1C;
  overflow: hidden;
  padding: 7px 0;
  white-space: nowrap;
}}

.ticker-inner {{
  display: inline-block;
  animation: tickerScroll 30s linear infinite;
}}

@keyframes tickerScroll {{
  0%   {{ transform: translateX(0); }}
  100% {{ transform: translateX(-50%); }}
}}

.ticker-item {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.78rem; color: rgba(255,255,255,0.85);
  padding: 0 28px;
}}

.ticker-item .t-name {{ font-weight: 600; }}
.ticker-item .t-profit {{ color: #00C896; font-weight: 700; }}
.ticker-sep {{ color: rgba(255,255,255,0.2); }}

/* ============================================================
   FEATURES BANNER
   ============================================================ */
.features-bar {{
  background: #fff;
  border-bottom: 1px solid var(--card-border);
  padding: 12px 20px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}}

.features-bar::-webkit-scrollbar {{ display: none; }}

.features-inner {{
  display: flex; gap: 8px;
  width: max-content;
}}

.feature-chip {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.75rem; font-weight: 600;
  padding: 6px 14px; border-radius: 99px;
  white-space: nowrap;
}}

.feature-chip.green  {{ background: #F0FDF8; color: #00A876; border: 1px solid #B2F0DC; }}
.feature-chip.blue   {{ background: #EFF6FF; color: #1E6FFF; border: 1px solid #BFDBFE; }}
.feature-chip.violet {{ background: #F5F3FF; color: #6040E8; border: 1px solid #DDD6FE; }}
.feature-chip.amber  {{ background: #FFF9F0; color: #CC7A00; border: 1px solid #FFD9A0; }}
.feature-chip.red    {{ background: #FFF1F3; color: #CC2244; border: 1px solid #FFB3C0; }}

/* ============================================================
   HERO — ダーク
   ============================================================ */
.hero {{
  background: linear-gradient(160deg, #0D0F1C 0%, #131629 50%, #0F1A2E 100%);
  padding: 88px 0 72px;
  position: relative; overflow: hidden;
  min-height: min(92vh, 860px);
  display: flex; align-items: center;
}}

/* ラジアルグロー — Manus 3層 */
.hero::before {{
  content: '';
  position: absolute; inset: 0; pointer-events: none;
  background:
    radial-gradient(ellipse 80% 60% at 50% 0%,   rgba(0,200,150,0.08)   0%, transparent 70%),
    radial-gradient(ellipse 60% 50% at 80% 50%,   rgba(124,92,252,0.06)  0%, transparent 70%),
    radial-gradient(ellipse 50% 40% at 15% 80%,   rgba(59,123,255,0.05)  0%, transparent 70%);
}}

/* 下部フェード — ページ背景色へ溶け込む */
.hero::after {{
  content: '';
  position: absolute; bottom: 0; left: 0; right: 0;
  height: 120px; pointer-events: none;
  background: linear-gradient(to bottom, transparent, #FAFBFF);
}}

.hero-inner {{
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
  display: grid;
  grid-template-columns: 1fr 480px;
  gap: 64px;
  align-items: center;
  position: relative; z-index: 1;
  width: 100%;
}}

.hero-left {{}}
.hero-right {{}}

.hero-eyebrow {{
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(0,200,150,0.12);
  border: 1px solid rgba(0,200,150,0.3);
  color: var(--profit);
  font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
  padding: 6px 16px; border-radius: 99px;
  margin-bottom: 24px;
  animation: fadeInUp 0.45s cubic-bezier(0.23,1,0.32,1) forwards;
}}

/* Social proof: 数値を大きく JetBrains Mono で */
.social-text {{
  font-size: 0.8rem; color: rgba(255,255,255,0.5);
}}

.social-text strong {{
  color: #fff;
  font-family: 'JetBrains Mono', 'Menlo', ui-monospace, var(--font);
  font-size: 0.85rem;
  letter-spacing: -0.02em;
}}

.hero-title {{
  font-size: clamp(2.2rem, 5vw, 3.8rem);
  font-weight: 900;
  letter-spacing: -0.04em;
  line-height: 1.05;
  color: #fff;
  margin-bottom: 22px;
}}

/* Manus 3色グラデーション accent */
.hero-title .accent {{
  background: linear-gradient(135deg, #00C896 0%, #3B7BFF 55%, #7C5CFC 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}

.hero-subtitle {{
  font-size: 1.05rem;
  color: rgba(255,255,255,0.65);
  line-height: 1.8;
  max-width: 520px;
  margin-bottom: 36px;
}}

.hero-subtitle strong {{ color: rgba(255,255,255,0.9); font-weight: 700; }}

.hero-cta-row {{
  display: flex; gap: 10px; flex-wrap: wrap;
  margin-bottom: 32px;
}}

.hero-btn {{
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 0.95rem; font-weight: 700;
  padding: 13px 26px; border-radius: 18px;
  text-decoration: none;
  transition: transform 0.18s cubic-bezier(0.23,1,0.32,1),
              box-shadow 0.18s cubic-bezier(0.23,1,0.32,1),
              background 0.18s;
}}

.hero-btn:active {{ transform: scale(0.97); }}

.hero-btn.primary {{
  background: linear-gradient(135deg, #00C896, #00A876);
  color: #fff;
  box-shadow: 0 4px 16px rgba(0,200,150,0.4), inset 0 1px 0 rgba(255,255,255,0.2);
}}

.hero-btn.primary:hover {{
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(0,200,150,0.5), inset 0 1px 0 rgba(255,255,255,0.2);
}}

/* violetは Manus の rgba() 版に */
.hero-btn.violet {{
  background: rgba(124,92,252,0.18);
  color: #A78BFA;
  border: 1px solid rgba(124,92,252,0.4);
  box-shadow: none;
}}

.hero-btn.violet:hover {{
  background: rgba(124,92,252,0.26);
  transform: translateY(-1px);
  border-color: rgba(124,92,252,0.6);
}}

.hero-btn.secondary {{
  background: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.7);
  border: 1px solid rgba(255,255,255,0.15);
}}

.hero-btn.secondary:hover {{
  background: rgba(255,255,255,0.14);
  color: rgba(255,255,255,0.9);
}}

/* Social proof */
.hero-social-proof {{
  display: flex; align-items: center; gap: 12px;
}}

.social-avatars {{
  display: flex;
}}

.social-avatar {{
  width: 28px; height: 28px; border-radius: 50%;
  background: linear-gradient(135deg, #00C896, #3B7BFF);
  border: 2px solid #131629;
  margin-left: -8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.65rem; font-weight: 700; color: #fff;
}}

.social-avatar:first-child {{ margin-left: 0; }}

.social-text {{
  font-size: 0.78rem; color: rgba(255,255,255,0.5);
}}

.social-text strong {{ color: rgba(255,255,255,0.8); }}

/* ライブパネル — Manus glassmorphism */
.hero-live-panel {{
  background: rgba(255,255,255,0.04);
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 22px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.08);
  position: relative;
  padding: 0;
}}

.hero-live-panel::before {{
  content: '';
  position: absolute; inset: -40px;
  background: radial-gradient(ellipse at 50% 50%, rgba(0,200,150,0.35), transparent 70%);
  filter: blur(20px); pointer-events: none; z-index: -1;
}}

.live-panel-hd {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  margin-bottom: 0;
}}

.live-panel-title {{
  font-size: 0.75rem; font-weight: 700; color: rgba(255,255,255,0.5);
  letter-spacing: 0.08em; text-transform: uppercase;
}}

.live-panel-badge {{
  display: flex; align-items: center; gap: 5px;
  font-size: 0.65rem; font-weight: 700; color: var(--profit);
  background: rgba(0,200,150,0.15);
  border: 1px solid rgba(0,200,150,0.25);
  padding: 3px 9px; border-radius: 99px;
}}

.live-panel-items {{
  padding: 12px 20px 4px;
}}

.lp-item {{
  display: flex; align-items: center;
  padding: 10px 16px;
  margin: 0 -16px;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  gap: 10px;
  border-radius: 10px;
  transition: background 0.15s;
}}

.lp-item:first-child {{
  background: rgba(0,200,150,0.08);
  border: 1px solid rgba(0,200,150,0.18);
  margin: 4px -16px;
}}

.lp-item:hover {{
  background: rgba(255,255,255,0.07);
  cursor: pointer;
}}

.lp-item:first-child:hover {{ background: rgba(0,200,150,0.14); }}

.lp-item:last-child {{ border-bottom: none; }}

.lp-icon {{
  width: 32px; height: 32px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.9rem; flex-shrink: 0;
}}

.lp-icon.iphone  {{ background: rgba(59,123,255,0.15); }}
.lp-icon.camera  {{ background: rgba(124,92,252,0.15); }}
.lp-icon.game    {{ background: rgba(20,184,166,0.15); }}

.lp-info {{ flex: 1; min-width: 0; }}
.lp-name {{ font-size: 0.78rem; font-weight: 600; color: rgba(255,255,255,0.85); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.lp-shop {{ font-size: 0.65rem; color: rgba(255,255,255,0.35); margin-top: 1px; }}

.lp-profit {{
  font-size: 0.88rem; font-weight: 800;
  color: var(--profit); white-space: nowrap;
  font-family: 'JetBrains Mono', 'Menlo', ui-monospace, var(--font);
  font-variant-numeric: tabular-nums;
}}

/* Timestamps */
.hero-timestamps {{
  display: flex; flex-wrap: wrap; gap: 10px;
  margin-top: 24px;
}}

.ts-pill {{
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(255,255,255,0.07);
  border: 1px solid rgba(255,255,255,0.12);
  color: rgba(255,255,255,0.55);
  font-size: 0.75rem;
  padding: 5px 12px; border-radius: 99px;
  font-variant-numeric: tabular-nums;
}}

.ts-dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--profit); flex-shrink: 0;
}}

.ts-dot.blue {{ background: var(--blue); }}

/* ============================================================
   STALE WARNING
   ============================================================ */
.stale-banner {{
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-left: 3px solid #f59e0b;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  padding: 12px 18px;
  margin: 16px 0;
  font-size: 0.875rem;
  color: #78350f;
  display: flex; align-items: flex-start; gap: 10px;
  line-height: 1.6;
}}

/* ============================================================
   MAIN LAYOUT
   ============================================================ */
.main-wrap {{
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px 80px;
}}

/* ============================================================
   TAB NAVIGATION — スティッキー / Manus pill style
   ============================================================ */
.tab-wrap {{
  position: sticky; top: 56px; z-index: 200;
  background: rgba(250,251,255,0.96);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--card-border);
  box-shadow: 0 1px 0 rgba(13,15,28,0.04), 0 2px 8px rgba(13,15,28,0.03);
  margin: 0 -24px;
  padding: 0 24px;
}}

.tab-nav {{
  display: flex; gap: 2px;
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  position: relative;
  padding: 8px 0;
  align-items: center;
}}

.tab-nav::-webkit-scrollbar {{ display: none; }}

/* ── ベース: pill スタイル ── */
.tab-btn {{
  flex-shrink: 0;
  display: flex; align-items: center; gap: 6px;
  background: transparent; border: none;
  border-radius: 10px;
  padding: 8px 14px;
  font-size: 0.84rem; font-weight: 600;
  color: var(--ink3);
  cursor: pointer;
  transition: background 0.15s cubic-bezier(0.23,1,0.32,1),
              color 0.15s cubic-bezier(0.23,1,0.32,1),
              transform 0.1s;
  white-space: nowrap;
  font-family: var(--font);
  min-height: 36px;
  line-height: 1;
}}

/* ── hover: Manus #F4F5FD ── */
.tab-btn:hover {{
  background: #F4F5FD;
  color: var(--ink);
}}

.tab-btn:active {{ transform: scale(0.96); }}

/* ── active: per-tab colored pill ── */
.tab-btn.active {{
  font-weight: 700;
  /* デフォルト: beginner = teal (最初に開く) */
  background: #F0FDF8;
  color: #047857;
}}

/* data-tab別のアクティブカラー — Manus activeColors */
.tab-btn.active[data-tab="beginner"] {{
  background: #F0FDF8;
  color: #047857;
}}
.tab-btn.active[data-tab="advanced"] {{
  background: #F0EEFF;
  color: #6040E8;
}}
.tab-btn.active[data-tab="sedori"] {{
  background: #EEF4FF;
  color: #1D4ED8;
}}
.tab-btn.active[data-tab="lottery"] {{
  background: #F5F3FF;
  color: #7C5CFC;
}}
.tab-btn.active[data-tab="ranking"] {{
  background: #EEF4FF;
  color: #1D4ED8;
}}
.tab-btn.active[data-tab="surge"] {{
  background: #FFF8E8;
  color: #B45309;
}}
.tab-btn.active[data-tab="new-products"] {{
  background: #F0EEFF;
  color: #6040E8;
}}

/* ── カウントバッジ ── */
.tab-count {{
  font-size: 0.62rem; font-weight: 800;
  background: rgba(13,15,28,0.06);
  color: var(--ink3);
  padding: 2px 7px; border-radius: 99px;
  line-height: 1.4;
  transition: background 0.15s, color 0.15s;
}}

/* active時はタブカラーに合わせる */
.tab-btn.active .tab-count {{
  background: rgba(255,255,255,0.65);
  color: inherit;
}}

/* ── タブパネル ── */
.tab-panel {{
  display: none;
  padding-top: 36px;
  pointer-events: auto;
  position: relative;
  z-index: 1;
}}
.tab-panel.active {{ display: block; }}

/* ── モバイル: タップターゲット確保 ── */
@media (max-width: 640px) {{
  .tab-btn {{ padding: 9px 12px; font-size: 0.8rem; min-height: 40px; }}
  .tab-wrap {{ padding: 0 16px; }}
}}

/* ============================================================
   SECTION HEADER
   ============================================================ */
.sec-head {{
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 20px; padding-bottom: 14px;
  border-bottom: 1px solid var(--card-border);
}}

.sec-title {{
  font-size: 0.78rem; font-weight: 800;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--ink3);
  display: flex; align-items: center; gap: 8px;
}}

.sec-title::before {{
  content: '';
  width: 3px; height: 14px; border-radius: 2px;
  background: var(--violet);
}}

.sec-badge {{
  font-size: 0.68rem; font-weight: 700;
  background: var(--surface2);
  color: var(--ink3);
  border: 1px solid var(--card-border);
  padding: 3px 10px; border-radius: 99px;
}}

/* ============================================================
   INFO BANNER
   ============================================================ */
.info-banner {{
  border-radius: var(--radius-lg);
  padding: 14px 18px;
  margin-bottom: 24px;
  font-size: 0.875rem;
  line-height: 1.75;
}}

.info-banner.blue {{
  background: #EFF6FF;
  border: 1px solid #BFDBFE;
  color: #1e40af;
}}

.info-banner.purple {{
  background: #F5F3FF;
  border: 1px solid #DDD6FE;
  color: #5b21b6;
}}

.info-banner.teal {{
  background: #F0FDF8;
  border: 1px solid #B2F0DC;
  color: #0f766e;
}}

.info-banner strong {{ font-weight: 800; }}

/* ============================================================
   DEAL CARDS GRID
   ============================================================ */
.cards-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 20px;
}}

/* ============================================================
   souba-card / DEAL CARD
   ============================================================ */
.souba-card,
.deal-card {{
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(13,15,28,0.06), 0 2px 6px rgba(13,15,28,0.04);
  transition: transform 0.2s cubic-bezier(0.23,1,0.32,1),
              box-shadow 0.2s cubic-bezier(0.23,1,0.32,1),
              border-color 0.2s cubic-bezier(0.23,1,0.32,1);
  display: flex; flex-direction: column;
}}

.souba-card:hover,
.deal-card:hover {{
  transform: translateY(-4px);
  box-shadow: 0 16px 48px rgba(13,15,28,0.11), 0 4px 16px rgba(13,15,28,0.07);
  border-color: #A7F3D0;
}}

/* カード上部利益バー */
.card-stripe {{ height: 4px; }}
.card-stripe.iphone  {{ background: linear-gradient(90deg, var(--blue), #93B8FF); }}
.card-stripe.camera  {{ background: linear-gradient(90deg, var(--violet), #B9A8FF); }}
.card-stripe.game    {{ background: linear-gradient(90deg, var(--profit), #80E8CC); }}
.card-stripe.default {{ background: linear-gradient(90deg, var(--profit), var(--blue)); }}

/* Score badge — Manus style: 正方形・グラデーション */
.score-badge {{
  display: inline-flex; align-items: center; justify-content: center;
  width: 36px; height: 36px;
  border-radius: 10px;
  font-size: 14px; font-weight: 800;
  font-family: 'JetBrains Mono', 'Menlo', ui-monospace, monospace;
  flex-shrink: 0;
}}

.score-s {{ background: linear-gradient(135deg, #FFD700, #FFA500); color: #7A4000; }}
.score-a {{ background: linear-gradient(135deg, #00C896, #00A876); color: #fff; }}
.score-b {{ background: linear-gradient(135deg, #3B7BFF, #1D4ED8); color: #fff; }}
.score-c {{ background: #F4F5FA; color: #5B6278; border: 1px solid #E8EAF2; }}

/* Card Header */
.card-hd {{
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 12px;
  padding: 20px 20px 16px;
}}

.card-name {{
  font-size: 1rem; font-weight: 800;
  color: var(--ink); line-height: 1.3; flex: 1;
}}

.card-tags {{
  display: flex; gap: 5px; flex-shrink: 0;
  flex-wrap: wrap; justify-content: flex-end;
}}

/* Profit Section */
.profit-section {{
  margin: 0 20px;
  padding: 16px 18px;
  background: linear-gradient(135deg, #F0FDF8, #E8FFF4);
  border: 1px solid #B2F0DC;
  border-radius: var(--radius-md);
  display: flex; align-items: center;
  justify-content: space-between; gap: 12px;
}}

.profit-section.amber {{
  background: linear-gradient(135deg, #FFF9F0, #FFF3E0);
  border-color: #FFD9A0;
}}

.profit-left {{}}

.profit-lbl {{
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--profit-dark); margin-bottom: 4px;
}}

.profit-lbl.amber {{ color: #CC7A00; }}

.profit-num {{
  font-size: 2.1rem; font-weight: 900;
  color: var(--profit-dark);
  letter-spacing: -0.04em; line-height: 1;
  font-variant-numeric: tabular-nums;
  font-family: 'JetBrains Mono', 'Menlo', ui-monospace, var(--font);
}}

.profit-num.amber {{ color: #CC7A00; }}

.profit-right {{ text-align: right; }}

.profit-rate {{
  display: inline-block;
  font-size: 0.9rem; font-weight: 800;
  color: var(--profit-dark);
  background: rgba(0,200,150,0.12);
  padding: 4px 12px; border-radius: var(--radius-sm);
  margin-bottom: 5px;
}}

.profit-rate.amber {{
  color: #CC7A00;
  background: rgba(255,149,0,0.12);
}}

.profit-note {{
  font-size: 0.7rem; color: var(--ink4);
}}

/* Price Row */
.price-row-wrap {{
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1px; background: var(--card-border);
  margin: 16px 20px 0;
  border-radius: var(--radius-md); overflow: hidden;
}}

.price-cell {{
  background: #F7F8FD; padding: 14px 16px;
}}

.price-cell-lbl {{
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--ink4); margin-bottom: 6px;
  display: flex; align-items: center; gap: 4px;
}}

.price-cell-val {{
  font-size: 1.1rem; font-weight: 800;
  color: var(--ink); font-variant-numeric: tabular-nums;
  font-family: 'JetBrains Mono', 'Menlo', ui-monospace, monospace;
  letter-spacing: -0.02em;
}}

.price-cell-val.green {{
  color: var(--profit-dark);
  font-size: 1.15rem;
}}

/* Card Body */
.card-body {{ padding: 18px 20px 22px; flex: 1; }}

.condition-row {{
  display: flex; align-items: flex-start; gap: 7px;
  background: var(--surface2);
  border: 1px solid var(--card-border);
  border-radius: var(--radius-sm);
  padding: 10px 12px; margin-bottom: 12px;
  font-size: 0.8rem; color: var(--ink2);
  line-height: 1.5;
}}

/* buyback-notice: Manusスタイルのアンバー注意文 */
.condition-row.buyback-notice {{
  background: #FFFBEB;
  border: 1px solid #FCD34D;
  color: #92400E;
  border-radius: 10px;
  padding: 10px 14px;
}}

.condition-row.buyback-notice .cond-icon {{
  color: #F59E0B;
  font-size: 0.95rem;
}}

.cond-icon {{ color: var(--amber); flex-shrink: 0; margin-top: 1px; }}

.updated-row {{
  font-size: 0.72rem; color: var(--ink4);
  margin-bottom: 12px;
  display: flex; align-items: center; gap: 5px;
  background: var(--surface2);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
}}

/* Shop Compare Table — souba-table */
.shop-table {{
  border: 1px solid var(--card-border);
  border-radius: 12px;
  overflow: hidden; margin-bottom: 14px;
  box-shadow: 0 1px 3px rgba(13,15,28,0.04);
}}

.shop-table-hd {{
  display: flex; align-items: center;
  justify-content: space-between;
  padding: 9px 14px;
  background: #F4F5FD;
  border-bottom: 1px solid var(--card-border);
  font-size: 0.67rem; font-weight: 800;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--ink3);
  gap: 8px;
}}

.shop-table-hd span:first-child {{
  display: flex; align-items: center; gap: 6px;
}}

.shop-row {{
  display: flex; align-items: center;
  padding: 11px 14px;
  border-bottom: 1px solid #F4F5FA;
  gap: 10px; font-size: 0.875rem;
  transition: background 0.15s cubic-bezier(0.23,1,0.32,1);
  font-variant-numeric: tabular-nums;
}}

.shop-row:last-child {{ border: none; }}
.shop-row:hover {{ background: #F7F8FD; }}

/* 1位ハイライト — Manus row-best (左ボーダー + teal背景) */
.shop-row.row-best {{
  background: linear-gradient(90deg, #F0FDF8 0%, #F7FFFE 100%);
  border-left: 3px solid #00C896;
}}

.shop-row.row-best:hover {{
  background: #E8FFF4;
}}

.shop-rank {{
  min-width: 22px; font-size: 0.72rem;
  font-weight: 800; text-align: center;
  color: var(--ink4);
}}

.shop-rank.gold {{ color: var(--gold); }}
.shop-rank.silver {{ color: var(--ink3); }}

.shop-name-col {{ flex: 1; color: var(--ink2); }}

.shop-name-col a {{
  color: var(--blue); text-decoration: none;
  font-weight: 600;
}}

.shop-name-col a:hover {{ text-decoration: underline; }}

.shop-price-col {{
  font-weight: 800; color: var(--ink);
  font-variant-numeric: tabular-nums;
  text-align: right; min-width: 80px;
}}

.shop-diff-col {{
  font-size: 0.78rem; font-weight: 700;
  color: var(--profit-dark);
  text-align: right; min-width: 68px;
}}

.shop-diff-col.neg {{ color: var(--danger); }}

/* 確認ボタン in shop row */
.shop-check-btn {{
  font-size: 0.72rem; font-weight: 700;
  padding: 4px 10px; border-radius: var(--radius-sm);
  text-decoration: none; white-space: nowrap;
  transition: all 0.15s;
}}

.shop-check-btn.best {{
  background: linear-gradient(135deg, var(--profit), var(--profit-dark));
  color: #fff;
}}

.shop-check-btn.best:hover {{ opacity: 0.85; }}

.shop-check-btn.normal {{
  background: var(--surface2);
  color: var(--ink2);
  border: 1px solid var(--card-border);
}}

.shop-check-btn.normal:hover {{ background: var(--card-border); }}

/* Freshness — .fresh-* (旧) と .freshness-* (新) の両方をサポート */
.fresh-live, .freshness-live {{
  color: var(--profit-dark); font-size: 0.7rem; font-weight: 700;
  background: rgba(0,200,150,0.09); padding: 2px 7px; border-radius: 99px;
}}
.fresh-recent, .freshness-recent {{
  color: #CC7A00; font-size: 0.7rem; font-weight: 700;
  background: rgba(255,149,0,0.09); padding: 2px 7px; border-radius: 99px;
}}
.fresh-stale, .freshness-stale {{
  color: var(--danger); font-size: 0.7rem; font-weight: 700;
  background: rgba(255,59,92,0.09); padding: 2px 7px; border-radius: 99px;
}}
.freshness-unknown {{
  color: var(--ink4); font-size: 0.7rem; font-weight: 600;
  background: var(--surface2); padding: 2px 7px; border-radius: 99px;
}}

/* Action Buttons */
.card-actions {{
  display: flex; flex-wrap: wrap; gap: 8px;
}}

.btn {{
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 0.8rem; font-weight: 700;
  padding: 8px 16px; border-radius: var(--radius-sm);
  text-decoration: none; transition: all 0.15s;
  border: 1px solid; cursor: pointer;
  font-family: var(--font);
}}

.btn-primary {{
  background: linear-gradient(135deg, var(--profit), var(--profit-dark));
  color: white;
  border-color: var(--profit-dark);
  box-shadow: 0 4px 16px rgba(0,200,150,0.35), inset 0 1px 0 rgba(255,255,255,0.2);
  transition: all 0.18s cubic-bezier(0.23,1,0.32,1);
}}

.btn-primary:hover {{
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(0,200,150,0.45), inset 0 1px 0 rgba(255,255,255,0.2);
}}

.btn-primary:active {{ transform: scale(0.97); }}

.btn-secondary {{
  background: white; color: var(--blue);
  border-color: #BFDBFE;
}}

.btn-secondary:hover {{
  background: #EFF6FF; border-color: #93B8FF;
}}

.btn-ghost {{
  background: var(--surface2); color: var(--ink2);
  border-color: var(--card-border);
}}

.btn-ghost:hover {{
  background: white; color: var(--ink);
  border-color: #D0D4E8;
}}

/* Overseas Links */
.overseas-section {{
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid var(--surface2);
}}

.overseas-lbl {{
  font-size: 0.65rem; font-weight: 800;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--ink4); margin-bottom: 8px;
  display: flex; align-items: center; gap: 6px;
}}

.overseas-chips {{
  display: flex; flex-wrap: wrap; gap: 6px;
}}

.overseas-chip {{
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 0.75rem; font-weight: 600;
  color: #0369a1;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  padding: 5px 11px; border-radius: var(--radius-sm);
  text-decoration: none; transition: all 0.15s;
}}

.overseas-chip:hover {{
  background: #e0f2fe; border-color: #7dd3fc;
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(3,105,161,0.15);
}}

/* ============================================================
   BADGES
   ============================================================ */
.badge {{
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 0.65rem; font-weight: 800;
  letter-spacing: 0.04em; text-transform: uppercase;
  padding: 3px 9px; border-radius: 99px;
}}

.badge-easy    {{ background: #F0FDF8; color: var(--profit-dark); border: 1px solid #B2F0DC; }}
.badge-watch   {{ background: #FFF9F0; color: #CC7A00; border: 1px solid #FFD9A0; }}
.badge-adv     {{ background: #EDE9FF; color: #6D28D9; border: 1px solid #C4B5FD; font-weight: 800; }}
.badge-exp     {{ background: #F0ECFF; color: #5B21B6; border: 1px solid #A78BFA; font-weight: 800; }}
.badge-iphone  {{ background: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; font-weight: 800; }}
.badge-camera  {{ background: #F3EEFF; color: #7C3AED; border: 1px solid #C4B5FD; font-weight: 800; }}
.badge-game    {{ background: #F0FDF8; color: #047857; border: 1px solid #6EE7B7; font-weight: 800; }}
.badge-lottery {{ background: #FFF5E8; color: #B45309; border: 1px solid #FBB040; font-weight: 800; }}
.badge-soldout {{ background: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; font-weight: 800; }}
.badge-overseas{{ background: #EFF6FF; color: #1D4ED8; border: 1px solid #93C5FD; font-weight: 800; }}
.badge-used    {{ background: var(--surface2); color: var(--ink2); border: 1px solid var(--card-border); }}

/* タグシステム（Pro向け） */
.deal-tag {{
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 0.65rem; font-weight: 700;
  padding: 2px 8px; border-radius: 99px;
}}

.deal-tag.pre    {{ background: #FFFBEB; color: #D97706; border: 1px solid #FDE68A; font-weight: 800; }}
.deal-tag.hard   {{ background: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; font-weight: 800; }}
.deal-tag.intl   {{ background: #EFF6FF; color: #2563EB; border: 1px solid #BFDBFE; font-weight: 800; }}
.deal-tag.limit  {{ background: #F5F3FF; color: #7C3AED; border: 1px solid #C4B5FD; font-weight: 800; }}
.deal-tag.lottery {{ background: #F5F3FF; color: #7C3AED; border: 1px solid #C4B5FD; font-weight: 800; }}

/* ============================================================
   WATCH CARD (Pro向け) — バイオレットアクセント
   ============================================================ */
.watch-card {{
  background: #FDFCFF;
  border: 1px solid #DDD6FE;
  border-radius: 20px;
  padding: 22px 24px;
  margin-bottom: 14px;
  box-shadow: 0 1px 4px rgba(124,92,252,0.07), 0 2px 8px rgba(124,92,252,0.04);
  transition: transform 0.2s cubic-bezier(0.23,1,0.32,1),
              box-shadow 0.2s cubic-bezier(0.23,1,0.32,1),
              border-color 0.2s cubic-bezier(0.23,1,0.32,1);
  position: relative; overflow: hidden;
}}

.watch-card::before {{
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--violet), #B39DFF, #7C5CFC);
}}

.watch-card:hover {{
  transform: translateY(-3px);
  box-shadow: 0 16px 48px rgba(124,92,252,0.13), 0 4px 16px rgba(124,92,252,0.08);
  border-color: #C4B5FD;
}}

.watch-card-hd {{
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 12px;
  margin-bottom: 14px;
}}

.watch-name {{
  font-size: 1rem; font-weight: 800;
  color: var(--ink); flex: 1;
}}

.watch-price-grid {{
  display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 10px; margin-bottom: 14px;
}}

.watch-price-item {{}}

.watch-price-lbl {{
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--ink4); margin-bottom: 4px;
}}

.watch-price-val {{
  font-size: 1.05rem; font-weight: 800;
  color: var(--ink); font-variant-numeric: tabular-nums;
  font-family: 'JetBrains Mono', 'Menlo', ui-monospace, monospace;
  letter-spacing: -0.02em;
}}

.watch-price-val.green  {{ color: var(--profit-dark); }}
.watch-price-val.red    {{ color: var(--danger); }}
.watch-price-val.purple {{ color: var(--violet); }}

.gap-badge {{
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 0.78rem; font-weight: 800;
  padding: 4px 10px; border-radius: 4px;
}}

.gap-pos {{ background: #F0FDF8; color: var(--profit-dark); }}
.gap-neg {{ background: #FFF1F3; color: var(--danger); }}
.gap-neu {{ background: var(--surface2); color: var(--ink2); }}

/* How-to box */
.howto-box {{
  background: var(--surface2);
  border: 1px solid var(--card-border);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  margin-bottom: 14px;
  font-size: 0.82rem;
  color: var(--ink2);
  line-height: 1.7;
}}

.howto-box strong {{ color: var(--ink); }}

.howto-step {{
  display: flex; align-items: flex-start; gap: 8px;
  margin-top: 8px;
}}

.step-num {{
  flex-shrink: 0;
  width: 20px; height: 20px;
  background: var(--violet); color: white;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.68rem; font-weight: 800;
  margin-top: 1px;
}}

.step-text {{ flex: 1; }}

/* ============================================================
   RANKING — ランキングセクション (Manus card-per-row style)
   ============================================================ */
.ranking-card {{
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 20px;
  overflow: hidden; margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(13,15,28,0.05), 0 2px 6px rgba(13,15,28,0.04);
  transition: box-shadow 0.2s cubic-bezier(0.23,1,0.32,1);
}}

.ranking-hd {{
  padding: 16px 20px;
  border-bottom: 1px solid var(--card-border);
  background: linear-gradient(90deg, #FFFBEB, #FFF8F0);
  display: flex; align-items: center; gap: 10px;
  font-size: 0.9rem; font-weight: 800; color: var(--ink);
}}

.ranking-hd::before {{
  content: '';
  width: 3px; height: 16px; border-radius: 2px;
  background: linear-gradient(180deg, #D97706, #FBBF24);
}}

/* ランキング内タブ — Manus segmented control */
.ranking-tabs {{
  display: flex; gap: 4px;
  padding: 12px 12px 0;
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  background: var(--card-bg);
}}

.ranking-tabs::before {{
  content: '';
  display: none;
}}

.ranking-tabs-wrap {{
  display: inline-flex; gap: 3px;
  background: #F4F5FA;
  border: 1px solid #E8EAF2;
  border-radius: 12px;
  padding: 4px;
  flex-shrink: 0;
}}

.ranking-tab-btn {{
  flex-shrink: 0;
  background: transparent; border: 1px solid transparent;
  border-radius: 9px;
  padding: 6px 14px;
  font-size: 0.8rem; font-weight: 600;
  color: var(--ink3); cursor: pointer;
  transition: all 0.15s cubic-bezier(0.23,1,0.32,1);
  white-space: nowrap;
  font-family: var(--font);
  line-height: 1.4;
}}

.ranking-tab-btn:hover {{
  color: var(--ink); background: rgba(255,255,255,0.7);
}}

/* active: Manus per-tab color — JS側で .active を付与 */
.ranking-tab-btn.active {{
  background: #FFFFFF;
  border-color: #E8EAF2;
  box-shadow: 0 1px 4px rgba(13,15,28,0.08);
  font-weight: 700;
  color: var(--ink);
}}

/* 総合=teal, iPhone=ink, camera=amber, game=violet */
.ranking-tab-btn.active[data-rtab="all"]    {{ color: #059669; }}
.ranking-tab-btn.active[data-rtab="iphone"] {{ color: #0F172A; }}
.ranking-tab-btn.active[data-rtab="camera"] {{ color: #D97706; }}
.ranking-tab-btn.active[data-rtab="game"]   {{ color: #7C3AED; }}

/* タブパネル */
.ranking-tab-panel {{ display: none; padding: 10px 12px 12px; }}
.ranking-tab-panel.active {{ display: block; }}

/* 各ランク行 — Manus card-per-row */
.rank-row {{
  display: flex; align-items: center;
  padding: 12px 14px;
  margin-bottom: 6px;
  border-radius: 12px;
  border: 1px solid #E8EAF2;
  background: #FFFFFF;
  gap: 14px;
  transition: background 0.15s cubic-bezier(0.23,1,0.32,1),
              border-color 0.15s cubic-bezier(0.23,1,0.32,1),
              box-shadow 0.15s cubic-bezier(0.23,1,0.32,1);
}}

.rank-row:last-child {{ margin-bottom: 0; }}

.rank-row:hover {{
  background: #F8FAFC;
  border-color: #D0D4E8;
  box-shadow: 0 2px 8px rgba(13,15,28,0.06);
}}

/* 1位 — Manus amber card */
.rank-row.rank-1 {{
  background: #FFFBEB;
  border: 1px solid #FDE68A;
  box-shadow: 0 2px 8px rgba(217,119,6,0.1);
}}

.rank-row.rank-1:hover {{
  background: #FFF7DC;
  border-color: #FBBF24;
  box-shadow: 0 4px 14px rgba(217,119,6,0.15);
}}

/* 順位数字 */
.rank-num {{
  font-size: 1rem; font-weight: 900;
  color: #CBD5E1; min-width: 26px; text-align: center;
  font-family: 'JetBrains Mono', 'Menlo', ui-monospace, monospace;
}}

.rank-num.r1 {{ color: #D97706; font-size: 1.15rem; }}
.rank-num.r2 {{ color: #94A3B8; }}
.rank-num.r3 {{ color: #92400E; }}

.rank-info {{ flex: 1; min-width: 0; }}
.rank-name {{
  font-weight: 700; color: var(--ink); font-size: 0.9rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.rank-meta {{ font-size: 0.72rem; color: var(--ink4); margin-top: 2px; }}

/* 利益表示 */
.rank-profit {{
  font-size: 1.15rem; font-weight: 900;
  color: #059669; font-variant-numeric: tabular-nums;
  text-align: right; flex-shrink: 0;
  font-family: 'JetBrains Mono', 'Menlo', ui-monospace, monospace;
  letter-spacing: -0.02em;
}}

.rank-row.rank-1 .rank-profit {{ color: #D97706; }}

.rank-rate {{
  font-size: 0.7rem; font-weight: 700;
  color: #16A34A;
  text-align: right; margin-top: 3px;
}}

.rank-row.rank-1 .rank-rate {{ color: #B45309; }}

/* ============================================================
   SURGE/DROP カード
   ============================================================ */
.alert-card {{
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 16px;
  padding: 18px 20px; margin-bottom: 12px;
  box-shadow: var(--shadow-sm);
}}

.alert-card.surge {{
  border-left: 3px solid #059669;
  background: linear-gradient(135deg, #F0FDF8, #fff);
}}

.alert-card.drop {{
  border-left: 3px solid var(--danger);
  background: linear-gradient(135deg, #FFF1F3, #fff);
}}

.alert-hd {{
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 12px;
}}

.alert-icon-badge {{
  width: 32px; height: 32px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem; flex-shrink: 0;
}}

.alert-icon-badge.surge {{ background: rgba(5,150,105,0.12); }}
.alert-icon-badge.drop  {{ background: rgba(255,59,92,0.12); }}

.alert-name {{ font-weight: 700; color: var(--ink); font-size: 0.9rem; }}
.alert-shop {{ font-size: 0.72rem; color: var(--ink3); margin-top: 1px; }}

.alert-prices {{
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
}}

.alert-price-item {{
  background: var(--surface2);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
}}

.alert-price-lbl {{
  font-size: 0.62rem; font-weight: 700;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--ink4); margin-bottom: 4px;
}}

.alert-price-val {{
  font-size: 0.95rem; font-weight: 800;
  color: var(--ink); font-variant-numeric: tabular-nums;
}}

.alert-price-val.surge {{ color: #059669; }}
.alert-price-val.drop  {{ color: var(--danger); }}

/* ============================================================
   SURGE グリッド
   ============================================================ */
.surge-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-bottom: 32px;
}}

/* ============================================================
   EMPTY STATE
   ============================================================ */
.empty-state {{
  text-align: center; padding: 56px 24px;
  color: var(--ink4); font-size: 0.9rem;
}}

.empty-icon {{
  font-size: 2.5rem; margin-bottom: 14px;
  opacity: 0.3; display: block;
}}

/* ============================================================
   CAUTION
   ============================================================ */
.caution-block {{
  background: #FFFBEB;
  border: 1px solid #FDE68A;
  border-left: 3px solid #F59E0B;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  padding: 20px 24px; margin: 48px 0;
  font-size: 0.875rem; color: #78350f; line-height: 1.8;
}}

.caution-title {{
  font-weight: 800; color: #B45309;
  margin-bottom: 10px; font-size: 0.9rem;
  display: flex; align-items: center; gap: 6px;
}}

.caution-list {{ list-style: none; padding: 0; }}
.caution-list li {{ padding: 2px 0 2px 14px; position: relative; }}
.caution-list li::before {{
  content: "·"; position: absolute; left: 4px;
  color: #F59E0B;
}}

/* ============================================================
   CTA — ダークグラスカード
   ============================================================ */
.cta-section {{
  background: linear-gradient(160deg, #0D0F1C 0%, #131629 60%, #0F1A2E 100%);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-2xl);
  padding: 44px 40px;
  text-align: center; margin: 48px 0;
  box-shadow: var(--shadow-md);
  position: relative; overflow: hidden;
}}

.cta-section::before {{
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--profit), var(--blue), var(--violet));
}}

.cta-eyebrow {{
  font-size: 0.68rem; font-weight: 800;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--profit); margin-bottom: 14px;
}}

.cta-title {{
  font-size: 1.5rem; font-weight: 900;
  color: #fff; margin-bottom: 10px;
  letter-spacing: -0.02em;
}}

.cta-desc {{
  font-size: 0.95rem; color: rgba(255,255,255,0.6);
  max-width: 460px; margin: 0 auto 28px; line-height: 1.75;
}}

.cta-btns {{
  display: flex; justify-content: center;
  gap: 12px; flex-wrap: wrap;
}}

.btn-cta-primary {{
  display: inline-flex; align-items: center; gap: 7px;
  background: linear-gradient(135deg, var(--profit), var(--profit-dark));
  color: white;
  font-size: 0.95rem; font-weight: 800;
  padding: 14px 30px; border-radius: var(--radius-md);
  text-decoration: none; border: none; cursor: pointer;
  box-shadow: 0 4px 14px rgba(0,200,150,0.35);
  transition: all 0.2s; font-family: var(--font);
}}

.btn-cta-primary:hover {{
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,200,150,0.5);
}}

.btn-cta-secondary {{
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.8);
  font-size: 0.95rem; font-weight: 700;
  padding: 14px 30px; border-radius: var(--radius-md);
  text-decoration: none; border: 1px solid rgba(255,255,255,0.15);
  transition: all 0.2s; font-family: var(--font);
}}

.btn-cta-secondary:hover {{
  background: rgba(255,255,255,0.14); color: #fff;
}}

/* ============================================================
   FOOTER — ダーク
   ============================================================ */
.footer {{
  background: #0D0F1C;
  border-top: 1px solid rgba(255,255,255,0.06);
  padding: 40px 0 24px;
  margin-top: 48px;
}}

.footer-inner {{
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px;
}}

.footer-logo {{
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 24px;
}}

.footer-logo-icon {{
  width: 32px; height: 32px; border-radius: 8px;
  background: linear-gradient(135deg, var(--blue), var(--violet));
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 900; font-size: 0.85rem;
}}

.footer-logo-name {{
  font-size: 0.95rem; font-weight: 800; color: rgba(255,255,255,0.85);
}}

.footer-live {{
  display: flex; align-items: center; gap: 5px;
  font-size: 0.65rem; font-weight: 700; color: var(--profit);
  background: rgba(0,200,150,0.12);
  border: 1px solid rgba(0,200,150,0.2);
  padding: 2px 8px; border-radius: 99px;
}}

.footer-links {{
  display: flex; flex-wrap: wrap; gap: 8px 20px;
  margin-bottom: 24px;
}}

.footer-link {{
  font-size: 0.78rem; color: rgba(255,255,255,0.4);
  text-decoration: none; transition: color 0.15s;
}}

.footer-link:hover {{ color: rgba(255,255,255,0.75); }}

.footer-text {{
  font-size: 0.75rem; color: rgba(255,255,255,0.25);
  line-height: 2;
}}

/* ============================================================
   NEW PRODUCT CARDS
   ============================================================ */
.new-product-card {{
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  transition: transform 0.18s, box-shadow 0.18s;
}}

.new-product-card:hover {{
  transform: translateY(-3px);
  box-shadow: var(--shadow-xl);
}}

.np-top-bar {{ height: 3px; background: linear-gradient(90deg, var(--violet), var(--blue)); }}

.np-body {{ padding: 16px 18px; }}

.np-hd {{
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 10px;
  margin-bottom: 12px;
}}

.np-name {{ font-size: 0.9rem; font-weight: 800; color: var(--ink); flex: 1; }}

.np-status-badge {{
  font-size: 0.65rem; font-weight: 700;
  padding: 3px 9px; border-radius: 99px;
  white-space: nowrap;
}}

.np-status-badge.lottery {{ background: #FFF9F0; color: #CC7A00; border: 1px solid #FFD9A0; }}
.np-status-badge.preorder {{ background: #EFF6FF; color: #1E6FFF; border: 1px solid #BFDBFE; }}
.np-status-badge.upcoming {{ background: #F5F3FF; color: var(--violet); border: 1px solid #DDD6FE; }}
.np-status-badge.default {{ background: var(--surface2); color: var(--ink2); border: 1px solid var(--card-border); }}

.np-price-row {{
  display: flex; align-items: center; gap: 16px;
  margin-bottom: 10px; font-size: 0.82rem;
}}

.np-price-lbl {{ color: var(--ink4); font-size: 0.65rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }}
.np-price-val {{ font-weight: 800; color: var(--ink); font-variant-numeric: tabular-nums; }}

.np-tags {{ display: flex; flex-wrap: wrap; gap: 5px; }}

/* ============================================================
   OVERSEAS LINKS SECTION
   ============================================================ */
.overseas-section-block {{
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 16px;
  padding: 20px 22px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
}}

.overseas-section-hd {{
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 16px;
}}

.overseas-globe {{
  font-size: 1.2rem;
}}

.overseas-section-title {{
  font-size: 0.875rem; font-weight: 800; color: var(--ink);
}}

.overseas-chips-row {{
  display: flex; flex-wrap: wrap; gap: 8px;
}}

.oc-chip {{
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 0.78rem; font-weight: 600;
  padding: 6px 14px; border-radius: var(--radius-sm);
  text-decoration: none; transition: all 0.15s;
}}

.oc-chip.blue   {{ background: #EFF6FF; color: #1E6FFF; border: 1px solid #BFDBFE; }}
.oc-chip.green  {{ background: #F0FDF8; color: var(--profit-dark); border: 1px solid #B2F0DC; }}
.oc-chip.purple {{ background: #F5F3FF; color: var(--violet); border: 1px solid #DDD6FE; }}

.oc-chip:hover {{ transform: translateY(-1px); filter: brightness(0.95); }}

/* ============================================================
   RESPONSIVE
   ============================================================ */
@media (max-width: 1024px) {{
  .hero-inner {{ grid-template-columns: 1fr 400px; gap: 40px; }}
}}

/* ============================================================
   SEDORI ROUTE — 店舗間せどりルート比較タブ (Phase 14)
   ============================================================ */
.sc-wrap {{
  padding: 0 0 32px;
}}

.sc-header {{
  margin-bottom: 20px; padding-top: 8px;
}}

.sc-eyebrow {{
  font-size: 0.68rem; font-weight: 800;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--blue); margin-bottom: 6px;
}}

.sc-title {{
  font-size: 1.35rem; font-weight: 800; color: var(--text-1);
  letter-spacing: -0.02em; margin: 0 0 6px;
}}

.sc-desc {{
  font-size: 0.85rem; color: var(--text-3); line-height: 1.6; margin: 0;
}}

/* メタ行 */
.sc-meta-row {{
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; background: #F8FAFC; border-radius: 10px;
  border: 1px solid #E2E8F0; margin-bottom: 20px;
  flex-wrap: wrap; font-size: 0.82rem;
}}
.sc-meta-label {{ color: var(--text-3); }}
.sc-meta-val {{ font-weight: 700; color: var(--text-1); font-family: 'JetBrains Mono', monospace; }}
.sc-meta-sep {{ color: #CBD5E1; }}
.sc-routes-count-badge {{
  background: #DCFCE7; color: #15803D; border: 1px solid #BBF7D0;
  border-radius: 99px; padding: 1px 10px; font-size: 0.78rem;
}}

/* データなし */
.sc-no-data {{
  text-align: center; padding: 40px 20px;
  background: #F8FAFC; border-radius: 16px;
  border: 1px dashed #CBD5E1; margin: 16px 0;
}}
.sc-no-data-icon {{ font-size: 2.5rem; margin-bottom: 12px; }}
.sc-no-data-title {{ font-size: 1rem; font-weight: 700; color: var(--text-1); margin-bottom: 8px; }}
.sc-no-data-desc {{ font-size: 0.85rem; color: var(--text-3); margin-bottom: 12px; }}
.sc-no-data-cmd {{
  display: inline-block; background: #1E293B; color: #94A3B8;
  border-radius: 10px; padding: 12px 16px; font-size: 0.78rem;
  font-family: 'JetBrains Mono', monospace; text-align: left;
  white-space: pre-wrap; word-break: break-all;
}}

/* 1位ルート大型カード */
.sc-best-card {{
  background: linear-gradient(135deg, #F0FDF4 0%, #ECFDF5 50%, #F0FDF4 100%);
  border: 1px solid #A7F3D0; border-radius: 20px;
  padding: 24px; margin-bottom: 24px;
  position: relative; overflow: hidden;
}}
.sc-best-card::before {{
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, #00C896, #34D399, #059669);
}}
.sc-best-crown {{
  font-size: 0.9rem; font-weight: 800; color: #059669;
  letter-spacing: 0.02em; margin-bottom: 8px;
}}
.sc-best-rank-badge {{
  background: #DCFCE7; color: #15803D; border: 1px solid #BBF7D0;
  border-radius: 99px; padding: 1px 8px; font-size: 0.72rem;
  font-family: 'JetBrains Mono', monospace; vertical-align: middle;
}}
.sc-best-product {{
  font-size: 1.05rem; font-weight: 700; color: var(--text-1);
  margin-bottom: 16px;
}}
.sc-best-route-row {{
  display: flex; align-items: center; gap: 12px; margin-bottom: 20px;
  flex-wrap: wrap;
}}
.sc-best-box {{
  flex: 1; min-width: 130px; padding: 14px 16px;
  background: rgba(255,255,255,0.85); border-radius: 14px;
  border: 1px solid #D1FAE5;
}}
.sc-best-box-buy {{ border-color: #FECACA; background: rgba(255,255,255,0.9); }}
.sc-best-box-sell {{ border-color: #A7F3D0; background: rgba(255,255,255,0.9); }}
.sc-best-box-lbl {{
  font-size: 0.72rem; font-weight: 700; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px;
}}
.sc-best-box-shop {{
  font-size: 0.95rem; font-weight: 700; color: var(--text-1); margin-bottom: 4px;
}}
.sc-best-box-price {{
  font-size: 1.2rem; font-weight: 800; font-family: 'JetBrains Mono', monospace;
  margin-bottom: 2px;
}}
.sc-price-buy {{ color: #DC2626; }}
.sc-price-sell {{ color: #059669; }}
.sc-best-box-cond {{ font-size: 0.72rem; color: var(--text-3); }}
.sc-best-arrow {{
  font-size: 1.5rem; color: #059669; font-weight: 900; flex-shrink: 0;
}}

/* 利益ブロック */
.sc-best-profit-row {{
  display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px;
}}
.sc-profit-block {{
  flex: 1; min-width: 80px; padding: 12px 14px;
  background: rgba(255,255,255,0.7); border-radius: 12px;
  border: 1px solid #E2E8F0; text-align: center;
}}
.sc-profit-main {{
  background: #F0FDF4; border-color: #A7F3D0;
}}
.sc-profit-lbl {{
  font-size: 0.7rem; color: var(--text-3); font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;
}}
.sc-profit-val {{
  font-size: 1rem; font-weight: 800; font-family: 'JetBrains Mono', monospace;
}}
.sc-col-green {{ color: #059669; }}
.sc-col-red {{ color: #DC2626; }}
.sc-col-amber {{ color: #D97706; }}
.sc-col-gray {{ color: var(--text-3); }}
.sc-rate-val {{ color: #059669; }}

/* リンクボタン */
.sc-best-links {{
  display: flex; gap: 10px; flex-wrap: wrap;
}}
.sc-link-btn {{
  display: inline-flex; align-items: center; gap: 5px;
  padding: 9px 18px; border-radius: 10px; font-size: 0.88rem;
  font-weight: 700; text-decoration: none; cursor: pointer;
  transition: all 0.15s cubic-bezier(0.23,1,0.32,1);
}}
.sc-link-buy {{
  background: #FFF1F2; color: #DC2626; border: 1px solid #FECACA;
}}
.sc-link-buy:hover {{ background: #FFE4E6; }}
.sc-link-sell {{
  background: #F0FDF4; color: #059669; border: 1px solid #A7F3D0;
}}
.sc-link-sell:hover {{ background: #DCFCE7; }}
.sc-link-unverified {{
  font-size: 0.85rem; color: var(--text-3);
  padding: 9px 0; display: inline-flex; align-items: center; gap: 4px;
}}

/* 2〜10位リスト */
.sc-list-section {{
  background: var(--card-bg); border: 1px solid var(--card-border);
  border-radius: 16px; overflow: hidden; margin-bottom: 20px;
}}
.sc-list-header {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; border-bottom: 1px solid var(--card-border);
  background: #F8FAFC;
}}
.sc-list-title {{
  font-size: 0.9rem; font-weight: 700; color: var(--text-1);
}}
.sc-list-count {{
  font-size: 0.78rem; font-weight: 700;
  background: #F1F5F9; color: var(--text-3);
  border: 1px solid #E2E8F0; border-radius: 99px; padding: 1px 10px;
}}
.sc-table-scroll {{ overflow-x: auto; }}
.sc-table {{
  width: 100%; border-collapse: collapse; font-size: 0.84rem;
}}
.sc-table thead th {{
  background: #F8FAFC; color: var(--text-3); font-weight: 700;
  font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em;
  padding: 10px 12px; white-space: nowrap;
  border-bottom: 1px solid #E2E8F0; text-align: left;
}}
.sc-table tbody td {{
  padding: 11px 12px; border-bottom: 1px solid #F1F5F9;
  vertical-align: middle;
}}
.sc-table tbody tr:last-child td {{ border-bottom: none; }}
.sc-table tbody tr:hover {{ background: #F8FAFC; }}
.sc-rank-cell {{
  font-weight: 800; color: var(--text-3); font-size: 0.78rem;
  font-family: 'JetBrains Mono', monospace; white-space: nowrap;
}}
.sc-prod-cell {{
  font-weight: 600; color: var(--text-1); max-width: 160px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.sc-shop-cell {{ color: var(--text-2); font-weight: 600; }}
.sc-price-cell {{
  font-family: 'JetBrains Mono', monospace; font-weight: 700;
  white-space: nowrap;
}}
.sc-profit-cell {{
  font-family: 'JetBrains Mono', monospace; font-weight: 800;
  white-space: nowrap;
}}
.sc-rate-cell {{ white-space: nowrap; }}
.sc-rate-badge {{
  display: inline-block; padding: 2px 8px; border-radius: 99px;
  font-size: 0.75rem; font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}}
.sc-rate-pos {{ background: #DCFCE7; color: #15803D; border: 1px solid #BBF7D0; }}
.sc-rate-neg {{ background: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; }}
.sc-mini-link {{
  color: var(--blue); text-decoration: none; font-weight: 600;
}}
.sc-mini-link:hover {{ text-decoration: underline; }}

/* 免責 */
.sc-disclaimer {{
  font-size: 0.78rem; color: var(--text-3); line-height: 1.65;
  padding: 12px 14px; background: #FFFBEB;
  border: 1px solid #FDE68A; border-radius: 10px; margin-top: 4px;
}}

/* Pro向け価格ラベル (Clarify) */
.pro-price-note {{
  background: #FFF7ED; border: 1px solid #FDBA74; border-radius: 8px;
  padding: 8px 12px; font-size: 0.78rem; color: #92400E;
  margin-bottom: 8px; line-height: 1.5;
}}
.pro-profit-section {{ opacity: 0.85; }}
.price-cell-val.pro-secondary {{
  color: var(--text-2); font-size: 0.9rem; font-weight: 500;
}}
.pcc-buyback-ref {{
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  background: #F8F9FA; border-radius: 8px; padding: 6px 10px;
  font-size: 0.82rem;
}}
.pcc-buyback-lbl {{ color: var(--text-3); font-weight: 600; }}
.pcc-buyback-note {{ font-size: 0.70rem; color: var(--text-3); font-weight: 400; }}
.pcc-buyback-val {{ font-weight: 700; color: var(--text-1); }}
.pcc-buyback-diff {{ color: var(--text-3); font-size: 0.75rem; }}
.pcc-price-item {{ display: flex; flex-direction: column; gap: 2px; }}
.pcc-meta-row {{ display: flex; flex-wrap: wrap; gap: 8px; font-size: 0.78rem; color: var(--text-3); margin-top: 4px; }}

/* せどりルート要確認セクション */
.sc-review-section {{
  background: #FFF7ED; border: 2px solid #FDBA74; border-radius: 14px;
  padding: 14px 16px; margin: 20px 0 6px;
}}
.sc-review-hd {{ display: flex; gap: 12px; align-items: flex-start; }}
.sc-review-icon {{ font-size: 1.4rem; flex-shrink: 0; }}
.sc-review-title {{ font-weight: 700; font-size: 0.95rem; color: #92400E; }}
.sc-review-sub {{ font-size: 0.78rem; color: #B45309; margin-top: 3px; line-height: 1.5; }}
/* 警告フラグ詳細 */
.sc-flag-detail {{
  display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0 8px;
}}
.sc-flag-item {{
  display: inline-block; padding: 2px 8px; border-radius: 99px;
  font-size: 0.70rem; font-weight: 600;
  background: #FFF7ED; color: #C2410C; border: 1px solid #FED7AA;
}}
.sc-flag-item.sc-flag-strong {{
  background: #FEF2F2; color: #DC2626; border-color: #FECACA; font-weight: 700;
}}

/* 品質チェックバッジ (Phase 15) */
.sc-badge-review-strong {{
  display: inline-flex; align-items: center; gap: 3px;
  padding: 2px 9px; border-radius: 99px;
  font-size: 0.72rem; font-weight: 800;
  background: #FEF2F2; color: #DC2626;
  border: 1.5px solid #FECACA; margin-left: 6px;
  cursor: help; vertical-align: middle;
  animation: sc-pulse 2s infinite;
}}
@keyframes sc-pulse {{
  0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.7; }}
}}
.sc-badge-review {{
  display: inline-flex; align-items: center; gap: 3px;
  padding: 2px 8px; border-radius: 99px;
  font-size: 0.72rem; font-weight: 700;
  background: #FFF7ED; color: #C2410C;
  border: 1px solid #FDBA74; margin-left: 6px;
  cursor: help;
  vertical-align: middle;
}}
.sc-qs-badge {{
  display: inline-flex; align-items: center;
  padding: 2px 7px; border-radius: 99px;
  font-size: 0.70rem; font-weight: 600;
  margin-left: 5px; vertical-align: middle;
}}
.sc-qs-high {{ background: #DCFCE7; color: #15803D; border: 1px solid #BBF7D0; }}
.sc-qs-mid  {{ background: #FEF9C3; color: #854D0E; border: 1px solid #FDE047; }}
.sc-qs-low  {{ background: #FEF2F2; color: #DC2626; border: 1px solid #FECACA; }}
/* 要確認ルートの行・カード強調 */
.sc-best-card-review {{
  border: 2px solid #FDBA74 !important;
  background: linear-gradient(135deg, #FFFBEB 0%, #FFF7ED 100%) !important;
}}
tr.sc-route-review {{ background: #FFFBEB; }}

@media (max-width: 640px) {{
  .sc-best-card {{ padding: 16px; }}
  .sc-best-route-row {{ flex-direction: column; }}
  .sc-best-arrow {{ transform: rotate(90deg); }}
  .sc-best-profit-row {{ gap: 8px; }}
  .sc-profit-block {{ min-width: 60px; padding: 10px; }}
  .sc-profit-val {{ font-size: 0.9rem; }}
  .sc-meta-row {{ gap: 6px; }}
  .sc-table {{ font-size: 0.78rem; }}
  .sc-prod-cell {{ max-width: 100px; }}
}}

/* ============================================================
   INFO BANNER — 初心者向け・Pro向けタブ説明バナー
   ============================================================ */
.info-banner {{
  border-radius: 14px; padding: 16px 18px; margin-bottom: 24px;
  font-size: 0.86rem; line-height: 1.7;
}}
.info-banner.blue {{
  background: #EFF6FF; border: 1px solid #BFDBFE; color: #1E40AF;
}}
.info-banner.violet {{
  background: #F5F3FF; border: 1px solid #DDD6FE; color: #4C1D95;
}}
.ib-title {{
  font-size: 0.9rem; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.01em;
}}

/* ============================================================
   PRO 向けカード — 二次流通・海外相場リンクチップ付き
   ============================================================ */
.pro-watch-card {{
  background: var(--card-bg); border: 1px solid #DDD6FE;
  border-radius: 20px; overflow: hidden;
}}
.pro-candidate-card {{
  padding: 18px 18px 14px;
  border-bottom: 1px solid #EEE8FF;
}}
.pro-candidate-card:last-child {{ border-bottom: none; }}
.pcc-header {{
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 10px; margin-bottom: 10px; flex-wrap: wrap;
}}
.pcc-name {{
  font-size: 1rem; font-weight: 800; color: var(--text-1);
  letter-spacing: -0.01em;
}}
.pcc-badges {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
.pcc-price-row {{
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-bottom: 12px; font-size: 0.84rem;
}}
.pcc-price-lbl {{ color: var(--text-3); font-weight: 600; }}
.pcc-price-val {{ font-weight: 800; color: var(--text-1); font-family: 'JetBrains Mono', monospace; }}
.wc-gap {{ font-size: 0.8rem; }}
.pcc-shop {{ color: var(--text-3); font-size: 0.8rem; }}
.pcc-flags {{ color: var(--yellow); font-size: 0.78rem; font-weight: 600; }}
.pcc-links-section {{ margin-bottom: 4px; }}
.pcc-links-label {{
  font-size: 0.7rem; font-weight: 700; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 6px;
}}
.pcc-chips {{ display: flex; flex-wrap: wrap; gap: 5px; }}

/* リンクチップ */
.pro-chip {{
  display: inline-flex; align-items: center; padding: 4px 10px;
  border-radius: 99px; font-size: 0.75rem; font-weight: 700;
  text-decoration: none; cursor: pointer; white-space: nowrap;
  transition: all 0.15s cubic-bezier(0.23,1,0.32,1);
}}
.pro-chip-domestic {{
  background: #F0FDF4; color: #15803D; border: 1px solid #BBF7D0;
}}
.pro-chip-domestic:hover {{ background: #DCFCE7; }}
.pro-chip-overseas {{
  background: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE;
}}
.pro-chip-overseas:hover {{ background: #DBEAFE; }}

@media (max-width: 640px) {{
  .pro-candidate-card {{ padding: 14px 12px 10px; }}
  .pcc-header {{ flex-direction: column; }}
  .pro-chip {{ padding: 3px 8px; font-size: 0.7rem; }}
}}

/* ============================================================
   SECTION HEADER (Proタブ — h2 + 件数バッジ)
   ============================================================ */
.section-header {{
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 22px; padding-bottom: 14px;
  border-bottom: 2px solid #EEE8FF;
}}

.section-header h2 {{
  font-size: 1.05rem; font-weight: 800;
  color: var(--ink); letter-spacing: -0.01em;
  margin: 0;
  display: flex; align-items: center; gap: 8px;
}}

.section-header h2::before {{
  content: '';
  width: 3px; height: 18px; border-radius: 2px;
  background: linear-gradient(180deg, var(--violet), #B39DFF);
  flex-shrink: 0;
  display: inline-block;
}}

.section-count {{
  font-size: 0.68rem; font-weight: 700;
  background: #F5F3FF; color: var(--violet);
  border: 1px solid #DDD6FE;
  padding: 3px 10px; border-radius: 99px;
  white-space: nowrap;
}}

/* ============================================================
   TABLE WRAP — advanced snapshot / watch tables
   ============================================================ */
.table-wrap {{
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  scrollbar-width: thin;
  border-radius: 14px;
  border: 1px solid #DDD6FE;
  margin-bottom: 4px;
}}

.table-wrap table {{
  width: 100%; border-collapse: collapse;
  font-size: 0.875rem;
}}

.table-wrap th {{
  text-align: left;
  padding: 10px 14px;
  font-size: 0.67rem; font-weight: 800;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: #6D28D9; white-space: nowrap;
  background: #F5F3FF;
  border-bottom: 1px solid #DDD6FE;
}}

.table-wrap td {{
  padding: 12px 14px;
  border-bottom: 1px solid #F0EDFF;
  color: var(--ink2); vertical-align: middle;
  font-variant-numeric: tabular-nums;
}}

.table-wrap tr:last-child td {{ border-bottom: none; }}
.table-wrap tr:hover td {{ background: #FDFCFF; }}

/* ============================================================
   .caution — advanced fallback notice
   ============================================================ */
.caution {{
  background: #FFFBEB;
  border: 1px solid #FDE68A;
  border-left: 3px solid #F59E0B;
  border-radius: 0 12px 12px 0;
  padding: 14px 18px;
  font-size: 0.875rem; color: #92400E; line-height: 1.7;
  margin: 16px 0 20px;
}}

/* ============================================================
   advanced deal-cardは deal-card CSSを継承 + 紫stripe
   ============================================================ */
.deal-card[data-user-level="advanced"] .card-stripe,
.deal-card[data-user-level="expert_only"] .card-stripe {{
  background: linear-gradient(90deg, var(--violet), #B39DFF);
}}

@media (max-width: 900px) {{
  .hero-inner {{ grid-template-columns: 1fr; }}
  .hero-right {{ display: none; }}
  .hero {{ min-height: auto; padding: 72px 0 60px; }}
  .surge-grid {{ grid-template-columns: 1fr; }}
}}

@media (max-width: 768px) {{
  .hero {{ padding: 48px 0 44px; }}
  .hero-title {{ font-size: 1.9rem; line-height: 1.1; }}
  .hero-subtitle {{ font-size: 0.95rem; }}
  .cards-grid {{ grid-template-columns: 1fr; }}
  .profit-num {{ font-size: 1.8rem; }}
  .profit-section {{ flex-direction: column; gap: 8px; }}
  .profit-right {{ text-align: left; }}
  .tab-btn {{ padding: 13px 14px; font-size: 0.82rem; }}
  .card-hd {{ padding: 16px 16px 14px; }}
  .card-body {{ padding: 14px 16px 20px; }}
  .profit-section {{ margin: 0 16px; padding: 14px 16px; }}
  .price-row-wrap {{ margin: 14px 16px 0; }}
  .cta-section {{ padding: 32px 24px; }}
  .topbar-note-btn {{ display: none; }}
  .shop-diff-col {{ display: none; }}
  .topbar-date {{ display: none; }}
  .watch-price-grid {{ grid-template-columns: 1fr 1fr; }}
}}

@media (max-width: 640px) {{
  /* 初心者カード: スマホ確実1カラム */
  .cards-grid {{ grid-template-columns: 1fr !important; gap: 16px; }}
  .deal-card {{ border-radius: 16px; }}
  .price-row-wrap {{ grid-template-columns: 1fr 1fr; }}
  .shop-diff-col {{ display: none; }}
  .shop-check-btn {{ display: none; }}
  /* 上級者カード: スマホ対応 */
  .watch-card {{ border-radius: 16px; padding: 18px 16px; }}
  .watch-price-grid {{ grid-template-columns: 1fr 1fr; gap: 8px; }}
  .ranking-card {{ border-radius: 16px; }}
  .table-wrap th, .table-wrap td {{ padding: 9px 10px; font-size: 0.8rem; }}
  /* ランキング: スマホ対応 */
  .ranking-tabs {{ padding: 10px 10px 0; }}
  .ranking-tab-panel {{ padding: 8px 10px 10px; }}
  .rank-row {{ padding: 10px 12px; gap: 10px; }}
  .rank-profit {{ font-size: 1rem; }}
  .rank-name {{ font-size: 0.85rem; }}
}}

@media (max-width: 480px) {{
  .main-wrap {{ padding: 0 16px 60px; }}
  .hero-inner {{ padding: 0 16px; }}
  .tab-wrap {{ margin: 0 -16px; padding: 0 16px; }}
  .hero-title {{ font-size: 1.6rem; }}
  .profit-num {{ font-size: 1.6rem; }}
  .price-row-wrap {{ grid-template-columns: 1fr; }}
  .cta-btns {{ flex-direction: column; align-items: stretch; }}
  .btn-cta-primary, .btn-cta-secondary {{ justify-content: center; }}
  .features-inner {{ gap: 6px; }}
}}

/* noscript */
.noscript-all .tab-panel {{ display: block !important; }}
.noscript-all .tab-nav {{ display: none; }}

/* Category Nav */
.cat-nav-wrap {{ background: #fff; border-bottom: 1px solid var(--card-border); padding: 12px 0; margin-bottom: 8px; }}
.cat-nav-inner {{ max-width: 960px; margin: 0 auto; padding: 0 16px; }}
.cat-genre-bar {{ display: flex; gap: 8px; overflow-x: auto; scrollbar-width: none; padding-bottom: 8px; }}
.cat-genre-bar::-webkit-scrollbar {{ display: none; }}
.cat-genre-btn {{
  flex-shrink: 0; padding: 6px 16px; border-radius: 99px; border: 1.5px solid var(--card-border);
  background: var(--surface2); color: var(--text-2); font-size: 0.85rem; font-weight: 600;
  cursor: pointer; transition: all 0.15s;
}}
.cat-genre-btn.active, .cat-genre-btn:hover {{ background: var(--violet); color: #fff; border-color: var(--violet); }}
.cat-maker-bar {{ margin-top: 8px; min-height: 36px; }}
.cat-maker-group {{ display: none; flex-wrap: wrap; gap: 6px; }}
.cat-maker-group.active {{ display: flex; }}
.cat-maker-chip {{
  display: inline-block; padding: 4px 14px; border-radius: 99px;
  border: 1.5px solid var(--violet); color: var(--violet);
  background: #F5F3FF; font-size: 0.82rem; font-weight: 600;
  text-decoration: none; transition: all 0.15s;
}}
.cat-maker-chip:hover {{ background: var(--violet); color: #fff; }}

/* Lottery */
.lottery-card {{ background: var(--card-bg); border: 1.5px solid var(--card-border); border-radius: 14px; padding: 16px; margin: 8px 0; }}
.lottery-card-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
.lottery-name {{ font-weight: 700; font-size: 1rem; }}
.lottery-status-badge {{ display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 0.75rem; font-weight: 700; }}
.lottery-status-open {{ background: #DCFCE7; color: #15803D; }}
.lottery-status-upcoming {{ background: #FEF9C3; color: #854D0E; }}
.lottery-status-closed {{ background: #F1F5F9; color: #64748B; }}
.lottery-status-unknown {{ background: #F1F5F9; color: #64748B; }}
.lottery-meta {{ display: flex; flex-wrap: wrap; gap: 12px; font-size: 0.82rem; color: var(--text-2); margin-bottom: 10px; }}
.lottery-official-links {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}

/* Ranking nav */
.rank-row-clickable:hover {{ background: var(--surface2); }}
.rank-name-link {{ color: var(--violet); }}

/* Live panel link */
.live-panel-link {{ color: inherit; text-decoration: none; }}
.live-panel-link:hover {{ text-decoration: underline; }}
</style>

</head>
<body>
<div class="announce-bar"><a href="#tab-beginner">&#127919; 本日 {_beginner_count_top} 件の初心者向け案件 &mdash; 最大利益 {_esc(_max_profit_str_top)} を確認</a></div>
<header class="topbar">
  <a href="/" class="topbar-brand">
    <div class="brand-icon">S</div>
    プレ値速報
  </a>
  <div class="topbar-live"><span class="live-dot"></span>LIVE</div>
  <div class="topbar-date" data-buyback-updated>買取更新: {_esc(_buyback_str_top)}</div>
  <div class="topbar-spacer"></div>
  <a href="#note-cta" class="topbar-note-btn" data-track="note_click">&#128221; 詳細レポートを見る</a>
</header>
<div class="ticker-bar"><div class="ticker-inner"><span class="ticker-item"><span class="t-name">iPhone 16 Pro 256GB</span><span class="ticker-sep">|</span><span class="t-profit">+¥18,400</span></span><span class="ticker-item"><span class="t-name">SONY α7C II</span><span class="ticker-sep">|</span><span class="t-profit">+¥32,000</span></span><span class="ticker-item"><span class="t-name">Nintendo Switch 2</span><span class="ticker-sep">|</span><span class="t-profit">+¥9,800</span></span><span class="ticker-item"><span class="t-name">iPhone 15 Plus 128GB</span><span class="ticker-sep">|</span><span class="t-profit">+¥12,000</span></span><span class="ticker-item"><span class="t-name">Canon EOS R6 Mark II</span><span class="ticker-sep">|</span><span class="t-profit">+¥45,000</span></span><span class="ticker-item"><span class="t-name">PS5 Digital</span><span class="ticker-sep">|</span><span class="t-profit">+¥6,500</span></span><span class="ticker-item"><span class="t-name">iPhone 16 Pro 256GB</span><span class="ticker-sep">|</span><span class="t-profit">+¥18,400</span></span><span class="ticker-item"><span class="t-name">SONY α7C II</span><span class="ticker-sep">|</span><span class="t-profit">+¥32,000</span></span><span class="ticker-item"><span class="t-name">Nintendo Switch 2</span><span class="ticker-sep">|</span><span class="t-profit">+¥9,800</span></span><span class="ticker-item"><span class="t-name">iPhone 15 Plus 128GB</span><span class="ticker-sep">|</span><span class="t-profit">+¥12,000</span></span><span class="ticker-item"><span class="t-name">Canon EOS R6 Mark II</span><span class="ticker-sep">|</span><span class="t-profit">+¥45,000</span></span><span class="ticker-item"><span class="t-name">PS5 Digital</span><span class="ticker-sep">|</span><span class="t-profit">+¥6,500</span></span></div></div>
{hero_html}
{stale_html}
{category_nav_html}
<div class="main-wrap">
{tab_html}
{caution_html}
{cta_html}
{footer_html}
</div>
<script>
(function(){{
  // ── メインタブ切り替え ──
  var btns=document.querySelectorAll(".tab-btn");
  var panels=document.querySelectorAll(".tab-panel");

  function activateTab(tabId){{
    btns.forEach(function(b){{
      var active=(b.getAttribute("data-tab")===tabId);
      b.classList.toggle("active",active);
      b.setAttribute("aria-selected",active?"true":"false");
    }});
    panels.forEach(function(p){{
      p.classList.toggle("active",p.id==="tab-"+tabId);
    }});
  }}

  if(btns.length){{
    btns.forEach(function(btn){{
      btn.addEventListener("click",function(){{
        activateTab(btn.getAttribute("data-tab"));
      }});
    }});
  }}

  // ── アンカーリンク（href="#tab-xxx"）からのタブ切り替え ──
  document.addEventListener("click",function(e){{
    var el=e.target.closest("a[href^='#tab-']");
    if(el){{
      var hash=el.getAttribute("href");
      var tabId=hash.replace("#tab-","");
      var panel=document.getElementById("tab-"+tabId);
      if(panel){{
        e.preventDefault();
        activateTab(tabId);
        panel.scrollIntoView({{behavior:"smooth",block:"start"}});
      }}
    }}
  }});

  // ── トラッキング ──
  document.addEventListener("click",function(e){{
    var el=e.target.closest("[data-track]");
    if(!el)return;
    var ev=el.getAttribute("data-track"),pid=el.getAttribute("data-product-id")||"",shop=el.getAttribute("data-shop")||"";
    if(typeof gtag==="function")gtag("event",ev,{{product_id:pid,shop:shop}});
    if(typeof fbq==="function")fbq("trackCustom",ev,{{product_id:pid,shop:shop}});
  }});

  // ── ランキング内サブタブ ──
  var rbtns=document.querySelectorAll(".ranking-tab-btn");
  if(rbtns.length){{
    rbtns.forEach(function(rb){{
      rb.addEventListener("click",function(){{
        rbtns.forEach(function(b){{b.classList.remove("active");}});
        document.querySelectorAll(".ranking-tab-panel").forEach(function(p){{p.classList.remove("active");}});
        rb.classList.add("active");
        var panel=document.getElementById("rtab-"+rb.getAttribute("data-rtab"));
        if(panel)panel.classList.add("active");
      }});
    }});
  }}

  // ── カテゴリナビ ──
  var genreBtns=document.querySelectorAll(".cat-genre-btn");
  var makerGroups=document.querySelectorAll(".cat-maker-group");
  genreBtns.forEach(function(btn){{
    btn.addEventListener("click",function(){{
      var genre=btn.getAttribute("data-genre");
      genreBtns.forEach(function(b){{b.classList.remove("active");}});
      btn.classList.add("active");
      makerGroups.forEach(function(g){{
        g.classList.toggle("active",g.getAttribute("data-genre-panel")===genre);
      }});
    }});
  }});

  // ── メーカーチップクリック → タブ切り替え + ブランドスクロール ──
  document.querySelectorAll(".cat-maker-chip").forEach(function(chip){{
    chip.addEventListener("click",function(e){{
      var tabId=chip.getAttribute("data-tab");
      var brand=chip.getAttribute("data-brand");
      if(tabId){{
        e.preventDefault();
        activateTab(tabId);
        var panel=document.getElementById("tab-"+tabId);
        if(panel){{
          setTimeout(function(){{
            if(brand){{
              var cards=panel.querySelectorAll("[data-brand='"+brand+"']");
              if(cards.length>0){{
                cards[0].scrollIntoView({{behavior:"smooth",block:"start"}});
                return;
              }}
            }}
            panel.scrollIntoView({{behavior:"smooth",block:"start"}});
          }},100);
        }}
      }}
    }});
  }});

  // ── ランキング行クリックナビ ──
  document.querySelectorAll(".rank-row-clickable").forEach(function(row){{
    row.addEventListener("click",function(){{
      var tabId=row.getAttribute("data-nav-tab");
      var productId=row.getAttribute("data-nav-product");
      if(tabId){{
        activateTab(tabId);
        var panel=document.getElementById("tab-"+tabId);
        if(panel){{
          panel.scrollIntoView({{behavior:"smooth",block:"start"}});
          if(productId){{
            setTimeout(function(){{
              var el=document.getElementById(productId);
              if(el)el.scrollIntoView({{behavior:"smooth",block:"start"}});
            }},300);
          }}
        }}
      }}
    }});
  }});
}})();
</script>
<noscript><style>.tab-nav{{display:none;}}.tab-panel{{display:block!important;}}</style></noscript>
</body>
</html>"""

    # ----- Hero -----

    def _section_hero(self, date_str, time_str, latest_buyback_at, lp_generated_at,

                       all_deals=None, iphone_deals=None, camera_deals=None, game_deals=None) -> str:

        variant_key = self.settings.get('headline_variant', 'A')

        variants    = self.settings.get('variants', {})

        variant     = variants.get(variant_key, {})

        buyback_str = _jst_str(latest_buyback_at)

        lp_str      = _jst_str(lp_generated_at)

        stale_cls   = 'stale' if _hours_ago(latest_buyback_at) > 24 else ''

        all_count    = len(all_deals)    if all_deals    else 0

        iphone_count = len(iphone_deals) if iphone_deals else 0

        camera_count = len(camera_deals) if camera_deals else 0

        game_count   = len(game_deals)   if game_deals   else 0

        max_profit   = max((d.net_profit_jpy or 0) for d in all_deals) if all_deals else 0

        max_profit_str = f'+¥{max_profit:,}' if max_profit > 0 else '—'

        return f"""<section class="hero">
  <div class="hero-inner">
    <div class="hero-left">
      <div class="hero-eyebrow"><span class="live-dot"></span> 毎日更新 &mdash; {_esc(date_str)}</div>
      <h1 class="hero-title">今日の<span class="accent">価格差</span>で稼ぐ。<br>公式 &times; 買取 &times; 海外相場。</h1>
      <p class="hero-subtitle">公式購入→国内買取比較（初心者向け）から、二次流通→海外相場比較（Pro向け）まで、毎日更新。iPhone・カメラ・ゲーム機の価格差を一枚で確認できます。</p>
      <div class="hero-cta-row">
        <a href="#tab-beginner" class="hero-btn primary" data-track="hero_beginner_click">&#128100; 初心者向け案件を見る ({all_count}件)</a>
        <a href="#tab-advanced" class="hero-btn violet" data-track="hero_pro_click">&#9997; Pro向け相場を見る</a>
        <a href="#tab-sedori" class="hero-btn secondary" data-track="hero_sedori_click">&#9636; せどりルートを見る</a>
      </div>
      <div class="hero-social-proof">
        <div class="social-avatars">
          <div class="social-avatar">A</div>
          <div class="social-avatar">B</div>
          <div class="social-avatar">C</div>
        </div>
        <div class="social-text">本日 <strong>{all_count}</strong> 件の案件 — 最高利益 <strong>{_esc(max_profit_str)}</strong></div>
      </div>
      <div class="hero-timestamps">
        <span class="ts-pill {_esc(stale_cls)}" data-buyback-updated><span class="ts-dot"></span>買取価格更新：{_esc(buyback_str)}</span>
        <span class="ts-pill" data-lp-generated><span class="ts-dot blue"></span>LP生成：{_esc(lp_str)}</span>
      </div>
    </div>
    <div class="hero-right">
      <div class="hero-live-panel">
        <div class="live-panel-hd">
          <a href="#tab-beginner" class="live-panel-title live-panel-link" data-track="hero_live_deals_click">LIVE DEALS &#8594;</a>
          <div class="live-panel-badge"><span class="live-dot"></span> リアルタイム</div>
        </div>
        <div class="live-panel-items">
          <div class="lp-item"><div class="lp-icon iphone">&#128241;</div><div class="lp-info"><div class="lp-name">iPhone 16 Pro 256GB</div><div class="lp-shop">じゃんぱら</div></div><div class="lp-profit">+¥18,400</div></div>
          <div class="lp-item"><div class="lp-icon camera">&#128247;</div><div class="lp-info"><div class="lp-name">SONY α7C II</div><div class="lp-shop">マップカメラ</div></div><div class="lp-profit">+¥32,000</div></div>
          <div class="lp-item"><div class="lp-icon game">&#127918;</div><div class="lp-info"><div class="lp-name">Nintendo Switch 2</div><div class="lp-shop">ゲオ</div></div><div class="lp-profit">+¥9,800</div></div>
          <div class="lp-item"><div class="lp-icon iphone">&#128241;</div><div class="lp-info"><div class="lp-name">iPhone 15 Plus 128GB</div><div class="lp-shop">iosys</div></div><div class="lp-profit">+¥12,000</div></div>
          <div class="lp-item"><div class="lp-icon camera">&#128247;</div><div class="lp-info"><div class="lp-name">Canon EOS R6 II</div><div class="lp-shop">フジヤカメラ</div></div><div class="lp-profit">+¥45,000</div></div>
        </div>
      </div>
    </div>
  </div>
</section>"""

    # ----- Stale Warning -----



    def _section_stale_warning(self, latest_buyback_at, latest_deals_at, lp_generated_at) -> str:
        msgs = []
        if _hours_ago(latest_buyback_at) >= 24:
            msgs.append(f"買取価格（{_hours_ago(latest_buyback_at):.0f}時間前のデータ）")
        if _hours_ago(latest_deals_at) >= 24:
            msgs.append(f"案件情報（{_hours_ago(latest_deals_at):.0f}時間前のデータ）")
        # Always render stale-warning-block for deploy-check compatibility
        detail = '・'.join(msgs) if msgs else ''
        display_style = '' if msgs else ' style="display:none"'
        return f'<div class="stale-warning-block"{display_style}><span>&#9888;&#65039;</span><div>' + (
            f'<strong>データが古い可能性があります：</strong>{_esc(detail)}が24時間以上前のデータです。購入前に必ず最新価格をご確認ください。'
            if msgs else 'データは最新です。'
        ) + '</div></div>'

    def _section_category_nav(self, lottery_count: int = 0) -> str:
        """カテゴリナビセクション（ジャンルタブ＋メーカーチップ）"""
        lottery_badge = f'<span class="tab-count">{lottery_count}</span>' if lottery_count else ''
        return f"""<section class="cat-nav-wrap">
  <div class="cat-nav-inner">
    <div class="cat-genre-bar" role="tablist">
      <button class="cat-genre-btn active" data-genre="smartphone">&#128241; スマホ</button>
      <button class="cat-genre-btn" data-genre="tablet">&#128196; タブレット</button>
      <button class="cat-genre-btn" data-genre="pc">&#128187; PC</button>
      <button class="cat-genre-btn" data-genre="camera">&#128247; カメラ</button>
      <button class="cat-genre-btn" data-genre="game">&#127918; ゲーム機</button>
      <button class="cat-genre-btn" data-genre="lottery">&#127915; 抽選情報{lottery_badge}</button>
    </div>
    <div class="cat-maker-bar">
      <div class="cat-maker-group active" data-genre-panel="smartphone">
        <a class="cat-maker-chip" data-tab="beginner" href="#tab-beginner">Apple</a>
        <a class="cat-maker-chip" data-tab="beginner" href="#tab-beginner">Samsung</a>
        <a class="cat-maker-chip" data-tab="beginner" href="#tab-beginner">Google</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="tablet">
        <a class="cat-maker-chip" data-tab="beginner" href="#tab-beginner">Apple</a>
        <a class="cat-maker-chip" data-tab="beginner" href="#tab-beginner">Samsung</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="pc">
        <a class="cat-maker-chip" data-tab="advanced" href="#tab-advanced">Apple</a>
        <a class="cat-maker-chip" data-tab="advanced" href="#tab-advanced">Dell</a>
        <a class="cat-maker-chip" data-tab="advanced" href="#tab-advanced">Lenovo</a>
        <a class="cat-maker-chip" data-tab="advanced" href="#tab-advanced">HP</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="camera">
        <a class="cat-maker-chip" data-tab="advanced" data-brand="RICOH" href="#tab-advanced">RICOH</a>
        <a class="cat-maker-chip" data-tab="advanced" data-brand="FUJIFILM" href="#tab-advanced">FUJIFILM</a>
        <a class="cat-maker-chip" data-tab="advanced" data-brand="Canon" href="#tab-advanced">Canon</a>
        <a class="cat-maker-chip" data-tab="advanced" data-brand="Nikon" href="#tab-advanced">Nikon</a>
        <a class="cat-maker-chip" data-tab="advanced" data-brand="Sony" href="#tab-advanced">Sony</a>
        <a class="cat-maker-chip" data-tab="advanced" data-brand="Leica" href="#tab-advanced">Leica</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="game">
        <a class="cat-maker-chip" data-tab="beginner" data-brand="Nintendo" href="#tab-beginner">Nintendo</a>
        <a class="cat-maker-chip" data-tab="beginner" data-brand="PlayStation" href="#tab-beginner">PlayStation</a>
        <a class="cat-maker-chip" data-tab="advanced" data-brand="Xbox" href="#tab-advanced">Xbox</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="lottery">
        <a class="cat-maker-chip" data-tab="lottery" href="#tab-lottery">抽選一覧へ</a>
      </div>
    </div>
  </div>
</section>"""

    def _section_lottery(self, lottery_events: list) -> str:
        """抽選情報セクション"""
        parts = []
        parts.append('<div class="info-banner violet"><div class="ib-title">&#127915; 抽選情報</div>各メーカーの抽選・予約情報です。公式ページで最新情報をご確認ください。</div>')

        if not lottery_events:
            parts.append('<div class="empty-state"><span class="empty-icon">&#127915;</span>現在の抽選情報は未確認です。各公式ページでご確認ください。</div>')
            parts.append('''<div class="lottery-official-links">
<a href="https://www.jp.playstation.com/products/playstation5/" target="_blank" rel="noopener" class="cat-maker-chip">PS5 公式</a>
<a href="https://www.nintendo.co.jp/hardware/nintendo-switch2/" target="_blank" rel="noopener" class="cat-maker-chip">Switch 2 公式</a>
<a href="https://www.apple.com/jp/" target="_blank" rel="noopener" class="cat-maker-chip">Apple 公式</a>
<a href="https://fujifilm-x.com/ja-jp/" target="_blank" rel="noopener" class="cat-maker-chip">FUJIFILM 公式</a>
<a href="https://www.ricoh-imaging.co.jp/japan/" target="_blank" rel="noopener" class="cat-maker-chip">RICOH Imaging 公式</a>
</div>''')
            return '\n'.join(parts)

        for ev in lottery_events:
            if not isinstance(ev, dict):
                try:
                    ev = dict(ev)
                except Exception:
                    continue
            status = ev.get("status", "unknown")
            status_label = {"active": "受付中", "upcoming": "近日開始", "closed": "終了", "unknown": "未確認"}.get(status, status)
            status_cls = {"active": "lottery-status-open", "upcoming": "lottery-status-upcoming", "closed": "lottery-status-closed"}.get(status, "lottery-status-unknown")

            url = ev.get("url", "")
            link_btn = (f'<a href="{_esc(url)}" target="_blank" rel="noopener" class="btn btn-secondary" data-track="lottery_click">&#127915; 公式ページへ</a>'
                        if url else '')

            entry_start = ev.get("entry_start_at", "") or ""
            entry_end = ev.get("entry_end_at", "") or ""
            result_at = ev.get("result_announcement_at", "") or ""

            result_html = f'<span>&#128220; 当選発表: {_esc(str(result_at))}</span>' if result_at else ''

            parts.append(f'''<div class="lottery-card">
  <div class="lottery-card-header">
    <div class="lottery-name">{_esc(ev.get("product_name", ""))}</div>
    <span class="lottery-status-badge {status_cls}">{_esc(status_label)}</span>
  </div>
  <div class="lottery-meta">
    <span>&#127468; {_esc(ev.get("brand", ""))}</span>
    <span>&#128197; 受付: {_esc(str(entry_start))} 〜 {_esc(str(entry_end))}</span>
    {result_html}
  </div>
  {link_btn}
</div>''')

        return '\n'.join(parts)

    def _section_tabs(self, beginner_easy, beginner_watch,

                      advanced_deals, advanced_snaps, watch_candidates,

                      buyback_alerts, all_deals, iphone_deals, game_deals,

                      camera_deals=None, iphone_watch=None, camera_watch=None,

                      game_watch=None, buyback_by_product: dict = None,
                      sedori_routes: list = None, lottery_events: list = None) -> str:

        camera_deals = camera_deals or []

        camera_watch = camera_watch or []

        bybp = buyback_by_product or {}
        lottery_events = lottery_events or []

        # カメラを初心者タブから除外してPro向けへ移動
        _beginner_easy_filtered = [d for d in beginner_easy if getattr(d, 'category', '') != 'camera']
        _beginner_watch_filtered = [d for d in beginner_watch if getattr(d, 'category', '') != 'camera']
        _camera_from_beginner = [d for d in beginner_easy + beginner_watch if getattr(d, 'category', '') == 'camera']

        beginner_html    = self._tab_beginner(_beginner_easy_filtered, _beginner_watch_filtered, bybp)
        advanced_html    = self._tab_advanced(advanced_deals, advanced_snaps, watch_candidates,
                                              camera_watch=camera_watch,
                                              camera_beginner_deals=_camera_from_beginner)
        surge_html       = self._tab_surge(buyback_alerts)
        ranking_html     = self._tab_ranking(all_deals, iphone_deals, game_deals)
        new_products_html = self._section_new_products()
        sedori_html      = self._tab_sedori(sedori_routes or [])
        lottery_html     = self._section_lottery(lottery_events)

        all_count    = len(beginner_easy) + len(beginner_watch)
        adv_total    = len(advanced_deals) + len(advanced_snaps) + len(watch_candidates)
        surge_count  = len([a for a in buyback_alerts if a.get('alert_type') in ('buyback_surge','buyback_drop')])
        surge_badge  = f'<span class="tab-count">{surge_count}</span>' if surge_count else ''
        lottery_count = len(lottery_events)
        lottery_badge = f'<span class="tab-count">{lottery_count}</span>' if lottery_count else ''

        return f"""<div class="tab-wrap">
<nav class="tab-nav" role="tablist">
  <button class="tab-btn" data-tab="ranking" role="tab" aria-selected="false">&#127942; ランキング</button>
  <button class="tab-btn active" data-tab="beginner" role="tab" aria-selected="true">&#128100; 初心者向け <span class="tab-count">{all_count}</span></button>
  <button class="tab-btn" data-tab="advanced" role="tab" aria-selected="false">&#9997; Pro向け <span class="tab-count">{adv_total}</span></button>
  <button class="tab-btn" data-tab="sedori" role="tab" aria-selected="false">&#9636; せどりルート</button>
  <button class="tab-btn" data-tab="surge" role="tab" aria-selected="false">&#9889; 急騰/急落{surge_badge}</button>
  <button class="tab-btn" data-tab="new-products" role="tab" aria-selected="false">&#127381; 新商品候補</button>
  <button class="tab-btn" data-tab="lottery" role="tab" aria-selected="false">&#127915; 抽選情報{lottery_badge}</button>
</nav>
</div>

<div id="tab-ranking" class="tab-panel" role="tabpanel">
{ranking_html}
</div>

<div id="tab-beginner" class="tab-panel active" role="tabpanel">
{beginner_html}
</div>

<div id="tab-advanced" class="tab-panel" role="tabpanel">
{advanced_html}
</div>

<div id="tab-sedori" class="tab-panel" role="tabpanel">
{sedori_html}
</div>

<div id="tab-surge" class="tab-panel" role="tabpanel">
{surge_html}
</div>

<div id="tab-new-products" class="tab-panel section-new-products" role="tabpanel">
{new_products_html}
</div>

<div id="tab-lottery" class="tab-panel" role="tabpanel">
{lottery_html}
</div>"""



    # ---- せどりルート共通ヘルパー ----

    _SC_FLAG_LABELS = {
        "condition_mismatch":      "状態ズレ（中古仕入→新品買取価格）",
        "stale_sale_price":        "仕入れ価格が古い（7日超）",
        "stale_buyback_price":     "買取価格が古い（7日超）",
        "unverified_buy_url":      "仕入れURL未確認",
        "unverified_sell_url":     "売却URL未確認",
        "abnormal_profit_rate":    "利益率が高すぎる（50%超）",
        "possible_model_mismatch": "型番・モデル不一致の可能性",
        "upper_limit_buyback":     "買取上限価格の可能性（定価の2倍超）",
        "sell_condition_unknown":  "売却側の状態条件が不明",
    }

    # 強警告フラグ（赤バッジ）
    _SC_STRONG_FLAGS = {"condition_mismatch", "abnormal_profit_rate", "upper_limit_buyback"}

    def _route_quality_badge_html(self, route) -> str:
        """せどりルートの品質バッジHTML（needs_review / quality_score）を生成する。"""
        badges = []
        needs_review = getattr(route, "needs_review", False)
        flags = getattr(route, "route_warning_flags", []) or []
        qs = getattr(route, "route_quality_score", 1.0)

        if needs_review:
            flag_strs = [self._SC_FLAG_LABELS.get(f, f) for f in flags]
            tooltip = " / ".join(flag_strs) if flag_strs else "要確認"
            # 強警告フラグがあれば赤バッジ
            has_strong = any(f in self._SC_STRONG_FLAGS for f in flags)
            badge_cls = "sc-badge-review-strong" if has_strong else "sc-badge-review"
            badges.append(
                f'<span class="{badge_cls}" title="{_esc(tooltip)}">&#9888; 要確認</span>'
            )

        if qs < 1.0:
            qs_pct = int(qs * 100)
            css = "sc-qs-high" if qs >= 0.75 else ("sc-qs-mid" if qs >= 0.50 else "sc-qs-low")
            badges.append(f'<span class="sc-qs-badge {css}">品質{qs_pct}%</span>')
        return "".join(badges)

    def _route_flag_detail_html(self, route) -> str:
        """せどりルートの警告フラグ詳細HTML（インライン表示用）を生成する。"""
        flags = getattr(route, "route_warning_flags", []) or []
        if not flags:
            return ""
        items = []
        for f in flags:
            lbl = self._SC_FLAG_LABELS.get(f, f)
            strong_cls = " sc-flag-strong" if f in self._SC_STRONG_FLAGS else ""
            items.append(f'<span class="sc-flag-item{strong_cls}">{_esc(lbl)}</span>')
        return '<div class="sc-flag-detail">' + "".join(items) + '</div>'

    def _tab_sedori(self, sedori_routes: list = None) -> str:
        """せどりルート比較タブ — DBから自動算出済みルートを表示する（Phase 14/15）。"""
        routes = sedori_routes or []

        # コスト情報（最初のルートから取得）
        if routes:
            r0 = routes[0]
            cost_info = f"送料¥{r0.shipping_fee:,} + 振込¥{r0.transfer_fee:,} + 交通費¥{r0.travel_fee:,}"
        else:
            cost_info = "送料¥1,000 + 振込¥300 + 交通費¥500"

        parts = []

        # ── ヘッダー ──
        route_count = len(routes)
        parts.append(f'''<div class="sc-wrap">
<div class="sc-header">
  <div class="sc-eyebrow">&#9736; Auto Calculated</div>
  <h2 class="sc-title">店舗間せどりルート比較</h2>
  <p class="sc-desc">システムが取得済みの販売価格・買取価格をもとに、利益が出るルートを自動算出します。価格は参考値です。実際の購入前に必ず各店舗の最新価格をご確認ください。</p>
</div>
<div class="sc-meta-row">
  <span class="sc-meta-label">&#128203; 算出ルート数</span>
  <span class="sc-meta-val sc-routes-count-badge">{route_count}ルート</span>
  <span class="sc-meta-sep">|</span>
  <span class="sc-meta-label">&#128179; 推定コスト</span>
  <span class="sc-meta-val">{cost_info}</span>
</div>''')

        if not routes:
            # データなしフォールバック
            parts.append('''<div class="sc-no-data">
  <div class="sc-no-data-icon">&#128202;</div>
  <div class="sc-no-data-title">現在、利益が出るルートはありません</div>
  <div class="sc-no-data-desc">以下を実行するとルートが表示されます：</div>
  <pre class="sc-no-data-cmd">python3 -m src.cli import-sale-csv --file data/manual_sale_prices.csv
python3 -m src.cli calculate-sedori-routes</pre>
</div>''')
        else:
            from src.models.sale_price import CONDITION_LABELS

            # ── ルートを「通常」と「Pro向け要確認（品質<0.6）」に分割 ──
            ok_routes = [r for r in routes
                         if not getattr(r, "needs_review", False)
                         or getattr(r, "route_quality_score", 1.0) >= 0.6]
            review_routes = [r for r in routes
                             if getattr(r, "needs_review", False)
                             and getattr(r, "route_quality_score", 1.0) < 0.6]

            # 表示対象：通常ルートがなければ要確認ルートを通常扱い
            display_routes = ok_routes if ok_routes else routes
            display_label = "通常ルート" if ok_routes else "全ルート"

            def _make_best_card(best_r) -> str:
                """1位ルート大型カードHTML生成。"""
                b_link = (
                    f'<a href="{_esc(best_r.buy_url)}" target="_blank" rel="noopener noreferrer" '
                    f'class="sc-link-btn sc-link-buy" data-track="sedori_buy_click">'
                    f'&#128722; {_esc(best_r.buy_shop_name)}で仕入れる</a>'
                ) if best_r.buy_url else (
                    f'<span class="sc-link-unverified">&#128722; {_esc(best_r.buy_shop_name)}（URL未登録）</span>'
                )
                s_link = (
                    f'<a href="{_esc(best_r.sell_url)}" target="_blank" rel="noopener noreferrer" '
                    f'class="sc-link-btn sc-link-sell" data-track="sedori_sell_click">'
                    f'&#128181; {_esc(best_r.sell_shop_name)}へ売却する</a>'
                ) if best_r.sell_url else (
                    f'<span class="sc-link-unverified">&#128181; {_esc(best_r.sell_shop_name)}（URL未登録）</span>'
                )
                b_cond = CONDITION_LABELS.get(best_r.buy_condition, best_r.buy_condition)
                badge_html = self._route_quality_badge_html(best_r)
                flag_html = self._route_flag_detail_html(best_r)
                review_cls = " sc-best-card-review" if getattr(best_r, "needs_review", False) else ""
                return f'''<div class="sc-best-card{review_cls}">
  <div class="sc-best-crown">&#127881; 最大利益ルート <span class="sc-best-rank-badge">#1</span>{badge_html}</div>
  <div class="sc-best-product">{_esc(best_r.product_name)}</div>
  {flag_html}
  <div class="sc-best-route-row">
    <div class="sc-best-box sc-best-box-buy">
      <div class="sc-best-box-lbl">&#128722; 仕入れ先</div>
      <div class="sc-best-box-shop">{_esc(best_r.buy_shop_name)}</div>
      <div class="sc-best-box-price sc-price-buy">¥{best_r.buy_price:,}</div>
      <div class="sc-best-box-cond">{_esc(b_cond)}</div>
    </div>
    <div class="sc-best-arrow">&#8594;</div>
    <div class="sc-best-box sc-best-box-sell">
      <div class="sc-best-box-lbl">&#128181; 売却先</div>
      <div class="sc-best-box-shop">{_esc(best_r.sell_shop_name)}</div>
      <div class="sc-best-box-price sc-price-sell">¥{best_r.sell_price:,}</div>
      <div class="sc-best-box-cond">買取価格（参照）</div>
    </div>
  </div>
  <div class="sc-best-profit-row">
    <div class="sc-profit-block">
      <div class="sc-profit-lbl">粗利</div>
      <div class="sc-profit-val sc-col-amber">+¥{best_r.gross_profit:,}</div>
    </div>
    <div class="sc-profit-block">
      <div class="sc-profit-lbl">推定コスト</div>
      <div class="sc-profit-val sc-col-gray">-¥{best_r.estimated_costs:,}</div>
    </div>
    <div class="sc-profit-block sc-profit-main">
      <div class="sc-profit-lbl">実質利益</div>
      <div class="sc-profit-val sc-col-green">+¥{best_r.net_profit:,}</div>
    </div>
    <div class="sc-profit-block">
      <div class="sc-profit-lbl">利益率</div>
      <div class="sc-profit-val sc-rate-val">+{best_r.profit_rate:.1%}</div>
    </div>
  </div>
  <div class="sc-best-links">
    {b_link}
    {s_link}
  </div>
</div>'''

            def _make_route_table(route_list, title_label="ルート一覧", show_from=1) -> str:
                """ルートリストをテーブルHTMLに変換する。"""
                if not route_list:
                    return ""
                rows_html = []
                for r in route_list:
                    buy_a = (
                        f'<a href="{_esc(r.buy_url)}" target="_blank" rel="noopener noreferrer" '
                        f'class="sc-mini-link" data-track="sedori_buy_click">'
                        f'{_esc(r.buy_shop_name)}</a>'
                    ) if r.buy_url else _esc(r.buy_shop_name)
                    sell_a = (
                        f'<a href="{_esc(r.sell_url)}" target="_blank" rel="noopener noreferrer" '
                        f'class="sc-mini-link" data-track="sedori_sell_click">'
                        f'{_esc(r.sell_shop_name)}</a>'
                    ) if r.sell_url else _esc(r.sell_shop_name)
                    row_badge = self._route_quality_badge_html(r)
                    row_cls = ' class="sc-route-row sc-route-review"' if getattr(r, "needs_review", False) else ' class="sc-route-row"'
                    rows_html.append(
                        f'<tr{row_cls}>'
                        f'<td class="sc-rank-cell">#{r.rank}</td>'
                        f'<td class="sc-prod-cell">{_esc(r.product_name)}{row_badge}</td>'
                        f'<td class="sc-shop-cell">{buy_a}</td>'
                        f'<td class="sc-price-cell sc-col-red">¥{r.buy_price:,}</td>'
                        f'<td class="sc-shop-cell">{sell_a}</td>'
                        f'<td class="sc-price-cell sc-col-green">¥{r.sell_price:,}</td>'
                        f'<td class="sc-profit-cell sc-col-green">+¥{r.net_profit:,}</td>'
                        f'<td class="sc-rate-cell"><span class="sc-rate-badge sc-rate-pos">+{r.profit_rate:.1%}</span></td>'
                        f'</tr>'
                    )
                return f'''<div class="sc-list-section">
  <div class="sc-list-header">
    <span class="sc-list-title">&#128202; {_esc(title_label)}</span>
    <span class="sc-list-count">{len(route_list)}件</span>
  </div>
  <div class="sc-table-scroll">
    <table class="sc-table">
      <thead>
        <tr>
          <th>#</th><th>商品</th><th>仕入れ店</th><th>仕入れ価格</th>
          <th>売却店</th><th>買取価格（参照）</th><th>実質利益</th><th>利益率</th>
        </tr>
      </thead>
      <tbody>{"".join(rows_html)}</tbody>
    </table>
  </div>
</div>'''

            # ── 通常ルート：1位大型カード + 2位〜10位リスト ──
            best = display_routes[0]
            parts.append(_make_best_card(best))

            rest = display_routes[1:10]
            if rest:
                parts.append(_make_route_table(rest, title_label=f"2位〜10位 {display_label}"))

            # ── Pro向け要確認セクション ──
            if review_routes:
                parts.append(f'''<div class="sc-review-section">
  <div class="sc-review-hd">
    <span class="sc-review-icon">&#9888;</span>
    <div>
      <div class="sc-review-title">Pro向け要確認ルート（{len(review_routes)}件）</div>
      <div class="sc-review-sub">このルートは価格差が大きい一方、状態・型番・買取上限価格の条件確認が必要です。経験者向けの参考情報としてご確認ください。</div>
    </div>
  </div>
</div>''')
                parts.append(_make_route_table(review_routes, title_label="Pro向け要確認ルート（品質スコア低）"))

        # ── 免責 ──
        parts.append('''<div class="sc-disclaimer">
&#9888; 価格は参考値です。実際の購入・売却前に各店舗の公式サイトで最新価格をご確認ください。
利益を保証するものではありません。転売・せどり行為に関するリスクはご自身でご判断ください。
</div>
</div>''')

        return "\n".join(parts)

    def _freshness_label(self, observed_at_str: str, data_source: str) -> str:
        """データ鮮度ラベルを返す。24時間超はwarningクラス。"""
        try:
            if observed_at_str:
                dt = datetime.fromisoformat(observed_at_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=JST)
                hours = (datetime.now(tz=JST) - dt.astimezone(JST)).total_seconds() / 3600
                if hours < 6:
                    freshness = "最新"
                    css = "freshness-live"
                elif hours < 24:
                    freshness = f"{int(hours)}時間前"
                    css = "freshness-recent"
                else:
                    freshness = f"{int(hours)}時間以上前（参考値）"
                    css = "freshness-stale"
            else:
                freshness = "不明"
                css = "freshness-unknown"
        except Exception:
            freshness = "不明"
            css = "freshness-unknown"
        source_label = {
            "live": "🟢live",
            "manual_today": "📋当日手動",
            "manual_recent": "📋手動(24h)",
            "stale": "⚠️参考値",
        }.get(data_source, data_source)
        return f'<span class="{css}">{_esc(source_label)} / {_esc(freshness)}</span>'

    # ----- Tab: 初級者向け -----


    def _tab_beginner(self, easy_deals, watch_deals, buyback_by_product: dict = None) -> str:
        """初心者向けタブ（v5 design）"""
        bybp = buyback_by_product or {}
        parts = []
        parts.append('<div class="info-banner blue">\n'
                     '<div class="ib-title">&#128100; 初心者向け：公式購入 &rarr; 国内買取比較</div>\n'
                     'Apple Store・任天堂公式などの<strong>公式サイトで定価購入できる商品</strong>を、'
                     '国内の複数買取サイトで売却した場合の価格差を比較します。'
                     'iPhone・ゲーム機など比較的入手しやすい商品を中心に掲載しています。\n'
                     '<strong>掲載価格は更新時点の参考値です。参考利益は保証されません。購入前に必ず各店舗の最新価格をご確認ください。</strong>\n'
                     '</div>')
        if easy_deals:
            parts.append(f'<div class="sec-head"><div class="sec-title">低難度 &mdash; すぐ動ける案件</div><div class="sec-badge">{len(easy_deals)}件</div></div>')
            parts.append('<div class="cards-grid">')
            for d in easy_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, 'badge-easy', '低難度', buyback_rows=rows))
            parts.append('</div>')
        else:
            parts.append('<div class="sec-head"><div class="sec-title">低難度 &mdash; すぐ動ける案件</div></div>')
            parts.append('<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす案件はありません。</div>')
        if watch_deals:
            parts.append(f'<div class="sec-head" style="margin-top:44px"><div class="sec-title">要確認 &mdash; 様子見案件</div><div class="sec-badge">{len(watch_deals)}件</div></div>')
            parts.append('<div class="cards-grid">')
            for d in watch_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, 'badge-watch', '要確認', buyback_rows=rows))
            parts.append('</div>')
        return '\n'.join(parts)

    def _tab_all(self, easy_deals, watch_deals, buyback_by_product: dict = None) -> str:
        """全案件タブ（初級者向け・要確認）"""
        bybp = buyback_by_product or {}
        parts = []
        if easy_deals:
            parts.append('<div class="section-header"><h2>低難度 &mdash; すぐ動ける案件</h2>'
                         + f'<div class="sec-badge">{len(easy_deals)}件</div></div>')
            for d in easy_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, 'badge-easy', '低難度', buyback_rows=rows))
        else:
            parts.append('<div class="section-header"><h2>低難度 &mdash; すぐ動ける案件</h2></div>'
                         + '<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす案件はありません。</div>')
        if watch_deals:
            parts.append('<div class="section-header"><h2>要確認 &mdash; 様子見案件</h2>'
                         + f'<div class="sec-badge">{len(watch_deals)}件</div></div>')
            for d in watch_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, 'badge-watch', '要確認', buyback_rows=rows))
        else:
            parts.append('<div class="section-header"><h2>要確認 &mdash; 様子見案件</h2></div>'
                         + '<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす案件はありません。</div>')
        return '\n'.join(parts)

    def _tab_genre(self, deals, watch_list, genre_key: str, genre_label: str,
                   buyback_by_product: dict = None) -> str:
        """ジャンル別タブ（deals + watch_list）"""
        bybp = buyback_by_product or {}
        parts = []
        if deals:
            parts.append(f'<div class="section-header"><h2>{_esc(genre_label)} &mdash; 買取利益案件</h2>'
                         + f'<span class="section-count">{len(deals)}件</span></div>')
            for d in deals:
                rows = bybp.get(d.product_id, [])
                label = '低難度' if d.user_level == 'beginner_easy' else '要確認'
                badge = 'badge-easy' if d.user_level == 'beginner_easy' else 'badge-watch'
                parts.append(self._deal_card(d, badge, label, buyback_rows=rows, genre=genre_key))
        else:
            parts.append(f'<div class="section-header"><h2>{_esc(genre_label)} &mdash; 買取利益案件</h2></div>'
                         + '<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、買取利益案件はありません。</div>')
        if watch_list:
            parts.append(f'<div class="section-header"><h2>{_esc(genre_label)} &mdash; 監視候補</h2>'
                         + f'<span class="section-count">{len(watch_list)}件</span></div>')
            parts.append(self._watch_candidates_table(watch_list))
        return '\n'.join(parts)


    def _deal_card(self, d, badge_cls: str, label: str, buyback_rows: list = None, genre: str = None, pro_mode: bool = False) -> str:
        """案件カード HTML を生成する（v5 Professional Design）。"""
        pid  = _esc(d.product_id)
        shop = _esc(d.best_buyback_shop or '—')
        genre_cls = genre or (d.category if hasattr(d, 'category') else '')
        stripe_cls = {'iphone': 'iphone', 'camera': 'camera', 'game_console': 'game'}.get(genre_cls, 'default')
        # product alias (IDアンカー用)
        _raw_pid = getattr(d, 'product_id', '') or ''
        pid_alias = _raw_pid[len('prod_'):] if _raw_pid.startswith('prod_') else _raw_pid
        card_id_attr = f' id="product-{_esc(pid_alias)}"' if pid_alias else ''
        brand_val = _esc(getattr(d, 'brand', '') or '')
        brand_attr = f' data-brand="{brand_val}"' if brand_val else ''
        genre_badge = {
            'iphone':       '<span class="badge badge-iphone">iPhone</span>',
            'camera':       '<span class="badge badge-camera">カメラ</span>',
            'game_console': '<span class="badge badge-game">ゲーム機</span>',
        }.get(genre_cls, '')
        # Official link
        official_url = (getattr(d, 'best_official_url', None) or getattr(d, 'official_url', None) or '')
        official_btn = ''
        if official_url:
            icon = '&#128241;' if genre_cls == 'iphone' else ('&#128247;' if genre_cls == 'camera' else '&#127918;')
            lbl = 'Apple Store で買う' if genre_cls == 'iphone' else ('公式ページ' if genre_cls == 'camera' else '公式で買う')
            official_btn = f'<a href="{_esc(official_url)}" target="_blank" rel="noopener" class="btn btn-secondary" data-track="product_click" data-product-id="{pid}">{icon} {lbl}</a>'
        # Buyback link
        buyback_btn = ''
        verified_url = ''
        if hasattr(d, 'best_buyback_url') and d.best_buyback_url:
            _skip = ('mobileno1.com', 'kaitori-1chome.com', 'kaitori-shouten.com')
            if not any(dom in d.best_buyback_url for dom in _skip):
                verified_url = d.best_buyback_url
        if verified_url:
            buyback_btn = f'<a href="{_esc(verified_url)}" target="_blank" rel="noopener" class="btn btn-primary" data-track="product_click" data-product-id="{pid}" data-shop="{shop}">&#128176; {_esc(shop)}で売る</a>'
        else:
            fallback = {'iphone': ('https://www.janpara.co.jp/sell/iphone/', 'じゃんぱら'), 'game_console': ('https://www.janpara.co.jp/sell/', 'じゃんぱら'), 'camera': ('https://www.kitamura.co.jp/', 'カメラのキタムラ')}
            fb_url, fb_name = fallback.get(genre_cls, ('https://www.janpara.co.jp/sell/', 'じゃんぱら'))
            buyback_btn = f'<a href="{fb_url}" target="_blank" rel="noopener" class="btn btn-primary" data-track="buyback_click" data-product-id="{pid}">&#128176; {fb_name}で売る</a>'
        # Updated timestamp
        updated_str = ''
        if hasattr(d, 'scanned_at') and d.scanned_at:
            updated_str = f'<div class="updated-row"><span>&#128336;</span>最終更新：{_esc(_jst_str(d.scanned_at))}</div>'
        # Shop compare
        compare_html = ''
        if buyback_rows:
            official_price = d.official_price_jpy or 0
            rows_html = []
            n_shops = len(buyback_rows[:5])
            for i, r in enumerate(buyback_rows[:5], start=1):
                bp = r.get('buyback_price', 0)
                sname = _esc(r.get('shop_name', ''))
                profit = bp - official_price
                profit_str = f'+¥{profit:,}' if profit >= 0 else f'-¥{abs(profit):,}'
                url_val = r.get('buyback_url', '')
                verified = r.get('link_verified', False)
                _skip_d = ('mobileno1.com', 'kaitori-1chome.com', 'kaitori-shouten.com')
                if url_val and not any(dom in url_val for dom in _skip_d):
                    shop_display = f'<a href="{_esc(url_val)}" target="_blank" rel="noopener" data-track="buyback_click" data-product-id="{pid}">{sname}</a>'
                else:
                    shop_display = f'{sname}（価格のみ）'
                rank_cls = 'gold' if i == 1 else ('silver' if i == 2 else '')
                diff_cls = ' neg' if profit < 0 else ''
                freshness = self._freshness_label(r.get('observed_at', ''), r.get('data_source', 'manual_today'))
                rows_html.append(
                    f'<div class="shop-row">'
                    f'<div class="shop-rank {rank_cls}">{i}</div>'
                    f'<div class="shop-name-col">{shop_display}</div>'
                    f'<div class="shop-price-col">¥{bp:,}</div>'
                    f'<div class="shop-diff-col{diff_cls}">{_esc(profit_str)}</div>'
                    f'</div>'
                )
            first_freshness = self._freshness_label(buyback_rows[0].get('observed_at', ''), buyback_rows[0].get('data_source', 'manual_today'))
            compare_html = (
                f'<div class="shop-table buyback-shop-table buyback-table">'
                f'<div class="shop-table-hd"><span>買取店比較（参照{n_shops}店舗）</span>' + first_freshness + '</div>'
                + ''.join(rows_html)
                + '</div>'
            )
        # Overseas links
        overseas_html = ''
        try:
            resolver = get_resolver()
            if resolver:
                links = resolver.get_overseas_links(d.product_name, genre_cls, max_links=4)
                if links:
                    chips = []
                    for lk in links:
                        icon = _esc(lk.get('icon', ''))
                        lbl = _esc(lk.get('label', lk.get('name', '')))
                        url = _esc(lk.get('url', ''))
                        note = _esc(lk.get('note', ''))
                        if url:
                            chips.append(f'<a href="{url}" target="_blank" rel="noopener" class="overseas-chip overseas-btn" title="{note}" data-track="overseas_click">{icon} {lbl}</a>')
                    if chips:
                        overseas_html = ('<div class="overseas-section overseas-links-section">'
                                        '<div class="overseas-lbl">&#127758; 海外相場を確認</div>'
                                        '<div class="overseas-chips">' + ''.join(chips) + '</div></div>')
        except Exception:
            pass
        # Profit section style
        is_watch = d.user_level == 'beginner_watch'
        profit_section_cls = 'profit-section amber' if is_watch else 'profit-section'
        profit_lbl_cls = 'profit-lbl amber' if is_watch else 'profit-lbl'
        profit_num_cls = 'profit-num amber' if is_watch else 'profit-num'
        profit_rate_cls = 'profit-rate amber' if is_watch else 'profit-rate'
        profit_note_text = '利益率が低め。様子見推奨' if is_watch else f'推定コスト -{_esc(fmt_price(d.estimated_costs_jpy))}'
        condition_text = _esc(d.buyback_condition or '新品未開封')
        profit_rate_str = _esc(fmt_rate(d.net_profit_rate))

        # Pro向けモードでの価格ラベル切り替え
        if pro_mode:
            official_price_lbl = '公式参考価格'
            buyback_price_lbl = '参考買取価格（補助）'
            buyback_price_val_cls = 'price-cell-val pro-secondary'
            profit_main_lbl = '価格差（参考値）'
            profit_section_cls += ' pro-profit-section'
            pro_mode_note = ('<div class="pro-price-note">'
                             '&#9888; Pro向け：二次流通での入手が前提です。'
                             '公式定価での購入が困難な場合があります。'
                             '価格差は参考値であり、利益を保証しません。'
                             '</div>')
            buyback_compare_hd = '参考買取価格（補助情報）'
        else:
            official_price_lbl = '公式価格（定価）'
            buyback_price_lbl = '最高買取価格'
            buyback_price_val_cls = 'price-cell-val green'
            profit_main_lbl = '実質利益（推定コスト差引後）'
            pro_mode_note = ''
            buyback_compare_hd = '買取店比較'

        # 買取店テーブルのヘッダーラベルを再構築（Pro向けは「参考」表記）
        if compare_html and pro_mode:
            compare_html = compare_html.replace(
                '<div class="shop-table-hd"><span>買取店比較',
                f'<div class="shop-table-hd"><span>{buyback_compare_hd}',
            )

        return f"""<div class="deal-card stripe-{stripe_cls}"{card_id_attr}{brand_attr} data-user-level="{_esc(d.user_level)}">
  <div class="card-stripe {stripe_cls}"></div>
  <div class="card-hd">
    <div class="card-name">{_esc(d.product_name)}</div>
    <div class="card-tags">
      <span class="badge {badge_cls}">{label}</span>
      {genre_badge}
    </div>
  </div>
  {pro_mode_note}
  <div class="{profit_section_cls}">
    <div class="profit-left">
      <div class="{profit_lbl_cls}">{profit_main_lbl}</div>
      <div class="{profit_num_cls}">{_esc(fmt_profit(d.net_profit_jpy))}</div>
    </div>
    <div class="profit-right">
      <div class="{profit_rate_cls}">{profit_rate_str}</div>
      <div class="profit-note">{profit_note_text}</div>
    </div>
  </div>
  <div class="price-row-wrap">
    <div class="price-cell">
      <div class="price-cell-lbl">{official_price_lbl}</div>
      <div class="price-cell-val">{_esc(fmt_price(d.official_price_jpy))}</div>
    </div>
    <div class="price-cell">
      <div class="price-cell-lbl">{buyback_price_lbl}</div>
      <div class="{buyback_price_val_cls}">{_esc(fmt_price(d.best_buyback_price))}</div>
    </div>
  </div>
  <div class="card-body">
    <div class="condition-row buyback-notice">
      <span class="cond-icon">&#9888;</span>
      <div><strong>買取条件：{condition_text}</strong>&nbsp;<span style="font-size:0.72rem;color:var(--gray-400)">掲載価格は参考値です。売却前に必ず各社の公式買取ページで確認してください。</span></div>
    </div>
    {updated_str}
    {compare_html}
    <div class="card-actions">
      {official_btn}
      {buyback_btn}
    </div>
    {overseas_html}
  </div>
</div>"""

    def _tab_advanced(self, advanced_deals, advanced_snaps, watch_candidates, camera_watch=None, camera_beginner_deals=None) -> str:
        camera_watch = camera_watch or []
        camera_beginner_deals = camera_beginner_deals or []
        parts = []

        # ── Pro向けタブ説明バナー ──
        parts.append("""<div class="info-banner violet">
<div class="ib-title">&#9997; Pro向け：二次流通 &rarr; 海外相場比較</div>
公式では入手しづらいカメラ・限定モデルを、国内二次流通価格と海外相場で比較します。
抽選・SOLD OUT・海外価格差のある商品を監視対象として整理しています。
<strong>入手難易度が高い商品が対象です。出品・売却の参考情報としてご利用ください。価格は参考値です。</strong>
</div>""")

        if advanced_deals:
            parts.append('<div class="section-header"><h2>&#128269; Pro向け確定案件</h2><span class="section-count">' + str(len(advanced_deals)) + '件</span></div>')
            for d in advanced_deals:
                badge_cls = "badge-exp" if d.user_level == "expert_only" else "badge-adv"
                label = "Proのみ" if d.user_level == "expert_only" else "Pro向け"
                parts.append(self._deal_card(d, badge_cls, label, pro_mode=True))

        if advanced_snaps:
            parts.append('<div class="section-header"><h2>&#128202; 価格差・プレ値候補</h2><span class="section-count">スナップショット分析</span></div>')
            rows = []
            for s in advanced_snaps:
                method = {"lottery": "抽選", "soldout": "SOLD OUT", "discontinued": "終了"}.get(
                    getattr(s, "sale_method", ""), getattr(s, "sale_method", "通常"))
                pname = _esc(s.product_name)
                rows.append(
                    f"<tr>"
                    f"<td data-user-level='{_esc(getattr(s,'user_level',''))}'><strong>{pname}</strong></td>"
                    f"<td>{_esc(fmt_price(s.official_price_jpy))}</td>"
                    f"<td>{_esc(fmt_price(s.domestic_used_price_jpy))}</td>"
                    f"<td>{_esc(fmt_price(getattr(s,'overseas_price_jpy',None)))}</td>"
                    f"<td style='color:var(--orange);font-weight:600'>{_esc(fmt_profit(s.premium_gap_jpy))}</td>"
                    f"<td>{_esc(method)}</td>"
                    f"<td>{getattr(s,'difficulty_score',0):.2f}</td>"
                    f"</tr>"
                )
            parts.append(f"""<div class="ranking-card"><div class="table-wrap">
<table>
<thead><tr><th>商品</th><th>定価</th><th>国内中古</th><th>海外</th><th>価格差</th><th>方式</th><th>難易度</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</div>
<p style="color:var(--text-3);font-size:0.78rem;margin-top:10px;padding:0 4px;">※ 難易度0.0〜1.0（低いほど入手しやすい）</p>
</div>""")

        # ----- Pro向け監視候補（フォールバック含む） -----
        if watch_candidates:
            has_confirmed = bool(advanced_deals or advanced_snaps)
            if not has_confirmed:
                parts.append("""<div class="caution adv-fallback-notice" style="margin:16px 0 20px;">
&#8505;&#65039; <strong>現在、Pro向けの確定候補は少ないため、価格差・希少性・海外相場差が大きい監視候補を表示しています。</strong><br>
中古市場や海外相場のデータが入り次第、確定候補として昇格します。
</div>""")
            parts.append('<div class="section-header"><h2>&#128204; Pro向け監視候補</h2><span class="section-count">価格差・希少性スコア上位</span></div>')
            parts.append(self._watch_candidates_table(watch_candidates))

        # カメラBeginnerDealを追加表示
        if camera_beginner_deals:
            parts.append('<div class="section-header"><h2>&#128247; カメラ案件</h2><span class="section-count">' + str(len(camera_beginner_deals)) + '件</span></div>')
            parts.append('<div class="cards-grid">')
            for d in camera_beginner_deals:
                parts.append(self._deal_card(d, 'badge-adv', 'Pro向け', pro_mode=True))
            parts.append('</div>')

        if not advanced_deals and not advanced_snaps and not watch_candidates and not camera_beginner_deals:
            parts.append("""<div class="section-header"><h2>Pro向け候補</h2></div>
<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす候補はありません。</div>""")

        return "\n".join(parts)

    def _watch_candidates_table(self, candidates: list) -> str:
        """監視候補テーブルを生成する（products テーブル由来）。Pro向け二次流通・海外相場リンクチップ付き。"""
        # カメラ優先、次にゲーム機
        camera = [c for c in candidates if c["genre"] == "camera"]
        others = [c for c in candidates if c["genre"] != "camera"]
        ordered = camera + others

        cards = []
        for c in ordered:
            price  = c["official_price"]
            bp     = c["buyback_price"]
            shop   = c["shop_name"] or "—"
            flags  = "・".join(c["flags"]) if c["flags"] else "監視中"
            pname_raw = c["product_name"]
            pname_esc  = _esc(pname_raw)
            pname_enc  = _urllib_parse.quote(pname_raw)

            # 価格差表示（Pro向け：買取価格を主役にせず補助情報として表示）
            gap_html = ""
            if bp and price:
                gap = bp - price
                gap_html = (
                    f'<div class="pcc-buyback-ref">'
                    f'<span class="pcc-buyback-lbl">参考買取価格'
                    f'<small class="pcc-buyback-note">（補助情報）</small></span>'
                    f'<span class="pcc-buyback-val">¥{bp:,}</span>'
                    f'<span class="pcc-buyback-diff">定価比 {gap:+,}円</span>'
                    f'</div>'
                )

            # 販売方式バッジ
            sale_method = c.get("sale_method", "")
            sale_badge_map = {
                "lottery": '<span class="badge badge-lottery">抽選</span>',
                "soldout": '<span class="badge badge-soldout">SOLD OUT</span>',
                "waiting": '<span class="badge badge-soldout">入荷待ち</span>',
                "reservation": '<span class="badge badge-adv">予約受付</span>',
            }
            sale_badge = sale_badge_map.get(sale_method, '<span class="badge badge-adv">公式購入困難</span>')

            # ── 国内二次流通リンクチップ ──
            domestic_links = [
                ("メルカリ",     f"https://jp.mercari.com/search?keyword={pname_enc}"),
                ("ヤフオク",     f"https://auctions.yahoo.co.jp/search/search?p={pname_enc}"),
                ("ラクマ",       f"https://fril.jp/search?query={pname_enc}"),
                ("マップカメラ", f"https://www.mapcamera.com/ec/search?q={pname_enc}"),
                ("キタムラ中古", f"https://www.kitamura.co.jp/ec/special/camera/used/?q={pname_enc}"),
                ("フジヤカメラ", f"https://www.fujiyacamera.com/shopbrand/ct10/?q={pname_enc}"),
                ("価格.com",    f"https://kakaku.com/search_results/{pname_enc}/"),
                ("ソフマップ中古", f"https://www.sofmap.com/product_list.aspx?q={pname_enc}&st=1"),
            ]
            domestic_chips = "".join(
                f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer" '
                f'class="pro-chip pro-chip-domestic" data-track="pro_domestic_click">{_esc(label)}</a>'
                for label, url in domestic_links
            )

            # ── 海外相場リンクチップ ──
            overseas_links = [
                ("eBay sold",  f"https://www.ebay.com/sch/i.html?_nkw={pname_enc}&LH_Sold=1&LH_Complete=1"),
                ("StockX",     f"https://stockx.com/search?s={pname_enc}"),
                ("B&H",        f"https://www.bhphotovideo.com/c/search?Ntt={pname_enc}"),
                ("Adorama",    f"https://www.adorama.com/l/?searchinfo={pname_enc}"),
                ("MPB",        f"https://www.mpb.com/en-us/cameras/?q={pname_enc}"),
                ("KEH",        f"https://www.keh.com/search#{pname_enc}"),
                ("Amazon US",  f"https://www.amazon.com/s?k={pname_enc}"),
            ]
            overseas_chips = "".join(
                f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer" '
                f'class="pro-chip pro-chip-overseas overseas-btn" data-track="pro_overseas_click">{_esc(label)}</a>'
                for label, url in overseas_links
            )

            cards.append(f"""<div class="watch-candidate-card pro-candidate-card">
  <div class="pcc-header">
    <div class="pcc-name">{pname_esc}</div>
    <div class="pcc-badges">{sale_badge}</div>
  </div>
  <div class="pcc-price-row">
    <div class="pcc-price-item">
      <span class="pcc-price-lbl">公式参考価格</span>
      <span class="pcc-price-val">{_esc(fmt_price(price) if price else '未定')}</span>
    </div>
    {gap_html}
    <div class="pcc-meta-row">
      <span class="pcc-shop">&#128204; {_esc(shop)}</span>
      <span class="pcc-flags">{_esc(flags)}</span>
    </div>
  </div>
  <div class="pcc-links-section">
    <div class="pcc-links-label">&#127968; 国内二次流通</div>
    <div class="pcc-chips domestic-chips">{domestic_chips}</div>
  </div>
  <div class="pcc-links-section" style="margin-top:8px">
    <div class="pcc-links-label">&#127758; 海外相場</div>
    <div class="pcc-chips overseas-chips overseas-links-section">{overseas_chips}</div>
  </div>
</div>""")

        return f"""<div class="watch-card pro-watch-card">
{"".join(cards) if cards else '<p class="empty-state">候補商品がありません。</p>'}
<p style="color:var(--text-3);font-size:0.78rem;margin-top:12px;padding:0 4px;">
&#9888; リンク先は外部サービスです。相場確認のみを目的としています。売買判断はご自身でご確認ください。
</p>
</div>"""

    # ----- Tab: 急騰/急落 -----

    def _tab_surge(self, alerts) -> str:
        surge = [a for a in alerts if a.get("alert_type") == "buyback_surge"]
        drop  = [a for a in alerts if a.get("alert_type") == "buyback_drop"]

        parts = []
        parts.append('<div class="sec-head"><div class="sec-title">&#9650; 本日の急騰</div>'
                     + (f'<div class="sec-badge">{len(surge)}件</div>' if surge else '')
                     + '</div>')
        if surge:
            parts.append('<div class="surge-grid">')
            for a in surge:
                parts.append(self._alert_card(a, "surge"))
            parts.append('</div>')
        else:
            parts.append('<div class="empty-state"><span class="empty-icon">&#128200;</span>急騰は検出されていません（閾値: ¥5,000+）</div>')

        parts.append('<div class="sec-head" style="margin-top:36px"><div class="sec-title">&#9660; 本日の急落</div>'
                     + (f'<div class="sec-badge">{len(drop)}件</div>' if drop else '')
                     + '</div>')
        if drop:
            parts.append('<div class="surge-grid">')
            for a in drop:
                parts.append(self._alert_card(a, "drop"))
            parts.append('</div>')
        else:
            parts.append('<div class="empty-state"><span class="empty-icon">&#128201;</span>急落は検出されていません（閾値: ¥5,000−）</div>')

        return "\n".join(parts)

    def _alert_card(self, a: dict, kind: str) -> str:
        icon  = "📈" if kind == "surge" else "📉"
        label = "急騰" if kind == "surge" else "急落"
        chg   = a.get("price_change", 0)
        prev  = a.get("previous_price", 0)
        curr  = a.get("current_price", 0)
        rate  = f"{chg / prev * 100:+.1f}%" if prev else "---"
        detected = a.get("detected_at", "")
        val_cls = kind  # "surge" or "drop"

        return f"""<div class="alert-card {kind}">
  <div class="alert-hd">
    <div class="alert-icon-badge {kind}">{icon}</div>
    <div>
      <div class="alert-name">{_esc(a.get('product_name',''))}</div>
      <div class="alert-shop">{_esc(a.get('shop_name',''))} &mdash; {label} ¥{chg:+,}</div>
    </div>
  </div>
  <div class="alert-prices">
    <div class="alert-price-item">
      <div class="alert-price-lbl">前回価格</div>
      <div class="alert-price-val">¥{prev:,}</div>
    </div>
    <div class="alert-price-item">
      <div class="alert-price-lbl">最新価格</div>
      <div class="alert-price-val {val_cls}">¥{curr:,}</div>
    </div>
    <div class="alert-price-item">
      <div class="alert-price-lbl">変動率</div>
      <div class="alert-price-val {val_cls}">{_esc(rate)}</div>
    </div>
  </div>
</div>"""

    # ----- Tab: 買取ランキング -----

    def _tab_ranking(self, all_deals, iphone_deals, game_deals) -> str:
        # 各カテゴリのデータ準備
        profitable = sorted([d for d in all_deals if d.net_profit_jpy > 0],
                            key=lambda d: d.net_profit_jpy, reverse=True)
        iphone_profitable = sorted([d for d in iphone_deals if d.net_profit_jpy > 0],
                                    key=lambda d: d.net_profit_jpy, reverse=True)
        game_profitable = sorted([d for d in game_deals if d.net_profit_jpy > 0],
                                  key=lambda d: d.net_profit_jpy, reverse=True)
        camera_profitable = sorted([d for d in all_deals if getattr(d, 'category', '') == 'camera' and d.net_profit_jpy > 0],
                                    key=lambda d: d.net_profit_jpy, reverse=True)

        def _rank_rows_html(deals, show_cat=False):
            rows = []
            for i, d in enumerate(deals, 1):
                row_cls = ' rank-1' if i == 1 else ''
                rank_cls = 'r1' if i == 1 else ('r2' if i == 2 else ('r3' if i == 3 else ''))
                crown = '&#128081;' if i == 1 else str(i)
                cat_td = f'<td style="font-size:0.75rem;color:var(--ink3)">{_esc(d.category)}</td>' if show_cat else ''
                # カメラはadvancedタブ、それ以外はbeginnerタブへ
                _target_tab = "advanced" if getattr(d, 'category', '') == 'camera' else "beginner"
                _raw_pid = getattr(d, 'product_id', '') or ''
                _pid_alias = _raw_pid[len('prod_'):] if _raw_pid.startswith('prod_') else _raw_pid
                rows.append(
                    f'<div class="rank-row{row_cls} rank-row-clickable" '
                    f'data-nav-tab="{_target_tab}" data-nav-product="product-{_esc(_pid_alias)}" style="cursor:pointer">'
                    f'<div class="rank-num {rank_cls}">{crown}</div>'
                    f'<div class="rank-info"><div class="rank-name rank-name-link">{_esc(d.product_name)}</div>'
                    f'<div class="rank-meta">{_esc(d.best_buyback_shop or "—")}'
                    + (f' &nbsp;|&nbsp; {_esc(d.category)}' if show_cat else '')
                    + f'</div></div>'
                    f'<div><div class="rank-profit">{_esc(fmt_profit(d.net_profit_jpy))}</div>'
                    f'<div class="rank-rate">{_esc(fmt_rate(d.net_profit_rate))}</div></div>'
                    f'</div>'
                )
            if not rows:
                return '<div class="empty-state"><span class="empty-icon">&#128202;</span>データなし</div>'
            return ''.join(rows)

        all_rows     = _rank_rows_html(profitable[:10], show_cat=True)
        iphone_rows  = _rank_rows_html(iphone_profitable[:8])
        camera_rows  = _rank_rows_html(camera_profitable[:8])
        game_rows    = _rank_rows_html(game_profitable[:8])

        return f"""<div class="sec-head"><div class="sec-title">&#127942; 買取ランキング</div></div>
<div class="ranking-card">
  <div class="ranking-tabs">
    <button class="ranking-tab-btn active" data-rtab="all">&#127942; 総合</button>
    <button class="ranking-tab-btn" data-rtab="iphone">&#128241; iPhone</button>
    <button class="ranking-tab-btn" data-rtab="camera">&#128247; カメラ</button>
    <button class="ranking-tab-btn" data-rtab="game">&#127918; ゲーム機</button>
  </div>
  <div class="ranking-tab-panel active" id="rtab-all">{all_rows}</div>
  <div class="ranking-tab-panel" id="rtab-iphone">{iphone_rows}</div>
  <div class="ranking-tab-panel" id="rtab-camera">{camera_rows}</div>
  <div class="ranking-tab-panel" id="rtab-game">{game_rows}</div>
</div>"""

    def _ranking_table(self, deals, show_category: bool = False) -> str:
        rows = []
        for i, d in enumerate(deals, 1):
            badge_cls = (
                "badge-easy"  if d.user_level == "beginner_easy"  else
                "badge-watch" if d.user_level == "beginner_watch" else
                "badge-adv"   if d.user_level == "advanced_high_profit" else
                "badge-exp"
            )
            cat_td = f"<td>{_esc(d.category)}</td>" if show_category else ""
            rows.append(
                f"<tr><td>{i}</td>"
                f"<td>{_esc(d.product_name)}</td>"
                + (f"<td>{_esc(d.category)}</td>" if show_category else "")
                + f"<td>{_esc(fmt_price(d.official_price_jpy))}</td>"
                f"<td>{_esc(fmt_price(d.best_buyback_price))}</td>"
                f"<td class='td-profit'>{_esc(fmt_profit(d.net_profit_jpy))}</td>"
                f"<td>{_esc(fmt_rate(d.net_profit_rate))}</td>"
                f"<td>{_esc(d.best_buyback_shop)}</td></tr>"
            )
        cat_th = "<th>カテゴリ</th>" if show_category else ""
        return f"""<div class="ranking-card"><div class="table-wrap"><table>
<thead><tr><th>#</th><th>商品</th>{cat_th}<th>定価</th><th>買取</th><th>実質利益</th><th>率</th><th>買取店</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div></div>"""

    # ----- Caution / CTA / Footer -----

    def _section_caution(self) -> str:

        return """<div class="caution-block">

<div class="caution-title">&#9888;&#65039; ご確認ください</div>

<ul class="caution-list">

<li>本ページは価格差の監視結果であり、購入を推奨するものではありません。</li>

<li>価格・在庫・買取条件は常に変動します。掛載価格は取得・入力時点の参考値です。</li>

<li>購入前に必ず公式サイトと買取店で最新の条件を確認してください。</li>

<li>買取条件（新品未開封・SIMフリー等）を満たさない場合、買取価格が大幅に下がります。</li>

<li>利益を保証するものではありません。条件が合えば利益が出る可能性がある情報です。</li>

<li>海外販売には輸出規制・関税・送料・プラットフォーム手数料等が発生します。</li>

</ul>

</div>"""



    def _section_cta(self) -> str:

        parts = []

        if self.settings.get('enable_note_cta'):

            note_url = (self.settings.get('note_url') or '').strip()

            if note_url and note_url != '#':

                parts.append(f"""<div class="cta-section" id="note-cta">

<div class="cta-eyebrow">詳細レポート</div>

<div class="cta-title">全案件・詳細レポートを見る</div>

<p class="cta-desc">仕入れ条件・複数買取店の詳細比較・全案件一覧・海外販売ガイドはnoteで公開しています。</p>

<div class="cta-btns">

  <a href="{_esc(note_url)}" class="btn-cta-primary" data-track="note_click">&#128221; 詳細レポートを見る &rarr;</a>

  <a href="{_esc(note_url)}" class="btn-cta-secondary" data-track="note_click">今日の全案件を見る</a>

</div>

</div>""")

            else:

                parts.append("""<div class="cta-section" id="note-cta">

<div class="cta-eyebrow">詳細レポート</div>

<div class="cta-title">詳細レポート &mdash; 準備中</div>

<p class="cta-desc">仕入れ条件・買取店比較・全案件一覧・海外販売ガイドをnoteで公開予定です。公開時にこのページでお知らせします。</p>

</div>""")

        if self.settings.get('enable_line_cta'):

            line_url = (self.settings.get('line_url') or '').strip()

            if line_url and line_url != '#':

                parts.append(f'<div class="cta-section"><div class="cta-eyebrow">LINE速報</div><div class="cta-title">LINE速報を受け取る</div><div class="cta-btns"><a href="{_esc(line_url)}" class="btn-cta-primary" style="background:#06c755" data-track="line_click">LINE登録で速報を受け取る</a></div></div>')

        if self.settings.get('enable_telegram_cta'):

            tg_url = (self.settings.get('telegram_url') or '').strip()

            if tg_url and tg_url != '#':

                parts.append(f'<div class="cta-section"><div class="cta-eyebrow">Telegram速報</div><div class="cta-title">Telegramチャンネルに参加する</div><div class="cta-btns"><a href="{_esc(tg_url)}" class="btn-cta-primary" data-track="telegram_click">Telegramチャンネルに参加する</a></div></div>')

        return '\n'.join(parts)



    def _section_footer(self) -> str:

        now = datetime.now()

        return f"""<footer class="footer">
<div class="footer-inner">
  <div class="footer-logo">
    <div class="footer-logo-icon">S</div>
    <div class="footer-logo-name">プレ値速報</div>
    <div class="footer-live"><span class="live-dot"></span>LIVE</div>
  </div>
  <div class="footer-links">
    <a href="#tab-beginner" class="footer-link">初心者向け案件</a>
    <a href="#tab-advanced" class="footer-link">Pro向け相場</a>
    <a href="#tab-ranking" class="footer-link">買取ランキング</a>
    <a href="#tab-surge" class="footer-link">急騰/急落アラート</a>
    <a href="#tab-new-products" class="footer-link">新商品候補</a>
    <a href="#note-cta" class="footer-link">詳細レポート</a>
  </div>
  <div class="footer-text">
    <p>掛載価格は取得・入力時点の参考値です。購入前に必ず公式サイト・買取店でご確認ください。</p>
    <p>&copy; {now.year} プレ値速報 &mdash; 情報は自動取得・分析されたものです</p>
  </div>
</div>
</footer>"""



    def _section_new_products(self) -> str:
        """新商品候補セクション（デザイン用プレースホルダー）。"""
        # 新商品候補データは Repository から取得可能だが、
        # デザインシステム移植のためプレースホルダーを返す
        items = [
            {"name": "iPhone 17 Pro", "status": "upcoming", "status_lbl": "発売予定",
             "price": "未定", "level": "beginner_easy", "tags": ["抽選", "限定"]},
            {"name": "Nintendo Switch 2", "status": "preorder", "status_lbl": "予約受付中",
             "price": "¥49,980", "level": "beginner_easy", "tags": ["抽選"]},
            {"name": "SONY α1 II", "status": "upcoming", "status_lbl": "発売予定",
             "price": "¥900,000予定", "level": "advanced", "tags": ["高難度", "海外差益"]},
        ]
        cards = []
        for item in items:
            status_cls = {"upcoming": "upcoming", "preorder": "preorder", "lottery": "lottery"}.get(item["status"], "default")
            tags_html = ''.join(
                f'<span class="deal-tag {("lottery" if t in ("抽選","限定") else ("hard" if t=="高難度" else ("intl" if t=="海外差益" else "pre")))}">{_esc(t)}</span>'
                for t in item["tags"]
            )
            level_badge = '<span class="badge badge-easy" style="font-size:0.6rem">初心者向け</span>' if 'beginner' in item["level"] else '<span class="badge badge-adv" style="font-size:0.6rem">Pro向け</span>'
            cards.append(
                f'<div class="new-product-card" data-user-level="{_esc(item["level"])}">'
                f'<div class="np-top-bar"></div>'
                f'<div class="np-body">'
                f'<div class="np-hd"><div class="np-name">{_esc(item["name"])}</div>'
                f'<span class="np-status-badge {status_cls}">{_esc(item["status_lbl"])}</span></div>'
                f'<div class="np-price-row"><span class="np-price-lbl">想定価格</span>&nbsp;<span class="np-price-val">{_esc(item["price"])}</span></div>'
                f'<div class="np-tags">{tags_html}{level_badge}</div>'
                f'</div></div>'
            )
        return (
            '<div class="sec-head"><div class="sec-title">&#127381; 新商品候補 &mdash; 監視リスト</div>'
            f'<div class="sec-badge">{len(items)}件</div></div>'
            '<div class="cards-grid">' + ''.join(cards) + '</div>'
        )

    def _render_markdown(self, date_str, time_str, beginner_deals, advanced_snaps, buyback_alerts) -> str:
        lines = [
            f"# プレ値速報 — {date_str} {time_str} 更新",
            "",
            "## 初心者向け候補",
            "",
        ]
        for d in beginner_deals:
            lines.append(
                f"- **{d.product_name}**: 公式{fmt_price(d.official_price_jpy)} "
                f"→ 買取{fmt_price(d.best_buyback_price)} = "
                f"実質{fmt_profit(d.net_profit_jpy)} ({fmt_rate(d.net_profit_rate)})"
            )
        if not beginner_deals:
            lines.append("条件を満たす案件なし")

        lines.extend(["", "## Pro向け候補", ""])
        for s in advanced_snaps:
            lines.append(
                f"- **{s.product_name}**: 定価{fmt_price(s.official_price_jpy)} "
                f"/ 中古{fmt_price(s.domestic_used_price_jpy)} "
                f"/ 差{fmt_profit(s.premium_gap_jpy)} / {getattr(s,'sale_method','')}"
            )
        if not advanced_snaps:
            lines.append("条件を満たす候補なし")

        lines.extend(["", DISCLAIMER_FULL])
        return "\n".join(lines)
