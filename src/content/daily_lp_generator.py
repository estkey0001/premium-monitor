"""日次LP自動生成エンジン v5 — Premium Design。
Apple/Bloomberg/TradingView風のライトテーマ。
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
    if not dt:
        return "不明"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    else:
        dt = dt.astimezone(JST)
    return dt.strftime("%Y-%m-%d %H:%M JST")


def _hours_ago(dt: Optional[datetime]) -> float:
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
        now = datetime.now()
        date_str = date_str or now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

        orig_variant = self.settings.get("headline_variant", "A")
        if variant:
            self.settings["headline_variant"] = variant

        out_dir = PROJECT_ROOT / self.settings.get("output", {}).get("daily_dir", "exports/lp/daily")
        out_dir.mkdir(parents=True, exist_ok=True)

        latest_buyback_at = self.repo.get_latest_buyback_observed_at()
        latest_deals_at   = self.repo.get_latest_beginner_deals_at()
        lp_generated_at   = now

        beginner_easy  = self.repo.list_beginner_deals(user_level="beginner_easy",  min_profit=0, limit=15)
        beginner_watch = self.repo.list_beginner_deals(user_level="beginner_watch", min_profit=0, limit=10)
        advanced_deals = self.repo.list_beginner_deals(user_level="advanced",       min_profit=0, limit=15)
        advanced_snaps = self.repo.list_premium_candidates_with_snapshots(limit=15, user_level="advanced")
        watch_candidates = self.repo.list_watch_candidates(genres=["camera", "game_console"], limit=20)

        buyback_by_product: dict = {}
        for _p in self.repo.list_products():
            _rows = self.repo.list_buyback_prices_by_product(_p.id, limit=5)
            if _rows:
                buyback_by_product[_p.id] = _rows

        buyback_alerts = self.repo.list_buyback_alerts(limit=20)

        all_deals    = self.repo.list_beginner_deals(min_profit=0, limit=50)
        iphone_deals = [d for d in all_deals if d.category == "iphone"]
        game_deals   = [d for d in all_deals if d.category == "game_console"]
        camera_deals = [d for d in all_deals if d.category == "camera"]
        iphone_watch = self.repo.list_watch_candidates(genres=["iphone"],       limit=15)
        camera_watch = self.repo.list_watch_candidates(genres=["camera"],       limit=15)
        game_watch   = self.repo.list_watch_candidates(genres=["game_console"], limit=15)

        page_html = self._render_page(
            date_str=date_str, time_str=time_str,
            latest_buyback_at=latest_buyback_at,
            latest_deals_at=latest_deals_at,
            lp_generated_at=lp_generated_at,
            beginner_easy=beginner_easy, beginner_watch=beginner_watch,
            advanced_deals=advanced_deals, advanced_snaps=advanced_snaps,
            watch_candidates=watch_candidates,
            buyback_alerts=buyback_alerts,
            all_deals=all_deals, iphone_deals=iphone_deals,
            game_deals=game_deals, camera_deals=camera_deals,
            iphone_watch=iphone_watch, camera_watch=camera_watch,
            game_watch=game_watch,
            buyback_by_product=buyback_by_product,
        )

        forbidden = check_forbidden(page_html)
        if forbidden:
            logger.warning("LP forbidden phrases: %s", forbidden)
            page_html, _ = sanitize_text(page_html)

        suffix = f"_{variant}" if variant else ""
        index_path = out_dir / f"index{suffix}.html"
        dated_path = out_dir / f"{date_str}{suffix}.html"
        md_path    = out_dir / "latest.md"

        index_path.write_text(page_html, encoding="utf-8")
        dated_path.write_text(page_html, encoding="utf-8")
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

    # ================================================================
    # HTML Rendering
    # ================================================================

    def _render_page(self, date_str, time_str,
                     latest_buyback_at, latest_deals_at, lp_generated_at,
                     beginner_easy, beginner_watch, advanced_deals, advanced_snaps,
                     watch_candidates, buyback_alerts, all_deals, iphone_deals, game_deals,
                     camera_deals=None, iphone_watch=None, camera_watch=None, game_watch=None,
                     buyback_by_product: dict = None) -> str:

        camera_deals = camera_deals or []
        iphone_watch = iphone_watch or []
        camera_watch = camera_watch or []
        game_watch   = game_watch   or []
        bybp         = buyback_by_product or {}

        site_title = _esc(self.settings.get("site_title", "プレ値速報"))
        ga_id      = self.settings.get("analytics", {}).get("google_analytics_id", "")
        meta_pixel = self.settings.get("analytics", {}).get("meta_pixel_id", "")

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

        _buyback_str_top = _jst_str(latest_buyback_at) if latest_buyback_at else "—"
        _lp_str_top = lp_generated_at.strftime("%m/%d %H:%M") if lp_generated_at else "—"

        hero_html    = self._section_hero(date_str, time_str, latest_buyback_at, lp_generated_at,
                                          all_deals=all_deals, iphone_deals=iphone_deals,
                                          camera_deals=camera_deals, game_deals=game_deals)
        stale_html   = self._section_stale_warning(latest_buyback_at, latest_deals_at, lp_generated_at)
        tab_html     = self._section_tabs(
            beginner_easy, beginner_watch,
            advanced_deals, advanced_snaps, watch_candidates,
            buyback_alerts, all_deals, iphone_deals, game_deals,
            camera_deals=camera_deals, iphone_watch=iphone_watch,
            camera_watch=camera_watch, game_watch=game_watch,
            buyback_by_product=bybp,
        )
        caution_html = self._section_caution()
        cta_html     = self._section_cta()
        footer_html  = self._section_footer()

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title}</title>
<meta name="description" content="{_esc(self.settings.get('site_description', ''))}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300..900;1,14..32,300..900&display=swap" rel="stylesheet">
{analytics_head}
<style>
/* ================================================================
   プレ値速報 v5 — Premium Light Design
   Apple / Bloomberg / TradingView / Linear 風
   ================================================================ */
:root {{
  /* Foundation */
  --bg:          #f8fafc;
  --bg-2:        #f1f5f9;
  --bg-card:     #ffffff;
  --bg-card-2:   #f8fafc;
  --surface:     #ffffff;

  /* Borders */
  --border:      #e2e8f0;
  --border-2:    #cbd5e1;
  --border-3:    #94a3b8;

  /* Text */
  --text-1:      #0f172a;
  --text-2:      #334155;
  --text-3:      #64748b;
  --text-4:      #94a3b8;

  /* Brand */
  --brand:       #2563eb;
  --brand-2:     #1d4ed8;
  --brand-light: #eff6ff;
  --brand-mid:   #dbeafe;

  /* Semantic */
  --green:       #059669;
  --green-2:     #047857;
  --green-light: #ecfdf5;
  --green-mid:   #d1fae5;

  --orange:      #d97706;
  --orange-light:#fffbeb;
  --orange-mid:  #fef3c7;

  --red:         #dc2626;
  --red-light:   #fef2f2;
  --red-mid:     #fee2e2;

  --purple:      #7c3aed;
  --purple-light:#f5f3ff;
  --purple-mid:  #ede9fe;

  --teal:        #0d9488;
  --teal-light:  #f0fdfa;
  --teal-mid:    #ccfbf1;

  /* Category */
  --iphone-color:  #2563eb;
  --iphone-bg:     #eff6ff;
  --camera-color:  #7c3aed;
  --camera-bg:     #f5f3ff;
  --game-color:    #0d9488;
  --game-bg:       #f0fdfa;

  /* Typography */
  --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'SF Mono', 'Fira Code', monospace;

  /* Radius */
  --r-xs:  4px;
  --r-sm:  8px;
  --r-md:  12px;
  --r-lg:  16px;
  --r-xl:  20px;
  --r-2xl: 28px;

  /* Shadow */
  --shadow-xs: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 6px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.04);
  --shadow-lg: 0 10px 15px rgba(0,0,0,0.07), 0 4px 6px rgba(0,0,0,0.04);
}}

*, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  font-family: var(--font);
  background: var(--bg);
  color: var(--text-1);
  line-height: 1.6;
  font-size: 15px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

/* ---- Layout ---- */
.container {{ max-width: 1100px; margin: 0 auto; padding: 0 20px 80px; }}

/* ---- Topbar ---- */
.topbar {{
  position: sticky; top: 0; z-index: 200;
  background: rgba(248,250,252,0.92);
  backdrop-filter: blur(16px) saturate(180%);
  -webkit-backdrop-filter: blur(16px) saturate(180%);
  border-bottom: 1px solid var(--border);
  height: 52px;
  display: flex; align-items: center;
  padding: 0 20px; gap: 12px;
}}
.topbar-brand {{
  font-size: 0.9rem; font-weight: 800;
  color: var(--text-1);
  display: flex; align-items: center; gap: 8px;
  text-decoration: none;
}}
.topbar-logo {{
  width: 26px; height: 26px;
  background: linear-gradient(135deg, var(--brand) 0%, var(--purple) 100%);
  border-radius: 7px;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem; font-weight: 900; color: #fff;
  flex-shrink: 0;
}}
.topbar-live {{
  display: flex; align-items: center; gap: 5px;
  font-size: 0.68rem; font-weight: 700;
  color: var(--green);
  background: var(--green-light);
  border: 1px solid var(--green-mid);
  padding: 3px 9px; border-radius: 99px;
}}
.live-dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green);
  animation: pulse-dot 2s ease-in-out infinite;
}}
@keyframes pulse-dot {{
  0%,100% {{ opacity:1; transform:scale(1); }}
  50% {{ opacity:0.4; transform:scale(0.7); }}
}}
.topbar-spacer {{ flex: 1; }}
.topbar-meta {{
  display: flex; align-items: center; gap: 16px;
  font-size: 0.72rem; color: var(--text-3);
  font-variant-numeric: tabular-nums;
}}

/* ---- Hero ---- */
.hero {{
  padding: 56px 0 48px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 0;
}}
.hero-inner {{
  max-width: 760px;
}}
.hero-eyebrow {{
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--brand);
  background: var(--brand-light);
  border: 1px solid var(--brand-mid);
  padding: 4px 12px; border-radius: 99px;
  margin-bottom: 20px;
}}
.hero-title {{
  font-size: clamp(1.8rem, 4vw, 2.8rem);
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.15;
  color: var(--text-1);
  margin-bottom: 16px;
}}
.hero-sub {{
  font-size: 1rem;
  color: var(--text-2);
  line-height: 1.75;
  max-width: 640px;
  margin-bottom: 32px;
}}
.hero-stats {{
  display: flex; flex-wrap: wrap; gap: 10px;
  margin-bottom: 28px;
}}
.hero-stat {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 12px 18px;
  min-width: 110px;
  box-shadow: var(--shadow-xs);
}}
.hero-stat-num {{
  font-size: 1.5rem; font-weight: 800;
  color: var(--green);
  line-height: 1;
  margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
}}
.hero-stat-num.blue {{ color: var(--brand); }}
.hero-stat-num.purple {{ color: var(--purple); }}
.hero-stat-num.teal {{ color: var(--teal); }}
.hero-stat-num.orange {{ color: var(--orange); font-size: 1.1rem; }}
.hero-stat-label {{
  font-size: 0.68rem; font-weight: 600;
  letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--text-3);
}}
.hero-timestamps {{
  display: flex; flex-wrap: wrap; gap: 10px;
}}
.ts-chip {{
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-3);
  font-size: 0.75rem; padding: 6px 14px;
  border-radius: 99px;
  font-variant-numeric: tabular-nums;
  box-shadow: var(--shadow-xs);
}}
.ts-dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green); flex-shrink: 0;
}}
.ts-dot.blue {{ background: var(--brand); }}

/* ---- Stale Warning ---- */
.stale-warning-block {{
  display: flex; align-items: flex-start; gap: 10px;
  background: var(--orange-light);
  border: 1px solid var(--orange-mid);
  border-left: 3px solid var(--orange);
  padding: 12px 18px;
  border-radius: 0 var(--r-md) var(--r-md) 0;
  margin: 16px 0;
  font-size: 0.875rem; color: #92400e; line-height: 1.6;
}}
.warn-icon {{ font-size: 1rem; flex-shrink: 0; margin-top: 1px; }}

/* ---- Tab Navigation ---- */
.tab-nav-wrap {{
  position: sticky; top: 52px; z-index: 100;
  background: rgba(248,250,252,0.95);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  margin-bottom: 0;
}}
.tab-nav {{
  display: flex; gap: 0;
  overflow-x: auto; -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  padding: 0 4px;
}}
.tab-nav::-webkit-scrollbar {{ display: none; }}
.tab-btn {{
  flex-shrink: 0;
  display: flex; align-items: center; gap: 6px;
  background: transparent; border: none;
  border-bottom: 2px solid transparent;
  padding: 14px 18px;
  font-size: 0.875rem; font-weight: 500;
  color: var(--text-3);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  margin-bottom: -1px;
  white-space: nowrap;
}}
.tab-btn:hover {{ color: var(--text-1); }}
.tab-btn.active {{
  color: var(--brand);
  border-bottom-color: var(--brand);
  font-weight: 700;
}}
.tab-btn .tab-count {{
  font-size: 0.65rem; font-weight: 700;
  background: var(--bg-2);
  color: var(--text-3);
  padding: 1px 6px; border-radius: 99px;
}}
.tab-btn.active .tab-count {{
  background: var(--brand-light);
  color: var(--brand);
}}
.tab-panel {{ display: none; padding: 32px 0 0; }}
.tab-panel.active {{ display: block; }}

/* ---- Section Header ---- */
.section-head {{
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 20px; padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}}
.section-title {{
  font-size: 0.8rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--text-3);
  display: flex; align-items: center; gap: 8px;
}}
.section-title::before {{
  content: '';
  width: 3px; height: 14px; border-radius: 2px;
  background: var(--brand);
}}
.section-badge {{
  font-size: 0.68rem; font-weight: 700;
  background: var(--bg-2); color: var(--text-3);
  border: 1px solid var(--border);
  padding: 3px 10px; border-radius: 99px;
}}

/* ---- Deal Cards Grid ---- */
.cards-grid {{ display: grid; gap: 16px; }}

@media (min-width: 768px) {{
  .cards-grid {{ grid-template-columns: 1fr 1fr; }}
}}

/* ---- Deal Card ---- */
.deal-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.2s, transform 0.2s, border-color 0.2s;
}}
.deal-card:hover {{
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
  border-color: var(--border-2);
}}

/* Category accent */
.deal-card .card-accent {{ height: 3px; }}
.deal-card.iphone-card .card-accent {{ background: var(--iphone-color); }}
.deal-card.camera-card .card-accent {{ background: var(--camera-color); }}
.deal-card.game-card .card-accent {{ background: var(--game-color); }}
.deal-card .card-accent {{ background: var(--brand); }}

/* Card Header */
.card-head {{
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 10px;
  padding: 18px 20px 14px;
}}
.card-name {{
  font-size: 0.95rem; font-weight: 700;
  color: var(--text-1); line-height: 1.3; flex: 1;
}}
.card-tags {{ display: flex; gap: 5px; flex-shrink: 0; flex-wrap: wrap; justify-content: flex-end; }}

/* Profit Banner */
.profit-banner {{
  margin: 0 20px;
  padding: 16px 18px;
  background: var(--green-light);
  border: 1px solid var(--green-mid);
  border-radius: var(--r-md);
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
}}
.profit-main {{ display: flex; align-items: baseline; gap: 8px; }}
.profit-amount {{
  font-size: 2rem; font-weight: 900;
  color: var(--green);
  letter-spacing: -0.03em; line-height: 1;
}}
.profit-rate {{
  font-size: 0.85rem; font-weight: 700;
  color: var(--green-2);
  background: var(--green-mid);
  padding: 3px 10px; border-radius: var(--r-xs);
}}
.profit-label-text {{
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--green-2); margin-bottom: 4px;
}}
.profit-note {{ font-size: 0.7rem; color: var(--text-3); text-align: right; }}

/* Price Grid */
.price-grid {{
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1px; background: var(--border);
  margin: 14px 20px 0;
  border-radius: var(--r-md); overflow: hidden;
}}
.price-cell {{ background: var(--bg-card); padding: 12px 14px; }}
.price-cell-label {{
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--text-3); margin-bottom: 5px;
}}
.price-cell-value {{
  font-size: 1.05rem; font-weight: 800;
  color: var(--text-1); font-variant-numeric: tabular-nums;
}}
.price-cell-value.buyback {{ color: var(--green); }}

/* Card Body */
.card-body {{ padding: 14px 20px 18px; }}
.condition-row {{
  display: flex; align-items: center; gap: 7px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 8px 12px; margin-bottom: 12px;
  font-size: 0.8rem; color: var(--text-2);
}}
.cond-icon {{ color: var(--orange); flex-shrink: 0; }}
.updated-row {{
  display: flex; align-items: center; gap: 5px;
  font-size: 0.72rem; color: var(--text-3); margin-bottom: 12px;
}}

/* Shop Compare */
.shop-compare {{
  border: 1px solid var(--border);
  border-radius: var(--r-md); overflow: hidden;
  margin-bottom: 14px;
}}
.shop-compare-header {{
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 14px;
  background: var(--bg-2);
  border-bottom: 1px solid var(--border);
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--text-3);
}}
.shop-row {{
  display: flex; align-items: center;
  padding: 9px 14px;
  border-bottom: 1px solid var(--border);
  gap: 10px; font-size: 0.875rem;
  transition: background 0.1s;
}}
.shop-row:last-child {{ border: none; }}
.shop-row:hover {{ background: var(--bg-2); }}
.shop-rank {{ min-width: 20px; font-size: 0.72rem; font-weight: 800; color: var(--text-3); text-align: center; }}
.shop-rank.r1 {{ color: #b45309; }}
.shop-rank.r2 {{ color: var(--text-3); }}
.shop-name-col {{ flex: 1; color: var(--text-2); }}
.shop-name-col a {{ color: var(--brand); text-decoration: none; }}
.shop-name-col a:hover {{ text-decoration: underline; }}
.shop-price-col {{ font-weight: 700; color: var(--text-1); font-variant-numeric: tabular-nums; text-align: right; min-width: 76px; }}
.shop-diff-col {{ font-size: 0.75rem; font-weight: 700; color: var(--green); text-align: right; min-width: 66px; }}
.shop-diff-col.neg {{ color: var(--red); }}

/* Card Actions */
.card-actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.btn-card {{
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 0.8rem; font-weight: 600;
  padding: 7px 14px; border-radius: var(--r-sm);
  text-decoration: none; transition: all 0.15s;
  border: 1px solid;
}}
.btn-primary {{
  background: var(--brand); color: #fff;
  border-color: var(--brand);
}}
.btn-primary:hover {{ background: var(--brand-2); border-color: var(--brand-2); }}
.btn-secondary {{
  background: var(--bg-card); color: var(--brand);
  border-color: var(--brand-mid);
}}
.btn-secondary:hover {{ background: var(--brand-light); border-color: var(--brand); }}
.btn-ghost {{
  background: var(--bg-2); color: var(--text-2);
  border-color: var(--border);
}}
.btn-ghost:hover {{ background: var(--bg-card); color: var(--text-1); border-color: var(--border-2); }}

/* ---- Badges / Tags ---- */
.badge {{
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 0.65rem; font-weight: 800;
  letter-spacing: 0.04em; text-transform: uppercase;
  padding: 3px 9px; border-radius: 99px;
}}
.badge-easy {{ background: var(--green-light); color: var(--green-2); border: 1px solid var(--green-mid); }}
.badge-watch {{ background: var(--orange-light); color: var(--orange); border: 1px solid var(--orange-mid); }}
.badge-adv {{ background: var(--purple-light); color: var(--purple); border: 1px solid var(--purple-mid); }}
.badge-exp {{ background: var(--red-light); color: var(--red); border: 1px solid var(--red-mid); }}
.badge-iphone {{ background: var(--iphone-bg); color: var(--iphone-color); border: 1px solid var(--brand-mid); }}
.badge-camera {{ background: var(--camera-bg); color: var(--camera-color); border: 1px solid var(--purple-mid); }}
.badge-game {{ background: var(--game-bg); color: var(--game-color); border: 1px solid var(--teal-mid); }}
.badge-lottery {{ background: #fef3c7; color: #92400e; border: 1px solid #fde68a; }}
.badge-soldout {{ background: var(--red-light); color: var(--red); border: 1px solid var(--red-mid); }}
.badge-overseas {{ background: #f0f9ff; color: #0369a1; border: 1px solid #bae6fd; }}

/* ---- Freshness ---- */
.freshness-live {{ color: var(--green); font-size: 0.7rem; font-weight: 700; }}
.freshness-recent {{ color: var(--orange); font-size: 0.7rem; font-weight: 700; }}
.freshness-stale {{ color: var(--red); font-size: 0.7rem; font-weight: 700; }}
.freshness-unknown {{ color: var(--text-3); font-size: 0.7rem; }}

/* ---- Overseas Links ---- */
.overseas-links {{
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-top: 10px; padding-top: 10px;
  border-top: 1px solid var(--border);
}}
.overseas-label {{
  width: 100%;
  font-size: 0.65rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--text-3); margin-bottom: 4px;
}}
.overseas-chip {{
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 0.75rem; font-weight: 600;
  color: #0369a1;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  padding: 4px 10px; border-radius: var(--r-sm);
  text-decoration: none; transition: all 0.15s;
}}
.overseas-chip:hover {{ background: #e0f2fe; border-color: #7dd3fc; }}

/* ---- Watch Candidate Card ---- */
.watch-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  padding: 18px 20px; margin-bottom: 12px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.2s, transform 0.2s;
}}
.watch-card:hover {{ box-shadow: var(--shadow-md); transform: translateY(-1px); }}
.watch-card-head {{
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 10px;
  margin-bottom: 12px;
}}
.watch-card-name {{ font-size: 0.95rem; font-weight: 700; color: var(--text-1); flex: 1; }}
.watch-price-row {{
  display: flex; gap: 16px; flex-wrap: wrap;
  margin-bottom: 10px; font-size: 0.875rem;
}}
.watch-price-item {{ display: flex; flex-direction: column; gap: 2px; }}
.watch-price-label {{ font-size: 0.65rem; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; }}
.watch-price-value {{ font-weight: 700; color: var(--text-1); font-variant-numeric: tabular-nums; }}
.watch-price-value.positive {{ color: var(--green); }}
.watch-price-value.negative {{ color: var(--red); }}
.watch-link {{ font-size: 0.8rem; }}
.watch-gap-badge {{
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 0.75rem; font-weight: 700;
  padding: 3px 10px; border-radius: var(--r-xs);
}}
.gap-positive {{ background: var(--green-light); color: var(--green-2); }}
.gap-negative {{ background: var(--red-light); color: var(--red); }}
.gap-neutral {{ background: var(--bg-2); color: var(--text-3); }}
.link-type-badge {{
  font-size: 0.65rem; font-weight: 600;
  color: var(--text-3); background: var(--bg-2);
  border: 1px solid var(--border);
  padding: 1px 6px; border-radius: 99px; margin-left: 4px;
}}
.unverified-link {{ font-size: 0.8rem; color: var(--text-3); }}

/* ---- Alert Card ---- */
.alert-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  padding: 18px 20px; margin-bottom: 12px;
  box-shadow: var(--shadow-sm);
}}
.alert-card.surge {{ border-left: 3px solid var(--green); background: var(--green-light); }}
.alert-card.drop {{ border-left: 3px solid var(--red); background: var(--red-light); }}

/* ---- Ranking ---- */
.ranking-card {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  overflow: hidden; margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
}}
.ranking-head {{
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-2);
  display: flex; align-items: center; gap: 8px;
  font-size: 0.85rem; font-weight: 700; color: var(--text-1);
}}
.ranking-row {{
  display: flex; align-items: center;
  padding: 11px 18px;
  border-bottom: 1px solid var(--border);
  gap: 12px; transition: background 0.1s;
}}
.ranking-row:last-child {{ border: none; }}
.ranking-row:hover {{ background: var(--bg-2); }}
.rank-num {{
  font-size: 1rem; font-weight: 900;
  color: var(--text-3); min-width: 26px; text-align: center;
}}
.rank-num.r1 {{ color: #b45309; }}
.rank-num.r2 {{ color: var(--text-3); }}
.rank-num.r3 {{ color: #92400e; }}
.rank-product {{ flex: 1; }}
.rank-name {{ font-weight: 600; color: var(--text-1); font-size: 0.9rem; }}
.rank-meta {{ font-size: 0.72rem; color: var(--text-3); margin-top: 2px; }}
.rank-profit {{
  font-size: 1.05rem; font-weight: 800;
  color: var(--green); font-variant-numeric: tabular-nums;
  text-align: right;
}}
.rank-rate {{ font-size: 0.72rem; color: var(--text-3); text-align: right; margin-top: 2px; }}

/* ---- Table ---- */
.table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: var(--r-md); border: 1px solid var(--border); }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
thead tr {{ background: var(--bg-2); border-bottom: 1px solid var(--border); }}
th {{ padding: 10px 12px; text-align: left; color: var(--text-3); font-weight: 700; font-size: 0.68rem; letter-spacing: 0.06em; text-transform: uppercase; white-space: nowrap; }}
td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); color: var(--text-2); word-break: break-word; }}
tbody tr:last-child td {{ border: none; }}
tbody tr:hover td {{ background: var(--bg-2); }}
.td-profit {{ color: var(--green); font-weight: 700; font-variant-numeric: tabular-nums; }}

/* ---- Empty State ---- */
.empty-state {{
  text-align: center; padding: 56px 24px;
  color: var(--text-3); font-size: 0.9rem;
}}
.empty-icon {{ font-size: 2rem; margin-bottom: 12px; opacity: 0.4; display: block; }}

/* ---- Caution ---- */
.caution-block {{
  background: var(--orange-light);
  border: 1px solid var(--orange-mid);
  border-left: 3px solid var(--orange);
  border-radius: 0 var(--r-md) var(--r-md) 0;
  padding: 20px 24px; margin: 40px 0;
  font-size: 0.875rem; color: #78350f; line-height: 1.8;
}}
.caution-title {{
  font-size: 0.875rem; font-weight: 700;
  color: var(--orange); margin-bottom: 10px;
  display: flex; align-items: center; gap: 6px;
}}
.caution-list {{ list-style: none; padding: 0; }}
.caution-list li {{ padding: 2px 0 2px 14px; position: relative; }}
.caution-list li::before {{ content: "·"; position: absolute; left: 4px; color: var(--orange); }}

/* ---- CTA ---- */
.cta-section {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-2xl);
  padding: 40px 36px;
  text-align: center;
  margin: 48px 0;
  box-shadow: var(--shadow-sm);
  position: relative; overflow: hidden;
}}
.cta-section::before {{
  content: '';
  position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: linear-gradient(90deg, var(--brand), var(--purple));
}}
.cta-eyebrow {{
  font-size: 0.68rem; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--brand); margin-bottom: 14px;
}}
.cta-title {{
  font-size: 1.4rem; font-weight: 800;
  color: var(--text-1); margin-bottom: 10px;
  letter-spacing: -0.02em;
}}
.cta-desc {{
  font-size: 0.9rem; color: var(--text-2);
  max-width: 440px; margin: 0 auto 24px; line-height: 1.7;
}}
.cta-buttons {{ display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }}
.btn-cta-primary {{
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--brand); color: #fff;
  font-size: 0.9rem; font-weight: 700;
  padding: 12px 26px; border-radius: var(--r-md);
  text-decoration: none; border: none; cursor: pointer;
  box-shadow: 0 4px 12px rgba(37,99,235,0.25);
  transition: all 0.2s;
}}
.btn-cta-primary:hover {{ background: var(--brand-2); transform: translateY(-1px); box-shadow: 0 6px 16px rgba(37,99,235,0.3); }}
.btn-cta-secondary {{
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--bg-card); color: var(--text-2);
  font-size: 0.9rem; font-weight: 600;
  padding: 12px 26px; border-radius: var(--r-md);
  text-decoration: none; border: 1px solid var(--border-2);
  transition: all 0.2s;
}}
.btn-cta-secondary:hover {{ background: var(--bg-2); color: var(--text-1); border-color: var(--border-3); }}

/* ---- Footer ---- */
.footer {{
  border-top: 1px solid var(--border);
  padding: 36px 0 24px;
  text-align: center; margin-top: 48px;
}}
.footer-text {{ font-size: 0.75rem; color: var(--text-3); line-height: 2.2; }}

/* ---- Adv Fallback Notice ---- */
.adv-fallback-notice {{
  display: flex; align-items: flex-start; gap: 10px;
  background: var(--brand-light);
  border: 1px solid var(--brand-mid);
  border-radius: var(--r-md);
  padding: 12px 16px; margin-bottom: 20px;
  font-size: 0.875rem; color: var(--brand-2); line-height: 1.6;
}}

/* ---- Hidden Anchors (deploy-check compatibility) ---- */
/* #tab-beginner and #tab-advanced IDs are used by tab panels directly */

/* ---- Responsive ---- */
@media (max-width: 768px) {{
  .hero {{ padding: 40px 0 36px; }}
  .hero-title {{ font-size: 1.7rem; }}
  .hero-sub {{ font-size: 0.9rem; }}
  .hero-stats {{ gap: 8px; }}
  .hero-stat {{ padding: 10px 14px; min-width: 90px; }}
  .hero-stat-num {{ font-size: 1.3rem; }}
  .profit-amount {{ font-size: 1.7rem; }}
  .profit-banner {{ flex-direction: column; gap: 8px; }}
  .profit-note {{ text-align: left; }}
  .tab-btn {{ padding: 12px 14px; font-size: 0.82rem; }}
  .card-head {{ padding: 14px 16px 12px; }}
  .card-body {{ padding: 12px 16px 16px; }}
  .profit-banner {{ margin: 0 16px; padding: 14px 16px; }}
  .price-grid {{ margin: 12px 16px 0; }}
  .cta-section {{ padding: 28px 20px; }}
  .topbar-meta {{ display: none; }}
  .shop-diff-col {{ display: none; }}
  table {{ font-size: 0.8rem; }}
  th, td {{ padding: 8px 8px; }}
}}
@media (max-width: 480px) {{
  .container {{ padding: 0 14px 60px; }}
  .hero-title {{ font-size: 1.5rem; }}
  .price-grid {{ grid-template-columns: 1fr; }}
  .cta-buttons {{ flex-direction: column; align-items: stretch; }}
  .btn-cta-primary, .btn-cta-secondary {{ justify-content: center; }}
  .cards-grid {{ grid-template-columns: 1fr; }}
}}

/* noscript */
.noscript-all .tab-panel {{ display: block !important; }}
.noscript-all .tab-nav {{ display: none; }}
</style>
</head>
<body>
<header class="topbar">
  <a href="/" class="topbar-brand">
    <div class="topbar-logo">P</div>
    プレ値速報
  </a>
  <div class="topbar-live"><span class="live-dot"></span>LIVE</div>
  <div class="topbar-spacer"></div>
  <div class="topbar-meta">
    <span data-buyback-updated>買取更新: {_esc(_buyback_str_top)}</span>
    <span data-lp-generated>生成: {_esc(_lp_str_top)}</span>
  </div>
</header>
<div class="container">
{hero_html}
{stale_html}
{tab_html}
{caution_html}
{cta_html}
{footer_html}
</div>
<script>
(function(){{
  // Tab switching
  var btns = document.querySelectorAll(".tab-btn");
  var panels = document.querySelectorAll(".tab-panel");
  if (btns.length) {{
    btns.forEach(function(btn) {{
      btn.addEventListener("click", function() {{
        btns.forEach(function(b) {{ b.classList.remove("active"); b.setAttribute("aria-selected","false"); }});
        panels.forEach(function(p) {{ p.classList.remove("active"); }});
        btn.classList.add("active");
        btn.setAttribute("aria-selected","true");
        var panel = document.getElementById("tab-" + btn.dataset.tab);
        if (panel) panel.classList.add("active");
      }});
    }});
  }}
  // Click tracking
  document.addEventListener("click", function(e) {{
    var el = e.target.closest("[data-track]");
    if (!el) return;
    var ev = el.getAttribute("data-track");
    var pid = el.getAttribute("data-product-id") || "";
    var shop = el.getAttribute("data-shop") || "";
    if (typeof gtag === "function") gtag("event", ev, {{product_id: pid, shop: shop}});
    if (typeof fbq === "function") fbq("trackCustom", ev, {{product_id: pid, shop: shop}});
  }});
}})();
</script>
<noscript><style>.tab-nav{{display:none;}}.tab-panel{{display:block!important;}}</style></noscript>
</body>
</html>"""

    # ================================================================
    # Hero
    # ================================================================

    def _section_hero(self, date_str, time_str, latest_buyback_at, lp_generated_at,
                      all_deals=None, iphone_deals=None, camera_deals=None, game_deals=None) -> str:
        variant_key = self.settings.get("headline_variant", "A")
        variants    = self.settings.get("variants", {})
        variant     = variants.get(variant_key, {})
        headline    = _esc(variant.get("headline", "今日の価格差を、1ページで確認。"))
        buyback_str = _jst_str(latest_buyback_at)
        lp_str      = _jst_str(lp_generated_at)
        stale_cls   = "stale" if _hours_ago(latest_buyback_at) > 24 else ""

        all_count    = len(all_deals)    if all_deals    else 0
        iphone_count = len(iphone_deals) if iphone_deals else 0
        camera_count = len(camera_deals) if camera_deals else 0
        game_count   = len(game_deals)   if game_deals   else 0
        max_profit   = max((d.net_profit_jpy or 0) for d in all_deals) if all_deals else 0
        max_profit_str = f"+¥{max_profit:,}" if max_profit > 0 else "—"

        return f"""<section class="hero">
  <div class="hero-inner">
    <div class="hero-eyebrow"><span>&#9679;</span> 毎日更新 &mdash; プレ値・買取差額レポート</div>
    <h1 class="hero-title">{headline}</h1>
    <p class="hero-sub">公式価格・買取価格・海外相場を毎日更新。初心者向けの低難度案件から、上級者向けの抽選・高プレ値候補まで整理しています。</p>
    <div class="hero-stats">
      <div class="hero-stat">
        <div class="hero-stat-num">{all_count}</div>
        <div class="hero-stat-label">本日の案件</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-num blue">{iphone_count}</div>
        <div class="hero-stat-label">iPhone</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-num purple">{camera_count}</div>
        <div class="hero-stat-label">カメラ</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-num teal">{game_count}</div>
        <div class="hero-stat-label">ゲーム機</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-num orange">{_esc(max_profit_str)}</div>
        <div class="hero-stat-label">最高実質利益</div>
      </div>
    </div>
    <div class="hero-timestamps">
      <span class="ts-chip {_esc(stale_cls)}" data-buyback-updated>
        <span class="ts-dot"></span>買取価格更新：{_esc(buyback_str)}
      </span>
      <span class="ts-chip" data-lp-generated>
        <span class="ts-dot blue"></span>LP生成：{_esc(lp_str)}
      </span>
    </div>
  </div>
</section>"""

    # ================================================================
    # Stale Warning
    # ================================================================

    def _section_stale_warning(self, latest_buyback_at, latest_deals_at, lp_generated_at) -> str:
        msgs = []
        if _hours_ago(latest_buyback_at) >= 24:
            msgs.append(f"買取価格（{_hours_ago(latest_buyback_at):.0f}時間前のデータ）")
        if _hours_ago(latest_deals_at) >= 24:
            msgs.append(f"案件情報（{_hours_ago(latest_deals_at):.0f}時間前のデータ）")
        if not msgs:
            return ""
        detail = "・".join(msgs)
        return f"""<div class="stale-warning-block">
  <span class="warn-icon">&#9888;&#65039;</span>
  <div><strong>データが古い可能性があります：</strong>{_esc(detail)}が24時間以上前のデータです。購入前に必ず最新価格をご確認ください。</div>
</div>"""

    # ================================================================
    # Tabs
    # ================================================================

    def _section_tabs(self, beginner_easy, beginner_watch,
                      advanced_deals, advanced_snaps, watch_candidates,
                      buyback_alerts, all_deals, iphone_deals, game_deals,
                      camera_deals=None, iphone_watch=None, camera_watch=None,
                      game_watch=None, buyback_by_product: dict = None) -> str:
        camera_deals = camera_deals or []
        iphone_watch = iphone_watch or []
        camera_watch = camera_watch or []
        game_watch   = game_watch   or []
        bybp         = buyback_by_product or {}

        beginner_html = self._tab_beginner(beginner_easy, beginner_watch, bybp)
        advanced_html = self._tab_advanced(advanced_deals, advanced_snaps, watch_candidates,
                                           camera_watch=camera_watch)
        surge_html    = self._tab_surge(buyback_alerts)
        ranking_html  = self._tab_ranking(all_deals, iphone_deals, game_deals)

        all_count    = len(beginner_easy) + len(beginner_watch)
        adv_total    = len(advanced_deals) + len(advanced_snaps) + len(watch_candidates)
        surge_count  = len([a for a in buyback_alerts if a.get("alert_type") in ("buyback_surge","buyback_drop")])

        return f"""<div class="tab-nav-wrap">
<nav class="tab-nav" role="tablist">
  <button class="tab-btn active" data-tab="beginner" role="tab" aria-selected="true">
    &#128100; 初心者向け <span class="tab-count">{all_count}</span>
  </button>
  <button class="tab-btn" data-tab="advanced" role="tab" aria-selected="false">
    &#128269; 上級者向け <span class="tab-count">{adv_total}</span>
  </button>
  <button class="tab-btn" data-tab="surge" role="tab" aria-selected="false">
    &#9889; 急騰/急落{f'<span class="tab-count">{surge_count}</span>' if surge_count else ""}
  </button>
  <button class="tab-btn" data-tab="ranking" role="tab" aria-selected="false">
    &#127942; 買取ランキング
  </button>
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

    # ================================================================
    # Freshness Label
    # ================================================================

    def _freshness_label(self, observed_at_str: str, data_source: str) -> str:
        try:
            if observed_at_str:
                dt = datetime.fromisoformat(observed_at_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=JST)
                hours = (datetime.now(tz=JST) - dt.astimezone(JST)).total_seconds() / 3600
                if hours < 6:
                    freshness, css = "最新", "freshness-live"
                elif hours < 24:
                    freshness, css = f"{int(hours)}時間前", "freshness-recent"
                else:
                    freshness, css = f"{int(hours)}時間以上前（参考値）", "freshness-stale"
            else:
                freshness, css = "不明", "freshness-unknown"
        except Exception:
            freshness, css = "不明", "freshness-unknown"
        source_label = {
            "live": "&#128994;live",
            "manual_today": "&#128203;当日手動",
            "manual_recent": "&#128203;手動(24h)",
            "stale": "&#9888;参考値",
        }.get(data_source, data_source)
        return f'<span class="{css}">{_esc(source_label)} / {_esc(freshness)}</span>'

    # ================================================================
    # Beginner Tab
    # ================================================================

    def _tab_beginner(self, easy_deals, watch_deals, buyback_by_product: dict = None) -> str:
        bybp = buyback_by_product or {}
        parts = []

        # 初心者向け説明バナー
        parts.append("""<div style="background:#eff6ff;border:1px solid #dbeafe;border-radius:12px;padding:14px 18px;margin-bottom:24px;font-size:0.875rem;color:#1e40af;line-height:1.7;">
