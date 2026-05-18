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
from src.market.link_resolver import get_resolver
from src.market.new_product_scanner import NewProductScanner

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

        # 新商品候補（watchingステータスのみ）
        try:
            _scanner = NewProductScanner(self.repo)
            new_product_candidates = _scanner.list_watching_candidates(limit=6)
        except Exception as _e:
            logger.warning("新商品候補取得エラー: %s", _e)
            new_product_candidates = []

        # ランキング用
        all_deals = self.repo.list_beginner_deals(min_profit=0, limit=50)
        iphone_deals = [d for d in all_deals if d.category == "iphone"]
        game_deals   = [d for d in all_deals if d.category == "game_console"]

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
            buyback_by_product=buyback_by_product,
            new_product_candidates=new_product_candidates,
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
            "new_products_count": len(new_product_candidates),
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
                     buyback_by_product: dict = None,
                     new_product_candidates: list = None) -> str:

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
        hero_html    = self._section_hero(date_str, time_str, latest_buyback_at, lp_generated_at)
        stale_html   = self._section_stale_warning(latest_buyback_at, latest_deals_at, lp_generated_at)
        tab_html     = self._section_tabs(
            beginner_easy, beginner_watch,
            advanced_deals, advanced_snaps,
            watch_candidates,
            buyback_alerts,
            all_deals, iphone_deals, game_deals,
            buyback_by_product=buyback_by_product or {},
        )
        new_products_html = self._section_new_products(new_product_candidates or [])
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
   プレ値速報 — Bloomberg/TradingView風 リデザイン
   ============================================================ */
:root {{
  /* カラーパレット */
  --bg: #0b0e17;
  --surface: #111827;
  --card: #161d2e;
  --card-hover: #1c2540;
  --border: #1e2a3a;
  --border-light: #253044;
  --text: #e2e8f0;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --accent: #3b82f6;
  --accent-dim: rgba(59,130,246,0.12);
  --green: #10b981;
  --green-dim: rgba(16,185,129,0.12);
  --yellow: #f59e0b;
  --yellow-dim: rgba(245,158,11,0.12);
  --orange: #f97316;
  --orange-dim: rgba(249,115,22,0.12);
  --red: #ef4444;
  --red-dim: rgba(239,68,68,0.12);
  /* タイポグラフィ */
  --font-sans: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
  --font-mono: "SF Mono", "Fira Code", "Cascadia Code", monospace;
  /* スペーシング */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-xl: 20px;
}}
*, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  font-family: var(--font-sans);
  background: var(--bg);
  color: var(--text);
  line-height: 1.65;
  font-size: 15px;
  -webkit-font-smoothing: antialiased;
}}
/* ---- Layout ---- */
.container {{
  max-width: 860px;
  margin: 0 auto;
  padding: 0 16px 48px;
}}
/* ---- Topbar ---- */
.topbar {{
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(12px);
}}
.topbar-brand {{
  font-size: 0.88rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}}
.topbar-brand .dot {{
  width: 8px; height: 8px;
  background: var(--green);
  border-radius: 50%;
  animation: pulse-dot 2s infinite;
}}
@keyframes pulse-dot {{
  0%, 100% {{ opacity: 1; transform: scale(1); }}
  50% {{ opacity: 0.5; transform: scale(0.8); }}
}}
.topbar-meta {{
  font-size: 0.75rem;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 16px;
}}
/* ---- Hero ---- */
.hero {{
  padding: 56px 0 36px;
  text-align: center;
  position: relative;
}}
.hero::before {{
  content: "";
  position: absolute;
  top: 0; left: 50%;
  transform: translateX(-50%);
  width: 600px; height: 300px;
  background: radial-gradient(ellipse at center, rgba(59,130,246,0.08) 0%, transparent 70%);
  pointer-events: none;
}}
.hero-eyebrow {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--accent-dim);
  border: 1px solid rgba(59,130,246,0.25);
  color: var(--accent);
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 4px 12px;
  border-radius: 99px;
  margin-bottom: 20px;
}}
.hero h1 {{
  font-size: clamp(1.6rem, 4vw, 2.2rem);
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.2;
  color: var(--text);
  margin-bottom: 12px;
}}
.hero-sub {{
  font-size: 0.95rem;
  color: var(--text-secondary);
  margin-bottom: 28px;
  max-width: 480px;
  margin-left: auto;
  margin-right: auto;
}}
.hero-timestamps {{
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}}
.ts-chip {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--card);
  border: 1px solid var(--border-light);
  color: var(--text-secondary);
  font-size: 0.78rem;
  padding: 6px 14px;
  border-radius: 99px;
  font-variant-numeric: tabular-nums;
}}
.ts-chip .ts-dot {{
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--green);
  flex-shrink: 0;
}}
.ts-chip.stale .ts-dot {{ background: var(--orange); }}
/* ---- Stale Warning ---- */
.stale-warning-block {{
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: rgba(249,115,22,0.08);
  border: 1px solid rgba(249,115,22,0.3);
  border-left: 4px solid var(--orange);
  padding: 14px 18px;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  margin: 16px 0;
  font-size: 0.875rem;
  color: #fed7aa;
  line-height: 1.6;
}}
.stale-warning-block .warn-icon {{ font-size: 1.1rem; flex-shrink: 0; margin-top: 1px; }}
/* ---- Tab Navigation ---- */
.tab-nav {{
  display: flex;
  gap: 4px;
  margin: 32px 0 0;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}}
