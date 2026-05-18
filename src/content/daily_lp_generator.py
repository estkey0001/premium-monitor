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
                     buyback_by_product: dict = None) -> str:

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

        # セクション生成
        hero_html    = self._section_hero(date_str, time_str, latest_buyback_at, lp_generated_at,
                                           all_deals=all_deals, iphone_deals=iphone_deals,
                                           camera_deals=camera_deals or [], game_deals=game_deals)
        stale_html   = self._section_stale_warning(latest_buyback_at, latest_deals_at, lp_generated_at)
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
        )
        caution_html = self._section_caution()
        cta_html     = self._section_cta()
        footer_html  = self._section_footer()

        # topbar用の日時文字列（_render_page スコープで利用）
        _buyback_str_top = _jst_str(latest_buyback_at) if latest_buyback_at else "—"
        _lp_str_top = lp_generated_at.strftime("%m/%d %H:%M") if lp_generated_at else "—"

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
   プレ値速報 — PROFESSIONAL EDITION
   コンセプト: このLP一枚で稼げる
   ============================================================ */

:root {{
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
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 8px rgba(0,0,0,0.06), 0 2px 4px rgba(0,0,0,0.04);
  --shadow-lg: 0 10px 20px rgba(0,0,0,0.08), 0 4px 8px rgba(0,0,0,0.04);
  --shadow-xl: 0 20px 40px rgba(0,0,0,0.10), 0 8px 16px rgba(0,0,0,0.06);
}}

*, *::before, *::after {{
  margin: 0; padding: 0;
  box-sizing: border-box;
  -webkit-font-smoothing: antialiased;
}}

html {{ scroll-behavior: smooth; }}

body {{
  font-family: var(--font);
  background: var(--gray-50);
  color: var(--gray-900);
  font-size: 15px;
  line-height: 1.6;
}}

/* ============================================================
   TOPBAR
   ============================================================ */
.topbar {{
  position: sticky; top: 0; z-index: 300;
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--gray-200);
  height: 56px;
  display: flex; align-items: center;
  padding: 0 20px; gap: 12px;
}}

.topbar-brand {{
  display: flex; align-items: center; gap: 10px;
  text-decoration: none; color: var(--gray-900);
  font-weight: 800; font-size: 0.95rem;
}}

.brand-icon {{
  width: 30px; height: 30px;
  background: linear-gradient(135deg, var(--blue-600), var(--purple-600));
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: white; font-weight: 900; font-size: 0.8rem;
  box-shadow: 0 2px 8px rgba(37,99,235,0.3);
  flex-shrink: 0;
}}

.topbar-live {{
  display: flex; align-items: center; gap: 5px;
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--green-600);
  background: var(--green-50);
  border: 1px solid var(--green-200);
  padding: 3px 10px; border-radius: 99px;
}}

.live-dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green-500);
  animation: blink 2s ease-in-out infinite;
}}

@keyframes blink {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.3; }}
}}

.topbar-date {{
  font-size: 0.78rem; color: var(--gray-500);
  font-variant-numeric: tabular-nums;
}}

.topbar-spacer {{ flex: 1; }}

.topbar-note-btn {{
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--blue-600); color: white;
  font-size: 0.78rem; font-weight: 700;
  padding: 7px 16px; border-radius: var(--radius-md);
  text-decoration: none;
  box-shadow: 0 2px 8px rgba(37,99,235,0.25);
  transition: all 0.2s;
  white-space: nowrap;
}}

.topbar-note-btn:hover {{
  background: var(--blue-700);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(37,99,235,0.35);
}}

/* ============================================================
   HERO
   ============================================================ */
.hero {{
  background: var(--white);
  border-bottom: 1px solid var(--gray-200);
  padding: 52px 0 44px;
}}

.hero-inner {{
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px;
}}

.hero-badge {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--blue-600);
  background: var(--blue-50);
  border: 1px solid var(--blue-200);
  padding: 5px 14px; border-radius: 99px;
  margin-bottom: 22px;
}}

.hero-title {{
  font-size: clamp(1.9rem, 4.5vw, 3rem);
  font-weight: 900;
  letter-spacing: -0.04em;
  line-height: 1.1;
  color: var(--gray-900);
  margin-bottom: 18px;
}}

.hero-title .accent {{
  color: var(--blue-600);
}}

.hero-subtitle {{
  font-size: 1.05rem;
  color: var(--gray-600);
  line-height: 1.75;
  max-width: 680px;
  margin-bottom: 36px;
}}

/* Hero Stats */
.hero-stats {{
  display: flex; flex-wrap: wrap; gap: 12px;
  margin-bottom: 32px;
}}

.stat-card {{
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-lg);
  padding: 14px 20px;
  min-width: 120px;
  box-shadow: var(--shadow-xs);
  transition: box-shadow 0.2s, transform 0.2s;
}}

.stat-card:hover {{
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}}

.stat-value {{
  font-size: 1.6rem; font-weight: 900;
  line-height: 1; margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
}}

.stat-value.green  {{ color: var(--green-600); }}
.stat-value.blue   {{ color: var(--blue-600); }}
.stat-value.purple {{ color: var(--purple-600); }}
.stat-value.teal   {{ color: var(--teal-600); }}
.stat-value.amber  {{ color: var(--amber-600); font-size: 1.1rem; }}

.stat-label {{
  font-size: 0.68rem; font-weight: 700;
  letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--gray-400);
}}