<strong>&#128100; 初心者向けとは？</strong><br>
公式店舗（Apple Store・任天堂公式など）で定価購入し、買取店に持ち込むことで利益が出る案件です。
新品未開封・SIMフリー等の条件を満たす必要があります。購入前に必ず最新の買取価格をご確認ください。
</div>""")

        if easy_deals:
            parts.append(f'<div class="section-head"><div class="section-title">低難度 &mdash; すぐ動ける案件</div><div class="section-badge">{len(easy_deals)}件</div></div>')
            parts.append('<div class="cards-grid">')
            for d in easy_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, "badge-easy", "低難度", buyback_rows=rows))
            parts.append('</div>')
        else:
            parts.append('<div class="section-head"><div class="section-title">低難度 &mdash; すぐ動ける案件</div></div>')
            parts.append('<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす案件はありません。</div>')

        if watch_deals:
            parts.append(f'<div class="section-head" style="margin-top:40px"><div class="section-title">要確認 &mdash; 様子見案件</div><div class="section-badge">{len(watch_deals)}件</div></div>')
            parts.append('<div class="cards-grid">')
            for d in watch_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, "badge-watch", "要確認", buyback_rows=rows))
            parts.append('</div>')

        return "\n".join(parts)

    # ================================================================
    # Deal Card
    # ================================================================

    def _deal_card(self, d, badge_cls: str, label: str, buyback_rows: list = None, genre: str = None) -> str:
        pid  = _esc(d.product_id)
        shop = _esc(d.best_buyback_shop or "—")
        links = ""

        if hasattr(d, "official_url") and d.official_url:
            links += (f'<a href="{_esc(d.official_url)}" target="_blank" rel="noopener" '
                      f'class="btn-card btn-secondary" data-track="product_click" data-product-id="{pid}">公式購入ページ &rarr;</a>')
        elif hasattr(d, "best_official_url") and d.best_official_url:
            links += (f'<a href="{_esc(d.best_official_url)}" target="_blank" rel="noopener" '
                      f'class="btn-card btn-secondary" data-track="product_click" data-product-id="{pid}">公式購入ページ &rarr;</a>')

        verified_url = ""
        if hasattr(d, "best_buyback_url") and d.best_buyback_url:
            _skip = ("mobileno1.com", "kaitori-1chome.com")
            if not any(dom in d.best_buyback_url for dom in _skip):
                verified_url = d.best_buyback_url
        if verified_url:
            links += (f'<a href="{_esc(verified_url)}" target="_blank" rel="noopener" '
                      f'class="btn-card btn-primary" data-track="product_click" data-product-id="{pid}" data-shop="{shop}">買取ページ &rarr;</a>')

        updated_str = ""
        if hasattr(d, "scanned_at") and d.scanned_at:
            updated_str = f'<div class="updated-row"><span>&#128336;</span>最終更新：{_esc(_jst_str(d.scanned_at))}</div>'

        compare_html = ""
        if buyback_rows:
            official_price = d.official_price_jpy or 0
            rows_html = []
            for i, r in enumerate(buyback_rows[:5], start=1):
                bp = r.get("buyback_price", 0)
                sname = _esc(r.get("shop_name", ""))
                profit = bp - official_price
                profit_str = f"+¥{profit:,}" if profit >= 0 else f"-¥{abs(profit):,}"
                url_val = r.get("buyback_url", "")
                verified = r.get("link_verified", False)
                if url_val and verified:
                    shop_display = (f'<a href="{_esc(url_val)}" target="_blank" rel="noopener" '
                                    f'data-track="buyback_click" data-product-id="{pid}" '
                                    f'data-shop="{sname}">{sname}</a>')
                else:
                    shop_display = sname
                rank_cls = "r1" if i == 1 else ("r2" if i == 2 else "")
                diff_cls = " neg" if profit < 0 else ""
                freshness = self._freshness_label(
                    r.get("observed_at", ""), r.get("data_source", "manual_today")
                )
                rows_html.append(
                    f'<div class="shop-row">'
                    f'<div class="shop-rank {rank_cls}">{i}</div>'
                    f'<div class="shop-name-col">{shop_display}</div>'
                    f'<div class="shop-price-col">¥{bp:,}</div>'
                    f'<div class="shop-diff-col{diff_cls}">{_esc(profit_str)}</div>'
                    f'</div>'
                )
            first_freshness = self._freshness_label(
                buyback_rows[0].get("observed_at", ""), buyback_rows[0].get("data_source", "manual_today")
            )
            n_shops = len(buyback_rows[:5])
            compare_html = (
                f'<div class="shop-compare buyback-shop-table buyback-table">'
                f'<div class="shop-compare-header"><span>買取店比較（参照{n_shops}店舗）</span>' + first_freshness + '</div>'
                + "".join(rows_html)
                + '</div>'
            )

        genre_cls = genre or (d.category if hasattr(d, "category") else "")
        genre_card_cls = {"iphone": "iphone-card", "camera": "camera-card", "game_console": "game-card"}.get(genre_cls, "")
        genre_badge = {
            "iphone": '<span class="badge badge-iphone">iPhone</span>',
            "camera": '<span class="badge badge-camera">カメラ</span>',
            "game_console": '<span class="badge badge-game">ゲーム機</span>',
        }.get(genre_cls, "")
        profit_rate_str = _esc(fmt_rate(d.net_profit_rate))
        is_watch = d.user_level == "beginner_watch"
        profit_bg = "background:var(--orange-light);border-color:var(--orange-mid);" if is_watch else ""
        profit_color = "color:var(--orange);" if is_watch else ""
        profit_rate_bg = "background:var(--orange-mid);color:var(--orange);" if is_watch else ""

        return f"""<div class="deal-card {_esc(genre_card_cls)}" data-user-level="{_esc(d.user_level)}">
  <div class="card-accent"></div>
  <div class="card-head">
    <div class="card-name">{_esc(d.product_name)}</div>
    <div class="card-tags">
      <span class="badge {badge_cls}">{label}</span>
      {genre_badge}
    </div>
  </div>
  <div class="profit-banner" style="{profit_bg}">
    <div class="profit-left">
      <div class="profit-label-text">実質利益（推定コスト差引後）</div>
      <div class="profit-main">
        <span class="profit-amount" style="{profit_color}">{_esc(fmt_profit(d.net_profit_jpy))}</span>
        <span class="profit-rate" style="{profit_rate_bg}">{profit_rate_str}</span>
      </div>
    </div>
    <div class="profit-note">推定コスト -{_esc(fmt_price(d.estimated_costs_jpy))}</div>
  </div>
  <div class="price-grid">
    <div class="price-cell">
      <div class="price-cell-label">公式価格（定価）</div>
      <div class="price-cell-value">{_esc(fmt_price(d.official_price_jpy))}</div>
    </div>
    <div class="price-cell">
      <div class="price-cell-label">最高買取価格</div>
      <div class="price-cell-value buyback">{_esc(fmt_price(d.best_buyback_price))}</div>
    </div>
  </div>
  <div class="card-body">
    <div class="condition-row buyback-notice">
      <span class="cond-icon">&#9888;</span>
      買取条件：{_esc(d.buyback_condition or "新品未開封")}　<span style="font-size:0.72rem;color:var(--text-3)">掲載価格は取得・入力時点の参考値です</span>
    </div>
    {updated_str}
    {compare_html}
    <div class="card-actions">{links}</div>
  </div>