.tab-nav::-webkit-scrollbar {{ display: none; }}
.tab-btn {{
  flex-shrink: 0;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 12px 20px;
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-muted);
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s;
  margin-bottom: -1px;
  white-space: nowrap;
  letter-spacing: 0.01em;
}}
.tab-btn:hover {{ color: var(--text-secondary); }}
.tab-btn.active {{
  color: var(--accent);
  border-bottom-color: var(--accent);
  font-weight: 600;
}}
.tab-panel {{ display: none; padding: 20px 0 0; }}
.tab-panel.active {{ display: block; }}
/* noscript fallback */
.noscript-all .tab-panel {{ display: block !important; }}
.noscript-all .tab-btn {{ display: none; }}
.noscript-all .tab-nav::before {{
  content: "※ JavaScript が無効です。全タブを表示しています。";
  display: block; color: var(--text-muted); font-size: 0.8rem; padding: 8px 0; width: 100%;
}}
/* ---- Section Headers ---- */
.section-header {{
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 28px 0 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}}
.section-header h2 {{
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--text-secondary);
  text-transform: uppercase;
}}
.section-header .section-count {{
  font-size: 0.72rem;
  background: var(--border);
  color: var(--text-muted);
  padding: 2px 8px;
  border-radius: 99px;
}}
/* ---- Cards ---- */
.card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 22px;
  margin: 10px 0;
  transition: border-color 0.15s, background 0.15s;
}}
.card:hover {{
  border-color: var(--border-light);
  background: var(--card-hover);
}}
.card-header {{
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}}
.card-title {{
  font-size: 1rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1.3;
  flex: 1;
}}
/* ---- Badges ---- */
.badge {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 99px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  white-space: nowrap;
  flex-shrink: 0;
}}
.badge-easy {{ background: var(--green-dim); color: var(--green); border: 1px solid rgba(16,185,129,0.25); }}
.badge-watch {{ background: var(--yellow-dim); color: var(--yellow); border: 1px solid rgba(245,158,11,0.25); }}
.badge-adv {{ background: var(--orange-dim); color: var(--orange); border: 1px solid rgba(249,115,22,0.25); }}
.badge-exp {{ background: var(--red-dim); color: var(--red); border: 1px solid rgba(239,68,68,0.25); }}
.badge-surge {{ background: var(--green-dim); color: var(--green); border: 1px solid rgba(16,185,129,0.25); }}
.badge-drop {{ background: var(--red-dim); color: var(--red); border: 1px solid rgba(239,68,68,0.25); }}
/* ---- Price Grid ---- */
.price-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 14px;
}}
.price-cell {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px 12px;
}}
.price-cell-label {{
  font-size: 0.7rem;
  color: var(--text-muted);
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin-bottom: 4px;
}}
.price-cell-value {{
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}}
.price-cell.profit-cell {{
  background: var(--green-dim);
  border-color: rgba(16,185,129,0.25);
  grid-column: span 2;
}}
.price-cell.profit-cell .price-cell-value {{
  font-size: 1.35rem;
  color: var(--green);
  letter-spacing: -0.02em;
}}
.profit-rate-badge {{
  display: inline-flex;
  align-items: center;
  background: rgba(16,185,129,0.2);
  color: var(--green);
  font-size: 0.75rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  margin-left: 8px;
  vertical-align: middle;
}}
/* ---- Price Rows (legacy support) ---- */
.price-row {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 0;
  border-bottom: 1px solid var(--border);
  font-size: 0.9rem;
}}
.price-row:last-child {{ border: none; }}
.price-label {{ color: var(--text-muted); font-size: 0.85rem; }}
.price-value {{ font-weight: 600; color: var(--text); font-variant-numeric: tabular-nums; }}
.profit {{ color: var(--green); font-size: 1.2rem; font-weight: 800; }}
/* ---- Condition Bar ---- */
.condition-bar {{
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--surface);
  border-radius: var(--radius-sm);
  margin: 12px 0;
  font-size: 0.82rem;
  color: var(--text-secondary);
}}
.condition-bar .cond-icon {{ color: var(--yellow); }}
/* ---- Buyback Compare ---- */
.buyback-compare {{
  margin: 14px 0 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}}