/* Timestamps */
.hero-timestamps {{
  display: flex; flex-wrap: wrap; gap: 10px;
}}

.ts-pill {{
  display: inline-flex; align-items: center; gap: 7px;
  background: var(--white);
  border: 1px solid var(--gray-200);
  color: var(--gray-500);
  font-size: 0.78rem;
  padding: 6px 14px; border-radius: 99px;
  box-shadow: var(--shadow-xs);
  font-variant-numeric: tabular-nums;
}}

.ts-dot {{
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--green-500); flex-shrink: 0;
}}

.ts-dot.blue {{ background: var(--blue-500); }}

/* ============================================================
   STALE WARNING
   ============================================================ */
.stale-banner {{
  background: var(--amber-50);
  border: 1px solid var(--amber-200);
  border-left: 3px solid var(--amber-500);
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
   TAB NAVIGATION
   ============================================================ */
.tab-wrap {{
  position: sticky; top: 56px; z-index: 200;
  background: rgba(248,250,252,0.96);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--gray-200);
  margin: 0 -24px;
  padding: 0 24px;
}}

.tab-nav {{
  display: flex; gap: 0;
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}}

.tab-nav::-webkit-scrollbar {{ display: none; }}

.tab-btn {{
  flex-shrink: 0;
  display: flex; align-items: center; gap: 7px;
  background: transparent; border: none;
  border-bottom: 2px solid transparent;
  padding: 15px 20px;
  font-size: 0.875rem; font-weight: 500;
  color: var(--gray-500);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  margin-bottom: -1px;
  white-space: nowrap;
  font-family: var(--font);
}}

.tab-btn:hover {{ color: var(--gray-800); }}

.tab-btn.active {{
  color: var(--blue-600);
  border-bottom-color: var(--blue-600);
  font-weight: 700;
}}

.tab-count {{
  font-size: 0.65rem; font-weight: 800;
  background: var(--gray-100);
  color: var(--gray-500);
  padding: 1px 7px; border-radius: 99px;
}}

.tab-btn.active .tab-count {{
  background: var(--blue-50);
  color: var(--blue-600);
}}

.tab-panel {{ display: none; padding-top: 36px; }}
.tab-panel.active {{ display: block; }}

/* ============================================================
   SECTION HEADER
   ============================================================ */
.sec-head {{
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 20px; padding-bottom: 14px;
  border-bottom: 1px solid var(--gray-200);
}}

.sec-title {{
  font-size: 0.78rem; font-weight: 800;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--gray-500);
  display: flex; align-items: center; gap: 8px;
}}

.sec-title::before {{
  content: '';
  width: 3px; height: 14px; border-radius: 2px;
  background: var(--blue-600);
}}

.sec-badge {{
  font-size: 0.68rem; font-weight: 700;
  background: var(--gray-100);
  color: var(--gray-500);
  border: 1px solid var(--gray-200);
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
  background: var(--blue-50);
  border: 1px solid var(--blue-200);
  color: #1e40af;
}}

.info-banner.purple {{
  background: var(--purple-50);
  border: 1px solid var(--purple-100);
  color: #5b21b6;
}}

.info-banner.teal {{
  background: var(--teal-50);
  border: 1px solid var(--teal-100);
  color: #0f766e;
}}

.info-banner strong {{ font-weight: 800; }}

/* ============================================================
   DEAL CARDS GRID
   ============================================================ */
.cards-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
  gap: 18px;
}}

/* ============================================================
   DEAL CARD
   ============================================================ */
.deal-card {{
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.25s, transform 0.25s, border-color 0.25s;
  display: flex; flex-direction: column;
}}

.deal-card:hover {{
  box-shadow: var(--shadow-xl);
  transform: translateY(-3px);
  border-color: var(--gray-300);
}}

/* Category top stripe */
.card-stripe {{ height: 3px; }}
.card-stripe.iphone   {{ background: linear-gradient(90deg, var(--blue-500), var(--blue-300)); }}
.card-stripe.camera   {{ background: linear-gradient(90deg, var(--purple-500), var(--purple-300)); }}
.card-stripe.game     {{ background: linear-gradient(90deg, var(--teal-500), var(--teal-300)); }}
.card-stripe.default  {{ background: linear-gradient(90deg, var(--blue-500), var(--green-500)); }}

/* Card Header */
.card-hd {{
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 12px;
  padding: 18px 20px 14px;
}}

.card-name {{
  font-size: 1rem; font-weight: 800;
  color: var(--gray-900); line-height: 1.3; flex: 1;
}}

.card-tags {{
  display: flex; gap: 5px; flex-shrink: 0;
  flex-wrap: wrap; justify-content: flex-end;
}}

/* Profit Section */
.profit-section {{
  margin: 0 20px;
  padding: 16px 18px;
  background: var(--green-50);
  border: 1px solid var(--green-200);
  border-radius: var(--radius-md);
  display: flex; align-items: center;
  justify-content: space-between; gap: 12px;
}}

.profit-section.amber {{
  background: var(--amber-50);
  border-color: var(--amber-200);
}}

.profit-left {{}}

.profit-lbl {{
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--green-700); margin-bottom: 4px;
}}

.profit-lbl.amber {{ color: var(--amber-600); }}

.profit-num {{
  font-size: 2.1rem; font-weight: 900;
  color: var(--green-600);
  letter-spacing: -0.04em; line-height: 1;
}}

.profit-num.amber {{ color: var(--amber-600); }}