</div>"""

    # ================================================================
    # Advanced Tab
    # ================================================================

    def _tab_advanced(self, advanced_deals, advanced_snaps, watch_candidates, camera_watch=None) -> str:
        parts = []
        camera_watch = camera_watch or []

        # 上級者向け説明バナー
        parts.append("""<div style="background:#f5f3ff;border:1px solid #ede9fe;border-radius:12px;padding:14px 18px;margin-bottom:24px;font-size:0.875rem;color:#5b21b6;line-height:1.7;">
<strong>&#128269; 上級者向けとは？</strong><br>
カメラ・限定品などの中古市場差額、抽選販売・SOLD OUT商品の転売、海外相場との価格差を活用する案件です。
入手難易度が高く、市場調査・タイミングが重要です。リスクを十分に理解した上でご判断ください。
</div>""")

        if advanced_deals:
            parts.append(f'<div class="section-head"><div class="section-title">高利益案件</div><div class="section-badge">{len(advanced_deals)}件</div></div>')
            parts.append('<div class="cards-grid">')
            for d in advanced_deals:
                badge_cls = "badge-exp" if d.user_level == "expert_only" else "badge-adv"
                label = "上級者限定" if d.user_level == "expert_only" else "高利益"
                card_html = self._deal_card(d, badge_cls, label)
                overseas_html = self._overseas_links_section(d.product_name, getattr(d, "category", "") or "")
                parts.append(card_html + overseas_html)
            parts.append('</div>')

        if advanced_snaps:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">プレ値・価格差候補</div><div class="section-badge">スナップショット分析</div></div>')
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
                    f"<td class='td-profit'>{_esc(fmt_profit(s.premium_gap_jpy))}</td>"
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

        # カメラ監視候補（中古市場差額）
        if camera_watch:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">カメラ &mdash; 中古市場・海外相場監視</div><div class="section-badge">価格差スコア上位</div></div>')
            parts.append('<div style="background:#f5f3ff;border:1px solid #ede9fe;border-radius:10px;padding:12px 16px;margin-bottom:16px;font-size:0.82rem;color:#5b21b6;line-height:1.6;">&#128247; カメラは新品・中古で市場が分かれています。例：A社の買取価格が10万円でF社の販売価格が8万円なら、F社で購入してA社で売却すると2万円の利益になります。海外相場（eBay・MPB等）も合わせて確認してください。</div>')
            for c in camera_watch:
                parts.append(self._watch_candidate_card(c))

        # その他の監視候補
        other_watch = [c for c in watch_candidates if c.get("genre") != "camera"]
        if other_watch:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">上級者向け監視候補</div><div class="section-badge">価格差・希少性スコア上位</div></div>')
            if not (advanced_deals or advanced_snaps or camera_watch):
                parts.append("""<div class="adv-fallback-notice">