.buyback-compare-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  font-size: 0.78rem;
  color: var(--text-muted);
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}}
.shop-compare-row {{
  display: flex;
  align-items: center;
  padding: 9px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 0.875rem;
  transition: background 0.1s;
}}
.shop-compare-row:last-child {{ border: none; }}
.shop-compare-row:hover {{ background: var(--surface); }}
.shop-rank {{
  color: var(--text-muted);
  min-width: 24px;
  font-size: 0.78rem;
  font-weight: 700;
}}
.shop-rank.rank-1 {{ color: var(--yellow); }}
.shop-name {{ flex: 1; padding: 0 10px; color: var(--text-secondary); }}
.shop-name a {{ color: var(--accent); text-decoration: none; }}
.shop-name a:hover {{ text-decoration: underline; }}
.shop-price {{ font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; min-width: 80px; text-align: right; }}
.shop-profit {{ font-size: 0.78rem; color: var(--green); min-width: 70px; text-align: right; font-weight: 600; }}
.shop-profit.negative {{ color: var(--red); }}
/* ---- Links ---- */
.links {{
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}}
.links a {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--accent);
  text-decoration: none;
  font-size: 0.82rem;
  font-weight: 500;
  padding: 6px 14px;
  border: 1px solid rgba(59,130,246,0.3);
  border-radius: var(--radius-sm);
  background: var(--accent-dim);
  transition: background 0.15s, border-color 0.15s;
}}
.links a:hover {{
  background: rgba(59,130,246,0.2);
  border-color: rgba(59,130,246,0.5);
}}
/* ---- Table ---- */
.data-table-wrap {{
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}}
thead tr {{
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}}
th {{
  padding: 10px 12px;
  text-align: left;
  color: var(--text-muted);
  font-weight: 600;
  font-size: 0.72rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  white-space: nowrap;
}}
td {{
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
  word-break: break-word;
}}
tbody tr:last-child td {{ border: none; }}
tbody tr:hover td {{ background: var(--surface); }}
td.profit-td {{ color: var(--green); font-weight: 700; font-variant-numeric: tabular-nums; }}
/* ---- Freshness Labels ---- */
.freshness-live {{ color: var(--green); font-size: 0.72rem; font-weight: 600; }}
.freshness-recent {{ color: var(--yellow); font-size: 0.72rem; font-weight: 600; }}
.freshness-stale {{ color: var(--red); font-size: 0.72rem; font-weight: 600; }}
.freshness-unknown {{ color: var(--text-muted); font-size: 0.72rem; }}
/* ---- Updated Timestamp ---- */
.updated-ts {{
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}}
/* ---- Empty State ---- */
.empty-msg {{
  text-align: center;
  color: var(--text-muted);
  padding: 32px 16px;
  font-size: 0.9rem;
}}
/* ---- Caution Block ---- */
.caution {{
  background: rgba(245,158,11,0.06);
  border: 1px solid rgba(245,158,11,0.2);
  border-left: 3px solid var(--yellow);
  padding: 18px 20px;
  margin: 32px 0;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.8;
}}
.caution strong {{ color: var(--yellow); display: block; margin-bottom: 8px; font-size: 0.9rem; }}
.caution ul {{ list-style: none; padding: 0; }}
.caution ul li {{ padding: 2px 0; }}
.caution ul li::before {{ content: "·  "; color: var(--text-muted); }}
/* ---- CTA Section ---- */
.cta-section {{
  margin: 40px 0;
  padding: 32px 24px;
  background: linear-gradient(135deg, rgba(59,130,246,0.06) 0%, rgba(16,185,129,0.04) 100%);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-xl);
  text-align: center;
}}
.cta-section h3 {{
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 8px;
}}
.cta-section p {{
  font-size: 0.875rem;
  color: var(--text-secondary);
  margin-bottom: 20px;
  max-width: 400px;
  margin-left: auto;
  margin-right: auto;
}}
.cta-buttons {{
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}}
.cta-btn {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 12px 24px;
  border-radius: var(--radius-md);
  text-decoration: none;
  font-weight: 600;
  font-size: 0.9rem;
  transition: all 0.15s;
}}
.cta-btn-primary {{
  background: var(--accent);
  color: #fff;
  border: 1px solid transparent;
}}
.cta-btn-primary:hover {{ background: #2563eb; }}
.cta-btn-secondary {{
  background: var(--card);
  color: var(--text-secondary);
  border: 1px solid var(--border-light);
}}
.cta-btn-secondary:hover {{ background: var(--card-hover); color: var(--text); }}
/* ---- Footer ---- */
.footer {{
  text-align: center;
  color: var(--text-muted);
  font-size: 0.78rem;
  padding: 40px 0 24px;
  line-height: 2;
  border-top: 1px solid var(--border);
  margin-top: 40px;
}}
/* ---- Watch Candidate Card ---- */
.watch-candidate-card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  margin: 10px 0;
}}
.watch-candidate-card .wc-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}}
.watch-candidate-card .wc-title {{
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--text);
}}
.watch-candidate-card .wc-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}}
.wc-tag {{
  font-size: 0.72rem;
  padding: 3px 9px;
  border-radius: 4px;
  font-weight: 600;
}}
.wc-tag-soldout {{ background: var(--red-dim); color: var(--red); }}
.wc-tag-lottery {{ background: var(--yellow-dim); color: var(--yellow); }}
.wc-tag-overseas {{ background: var(--accent-dim); color: var(--accent); }}
.wc-tag-camera {{ background: rgba(139,92,246,0.12); color: #a78bfa; }}
.wc-tag-game {{ background: rgba(20,184,166,0.12); color: #2dd4bf; }}
/* ---- Alert Card ---- */
.alert-card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  margin: 10px 0;
}}
.alert-card.surge {{ border-left: 3px solid var(--green); }}
.alert-card.drop {{ border-left: 3px solid var(--red); }}
/* ---- Ranking Table ---- */
.ranking-card {{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  margin: 10px 0;
}}
.ranking-card table {{ font-size: 0.85rem; }}
.ranking-card th {{ background: var(--surface); }}
.rank-num {{ color: var(--text-muted); font-weight: 700; font-size: 0.85rem; }}
.rank-num.top3 {{ color: var(--yellow); }}
/* ---- Divider ---- */
.section-divider {{
  height: 1px;
  background: var(--border);
  margin: 24px 0;
}}
/* ---- Responsive ---- */
@media (max-width: 600px) {{
  .hero {{ padding: 40px 0 28px; }}
  .hero h1 {{ font-size: 1.5rem; }}
  .price-grid {{ grid-template-columns: 1fr 1fr; gap: 8px; }}
  .price-cell.profit-cell .price-cell-value {{ font-size: 1.15rem; }}
  .tab-btn {{ padding: 10px 14px; font-size: 0.82rem; }}
  table {{ font-size: 0.8rem; }}
  th, td {{ padding: 8px 8px; }}
  .card {{ padding: 16px; }}
  .cta-section {{ padding: 24px 16px; }}
  .topbar-meta {{ display: none; }}
  .shop-profit {{ display: none; }}
}}
@media (max-width: 400px) {{
  .price-grid {{ grid-template-columns: 1fr; }}
  .price-cell.profit-cell {{ grid-column: span 1; }}
}}
/* ────────── デザイン改善 ────────── */
/* カード hover effect */
.card {{
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}}
.card:hover {{
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.35);
}}
/* 初心者向けカード: 左ボーダーをグリーン */
.card[data-user-level="beginner_easy"] {{
  border-left: 3px solid var(--green);
}}
.card[data-user-level="beginner_watch"] {{
  border-left: 3px solid var(--cyan);
}}
/* 上級者向けカード: 左ボーダーをオレンジ */
.card[data-user-level="advanced_high_profit"],
.card[data-user-level="expert_only"],
.adv-snap-card {{
  border-left: 3px solid var(--orange);
}}
/* 監視候補カード */
.watch-candidate-card {{
  border-left: 3px solid var(--yellow);
}}
/* .badge 改善 */
.badge-easy {{
  background: rgba(0,170,101,0.15);
  color: var(--green);
  border: 1px solid rgba(0,170,101,0.4);
}}
.badge-watch {{
  background: rgba(34,211,238,0.12);
  color: var(--cyan);
  border: 1px solid rgba(34,211,238,0.3);
}}
.badge-adv {{
  background: rgba(251,146,60,0.12);
  color: var(--orange);
  border: 1px solid rgba(251,146,60,0.3);
}}
.badge-exp {{
  background: rgba(239,68,68,0.12);
  color: var(--red);
  border: 1px solid rgba(239,68,68,0.3);
}}
/* 販売方法バッジ */
.sale-method-badge {{
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 20px;
  background: rgba(251,191,36,0.15);
  color: var(--yellow);
  border: 1px solid rgba(251,191,36,0.3);
  margin-left: 6px;
}}
/* no-data 表示 */
.no-data {{
  color: var(--text-muted);
  font-size: 0.78rem;
  font-style: italic;
}}
/* 上級者タブのメタ情報行 */
.adv-meta-row {{
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin: 8px 0 4px;
}}
.adv-meta-item {{
  font-size: 0.78rem;
  color: var(--text-muted);
}}
.adv-meta-item strong {{
  color: var(--text);
}}
/* フォールバック通知 */
.adv-fallback-notice {{
  display: flex;
  gap: 10px;
  align-items: flex-start;
  background: rgba(34,211,238,0.06);
  border: 1px solid rgba(34,211,238,0.2);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 16px;
  font-size: 0.82rem;
  color: var(--text-muted);
}}
.adv-fallback-icon {{ font-size: 1.1rem; margin-top: 1px; }}
.adv-fallback-notice strong {{ color: var(--cyan); }}
/* 監視候補 price row */
.watch-price-row {{
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
  margin: 8px 0 6px;
}}
.watch-price-item {{
  font-size: 0.78rem;
  color: var(--text-muted);
}}
.watch-gap {{
  font-size: 0.82rem;
  font-weight: 600;
}}
.watch-links-row {{
  font-size: 0.82rem;
  margin-bottom: 8px;
}}
.watch-footer-note {{
  font-size: 0.74rem;
  color: var(--text-muted);
  margin-top: 12px;
  padding: 6px 8px;
  border-left: 2px solid var(--border-light);
  font-style: italic;
}}
/* link-type badge */
.link-type-badge {{
  display: inline-block;
  font-size: 0.68rem;
  background: var(--surface);
  border: 1px solid var(--border-light);
  color: var(--text-muted);
  padding: 1px 6px;
  border-radius: 10px;
  margin-left: 4px;
  vertical-align: middle;
}}
/* 海外相場リンクセクション */
.overseas-links-section {{
  margin-top: 12px;
  padding: 12px;
  background: rgba(15,23,42,0.6);
  border: 1px solid var(--border);
  border-radius: 8px;
}}
.overseas-links-header {{
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin-bottom: 8px;
  flex-wrap: wrap;
}}
.overseas-links-title {{
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--cyan);
}}
.overseas-links-note {{
  font-size: 0.72rem;
  color: var(--text-muted);
}}
.overseas-btn-row {{
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}}
.overseas-btn {{
  display: inline-block;
  font-size: 0.76rem;
  padding: 4px 10px;
  border-radius: 20px;
  background: var(--surface);
  border: 1px solid var(--border-light);
  color: var(--cyan);
  text-decoration: none;
  transition: background 0.12s, border-color 0.12s;
  white-space: nowrap;
}}
.overseas-btn:hover {{
  background: rgba(34,211,238,0.1);
  border-color: var(--cyan);
}}
/* 買取店比較テーブル */
.buyback-shop-table {{
  margin-top: 12px;
}}
.buyback-table-wrap {{
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}}
.buyback-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 0.82rem;
}}
.buyback-table thead tr {{
  background: var(--surface);
  color: var(--text-muted);
  font-size: 0.75rem;
}}
.buyback-table th {{
  padding: 5px 8px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}}