.profit-right {{ text-align: right; }}

.profit-rate {{
  display: inline-block;
  font-size: 0.9rem; font-weight: 800;
  color: var(--green-700);
  background: var(--green-100);
  padding: 4px 12px; border-radius: var(--radius-sm);
  margin-bottom: 5px;
}}

.profit-rate.amber {{
  color: var(--amber-700);
  background: var(--amber-100);
}}

.profit-note {{
  font-size: 0.7rem; color: var(--gray-400);
}}

/* Price Row */
.price-row-wrap {{
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1px; background: var(--gray-200);
  margin: 14px 20px 0;
  border-radius: var(--radius-md); overflow: hidden;
}}

.price-cell {{
  background: var(--white); padding: 12px 14px;
}}

.price-cell-lbl {{
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--gray-400); margin-bottom: 5px;
}}

.price-cell-val {{
  font-size: 1.05rem; font-weight: 800;
  color: var(--gray-900); font-variant-numeric: tabular-nums;
}}

.price-cell-val.green {{ color: var(--green-600); }}

/* Card Body */
.card-body {{ padding: 14px 20px 20px; flex: 1; }}

.condition-row {{
  display: flex; align-items: flex-start; gap: 7px;
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-sm);
  padding: 8px 12px; margin-bottom: 12px;
  font-size: 0.8rem; color: var(--gray-600);
  line-height: 1.5;
}}

.cond-icon {{ color: var(--amber-500); flex-shrink: 0; margin-top: 1px; }}

.updated-row {{
  font-size: 0.72rem; color: var(--gray-400);
  margin-bottom: 12px;
  display: flex; align-items: center; gap: 5px;
}}

/* Shop Compare Table */
.shop-table {{
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-md);
  overflow: hidden; margin-bottom: 14px;
}}

.shop-table-hd {{
  display: flex; align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--gray-50);
  border-bottom: 1px solid var(--gray-200);
  font-size: 0.65rem; font-weight: 800;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--gray-500);
}}

.shop-row {{
  display: flex; align-items: center;
  padding: 9px 14px;
  border-bottom: 1px solid var(--gray-100);
  gap: 10px; font-size: 0.875rem;
  transition: background 0.1s;
}}

.shop-row:last-child {{ border: none; }}
.shop-row:hover {{ background: var(--gray-50); }}

.shop-rank {{
  min-width: 22px; font-size: 0.72rem;
  font-weight: 800; text-align: center;
  color: var(--gray-400);
}}

.shop-rank.gold {{ color: #b45309; }}
.shop-rank.silver {{ color: var(--gray-500); }}

.shop-name-col {{ flex: 1; color: var(--gray-700); }}

.shop-name-col a {{
  color: var(--blue-600); text-decoration: none;
  font-weight: 600;
}}

.shop-name-col a:hover {{ text-decoration: underline; }}

.shop-price-col {{
  font-weight: 800; color: var(--gray-900);
  font-variant-numeric: tabular-nums;
  text-align: right; min-width: 80px;
}}

.shop-diff-col {{
  font-size: 0.78rem; font-weight: 700;
  color: var(--green-600);
  text-align: right; min-width: 68px;
}}

.shop-diff-col.neg {{ color: var(--red-500); }}

/* Freshness */
.fresh-live   {{ color: var(--green-600); font-size: 0.7rem; font-weight: 700; }}
.fresh-recent {{ color: var(--amber-600); font-size: 0.7rem; font-weight: 700; }}
.fresh-stale  {{ color: var(--red-500);   font-size: 0.7rem; font-weight: 700; }}

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
  background: var(--blue-600); color: white;
  border-color: var(--blue-600);
  box-shadow: 0 2px 6px rgba(37,99,235,0.2);
}}

.btn-primary:hover {{
  background: var(--blue-700); border-color: var(--blue-700);
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(37,99,235,0.3);
}}

.btn-secondary {{
  background: white; color: var(--blue-600);
  border-color: var(--blue-200);
}}

.btn-secondary:hover {{
  background: var(--blue-50); border-color: var(--blue-400);
}}

.btn-ghost {{
  background: var(--gray-50); color: var(--gray-700);
  border-color: var(--gray-200);
}}

.btn-ghost:hover {{
  background: white; color: var(--gray-900);
  border-color: var(--gray-300);
}}

/* Overseas Links */
.overseas-section {{
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid var(--gray-100);
}}