<span>ℹ️</span>
<div><strong>現在、確定候補は少ないため監視候補を表示しています。</strong>中古市場データ入手後に確定候補へ昇格します。</div>
</div>""")
            for c in other_watch:
                parts.append(self._watch_candidate_card(c))

        if not advanced_deals and not advanced_snaps and not camera_watch and not other_watch:
            parts.append('<div class="empty-state"><span class="empty-icon">&#128269;</span>現在、条件を満たす候補はありません。</div>')

        return "\n".join(parts)

    # ================================================================
    # Watch Candidate Card (new design)
    # ================================================================

    def _watch_candidate_card(self, c: dict) -> str:
        """監視候補カード（上級者向け）を生成する。"""
        resolver = get_resolver()
        genre = c.get("genre", "")
        product_name = c.get("product_name", "")
        price  = c.get("official_price")
        bp     = c.get("buyback_price")
        shop   = _esc(c.get("shop_name") or "—")
        flags  = "・".join(c.get("flags", [])) if c.get("flags") else "監視中"

        # ジャンルバッジ
        genre_badge = {
            "iphone": '<span class="badge badge-iphone">iPhone</span>',
            "camera": '<span class="badge badge-camera">カメラ</span>',
            "game_console": '<span class="badge badge-game">ゲーム機</span>',
        }.get(genre, "")

        # 価格差
        gap_html = ""
        if bp and price:
            gap = bp - price
            gap_cls = "gap-positive" if gap > 0 else ("gap-negative" if gap < 0 else "gap-neutral")
            gap_str = f"+¥{gap:,}" if gap >= 0 else f"-¥{abs(gap):,}"
            gap_html = f'<span class="watch-gap-badge {gap_cls}">差額 {_esc(gap_str)}</span>'

        # 買取リンク
        db_url = c.get("buyback_url") or ""
        shop_id = c.get("shop_id") or ""
        buy_link_html = ""
        if resolver:
            resolved_url, link_type = resolver.resolve_buyback_url(
                shop_id=shop_id, genre=genre, db_url=db_url, link_verified=bool(db_url)
            )
            link_type_lbl = _esc(resolver.link_type_label(link_type))
            if resolved_url:
                buy_link_html = (f'<a href="{_esc(resolved_url)}" target="_blank" rel="noopener" '
                                 f'class="btn-card btn-primary watch-link" data-track="buyback_click" data-shop="{shop}">'
                                 f'買取価格を確認 &rarr;</a>'
                                 f'<span class="link-type-badge">{link_type_lbl}</span>')
            else:
                buy_link_html = '<span class="unverified-link">公式買取ページで確認してください</span>'
        elif db_url:
            buy_link_html = (f'<a href="{_esc(db_url)}" target="_blank" rel="noopener" '
                             f'class="btn-card btn-primary watch-link" data-track="buyback_click">買取価格を確認 &rarr;</a>')

        # 海外相場リンク
        overseas_html = self._overseas_links_section(product_name, genre)

        return f"""<div class="watch-card watch-candidate-card">
  <div class="watch-card-head">
    <div class="watch-card-name">{_esc(product_name)}</div>
    <div class="card-tags">
      {genre_badge}
      <span class="badge badge-adv">監視中</span>
    </div>
  </div>
  <div class="watch-price-row">
    <div class="watch-price-item">
      <div class="watch-price-label">公式価格</div>
      <div class="watch-price-value">{_esc(fmt_price(price) if price else "—")}</div>
    </div>
    <div class="watch-price-item">
      <div class="watch-price-label">最新買取価格</div>
      <div class="watch-price-value positive">{_esc(fmt_price(bp) if bp else "—")}</div>
    </div>
    <div class="watch-price-item">
      <div class="watch-price-label">買取店</div>
      <div class="watch-price-value">{shop}</div>
    </div>
    <div class="watch-price-item">
      <div class="watch-price-label">価格差</div>
      <div class="watch-price-value">{gap_html}</div>
    </div>
  </div>
  <div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
    {buy_link_html}
  </div>
  {overseas_html}