.buyback-table td {{
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}}
.buyback-shop-row.rank-1 td {{
  background: rgba(0,170,101,0.07);
}}
.shop-rank-cell {{
  font-weight: 700;
  color: var(--text-muted);
  width: 24px;
  text-align: center;
}}
.buyback-shop-row.rank-1 .shop-rank-cell {{
  color: var(--green);
}}
.shop-price-cell {{
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
}}
.buyback-shop-row.rank-1 .shop-price-cell {{
  color: var(--green);
}}
.shop-diff-cell {{
  white-space: nowrap;
  font-size: 0.8rem;
}}
.shop-diff-cell.positive {{ color: var(--green); }}
.shop-diff-cell.negative {{ color: var(--red); }}
.shop-link-cell a {{
  font-size: 0.75rem;
  color: var(--cyan);
  white-space: nowrap;
}}
.unverified-link {{
  font-size: 0.74rem;
  color: var(--text-muted);
  font-style: italic;
}}
.buyback-best-price {{
  color: var(--green);
}}
.shop-count-badge {{
  font-size: 0.72rem;
  background: var(--surface);
  border: 1px solid var(--border-light);
  padding: 2px 8px;
  border-radius: 20px;
  color: var(--text-muted);
}}
.buyback-median {{
  font-size: 0.72rem;
  color: var(--text-muted);
}}
.price-summary-row {{
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
  margin: 6px 0 4px;
}}
.price-summary-item {{
  font-size: 0.78rem;
  color: var(--text-muted);
}}
.price-summary-item strong {{
  color: var(--green);
}}
.stale-warning {{
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.25);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 0.78rem;
  color: var(--red);
  margin: 8px 0;
}}
.buyback-notice {{
  font-size: 0.72rem;
  color: var(--text-muted);
  margin-top: 8px;
  padding: 6px 8px;
  border-left: 2px solid var(--border-light);
  font-style: italic;
}}
/* 新商品候補セクション */
.section-new-products {{
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
}}
.section-new-products .section-title {{
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--cyan);
  margin-bottom: 6px;
}}
.section-new-products .section-desc {{
  font-size: 0.82rem;
  color: var(--text-muted);
  margin-bottom: 16px;
}}
.new-product-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
}}
.new-product-card {{
  background: var(--card);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  padding: 14px;
}}
.npc-header {{
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}}
.npc-category {{
  font-size: 0.72rem;
  background: var(--blue);
  color: #fff;
  padding: 2px 8px;
  border-radius: 20px;
}}
.npc-sale-method {{
  font-size: 0.72rem;
  background: var(--yellow);
  color: #000;
  padding: 2px 8px;
  border-radius: 20px;
}}
.npc-name {{
  font-size: 0.92rem;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 4px;
}}
.npc-meta, .npc-price {{
  font-size: 0.78rem;
  color: var(--text-muted);
  margin-bottom: 3px;
}}
.npc-score {{
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 6px;
}}
.score-bar {{
  color: var(--green);
  font-family: monospace;
  letter-spacing: -1px;
}}
.score-val {{
  color: var(--text);
  font-weight: 700;
  margin-left: 4px;
}}
.npc-reason {{
  font-size: 0.74rem;
  color: var(--text-muted);
  margin-top: 4px;
  font-style: italic;
}}
.section-note {{
  font-size: 0.74rem;
  color: var(--text-muted);
  margin-top: 12px;
}}
</style>
</head>
<body>
<header class="topbar">
  <div class="topbar-brand"><span class="dot"></span>プレ値速報</div>
  <div class="topbar-meta">
    <span>買取更新: {_esc(_buyback_str_top)}</span>
    <span>生成: {_esc(_lp_str_top)}</span>
  </div>