.overseas-lbl {{
  font-size: 0.65rem; font-weight: 800;
  letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--gray-400); margin-bottom: 8px;
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

.badge-easy    {{ background: var(--green-50);  color: var(--green-700);  border: 1px solid var(--green-200); }}
.badge-watch   {{ background: var(--amber-50);  color: var(--amber-700);  border: 1px solid var(--amber-200); }}
.badge-adv     {{ background: var(--purple-50); color: var(--purple-600); border: 1px solid var(--purple-100); }}
.badge-iphone  {{ background: var(--blue-50);   color: var(--blue-700);   border: 1px solid var(--blue-200); }}
.badge-camera  {{ background: var(--purple-50); color: var(--purple-600); border: 1px solid var(--purple-100); }}
.badge-game    {{ background: var(--teal-50);   color: var(--teal-600);   border: 1px solid var(--teal-100); }}
.badge-lottery {{ background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
.badge-soldout {{ background: var(--red-50); color: var(--red-600); border: 1px solid var(--red-100); }}
.badge-overseas{{ background: #f0f9ff; color: #0369a1; border: 1px solid #bae6fd; }}
.badge-used    {{ background: var(--gray-100); color: var(--gray-700); border: 1px solid var(--gray-300); }}

/* ============================================================
   WATCH CARD (上級者向け)
   ============================================================ */
.watch-card {{
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-xl);
  padding: 20px 22px;
  margin-bottom: 14px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.2s, transform 0.2s;
}}

.watch-card:hover {{
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}}

.watch-card-hd {{
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 12px;
  margin-bottom: 14px;
}}

.watch-name {{
  font-size: 1rem; font-weight: 800;
  color: var(--gray-900); flex: 1;
}}

.watch-price-grid {{
  display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 10px; margin-bottom: 14px;
}}

.watch-price-item {{}}

.watch-price-lbl {{
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--gray-400); margin-bottom: 4px;
}}

.watch-price-val {{
  font-size: 1rem; font-weight: 800;
  color: var(--gray-900); font-variant-numeric: tabular-nums;
}}

.watch-price-val.green  {{ color: var(--green-600); }}
.watch-price-val.red    {{ color: var(--red-500); }}
.watch-price-val.purple {{ color: var(--purple-600); }}

.gap-badge {{
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 0.78rem; font-weight: 800;
  padding: 4px 10px; border-radius: var(--radius-xs, 4px);
}}

.gap-pos {{ background: var(--green-50); color: var(--green-700); }}
.gap-neg {{ background: var(--red-50);   color: var(--red-600); }}
.gap-neu {{ background: var(--gray-100); color: var(--gray-600); }}

/* How-to box */
.howto-box {{
  background: var(--gray-50);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-md);
  padding: 12px 14px;
  margin-bottom: 14px;
  font-size: 0.82rem;
  color: var(--gray-700);
  line-height: 1.7;
}}

.howto-box strong {{ color: var(--gray-900); }}

.howto-step {{
  display: flex; align-items: flex-start; gap: 8px;
  margin-top: 8px;
}}

.step-num {{
  flex-shrink: 0;
  width: 20px; height: 20px;
  background: var(--blue-600); color: white;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.68rem; font-weight: 800;
  margin-top: 1px;
}}

.step-text {{ flex: 1; }}

/* ============================================================
   RANKING
   ============================================================ */
.ranking-card {{
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-xl);
  overflow: hidden; margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
}}

.ranking-hd {{
  padding: 14px 20px;
  border-bottom: 1px solid var(--gray-200);
  background: var(--gray-50);
  display: flex; align-items: center; gap: 8px;
  font-size: 0.875rem; font-weight: 800; color: var(--gray-800);
}}

.rank-row {{
  display: flex; align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid var(--gray-100);
  gap: 14px; transition: background 0.1s;
}}

.rank-row:last-child {{ border: none; }}
.rank-row:hover {{ background: var(--gray-50); }}

.rank-num {{
  font-size: 1.1rem; font-weight: 900;
  color: var(--gray-300); min-width: 28px; text-align: center;
}}

.rank-num.r1 {{ color: #b45309; }}
.rank-num.r2 {{ color: var(--gray-400); }}
.rank-num.r3 {{ color: #92400e; }}

.rank-info {{ flex: 1; }}
.rank-name {{ font-weight: 700; color: var(--gray-900); font-size: 0.9rem; }}
.rank-meta {{ font-size: 0.72rem; color: var(--gray-400); margin-top: 2px; }}

.rank-profit {{
  font-size: 1.1rem; font-weight: 900;
  color: var(--green-600); font-variant-numeric: tabular-nums;
  text-align: right;
}}

.rank-rate {{
  font-size: 0.72rem; color: var(--gray-400);
  text-align: right; margin-top: 2px;
}}

/* ============================================================
   ALERT CARDS
   ============================================================ */
.alert-card {{
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-xl);
  padding: 18px 20px; margin-bottom: 12px;
  box-shadow: var(--shadow-sm);
}}

.alert-card.surge {{
  border-left: 3px solid var(--green-500);
  background: var(--green-50);
}}

.alert-card.drop {{
  border-left: 3px solid var(--red-500);
  background: var(--red-50);
}}

/* ============================================================
   EMPTY STATE
   ============================================================ */
.empty-state {{
  text-align: center; padding: 56px 24px;
  color: var(--gray-400); font-size: 0.9rem;
}}

.empty-icon {{
  font-size: 2.5rem; margin-bottom: 14px;
  opacity: 0.3; display: block;
}}

/* ============================================================
   CAUTION
   ============================================================ */
.caution-block {{
  background: var(--amber-50);
  border: 1px solid var(--amber-200);
  border-left: 3px solid var(--amber-500);
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  padding: 20px 24px; margin: 48px 0;
  font-size: 0.875rem; color: #78350f; line-height: 1.8;
}}

.caution-title {{
  font-weight: 800; color: var(--amber-700);
  margin-bottom: 10px; font-size: 0.9rem;
  display: flex; align-items: center; gap: 6px;
}}

.caution-list {{ list-style: none; padding: 0; }}
.caution-list li {{ padding: 2px 0 2px 14px; position: relative; }}
.caution-list li::before {{
  content: "·"; position: absolute; left: 4px;
  color: var(--amber-500);
}}

/* ============================================================
   CTA
   ============================================================ */
.cta-section {{
  background: var(--white);
  border: 1px solid var(--gray-200);
  border-radius: var(--radius-2xl);
  padding: 44px 40px;
  text-align: center; margin: 48px 0;
  box-shadow: var(--shadow-md);
  position: relative; overflow: hidden;
}}

.cta-section::before {{
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--blue-500), var(--purple-500), var(--green-500));
}}

.cta-eyebrow {{
  font-size: 0.68rem; font-weight: 800;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--blue-600); margin-bottom: 14px;
}}

.cta-title {{
  font-size: 1.5rem; font-weight: 900;
  color: var(--gray-900); margin-bottom: 10px;
  letter-spacing: -0.02em;
}}

.cta-desc {{
  font-size: 0.95rem; color: var(--gray-600);
  max-width: 460px; margin: 0 auto 28px; line-height: 1.75;
}}

.cta-btns {{
  display: flex; justify-content: center;
  gap: 12px; flex-wrap: wrap;
}}

.btn-cta-primary {{
  display: inline-flex; align-items: center; gap: 7px;
  background: var(--blue-600); color: white;
  font-size: 0.95rem; font-weight: 800;
  padding: 14px 30px; border-radius: var(--radius-md);
  text-decoration: none; border: none; cursor: pointer;
  box-shadow: 0 4px 14px rgba(37,99,235,0.3);
  transition: all 0.2s; font-family: var(--font);
}}

.btn-cta-primary:hover {{
  background: var(--blue-700);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(37,99,235,0.4);
}}

.btn-cta-secondary {{
  display: inline-flex; align-items: center; gap: 7px;
  background: white; color: var(--gray-700);
  font-size: 0.95rem; font-weight: 700;
  padding: 14px 30px; border-radius: var(--radius-md);
  text-decoration: none; border: 1px solid var(--gray-300);
  transition: all 0.2s; font-family: var(--font);
}}

.btn-cta-secondary:hover {{
  background: var(--gray-50); color: var(--gray-900);
  border-color: var(--gray-400);
}}

/* ============================================================
   FOOTER
   ============================================================ */
.footer {{
  border-top: 1px solid var(--gray-200);
  padding: 36px 0 24px;
  text-align: center; margin-top: 48px;
}}

.footer-text {{
  font-size: 0.78rem; color: var(--gray-400);
  line-height: 2.2;
}}

/* ============================================================
   RESPONSIVE
   ============================================================ */
@media (max-width: 768px) {{
  .hero {{ padding: 40px 0 36px; }}
  .hero-title {{ font-size: 1.8rem; }}
  .hero-subtitle {{ font-size: 0.95rem; }}
  .cards-grid {{ grid-template-columns: 1fr; }}
  .profit-num {{ font-size: 1.8rem; }}
  .profit-section {{ flex-direction: column; gap: 8px; }}
  .profit-right {{ text-align: left; }}
  .tab-btn {{ padding: 13px 14px; font-size: 0.82rem; }}
  .card-hd {{ padding: 14px 16px 12px; }}
  .card-body {{ padding: 12px 16px 18px; }}
  .profit-section {{ margin: 0 16px; padding: 14px 16px; }}
  .price-row-wrap {{ margin: 12px 16px 0; }}
  .cta-section {{ padding: 32px 24px; }}
  .topbar-note-btn {{ display: none; }}
  .shop-diff-col {{ display: none; }}
  .topbar-date {{ display: none; }}
  .watch-price-grid {{ grid-template-columns: 1fr 1fr; }}
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
  .hero-stats {{ gap: 8px; }}
  .stat-card {{ padding: 10px 14px; min-width: 90px; }}
  .stat-value {{ font-size: 1.3rem; }}
}}

/* noscript */
.noscript-all .tab-panel {{ display: block !important; }}
.noscript-all .tab-nav {{ display: none; }}
</style>

</head>
<body>
<header class="topbar">
  <a href="/" class="topbar-brand">
    <div class="brand-icon">P</div>
    プレ値速報
  </a>
  <div class="topbar-live"><span class="live-dot"></span>LIVE</div>
  <div class="topbar-date" data-buyback-updated>買取更新: {_esc(_buyback_str_top)}</div>
  <div class="topbar-spacer"></div>
  <a href="#note-cta" class="topbar-note-btn" data-track="note_click">&#128221; 詳細レポートを見る</a>
</header>
{hero_html}
{stale_html}
<div class="main-wrap">
{tab_html}
{caution_html}
{cta_html}
{footer_html}
</div>
<script>
(function(){{
  var btns=document.querySelectorAll(".tab-btn");
  var panels=document.querySelectorAll(".tab-panel");
  if(btns.length){{
    btns.forEach(function(btn){{
      btn.addEventListener("click",function(){{
        btns.forEach(function(b){{b.classList.remove("active");b.setAttribute("aria-selected","false");}});
        panels.forEach(function(p){{p.classList.remove("active");}});
        btn.classList.add("active");
        btn.setAttribute("aria-selected","true");
        var panel=document.getElementById("tab-"+btn.dataset.tab);
        if(panel)panel.classList.add("active");
      }});
    }});
  }}
  document.addEventListener("click",function(e){{
    var el=e.target.closest("[data-track]");
    if(!el)return;
    var ev=el.getAttribute("data-track"),pid=el.getAttribute("data-product-id")||"",shop=el.getAttribute("data-shop")||"";
    if(typeof gtag==="function")gtag("event",ev,{{product_id:pid,shop:shop}});
    if(typeof fbq==="function")fbq("trackCustom",ev,{{product_id:pid,shop:shop}});
  }});
}})();
document.addEventListener("click",function(e){{
  var t=e.target.closest("[data-track]");
  if(!t)return;
  var ev=t.getAttribute("data-track"),
      pid=t.getAttribute("data-product-id")||"",
      shop=t.getAttribute("data-shop")||"";
  if(typeof gtag==="function")gtag("event",ev,{{product_id:pid,shop:shop}});
  if(typeof fbq==="function")fbq("trackCustom",ev,{{product_id:pid,shop:shop}});
}});
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

    <div class="hero-badge"><span>&#9679;</span> 毎日更新 &mdash; {_esc(date_str)}</div>

    <h1 class="hero-title">今日の<span class="accent">価格差</span>で稼ぐ。<br>公式価格 &times; 買取相場 &times; 海外相場。</h1>

    <p class="hero-subtitle">iPhone・カメラ・ゲーム機の公式価格と買取価格の差額を毎日更新。初心者向けの低難度案件から、上級者向けの中古市場差額・海外相場まで、このページ一枚で行動できます。</p>

    <div class="hero-stats">

      <div class="stat-card"><div class="stat-value green">{all_count}</div><div class="stat-label">本日の案件</div></div>

      <div class="stat-card"><div class="stat-value blue">{iphone_count}</div><div class="stat-label">iPhone</div></div>

      <div class="stat-card"><div class="stat-value purple">{camera_count}</div><div class="stat-label">カメラ</div></div>

      <div class="stat-card"><div class="stat-value teal">{game_count}</div><div class="stat-label">ゲーム機</div></div>

      <div class="stat-card"><div class="stat-value amber">{_esc(max_profit_str)}</div><div class="stat-label">最高実質利益</div></div>

    </div>

    <div class="hero-timestamps">

      <span class="ts-pill {_esc(stale_cls)}" data-buyback-updated><span class="ts-dot"></span>買取価格更新：{_esc(buyback_str)}</span>

      <span class="ts-pill" data-lp-generated><span class="ts-dot blue"></span>LP生成：{_esc(lp_str)}</span>

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

    def _section_tabs(self, beginner_easy, beginner_watch,

                      advanced_deals, advanced_snaps, watch_candidates,

                      buyback_alerts, all_deals, iphone_deals, game_deals,

                      camera_deals=None, iphone_watch=None, camera_watch=None,

                      game_watch=None, buyback_by_product: dict = None) -> str:

        camera_deals = camera_deals or []

        camera_watch = camera_watch or []

        bybp = buyback_by_product or {}

        beginner_html = self._tab_beginner(beginner_easy, beginner_watch, bybp)

        advanced_html = self._tab_advanced(advanced_deals, advanced_snaps, watch_candidates,

                                           camera_watch=camera_watch)

        surge_html    = self._tab_surge(buyback_alerts)

        ranking_html  = self._tab_ranking(all_deals, iphone_deals, game_deals)

        all_count    = len(beginner_easy) + len(beginner_watch)

        adv_total    = len(advanced_deals) + len(advanced_snaps) + len(watch_candidates)

        surge_count  = len([a for a in buyback_alerts if a.get('alert_type') in ('buyback_surge','buyback_drop')])

        surge_badge  = f'<span class="tab-count">{surge_count}</span>' if surge_count else ''

        return f"""<div class="tab-wrap">

<nav class="tab-nav" role="tablist">

  <button class="tab-btn active" data-tab="beginner" role="tab" aria-selected="true">⁠&#128100; 初心者向け <span class="tab-count">{all_count}</span></button>

  <button class="tab-btn" data-tab="advanced" role="tab" aria-selected="false">&#128269; 上級者向け <span class="tab-count">{adv_total}</span></button>

  <button class="tab-btn" data-tab="surge" role="tab" aria-selected="false">&#9889; 急騰/急落{surge_badge}</button>

  <button class="tab-btn" data-tab="ranking" role="tab" aria-selected="false">&#127942; 買取ランキング</button>

</nav>

</div>

<div id="tab-beginner" class="tab-panel active" role="tabpanel">

{beginner_html}

</div>

<div id="tab-advanced" class="tab-panel" role="tabpanel">

{advanced_html}

</div>

<div id="tab-surge" class="tab-panel" role="tabpanel">

{surge_html}

</div>

<div id="tab-ranking" class="tab-panel" role="tabpanel">

{ranking_html}

</div>"""



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
                     '<strong>&#128100; 初心者向けとは？</strong><br>\n'
                     'Apple Store・任天堂公式など<strong>正規店で定価購入</strong>し、買取店に持ち込むことで利益が出る案件です。\n'
                     '新品未開封・SIMフリー等の条件を満たす必要があります。\n'
                     '購入前に必ず最新の買取価格をご確認ください。\n'
                     '<strong>利益は参考値です。条件・在庫・買取価格は常に変動します。</strong>\n'
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


    def _deal_card(self, d, badge_cls: str, label: str, buyback_rows: list = None, genre: str = None) -> str:
        """案件カード HTML を生成する（v5 Professional Design）。"""
        pid  = _esc(d.product_id)
        shop = _esc(d.best_buyback_shop or '—')
        genre_cls = genre or (d.category if hasattr(d, 'category') else '')
        stripe_cls = {'iphone': 'iphone', 'camera': 'camera', 'game_console': 'game'}.get(genre_cls, 'default')
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
        return f"""<div class="deal-card" data-user-level="{_esc(d.user_level)}">
  <div class="card-stripe {stripe_cls}"></div>
  <div class="card-hd">
    <div class="card-name">{_esc(d.product_name)}</div>
    <div class="card-tags">
      <span class="badge {badge_cls}">{label}</span>
      {genre_badge}
    </div>
  </div>
  <div class="{profit_section_cls}">
    <div class="profit-left">
      <div class="{profit_lbl_cls}">実質利益（推定コスト差引後）</div>
      <div class="{profit_num_cls}">{_esc(fmt_profit(d.net_profit_jpy))}</div>
    </div>
    <div class="profit-right">
      <div class="{profit_rate_cls}">{profit_rate_str}</div>
      <div class="profit-note">{profit_note_text}</div>
    </div>
  </div>
  <div class="price-row-wrap">
    <div class="price-cell">
      <div class="price-cell-lbl">公式価格（定価）</div>
      <div class="price-cell-val">{_esc(fmt_price(d.official_price_jpy))}</div>
    </div>
    <div class="price-cell">
      <div class="price-cell-lbl">最高買取価格</div>
      <div class="price-cell-val green">{_esc(fmt_price(d.best_buyback_price))}</div>
    </div>
  </div>
  <div class="card-body">
    <div class="condition-row buyback-notice">
      <span class="cond-icon">&#9888;</span>
      <div><strong>買取条件：{condition_text}</strong>&nbsp;<span style="font-size:0.72rem;color:var(--gray-400)">掛載価格は参考値です</span></div>
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

    def _tab_advanced(self, advanced_deals, advanced_snaps, watch_candidates, camera_watch=None) -> str:
        camera_watch = camera_watch or []
        parts = []

        if advanced_deals:
            parts.append('<div class="section-header"><h2>高利益案件</h2><span class="section-count">' + str(len(advanced_deals)) + '件</span></div>')
            for d in advanced_deals:
                badge_cls = "badge-exp" if d.user_level == "expert_only" else "badge-adv"
                label = "上級者限定" if d.user_level == "expert_only" else "高利益"
                parts.append(self._deal_card(d, badge_cls, label))

        if advanced_snaps:
            parts.append('<div class="section-header"><h2>プレ値・価格差候補</h2><span class="section-count">スナップショット分析</span></div>')
            rows = []
            for s in advanced_snaps:
                method = {"lottery": "抽選", "soldout": "SOLD OUT", "discontinued": "終了"}.get(
                    getattr(s, "sale_method", ""), getattr(s, "sale_method", "通常"))
                rows.append(
                    f"<tr>"
                    f"<td data-user-level='{_esc(getattr(s,'user_level',''))}'>{_esc(s.product_name)}</td>"
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

        # ----- フォールバック: 上級者向け監視候補 -----
        if watch_candidates:
            has_confirmed = bool(advanced_deals or advanced_snaps)
            if not has_confirmed:
                parts.append("""<div class="caution" style="margin:16px 0 20px;">
ℹ️ <strong>現在、上級者向けの確定候補は少ないため、価格差・希少性・海外相場差が大きい監視候補を表示しています。</strong><br>
中古市場や海外相場のデータが入り次第、確定候補として昇格します。
</div>""")
            parts.append('<div class="section-header"><h2>上級者向け監視候補</h2><span class="section-count">価格差・希少性スコア上位</span></div>')
            parts.append(self._watch_candidates_table(watch_candidates))

        if not advanced_deals and not advanced_snaps and not watch_candidates:
            parts.append('<div class="section-header"><h2>上級者向け候補</h2></div><p class="empty-state">現在、条件を満たす候補はありません。</p>')

        return "\n".join(parts)

    def _watch_candidates_table(self, candidates: list) -> str:
        """監視候補テーブルを生成する（products テーブル由来）。"""
        # カメラ優先、次にゲーム機
        camera = [c for c in candidates if c["genre"] == "camera"]
        others = [c for c in candidates if c["genre"] != "camera"]
        ordered = camera + others

        rows = []
        for c in ordered:
            price  = c["official_price"]
            bp     = c["buyback_price"]
            shop   = c["shop_name"] or "—"
            flags  = "・".join(c["flags"]) if c["flags"] else "監視中"
            # 買取価格がある場合は差額も表示
            gap_str = ""
            if bp and price:
                gap = bp - price
                gap_str = f'<br><span style="color:var(--green);font-size:0.82rem">'
                gap_str += f'買取 ¥{bp:,} (差 {gap:+,}円)</span>'
            buy_link = ""
            if c.get("buyback_url"):
                buy_link = f'<a href="{_esc(c["buyback_url"])}" target="_blank" rel="noopener" style="font-size:0.78rem;color:var(--accent)">買取ページ</a>'

            rows.append(
                f"<tr class='watch-candidate-card'>"
                f"<td><strong>{_esc(c['product_name'])}</strong>{gap_str}</td>"
                f"<td>{_esc(fmt_price(price) if price else '—')}</td>"
                f"<td>{_esc(shop)}</td>"
                f"<td><span style='color:var(--yellow);font-size:0.82rem'>{_esc(flags)}</span></td>"
                f"<td>{buy_link}</td>"
                f"</tr>"
            )

        return f"""<div class="watch-card"><div class="table-wrap">
<table>
<thead><tr><th>商品</th><th>公式価格</th><th>最新買取店</th><th>注目ポイント</th><th>リンク</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</div>
<p style="color:var(--text-3);font-size:0.78rem;margin-top:10px;padding:0 4px;">
※ 監視候補は価格差・希少性スコアが高い商品です。中古市場データ入手後に確定候補へ昇格します。
</p>
</div>"""

    # ----- Tab: 急騰/急落 -----

    def _tab_surge(self, alerts) -> str:
        surge = [a for a in alerts if a.get("alert_type") == "buyback_surge"]
        drop  = [a for a in alerts if a.get("alert_type") == "buyback_drop"]

        parts = []

        if surge:
            parts.append('<div class="section-header"><h2>本日の急騰</h2></div>')
            for a in surge:
                parts.append(self._alert_card(a, "surge"))
        else:
            parts.append('<div class="section-header"><h2>本日の急騰</h2></div><p class="empty-state">急騰は検出されていません（閾値: ¥5,000+）</p>')

        if drop:
            parts.append('<div class="section-header"><h2>本日の急落</h2></div>')
            for a in drop:
                parts.append(self._alert_card(a, "drop"))
        else:
            parts.append('<div class="section-header"><h2>本日の急落</h2></div><p class="empty-state">急落は検出されていません（閾値: ¥5,000−）</p>')

        return "\n".join(parts)

    def _alert_card(self, a: dict, kind: str) -> str:
        icon  = "📈" if kind == "surge" else "📉"
        badge = "badge-surge" if kind == "surge" else "badge-drop"
        label = "急騰" if kind == "surge" else "急落"
        chg   = a.get("price_change", 0)
        prev  = a.get("previous_price", 0)
        curr  = a.get("current_price", 0)
        rate  = f"{chg / prev * 100:+.1f}%" if prev else "---"
        detected = a.get("detected_at", "")

        return f"""<div class="card" style="padding:14px 18px;">
<p>{icon} <strong>{_esc(a.get('product_name',''))}</strong>
  @ <span style="color:var(--muted)">{_esc(a.get('shop_name',''))}</span>
  <span class="badge {badge}">{label} ¥{chg:+,}</span></p>
<div class="price-row" style="margin-top:8px;">
  <span class="price-label">前回価格</span><span class="price-value">¥{prev:,}</span>
</div>
<div class="price-row">
  <span class="price-label">最新価格</span><span class="price-value">¥{curr:,}</span>
</div>
<div class="price-row">
  <span class="price-label">変動額 / 変動率</span>
  <span class="price-value">¥{chg:+,} / {_esc(rate)}</span>
</div>
<div class="price-row">
  <span class="price-label">検出時刻</span>
  <span class="price-value" style="font-size:0.82rem;color:var(--muted)">{_esc(str(detected))}</span>
</div>
</div>"""

    # ----- Tab: 買取ランキング -----

    def _tab_ranking(self, all_deals, iphone_deals, game_deals) -> str:
        parts = []

        # 実質利益ランキング
        profitable = sorted([d for d in all_deals if d.net_profit_jpy > 0],
                            key=lambda d: d.net_profit_jpy, reverse=True)
        if profitable:
            parts.append('<div class="section-header"><h2>実質利益ランキング</h2><span class="section-count">全カテゴリ</span></div>')
            parts.append(self._ranking_table(profitable[:10], show_category=True))
        else:
            parts.append('<div class="section-header"><h2>実質利益ランキング</h2></div><p class="empty-state">データなし</p>')

        # iPhoneランキング
        iphone_profitable = sorted([d for d in iphone_deals if d.net_profit_jpy > 0],
                                    key=lambda d: d.net_profit_jpy, reverse=True)
        if iphone_profitable:
            parts.append('<div class="section-header"><h2>iPhone ランキング</h2></div>')
            parts.append(self._ranking_table(iphone_profitable[:5]))

        # ゲーム機ランキング
        game_profitable = sorted([d for d in game_deals if d.net_profit_jpy > 0],
                                  key=lambda d: d.net_profit_jpy, reverse=True)
        if game_profitable:
            parts.append('<div class="section-header"><h2>ゲーム機 ランキング</h2></div>')
            parts.append(self._ranking_table(game_profitable[:5]))

        # 買取店別ランキング
        shop_totals: dict = {}
        for d in all_deals:
            if d.best_buyback_shop and d.net_profit_jpy > 0:
                shop_totals[d.best_buyback_shop] = shop_totals.get(d.best_buyback_shop, 0) + 1
        if shop_totals:
            parts.append('<div class="section-header"><h2>買取店別 案件数ランキング</h2></div>')
            rows = []
            for i, (shop, cnt) in enumerate(
                sorted(shop_totals.items(), key=lambda x: x[1], reverse=True)[:8], 1
            ):
                rows.append(f"<tr><td>{i}</td><td>{_esc(shop)}</td><td>{cnt}件</td></tr>")
            parts.append(f"""<div class="ranking-card"><div class="table-wrap"><table>
<thead><tr><th>#</th><th>買取店</th><th>案件数</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div></div>""")

        return "\n".join(parts)

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

<div class="footer-text">

<p>掛載価格は取得・入力時点の参考値です。購入前に必ず公式サイト・買取店でご確認ください。</p>

<p>&copy; {now.year} プレ値速報 &mdash; 情報は自動取得・分析されたものです</p>

</div>

</footer>"""



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

        lines.extend(["", "## 上級者向け候補", ""])
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