</div>"""

    # ================================================================
    # Overseas Links Section
    # ================================================================

    def _overseas_links_section(self, product_name: str, genre: str) -> str:
        """海外相場リンクセクションを生成する。"""
        try:
            resolver = get_resolver()
            if not resolver:
                return ""
            links = resolver.get_overseas_links(product_name, genre, max_links=6)
            if not links:
                return ""
            chips = []
            for lk in links:
                icon = _esc(lk.get("icon", ""))
                label = _esc(lk.get("label", lk.get("name", "")))
                url = _esc(lk.get("url", ""))
                note = _esc(lk.get("note", ""))
                if url:
                    chips.append(
                        f'<a href="{url}" target="_blank" rel="noopener" '
                        f'class="overseas-chip overseas-btn" title="{note}" data-track="overseas_click">'
                        f'{icon} {label}</a>'
                    )
            if not chips:
                return ""
            return (
                '<div class="overseas-links overseas-links-section">'
                '<span class="overseas-label">海外相場を確認</span>'
                + "".join(chips)
                + '</div>'
            )
        except Exception:
            return ""

    # ================================================================
    # Surge Tab
    # ================================================================

    def _tab_surge(self, alerts) -> str:
        surge = [a for a in alerts if a.get("alert_type") == "buyback_surge"]
        drop  = [a for a in alerts if a.get("alert_type") == "buyback_drop"]
        parts = []
        if surge:
            parts.append('<div class="section-head"><div class="section-title">本日の急騰</div></div>')
            for a in surge:
                parts.append(self._alert_card(a, "surge"))
        else:
            parts.append('<div class="section-head"><div class="section-title">本日の急騰</div></div>')
            parts.append('<div class="empty-state"><span class="empty-icon">&#9989;</span>急騰は検出されていません（閾値: ¥5,000+）</div>')
        if drop:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">本日の急落</div></div>')
            for a in drop:
                parts.append(self._alert_card(a, "drop"))
        else:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">本日の急落</div></div>')
            parts.append('<div class="empty-state"><span class="empty-icon">&#9989;</span>急落は検出されていません（閾値: ¥5,000−）</div>')
        return "\n".join(parts)

    def _alert_card(self, a: dict, kind: str) -> str:
        badge = "badge-easy" if kind == "surge" else "badge-exp"
        label = "急騰" if kind == "surge" else "急落"
        prev  = a.get("prev_price", 0) or 0
        curr  = a.get("current_price", 0) or 0
        chg   = curr - prev
        rate  = f"{chg/prev*100:+.1f}%" if prev else "—"
        detected = a.get("detected_at", "")
        return f"""<div class="alert-card {kind}">