</header>
<div class="container">
{hero_html}
{stale_html}
{tab_html}
{new_products_html}
{caution_html}
{cta_html}
{footer_html}
</div>
<script>
(function(){{
  var btns=document.querySelectorAll(".tab-btn");
  var panels=document.querySelectorAll(".tab-panel");
  if(!btns.length)return;
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

    def _section_hero(self, date_str, time_str, latest_buyback_at, lp_generated_at) -> str:
        variant_key = self.settings.get("headline_variant", "A")
        variants    = self.settings.get("variants", {})
        variant     = variants.get(variant_key, {})
        headline    = _esc(variant.get("headline", self.settings.get("site_title", "プレ値速報")))
        buyback_str = _jst_str(latest_buyback_at)
        lp_str      = _jst_str(lp_generated_at)
        stale_cls   = "stale" if _hours_ago(latest_buyback_at) > 24 else ""
        return f"""<div class="hero">
  <div class="hero-eyebrow"><span>毎日更新</span></div>
  <h1>{headline}</h1>
  <p class="hero-sub">公式価格と買取価格の差額を毎日監視。初心者でも分かりやすく整理しています。</p>
  <div class="hero-timestamps">
    <span class="ts-chip {_esc(stale_cls)}" data-buyback-updated>
      <span class="ts-dot"></span>買取価格更新：{_esc(buyback_str)}
    </span>
    <span class="ts-chip" data-lp-generated>
      <span class="ts-dot" style="background:var(--accent)"></span>LP生成：{_esc(lp_str)}
    </span>
  </div>
</div>"""
    # ----- Stale Warning -----
    def _section_stale_warning(self, latest_buyback_at, latest_deals_at, lp_generated_at) -> str:
        msgs = []
        buyback_h = _hours_ago(latest_buyback_at)
        deals_h   = _hours_ago(latest_deals_at)
        lp_h      = _hours_ago(lp_generated_at)
        if buyback_h >= 24:
            msgs.append(f"買取価格（{buyback_h:.0f}時間前のデータ）")
        if deals_h >= 24:
            msgs.append(f"案件情報（{deals_h:.0f}時間前のデータ）")
        if lp_h >= 24:
            msgs.append(f"LP（{lp_h:.0f}時間前に生成）")
        if not msgs:
            return ""
        detail = "・".join(msgs)
        return f"""<div class="stale-warning-block">
  <span class="warn-icon">⚠️</span>
  <div><strong>データが古い可能性があります：</strong>{_esc(detail)}が24時間以上前のデータです。購入前に必ず買取店公式ページで最新価格をご確認ください。</div>
</div>"""
    def _section_tabs(self, beginner_easy, beginner_watch,
                      advanced_deals, advanced_snaps, watch_candidates,
                      buyback_alerts, all_deals, iphone_deals, game_deals,
                      buyback_by_product: dict = None) -> str:

        beginner_html = self._tab_beginner(beginner_easy, beginner_watch,
                                           buyback_by_product=buyback_by_product or {})
        advanced_html = self._tab_advanced(advanced_deals, advanced_snaps, watch_candidates)
        surge_html    = self._tab_surge(buyback_alerts)
        ranking_html  = self._tab_ranking(all_deals, iphone_deals, game_deals)

        surge_count = len([a for a in buyback_alerts if a.get("alert_type") in ("buyback_surge", "buyback_drop")])
        surge_label = f"急騰/急落{'(' + str(surge_count) + ')' if surge_count else ''}"
        adv_total   = len(advanced_deals) + len(advanced_snaps) + len(watch_candidates)

        return f"""<nav class="tab-nav" role="tablist">
  <button class="tab-btn active" data-tab="beginner" role="tab" aria-selected="true" aria-controls="tab-beginner">初級者向け <span style="font-size:0.72rem;opacity:0.7">({len(beginner_easy)+len(beginner_watch)}件)</span></button>
  <button class="tab-btn" data-tab="advanced" role="tab" aria-selected="false" aria-controls="tab-advanced">上級者向け <span style="font-size:0.72rem;opacity:0.7">({adv_total}件)</span></button>
  <button class="tab-btn" data-tab="surge" role="tab" aria-selected="false" aria-controls="tab-surge">急騰 / 急落</button>
  <button class="tab-btn" data-tab="ranking" role="tab" aria-selected="false" aria-controls="tab-ranking">買取ランキング</button>
</nav>
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

    # ----- データ鮮度ラベル -----

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
        bybp = buyback_by_product or {}
        parts = []

        if easy_deals:
            parts.append('<div class="section-header"><h2>低難度 — すぐ動ける案件</h2><span class="section-count">' + str(len(easy_deals)) + '件</span></div>')
            for d in easy_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, "badge-easy", "低難度", buyback_rows=rows))
        else:
            parts.append('<div class="section-header"><h2>低難度 — すぐ動ける案件</h2></div><p class="empty-msg">現在、条件を満たす案件はありません。</p>')

        if watch_deals:
            parts.append('<div class="section-header"><h2>要確認 — 様子見案件</h2><span class="section-count">' + str(len(watch_deals)) + '件</span></div>')
            for d in watch_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, "badge-watch", "要確認", buyback_rows=rows))
        else:
            parts.append('<div class="section-header"><h2>要確認 — 様子見案件</h2></div><p class="empty-msg">現在、条件を満たす案件はありません。</p>')

        return "\n".join(parts)

    def _deal_card(self, d, badge_cls: str, label: str, buyback_rows: list = None) -> str:
        """初心者向け案件カードHTML。複数買取店価格順テーブルを含む。"""
        import json as _json
        pid = _esc(d.product_id)
        official_price = d.official_price_jpy or 0

        # ---- 複数店舗データを決定 ----
        # buyback_prices_json（DBから）を優先。なければ buyback_rows（LP generator取得）を使用
        shop_entries = []
        json_str = getattr(d, "buyback_prices_json", "") or ""
        if json_str:
            try:
                shop_entries = _json.loads(json_str)
            except Exception:
                shop_entries = []
        if not shop_entries and buyback_rows:
            # buyback_rowsから変換
            shop_entries = [
                {
                    "shop_id": r.get("shop_id", ""),
                    "shop_name": r.get("shop_name", ""),
                    "price": r.get("buyback_price", 0),
                    "url": r.get("buyback_url", "") or "",
                    "link_verified": bool(r.get("link_verified", False)),
                    "data_source": r.get("data_source", "manual_today"),
                }
                for r in buyback_rows[:5]
            ]
        # 価格降順でソート
        shop_entries = sorted(shop_entries, key=lambda x: x.get("price", 0), reverse=True)[:5]

        # ---- 鮮度 ----
        scanned_at_str = _jst_str(d.scanned_at) if hasattr(d, "scanned_at") and d.scanned_at else "—"
        # buyback_rowsから observed_at を取得（スキャン日時より正確）
        freshness_src = buyback_rows[0] if buyback_rows else {}
        freshness_html = self._freshness_label(
            freshness_src.get("observed_at", ""), freshness_src.get("data_source", "manual_today")
        )

        # ---- stale警告 ----
        stale_warning = ""
        data_src = freshness_src.get("data_source", "manual_today")
        if data_src == "stale" or (not freshness_src and not json_str):
            stale_warning = '<div class="stale-warning">⚠️ このデータは古い可能性があります。必ず各買取店で最新価格をご確認ください。</div>'

        # ---- 複数店舗比較テーブル ----
        shop_count = getattr(d, "buyback_shop_count", len(shop_entries)) or len(shop_entries) or 1
        median_price = getattr(d, "median_buyback_price", None)

        _link_res = get_resolver()
        genre = getattr(d, "category", "") or ""
        rows_html = []
        for i, s in enumerate(shop_entries, start=1):
            bp = s.get("price", 0)
            shop_id_val = s.get("shop_id", "")
            sname = _esc(s.get("shop_name", "") or shop_id_val)
            db_url = (s.get("url") or "").strip()
            verified = bool(s.get("link_verified", False))
            diff = bp - official_price
            diff_str = f"+¥{diff:,}" if diff >= 0 else f"−¥{abs(diff):,}"
            rank_cls = " rank-1" if i == 1 else ""
            diff_cls = " positive" if diff > 0 else " negative" if diff < 0 else ""

            # link_resolver でURL補完
            resolved_url, link_type = _link_res.resolve_buyback_url(
                shop_id=shop_id_val, genre=genre, db_url=db_url, link_verified=verified
            )
            link_type_lbl = _esc(_link_res.link_type_label(link_type))

            if resolved_url:
                link_cell = (f'<a href="{_esc(resolved_url)}" target="_blank" rel="noopener" '
                             f'data-track="buyback_click" data-product-id="{pid}" '
                             f'data-shop="{sname}" title="{link_type_lbl}">'
                             f'買取価格を確認 →</a>'
                             f'<span class="link-type-badge">{link_type_lbl}</span>')
            else:
                link_cell = '<span class="unverified-link">公式買取ページで確認してください</span>'

            rows_html.append(
                f'<tr class="buyback-shop-row{rank_cls}">'
                f'<td class="shop-rank-cell">{i}</td>'
                f'<td class="shop-name-cell">{sname}</td>'
                f'<td class="shop-price-cell">¥{bp:,}</td>'
                f'<td class="shop-diff-cell{diff_cls}">{_esc(diff_str)}</td>'
                f'<td class="shop-link-cell">{link_cell}</td>'
                f'</tr>'
            )

        median_row = f'<span class="buyback-median">中央値 ¥{median_price:,}</span>' if median_price else ""
        shop_count_badge = f'<span class="shop-count-badge">参照 {shop_count} 店舗</span>'

        compare_html = ""
        if rows_html:
            compare_html = f"""<div class="buyback-compare buyback-shop-table">
  <div class="buyback-compare-header">
    <span>本日の買取価格比較</span>
    {freshness_html}
    {shop_count_badge}
    {median_row}
  </div>
  <div class="buyback-table-wrap">
    <table class="buyback-table">
      <thead><tr><th>#</th><th>買取店</th><th>買取価格</th><th>参考差額</th><th>リンク</th></tr></thead>
      <tbody>{"".join(rows_html)}</tbody>
    </table>
  </div>
</div>"""

        # ---- 公式ページリンク ----
        official_link = ""
        if d.official_url:
            official_link = (f'<a href="{_esc(d.official_url)}" target="_blank" rel="noopener" '
                             f'data-track="product_click" data-product-id="{pid}">公式購入ページ →</a>')

        # ---- カード組み立て ----
        profit_rate_str = _esc(fmt_rate(d.net_profit_rate))
        best_price_str = fmt_price(d.best_buyback_price)
        diff_top = (d.best_buyback_price or 0) - official_price
        diff_top_str = f"+¥{diff_top:,}" if diff_top >= 0 else f"−¥{abs(diff_top):,}"

        return f"""<div class="card" data-user-level="{_esc(d.user_level)}">
  <div class="card-header">
    <div class="card-title">{_esc(d.product_name)}</div>
    <span class="badge {badge_cls}">{label}</span>
  </div>
  <div class="price-grid">
    <div class="price-cell">
      <div class="price-cell-label">公式価格</div>
      <div class="price-cell-value">{_esc(fmt_price(official_price or None))}</div>
    </div>
    <div class="price-cell">
      <div class="price-cell-label">最高買取価格</div>
      <div class="price-cell-value buyback-best-price">{_esc(best_price_str)}</div>
    </div>
    <div class="price-cell profit-cell">
      <div class="price-cell-label">実質利益（推定コスト差引後）</div>
      <div class="price-cell-value">{_esc(fmt_profit(d.net_profit_jpy))} <span class="profit-rate-badge">{profit_rate_str}</span></div>
    </div>
  </div>
  <div class="price-summary-row">
    <span class="price-summary-item">参考差額（最高値）: <strong>{_esc(diff_top_str)}</strong></span>
    <span class="price-summary-item">{shop_count_badge}</span>
    <span class="price-summary-item">更新: {_esc(scanned_at_str)}</span>
  </div>
  <div class="condition-bar">
    <span class="cond-icon">⚠</span>
    <span>買取条件：{_esc(d.buyback_condition or '新品未開封')}　推定コスト：-{_esc(fmt_price(d.estimated_costs_jpy))}</span>
  </div>
  {stale_warning}
  {compare_html}
  <div class="buyback-notice">※ 掲載価格は取得・入力時点の参考値です。買取価格・条件は短時間で変動するため、売却前に必ず各買取店の公式情報をご確認ください。</div>
  <div class="links">{official_link}</div>
</div>"""

    # ----- Tab: 上級者向け -----

    def _tab_advanced(self, advanced_deals, advanced_snaps, watch_candidates) -> str:
        parts = []
        _link_res = get_resolver()

        if advanced_deals:
            parts.append('<div class="section-header"><h2>高利益案件</h2><span class="section-count">' + str(len(advanced_deals)) + '件</span></div>')
            for d in advanced_deals:
                badge_cls = "badge-exp" if d.user_level == "expert_only" else "badge-adv"
                label = "上級者限定" if d.user_level == "expert_only" else "高利益"
                card_html = self._deal_card(d, badge_cls, label)
                # 海外相場リンクセクションを追加
                overseas_html = self._overseas_links_section(
                    d.product_name, getattr(d, "category", "") or ""
                )
                parts.append(card_html + overseas_html)

        if advanced_snaps:
            parts.append('<div class="section-header"><h2>プレ値・価格差候補</h2><span class="section-count">スナップショット分析</span></div>')
            for s in advanced_snaps:
                method_key = getattr(s, "sale_method", "")
                method_label = {"lottery": "🎰 抽選", "soldout": "❌ SOLD OUT",
                                "discontinued": "🚫 終了", "limited": "⚡ 限定"}.get(
                    method_key, method_key or "通常")
                difficulty = getattr(s, "difficulty_score", 0) or 0
                genre = getattr(s, "genre", "") or getattr(s, "category", "") or ""
                overseas_html = self._overseas_links_section(s.product_name, genre)

                parts.append(f"""<div class="card adv-snap-card">
  <div class="card-header">
    <div class="card-title">{_esc(s.product_name)}</div>
    <span class="badge badge-adv">上級者向け</span>
    {f'<span class="sale-method-badge">{_esc(method_label)}</span>' if method_label else ""}
  </div>
  <div class="price-grid">
    <div class="price-cell"><div class="price-cell-label">定価</div>
      <div class="price-cell-value">{_esc(fmt_price(s.official_price_jpy))}</div></div>
    <div class="price-cell"><div class="price-cell-label">国内中古</div>
      <div class="price-cell-value">{_esc(fmt_price(s.domestic_used_price_jpy)) if s.domestic_used_price_jpy else '<span class="no-data">未取得</span>'}</div></div>
    <div class="price-cell"><div class="price-cell-label">海外相場</div>
      <div class="price-cell-value">{_esc(fmt_price(getattr(s,"overseas_price_jpy",None))) if getattr(s,"overseas_price_jpy",None) else '<span class="no-data">未取得</span>'}</div></div>
    <div class="price-cell profit-cell"><div class="price-cell-label">価格差</div>
      <div class="price-cell-value" style="color:var(--orange)">{_esc(fmt_profit(s.premium_gap_jpy))}</div></div>
  </div>
  <div class="adv-meta-row">
    <span class="adv-meta-item">難易度: <strong>{difficulty:.1f}</strong>/1.0</span>
    <span class="adv-meta-item">販売方式: <strong>{_esc(method_label)}</strong></span>
  </div>
  <div class="buyback-notice">※ 難易度0.0〜1.0（高いほど入手が難しい）。価格差は参考値です。</div>
{overseas_html}
</div>""")

        # ----- フォールバック: 上級者向け監視候補 -----
        if watch_candidates:
            has_confirmed = bool(advanced_deals or advanced_snaps)
            if not has_confirmed:
                parts.append("""<div class="adv-fallback-notice">
<span class="adv-fallback-icon">ℹ️</span>
<div><strong>現在、上級者向けの確定候補は少ないため、価格差・希少性・海外相場差が大きい監視候補を表示しています。</strong><br>
<span>中古市場や海外相場のデータが入り次第、確定候補として昇格します。</span></div>
</div>""")
            parts.append('<div class="section-header"><h2>上級者向け監視候補</h2><span class="section-count">価格差・希少性スコア上位</span></div>')
            parts.append(self._watch_candidates_table(watch_candidates))

        if not advanced_deals and not advanced_snaps and not watch_candidates:
            parts.append('<div class="section-header"><h2>上級者向け候補</h2></div><p class="empty-msg">現在、条件を満たす候補はありません。</p>')

        return "\n".join(parts)

    def _watch_candidates_table(self, candidates: list) -> str:
        """監視候補カードを生成する（products テーブル由来）。海外相場リンク込み。"""
        _link_res = get_resolver()
        # カメラ優先、次にゲーム機
        camera = [c for c in candidates if c["genre"] == "camera"]
        others = [c for c in candidates if c["genre"] != "camera"]
        ordered = camera + others

        cards = []
        for c in ordered:
            price  = c["official_price"]
            bp     = c["buyback_price"]
            shop   = _esc(c["shop_name"] or "—")
            flags  = "・".join(c["flags"]) if c["flags"] else "監視中"
            genre  = c.get("genre", "")

            # 買取リンク解決
            db_url = c.get("buyback_url") or ""
            shop_id = c.get("shop_id") or ""
            resolved_url, link_type = _link_res.resolve_buyback_url(
                shop_id=shop_id, genre=genre, db_url=db_url, link_verified=bool(db_url)
            )
            link_type_lbl = _esc(_link_res.link_type_label(link_type))

            if resolved_url:
                buy_link = (f'<a href="{_esc(resolved_url)}" target="_blank" rel="noopener" '
                            f'data-track="buyback_click" data-shop="{shop}" '
                            f'title="{link_type_lbl}">買取価格を確認 →</a>'
                            f'<span class="link-type-badge">{link_type_lbl}</span>')
            else:
                buy_link = '<span class="unverified-link">公式買取ページで確認</span>'

            # 価格差
            gap_html = ""
            if bp and price:
                gap = bp - price
                gap_color = "var(--green)" if gap > 0 else "var(--text-muted)"
                gap_html = f'<span class="watch-gap" style="color:{gap_color}">買取 ¥{bp:,}（差 {gap:+,}円）</span>'

            # 海外相場リンク
            overseas_html = self._overseas_links_section(c["product_name"], genre)

            cards.append(f"""<div class="card watch-candidate-card">
  <div class="card-header">
    <div class="card-title">{_esc(c["product_name"])}</div>
    <span class="badge badge-watch">{_esc(flags)}</span>
  </div>
  <div class="watch-price-row">
    <span class="watch-price-item">公式価格: <strong>{_esc(fmt_price(price)) if price else "—"}</strong></span>
    {gap_html}
    <span class="watch-price-item">最新買取店: <strong>{shop}</strong></span>
  </div>
  <div class="watch-links-row">{buy_link}</div>
{overseas_html}
</div>""")

        footer = '<p class="watch-footer-note">※ 監視候補は価格差・希少性スコアが高い商品です。中古市場データ入手後に確定候補へ昇格します。</p>'
        return "\n".join(cards) + footer

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
            parts.append('<div class="section-header"><h2>本日の急騰</h2></div><p class="empty-msg">急騰は検出されていません（閾値: ¥5,000+）</p>')

        if drop:
            parts.append('<div class="section-header"><h2>本日の急落</h2></div>')
            for a in drop:
                parts.append(self._alert_card(a, "drop"))
        else:
            parts.append('<div class="section-header"><h2>本日の急落</h2></div><p class="empty-msg">急落は検出されていません（閾値: ¥5,000−）</p>')

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
            parts.append('<div class="section-header"><h2>実質利益ランキング</h2></div><p class="empty-msg">データなし</p>')

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
            parts.append(f"""<div class="ranking-card"><div class="data-table-wrap"><table>
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
                f"<td class='profit-td'>{_esc(fmt_profit(d.net_profit_jpy))}</td>"
                f"<td>{_esc(fmt_rate(d.net_profit_rate))}</td>"
                f"<td>{_esc(d.best_buyback_shop)}</td></tr>"
            )
        cat_th = "<th>カテゴリ</th>" if show_category else ""
        return f"""<div class="ranking-card"><div class="data-table-wrap"><table>
<thead><tr><th>#</th><th>商品</th>{cat_th}<th>定価</th><th>買取</th><th>実質利益</th><th>率</th><th>買取店</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div></div>"""

    # ----- 海外相場リンクセクション -----

    def _overseas_links_section(self, product_name: str, genre: str) -> str:
        """海外相場確認リンクのHTMLブロックを生成する。
        価格データがなくても常にリンクを表示する。
        """
        _link_res = get_resolver()
        links = _link_res.get_overseas_links(product_name, genre, max_links=6)
        if not links:
            return ""

        btns = []
        for lk in links:
            btns.append(
                f'<a href="{_esc(lk["url"])}" target="_blank" rel="noopener" '
                f'class="overseas-btn" data-track="overseas_click" '
                f'data-market="{_esc(lk["market_id"])}" '
                f'title="{_esc(lk["note"])}">'
                f'{_esc(lk["icon"])} {_esc(lk["label"])}</a>'
            )

        return f"""<div class="overseas-links-section">
  <div class="overseas-links-header">
    <span class="overseas-links-title">🌍 海外相場を確認する</span>
    <span class="overseas-links-note">価格未取得でもリンク先で相場確認できます</span>
  </div>
  <div class="overseas-btn-row">{"".join(btns)}</div>
</div>"""

    # ----- 新商品候補セクション -----

    def _section_new_products(self, candidates: list) -> str:
        """watchingステータスの新商品候補を表示するセクション。"""
        if not candidates:
            return ""

        _SALE_LABEL = {
            "lottery": "🎰 抽選",
            "limited": "⚡ 限定",
            "preorder": "📋 予約",
            "normal": "🛒 通常",
            "sold_out": "❌ 品切",
        }
        _CAT_LABEL = {
            "iphone": "iPhone",
            "game_console": "ゲーム機",
            "mac": "Mac",
            "ipad": "iPad",
            "apple_watch": "Apple Watch",
            "camera": "カメラ",
            "airpods": "AirPods",
        }

        cards = []
        for c in candidates:
            sale_label = _SALE_LABEL.get(getattr(c, "sale_method", ""), "")
            cat_label  = _CAT_LABEL.get(getattr(c, "category", ""), getattr(c, "category", ""))
            official_price_str = (
                f"公式予想価格: {fmt_price(c.official_price)}" if getattr(c, "official_price", None) else ""
            )
            release_str = (
                f"発売予定: {_esc(c.release_date)}" if getattr(c, "release_date", None) else "発売日未定"
            )
            resale_score = getattr(c, "resale_potential_score", 0.0) or 0.0
            resale_bar = int(min(resale_score * 10, 10))
            cards.append(f"""<div class="new-product-card">
  <div class="npc-header">
    <span class="npc-category">{_esc(cat_label)}</span>
    {f'<span class="npc-sale-method">{_esc(sale_label)}</span>' if sale_label else ""}
  </div>
  <div class="npc-name">{_esc(c.product_name)}</div>
  <div class="npc-meta">{_esc(release_str)}</div>
  {f'<div class="npc-price">{_esc(official_price_str)}</div>' if official_price_str else ""}
  <div class="npc-score">
    転売期待度: <span class="score-bar">{"█" * resale_bar}{"░" * (10 - resale_bar)}</span>
    <span class="score-val">{resale_score:.1f}</span>
  </div>
  {f'<div class="npc-reason">{_esc(c.reason)}</div>' if getattr(c, "reason", None) else ""}
</div>""")

        return f"""<section class="section-new-products" id="new-products">
<h2 class="section-title">🆕 注目の新商品・新モデル候補</h2>
<p class="section-desc">発売が噂・発表されている注目商品です。入手難易度・転売期待度を事前にチェックしてください。</p>
<div class="new-product-grid">
{"".join(cards)}
</div>
<p class="section-note">※ 情報は公式発表前の段階です。変更・中止の可能性があります。自動購入・自動応募は一切行いません。</p>
</section>"""

    # ----- Caution / CTA / Footer -----

    def _section_caution(self) -> str:
        return """<div class="caution">
<strong>⚠️ ご確認ください</strong>
<ul>
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
<h3>詳細レポートを読む</h3>
<p>仕入れ条件・複数買取店の比較・全案件一覧はnoteで公開しています。</p>
<div class="cta-buttons">
  <a href="{_esc(note_url)}" class="cta-btn cta-btn-primary" data-track="note_click">詳細レポートを見る →</a>
  <a href="{_esc(note_url)}" class="cta-btn cta-btn-secondary" data-track="note_click">今日の全案件を見る</a>
</div>
</div>""")
            else:
                parts.append("""<div class="cta-section">
<h3>詳細レポート — 準備中</h3>
<p>仕入れ条件・買取店比較・全案件一覧をnoteで公開予定です。公開時にこのページでお知らせします。</p>
</div>""")
        if self.settings.get("enable_line_cta"):
            line_url = (self.settings.get("line_url") or "").strip()
            if line_url and line_url != "#":
                parts.append(f'<div class="cta-section"><h3>LINE速報</h3><p>プレ値候補をLINEで受け取れます。</p><div class="cta-buttons"><a href="{_esc(line_url)}" class="cta-btn" style="background:#06c755;color:#fff;" data-track="line_click">LINE登録で速報を受け取る</a></div></div>')
        if self.settings.get("enable_telegram_cta"):
            tg_url = (self.settings.get("telegram_url") or "").strip()
            if tg_url and tg_url != "#":
                parts.append(f'<div class="cta-section"><h3>Telegram速報</h3><p>Telegramチャンネルで最新情報を受け取れます。</p><div class="cta-buttons"><a href="{_esc(tg_url)}" class="cta-btn cta-btn-primary" data-track="telegram_click">Telegramチャンネルに参加する</a></div></div>')
        return "\n".join(parts)

    def _section_footer(self) -> str:
        now = datetime.now()
        return f"""<div class="footer">
<p>価格情報は参考値です。購入前に必ず公式サイト・買取店でご確認ください。</p>
<p>© {now.year} プレ値速報 — 情報は自動取得・分析されたものです</p>
</div>"""

    # ===== Markdown版 =====

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