<p><strong>{_esc(a.get("product_name",""))}</strong>
@ <span style="color:var(--text-3)">{_esc(a.get("shop_name",""))}</span>
<span class="badge {badge}">{label} ¥{chg:+,}</span></p>
<div style="display:flex;gap:24px;margin-top:10px;flex-wrap:wrap;font-size:0.875rem;">
  <div><div style="font-size:0.65rem;color:var(--text-3);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:3px">前回価格</div><div style="font-weight:700">¥{prev:,}</div></div>
  <div><div style="font-size:0.65rem;color:var(--text-3);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:3px">最新価格</div><div style="font-weight:700">¥{curr:,}</div></div>
  <div><div style="font-size:0.65rem;color:var(--text-3);text-transform:uppercase;letter-spacing:0.05em;margin-bottom:3px">変動</div><div style="font-weight:700">¥{chg:+,} / {_esc(rate)}</div></div>
</div>
<div style="font-size:0.72rem;color:var(--text-3);margin-top:8px">検出時刻：{_esc(str(detected))}</div>
</div>"""

    # ================================================================
    # Ranking Tab
    # ================================================================

    def _tab_ranking(self, all_deals, iphone_deals, game_deals) -> str:
        parts = []
        profitable = sorted([d for d in all_deals if d.net_profit_jpy > 0],
                            key=lambda d: d.net_profit_jpy, reverse=True)
        if profitable:
            parts.append('<div class="section-head"><div class="section-title">実質利益ランキング</div><div class="section-badge">全カテゴリ</div></div>')
            parts.append(self._ranking_table(profitable[:10], show_category=True))
        else:
            parts.append('<div class="section-head"><div class="section-title">実質利益ランキング</div></div>')
            parts.append('<div class="empty-state">データなし</div>')

        iphone_p = sorted([d for d in iphone_deals if d.net_profit_jpy > 0],
                          key=lambda d: d.net_profit_jpy, reverse=True)
        if iphone_p:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">iPhone ランキング</div></div>')
            parts.append(self._ranking_table(iphone_p[:5]))

        game_p = sorted([d for d in game_deals if d.net_profit_jpy > 0],
                        key=lambda d: d.net_profit_jpy, reverse=True)
        if game_p:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">ゲーム機 ランキング</div></div>')
            parts.append(self._ranking_table(game_p[:5]))

        shop_totals: dict = {}
        for d in all_deals:
            if d.best_buyback_shop and d.net_profit_jpy > 0:
                shop_totals[d.best_buyback_shop] = shop_totals.get(d.best_buyback_shop, 0) + 1
        if shop_totals:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">買取店別 案件数</div></div>')
            rows = []
            for i, (shop, cnt) in enumerate(sorted(shop_totals.items(), key=lambda x: x[1], reverse=True)[:8], 1):
                rows.append(f"<tr><td>{i}</td><td>{_esc(shop)}</td><td>{cnt}件</td></tr>")
            parts.append(f"""<div class="ranking-card"><div class="table-wrap">
<table><thead><tr><th>#</th><th>買取店</th><th>案件数</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div></div>""")

        return "\n".join(parts)

    def _ranking_table(self, deals, show_category: bool = False) -> str:
        rows_html = []
        for i, d in enumerate(deals, 1):
            rank_cls = "r1" if i == 1 else ("r2" if i == 2 else ("r3" if i == 3 else ""))
            cat_td = f"<td>{_esc(d.category)}</td>" if show_category else ""
            rows_html.append(
                f"<tr><td class='rank-num {rank_cls}'>{i}</td>"
                f"<td><div class='rank-name'>{_esc(d.product_name)}</div>"
                f"<div class='rank-meta'>{_esc(d.best_buyback_shop or '')}</div></td>"
                + (f"<td>{_esc(d.category)}</td>" if show_category else "")
                + f"<td>{_esc(fmt_price(d.official_price_jpy))}</td>"
                f"<td>{_esc(fmt_price(d.best_buyback_price))}</td>"
                f"<td class='td-profit'>{_esc(fmt_profit(d.net_profit_jpy))}</td>"
                f"<td>{_esc(fmt_rate(d.net_profit_rate))}</td></tr>"
            )
        cat_th = "<th>カテゴリ</th>" if show_category else ""
        return f"""<div class="ranking-card"><div class="table-wrap">
<table>
<thead><tr><th>#</th><th>商品</th>{cat_th}<th>定価</th><th>買取</th><th>実質利益</th><th>率</th></tr></thead>
<tbody>{"".join(rows_html)}</tbody>
</table></div></div>"""

    # ================================================================
    # Caution / CTA / Footer
    # ================================================================

    def _section_caution(self) -> str:
        return """<div class="caution-block">
<div class="caution-title"><span>&#9888;&#65039;</span> ご確認ください</div>
<ul class="caution-list">
<li>本ページは価格差の監視結果であり、購入を推奨するものではありません。</li>
<li>価格・在庫・買取条件は常に変動します。</li>
<li>購入前に必ず公式サイトと買取店で最新の条件を確認してください。</li>
<li>買取条件（新品未開封・SIMフリー等）を満たさない場合、買取価格が下がります。</li>
<li>利益を保証するものではありません。条件が合えば利益が出る可能性がある情報です。</li>
</ul>
</div>"""

    def _section_cta(self) -> str:
        parts = []
        if self.settings.get("enable_note_cta"):
            note_url = (self.settings.get("note_url") or "").strip()
            if note_url and note_url != "#":
                parts.append(f"""<div class="cta-section">
<div class="cta-eyebrow">詳細レポート</div>
<div class="cta-title">全案件・詳細レポートを見る</div>
<p class="cta-desc">仕入れ条件・複数買取店の詳細比較・全案件一覧はnoteで公開しています。</p>
<div class="cta-buttons">
  <a href="{_esc(note_url)}" class="btn-cta-primary" data-track="note_click">詳細レポートを見る &rarr;</a>
  <a href="{_esc(note_url)}" class="btn-cta-secondary" data-track="note_click">今日の全案件を見る</a>
</div>
</div>""")
            else:
                parts.append("""<div class="cta-section">
<div class="cta-eyebrow">詳細レポート</div>
<div class="cta-title">詳細レポート &mdash; 準備中</div>
<p class="cta-desc">仕入れ条件・買取店比較・全案件一覧をnoteで公開予定です。公開時にこのページでお知らせします。</p>
</div>""")
        if self.settings.get("enable_line_cta"):
            line_url = (self.settings.get("line_url") or "").strip()
            if line_url and line_url != "#":
                parts.append(f'<div class="cta-section"><div class="cta-eyebrow">LINE速報</div><div class="cta-title">LINE速報を受け取る</div><div class="cta-buttons"><a href="{_esc(line_url)}" class="btn-cta-primary" style="background:#06c755" data-track="line_click">LINE登録で速報を受け取る</a></div></div>')
        if self.settings.get("enable_telegram_cta"):
            tg_url = (self.settings.get("telegram_url") or "").strip()
            if tg_url and tg_url != "#":
                parts.append(f'<div class="cta-section"><div class="cta-eyebrow">Telegram速報</div><div class="cta-title">Telegramチャンネルに参加する</div><div class="cta-buttons"><a href="{_esc(tg_url)}" class="btn-cta-primary" data-track="telegram_click">Telegramチャンネルに参加する</a></div></div>')
        return "\n".join(parts)

    def _section_footer(self) -> str:
        now = datetime.now()
        return f"""<footer class="footer">
<div class="footer-text">
<p>価格情報は参考値です。購入前に必ず公式サイト・買取店でご確認ください。</p>
<p>&copy; {now.year} プレ値速報 &mdash; 情報は自動取得・分析されたものです</p>
</div>
</footer>"""

    # ================================================================
    # Markdown
    # ================================================================

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
