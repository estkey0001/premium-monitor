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
        hero_html    = self._section_hero(date_str, time_str, latest_buyback_at, lp_generated_at)
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
   プレ値速報 v3 — Premium Ad-Ready UI
   ============================================================ */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
:root {{
  --bg:#060a12; --surface:#0d1220; --card:#111827; --card-2:#151e2e;
  --border:#1a2540; --border-2:#243050;
  --text:#f1f5f9; --text-2:#94a3b8; --text-3:#64748b;
  --accent:#4f8ef7; --accent-2:#3b7cf0; --accent-glow:rgba(79,142,247,0.15);
  --green:#10d98a; --green-2:#0ec47c; --green-dim:rgba(16,217,138,0.1); --green-glow:rgba(16,217,138,0.2);
  --yellow:#fbbf24; --yellow-dim:rgba(251,191,36,0.1);
  --orange:#f97316; --orange-dim:rgba(249,115,22,0.1);
  --red:#f43f5e; --red-dim:rgba(244,63,94,0.1);
  --iphone-color:#4f8ef7; --iphone-dim:rgba(79,142,247,0.12);
  --camera-color:#a78bfa; --camera-dim:rgba(167,139,250,0.12);
  --game-color:#2dd4bf; --game-dim:rgba(45,212,191,0.12);
  --font:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  --r-sm:8px; --r-md:12px; --r-lg:16px; --r-xl:24px;
  --shadow-card:0 1px 3px rgba(0,0,0,0.4),0 0 0 1px rgba(255,255,255,0.04);
  --shadow-glow:0 0 24px rgba(79,142,247,0.12);
}}
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}
html{{scroll-behavior:smooth;}}
body{{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6;font-size:15px;-webkit-font-smoothing:antialiased;}}
/* Topbar */
.topbar{{position:sticky;top:0;z-index:200;background:rgba(6,10,18,0.9);backdrop-filter:blur(20px);border-bottom:1px solid var(--border);padding:0 20px;height:52px;display:flex;align-items:center;justify-content:space-between;}}
.topbar-logo{{font-size:0.9rem;font-weight:800;color:var(--text);display:flex;align-items:center;gap:8px;}}
.live-dot{{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:livepulse 2s ease-in-out infinite;}}
@keyframes livepulse{{0%,100%{{opacity:1;box-shadow:0 0 6px var(--green);}}50%{{opacity:0.4;box-shadow:0 0 2px var(--green);}}}}
.topbar-badge{{font-size:0.65rem;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;background:var(--accent-glow);color:var(--accent);border:1px solid rgba(79,142,247,0.3);padding:2px 8px;border-radius:99px;}}
.topbar-right{{display:flex;align-items:center;gap:20px;font-size:0.72rem;color:var(--text-3);font-variant-numeric:tabular-nums;}}
/* Layout */
.container{{max-width:900px;margin:0 auto;padding:0 16px 64px;}}
/* Hero */
.hero{{position:relative;padding:64px 0 44px;text-align:center;overflow:hidden;}}
.hero-bg{{position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse 80% 60% at 50% -10%,rgba(79,142,247,0.12) 0%,transparent 60%),radial-gradient(ellipse 40% 30% at 80% 80%,rgba(167,139,250,0.06) 0%,transparent 50%);}}
.hero-eyebrow{{display:inline-flex;align-items:center;gap:6px;background:var(--accent-glow);border:1px solid rgba(79,142,247,0.3);color:var(--accent);font-size:0.68rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;padding:5px 14px;border-radius:99px;margin-bottom:24px;}}
.hero h1{{font-size:clamp(1.8rem,5vw,2.8rem);font-weight:900;letter-spacing:-0.03em;line-height:1.1;color:var(--text);margin-bottom:16px;}}
.hero h1 .highlight{{background:linear-gradient(135deg,var(--accent) 0%,#7c3aed 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}}
.hero-sub{{font-size:1rem;color:var(--text-2);max-width:520px;margin:0 auto 32px;line-height:1.7;}}
.hero-timestamps{{display:flex;flex-wrap:wrap;justify-content:center;gap:10px;}}
.ts-chip{{display:inline-flex;align-items:center;gap:6px;background:var(--surface);border:1px solid var(--border-2);color:var(--text-2);font-size:0.75rem;padding:6px 14px;border-radius:99px;font-variant-numeric:tabular-nums;}}
.ts-chip .ts-dot{{width:6px;height:6px;border-radius:50%;background:var(--green);flex-shrink:0;}}
.ts-chip.stale .ts-dot{{background:var(--orange);}}
/* Stale Warning */
.stale-warning-block{{display:flex;align-items:flex-start;gap:12px;background:rgba(249,115,22,0.07);border:1px solid rgba(249,115,22,0.25);border-left:3px solid var(--orange);padding:14px 18px;border-radius:0 var(--r-md) var(--r-md) 0;margin:16px 0;font-size:0.875rem;color:#fed7aa;line-height:1.6;}}
.warn-icon{{font-size:1.1rem;flex-shrink:0;margin-top:1px;}}
/* Genre Nav */
.genre-nav-wrap{{margin:36px 0 0;border-bottom:1px solid var(--border);}}
.genre-nav{{display:flex;gap:0;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;}}
.genre-nav::-webkit-scrollbar{{display:none;}}
.genre-btn{{flex-shrink:0;display:flex;align-items:center;gap:8px;background:transparent;border:none;border-bottom:2px solid transparent;padding:14px 20px;font-size:0.875rem;font-weight:500;color:var(--text-3);cursor:pointer;transition:color 0.15s,border-color 0.15s;margin-bottom:-1px;white-space:nowrap;}}
.genre-btn:hover{{color:var(--text-2);}}
.genre-btn.active{{color:var(--text);border-bottom-color:var(--accent);font-weight:700;}}
.genre-icon{{width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:0.85rem;}}
.genre-btn.active .genre-icon{{background:var(--accent-glow);}}
.genre-btn[data-genre="all"] .genre-icon{{background:rgba(255,255,255,0.06);}}
.genre-btn[data-genre="iphone"] .genre-icon{{background:var(--iphone-dim);}}
.genre-btn[data-genre="camera"] .genre-icon{{background:var(--camera-dim);}}
.genre-btn[data-genre="game_console"] .genre-icon{{background:var(--game-dim);}}
.genre-btn[data-genre="advanced"] .genre-icon{{background:var(--orange-dim);}}
.genre-btn[data-genre="surge"] .genre-icon{{background:var(--yellow-dim);}}
.genre-btn[data-genre="ranking"] .genre-icon{{background:var(--green-dim);}}
.genre-count{{font-size:0.65rem;font-weight:700;background:var(--border);color:var(--text-3);padding:1px 6px;border-radius:99px;}}
.genre-btn.active .genre-count{{background:var(--accent-glow);color:var(--accent);}}
.genre-panel{{display:none;padding:24px 0 0;}}
.genre-panel.active{{display:block;}}
/* Section Header */
.section-header{{display:flex;align-items:center;gap:10px;margin:28px 0 16px;padding-bottom:12px;border-bottom:1px solid var(--border);}}
.section-header h2{{font-size:0.78rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-3);}}
.section-count{{font-size:0.68rem;background:var(--border);color:var(--text-3);padding:2px 8px;border-radius:99px;}}
/* Deal Card */
.deal-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r-lg);margin:12px 0;overflow:hidden;box-shadow:var(--shadow-card);transition:border-color 0.2s,box-shadow 0.2s;position:relative;}}
.deal-card:hover{{border-color:var(--border-2);box-shadow:var(--shadow-card),var(--shadow-glow);}}
.deal-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--accent) 0%,transparent 100%);opacity:0;transition:opacity 0.2s;}}
.deal-card:hover::before{{opacity:1;}}
.deal-card.iphone::before{{background:linear-gradient(90deg,var(--iphone-color) 0%,transparent 100%);}}
.deal-card.camera::before{{background:linear-gradient(90deg,var(--camera-color) 0%,transparent 100%);}}
.deal-card.game_console::before{{background:linear-gradient(90deg,var(--game-color) 0%,transparent 100%);}}
.card-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:18px 20px 14px;border-bottom:1px solid var(--border);}}
.card-title{{font-size:1rem;font-weight:700;color:var(--text);line-height:1.3;flex:1;}}
.card-badges{{display:flex;gap:6px;flex-shrink:0;flex-wrap:wrap;justify-content:flex-end;}}
/* Profit Banner */
.profit-banner{{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;background:var(--green-dim);border-bottom:1px solid rgba(16,217,138,0.15);}}
.profit-main{{display:flex;align-items:baseline;gap:10px;}}
.profit-amount{{font-size:1.8rem;font-weight:900;color:var(--green);letter-spacing:-0.03em;line-height:1;text-shadow:0 0 20px var(--green-glow);}}
.profit-rate{{font-size:0.85rem;font-weight:700;color:var(--green-2);background:rgba(16,217,138,0.15);padding:3px 10px;border-radius:6px;}}
.profit-label{{font-size:0.72rem;color:var(--text-3);text-transform:uppercase;letter-spacing:0.05em;}}
/* Price Grid */
.price-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);border-bottom:1px solid var(--border);}}
.price-cell{{background:var(--card);padding:12px 16px;}}
.price-cell-label{{font-size:0.68rem;color:var(--text-3);font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin-bottom:4px;}}
.price-cell-value{{font-size:1rem;font-weight:700;color:var(--text);font-variant-numeric:tabular-nums;}}
/* Card Body */
.card-body{{padding:14px 20px;}}
.condition-row{{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--surface);border-radius:var(--r-sm);margin-bottom:12px;font-size:0.8rem;color:var(--text-2);}}
.condition-row .cond-icon{{color:var(--yellow);font-size:0.85rem;}}
.updated-ts{{display:flex;align-items:center;gap:5px;font-size:0.72rem;color:var(--text-3);margin-bottom:12px;}}
/* Buyback Compare */
.buyback-compare{{border:1px solid var(--border);border-radius:var(--r-md);overflow:hidden;margin-bottom:12px;}}
.compare-header{{display:flex;align-items:center;justify-content:space-between;padding:8px 14px;background:var(--surface);border-bottom:1px solid var(--border);font-size:0.7rem;font-weight:700;letter-spacing:0.05em;text-transform:uppercase;color:var(--text-3);}}
.shop-row{{display:flex;align-items:center;padding:9px 14px;border-bottom:1px solid var(--border);font-size:0.875rem;transition:background 0.1s;}}
.shop-row:last-child{{border:none;}}
.shop-row:hover{{background:var(--surface);}}
.shop-rank{{min-width:22px;font-size:0.75rem;font-weight:800;color:var(--text-3);}}
.shop-rank.r1{{color:var(--yellow);}}
.shop-rank.r2{{color:var(--text-2);}}
.shop-name{{flex:1;padding:0 10px;color:var(--text-2);}}
.shop-name a{{color:var(--accent);text-decoration:none;}}
.shop-name a:hover{{text-decoration:underline;}}
.shop-price{{font-weight:700;color:var(--text);font-variant-numeric:tabular-nums;min-width:80px;text-align:right;}}
.shop-profit{{font-size:0.75rem;font-weight:700;color:var(--green);min-width:68px;text-align:right;}}
.shop-profit.neg{{color:var(--red);}}
/* Card Links */
.card-links{{display:flex;flex-wrap:wrap;gap:8px;}}
.card-link{{display:inline-flex;align-items:center;gap:5px;color:var(--accent);text-decoration:none;font-size:0.8rem;font-weight:600;padding:7px 14px;border:1px solid rgba(79,142,247,0.3);border-radius:var(--r-sm);background:var(--accent-glow);transition:all 0.15s;}}
.card-link:hover{{background:rgba(79,142,247,0.2);border-color:rgba(79,142,247,0.5);}}
/* Badges */
.badge{{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:99px;font-size:0.68rem;font-weight:700;letter-spacing:0.04em;white-space:nowrap;}}
.badge-easy{{background:var(--green-dim);color:var(--green);border:1px solid rgba(16,217,138,0.25);}}
.badge-watch{{background:var(--yellow-dim);color:var(--yellow);border:1px solid rgba(251,191,36,0.25);}}
.badge-adv{{background:var(--orange-dim);color:var(--orange);border:1px solid rgba(249,115,22,0.25);}}
.badge-exp{{background:var(--red-dim);color:var(--red);border:1px solid rgba(244,63,94,0.25);}}
.badge-surge{{background:var(--green-dim);color:var(--green);border:1px solid rgba(16,217,138,0.25);}}
.badge-drop{{background:var(--red-dim);color:var(--red);border:1px solid rgba(244,63,94,0.25);}}
.badge-iphone{{background:var(--iphone-dim);color:var(--iphone-color);border:1px solid rgba(79,142,247,0.25);}}
.badge-camera{{background:var(--camera-dim);color:var(--camera-color);border:1px solid rgba(167,139,250,0.25);}}
.badge-game{{background:var(--game-dim);color:var(--game-color);border:1px solid rgba(45,212,191,0.25);}}
/* Freshness */
.freshness-live{{color:var(--green);font-size:0.7rem;font-weight:600;}}
.freshness-recent{{color:var(--yellow);font-size:0.7rem;font-weight:600;}}
.freshness-stale{{color:var(--red);font-size:0.7rem;font-weight:600;}}
.freshness-unknown{{color:var(--text-3);font-size:0.7rem;}}
/* Watch Card */
.watch-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r-lg);padding:16px 20px;margin:10px 0;box-shadow:var(--shadow-card);}}
/* Table */
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:var(--r-md);border:1px solid var(--border);}}
table{{width:100%;border-collapse:collapse;font-size:0.85rem;}}
thead tr{{background:var(--surface);border-bottom:1px solid var(--border);}}
th{{padding:10px 12px;text-align:left;color:var(--text-3);font-weight:700;font-size:0.68rem;letter-spacing:0.06em;text-transform:uppercase;white-space:nowrap;}}
td{{padding:10px 12px;border-bottom:1px solid var(--border);color:var(--text-2);word-break:break-word;}}
tbody tr:last-child td{{border:none;}}
tbody tr:hover td{{background:var(--surface);}}
.td-profit{{color:var(--green);font-weight:700;font-variant-numeric:tabular-nums;}}
.td-rank{{color:var(--text-3);font-weight:800;font-size:0.85rem;}}
.td-rank.top{{color:var(--yellow);}}
/* Alert Card */
.alert-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r-lg);padding:18px 20px;margin:10px 0;box-shadow:var(--shadow-card);}}
.alert-card.surge{{border-left:3px solid var(--green);}}
.alert-card.drop{{border-left:3px solid var(--red);}}
/* Ranking Card */
.ranking-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden;margin:10px 0;box-shadow:var(--shadow-card);}}
/* Empty State */
.empty-state{{text-align:center;padding:48px 24px;color:var(--text-3);font-size:0.9rem;}}
.empty-icon{{font-size:2rem;margin-bottom:12px;opacity:0.4;display:block;}}
/* Caution */
.caution{{background:rgba(251,191,36,0.05);border:1px solid rgba(251,191,36,0.18);border-left:3px solid var(--yellow);padding:18px 22px;margin:36px 0;border-radius:0 var(--r-md) var(--r-md) 0;font-size:0.875rem;color:var(--text-2);line-height:1.8;}}
.caution strong{{color:var(--yellow);display:block;margin-bottom:10px;font-size:0.9rem;}}
.caution ul{{list-style:none;padding:0;}}
.caution ul li{{padding:2px 0;}}
.caution ul li::before{{content:"·  ";color:var(--text-3);}}
/* CTA */
.cta-section{{margin:48px 0;padding:40px 32px;background:linear-gradient(135deg,rgba(79,142,247,0.08) 0%,rgba(124,58,237,0.06) 50%,rgba(16,217,138,0.04) 100%);border:1px solid var(--border-2);border-radius:var(--r-xl);text-align:center;position:relative;overflow:hidden;}}
.cta-section h3{{font-size:1.25rem;font-weight:800;color:var(--text);margin-bottom:10px;letter-spacing:-0.02em;}}
.cta-section p{{font-size:0.9rem;color:var(--text-2);margin-bottom:24px;max-width:440px;margin-left:auto;margin-right:auto;line-height:1.7;}}
.cta-buttons{{display:flex;flex-wrap:wrap;justify-content:center;gap:12px;}}
.cta-btn{{display:inline-flex;align-items:center;gap:6px;padding:13px 28px;border-radius:var(--r-md);text-decoration:none;font-weight:700;font-size:0.9rem;transition:all 0.2s;}}
.cta-btn-primary{{background:linear-gradient(135deg,var(--accent) 0%,#6366f1 100%);color:#fff;border:1px solid transparent;box-shadow:0 4px 16px rgba(79,142,247,0.3);}}
.cta-btn-primary:hover{{transform:translateY(-1px);box-shadow:0 6px 20px rgba(79,142,247,0.4);}}
.cta-btn-secondary{{background:var(--card);color:var(--text-2);border:1px solid var(--border-2);}}
.cta-btn-secondary:hover{{background:var(--card-2);color:var(--text);}}
/* Footer */
.footer{{text-align:center;color:var(--text-3);font-size:0.75rem;padding:40px 0 24px;line-height:2.2;border-top:1px solid var(--border);margin-top:48px;}}
/* Responsive */
@media(max-width:640px){{
  .hero{{padding:48px 0 32px;}}
  .hero h1{{font-size:1.7rem;}}
  .profit-amount{{font-size:1.5rem;}}
  .genre-btn{{padding:12px 14px;font-size:0.8rem;}}
  .card-head{{padding:14px 16px 12px;}}
  .card-body{{padding:12px 16px;}}
  .profit-banner{{padding:12px 16px;}}
  .price-cell{{padding:10px 12px;}}
  .cta-section{{padding:28px 20px;}}
  .topbar-right{{display:none;}}
  table{{font-size:0.78rem;}}
  th,td{{padding:8px 8px;}}
  .shop-profit{{display:none;}}
}}
@media(max-width:400px){{
  .price-grid{{grid-template-columns:1fr;}}
  .cta-buttons{{flex-direction:column;align-items:center;}}
  .cta-btn{{width:100%;justify-content:center;}}
}}
/* noscript */
.noscript-all .genre-panel{{display:block!important;}}
.noscript-all .genre-btn{{display:none;}}
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
{caution_html}
{cta_html}
{footer_html}
</div>
<script>
(function(){{
  var gbtns=document.querySelectorAll(".genre-btn");
  var gpanels=document.querySelectorAll(".genre-panel");
  if(gbtns.length){{
    gbtns.forEach(function(btn){{
      btn.addEventListener("click",function(){{
        gbtns.forEach(function(b){{b.classList.remove("active");b.setAttribute("aria-selected","false");}});
        gpanels.forEach(function(p){{p.classList.remove("active");}});
        btn.classList.add("active");
        btn.setAttribute("aria-selected","true");
        var panel=document.getElementById("genre-"+btn.dataset.genre);
        if(panel)panel.classList.add("active");
      }});
    }});
  }}
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
<noscript><style>.genre-nav{{display:none;}}.genre-panel{{display:block!important;}}</style></noscript>
</body>
</html>"""

    # ----- Hero -----

    def _section_hero(self, date_str, time_str, latest_buyback_at, lp_generated_at) -> str:
        variant_key = self.settings.get('headline_variant', 'A')
        variants    = self.settings.get('variants', {})
        variant     = variants.get(variant_key, {})
        headline    = _esc(variant.get('headline', self.settings.get('site_title', 'プレ値速報')))
        buyback_str = _jst_str(latest_buyback_at)
        lp_str      = _jst_str(lp_generated_at)
        stale_cls   = 'stale' if _hours_ago(latest_buyback_at) > 24 else ''
        return f"""<div class="hero">
  <div class="hero-bg"></div>
  <div class="hero-eyebrow"><span>&#9679;</span> 毎日更新 &mdash; プレ値監視情報</div>
  <h1><span class="highlight">公式価格</span>と買取価格の差額を、毎日チェック。</h1>
  <p class="hero-sub">iPhone・カメラ・ゲーム機の公式価格と買取価格の差額を毎日監視。ジャンル別に整理しています。</p>
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
                      camera_deals=None, iphone_watch=None, camera_watch=None,
                      game_watch=None, buyback_by_product: dict = None) -> str:
        camera_deals  = camera_deals  or []
        iphone_watch  = iphone_watch  or []
        camera_watch  = camera_watch  or []
        game_watch    = game_watch    or []
        bybp = buyback_by_product or {}
        # ---- タブコンテンツ生成 ----
        all_html      = self._tab_all(beginner_easy, beginner_watch, bybp)
        iphone_html   = self._tab_genre(iphone_deals, iphone_watch, 'iphone', 'iPhone', bybp)
        camera_html   = self._tab_genre(camera_deals, camera_watch, 'camera', 'カメラ', bybp)
        game_html     = self._tab_genre(game_deals, game_watch, 'game_console', 'ゲーム機', bybp)
        advanced_html = self._tab_advanced(advanced_deals, advanced_snaps, watch_candidates)
        surge_html    = self._tab_surge(buyback_alerts)
        ranking_html  = self._tab_ranking(all_deals, iphone_deals, game_deals)
        # ---- カウント ----
        all_count    = len(beginner_easy) + len(beginner_watch)
        iphone_count = len(iphone_deals)
        camera_count = len(camera_deals)
        game_count   = len(game_deals)
        adv_total    = len(advanced_deals) + len(advanced_snaps) + len(watch_candidates)
        surge_count  = len([a for a in buyback_alerts if a.get('alert_type') in ('buyback_surge','buyback_drop')])
        surge_badge  = f'<span class="genre-count">{surge_count}</span>' if surge_count else ''
        return f"""<div class="genre-nav-wrap">
<nav class="genre-nav" role="tablist">
  <button class="genre-btn active" data-genre="all" role="tab" aria-selected="true" aria-controls="genre-all">
    <span class="genre-icon">&#128202;</span>全案件<span class="genre-count">{all_count}</span>
  </button>
  <button class="genre-btn" data-genre="iphone" role="tab" aria-selected="false" aria-controls="genre-iphone">
    <span class="genre-icon">&#128241;</span>iPhone<span class="genre-count">{iphone_count}</span>
  </button>
  <button class="genre-btn" data-genre="camera" role="tab" aria-selected="false" aria-controls="genre-camera">
    <span class="genre-icon">&#128247;</span>カメラ<span class="genre-count">{camera_count}</span>
  </button>
  <button class="genre-btn" data-genre="game_console" role="tab" aria-selected="false" aria-controls="genre-game_console">
    <span class="genre-icon">&#127918;</span>ゲーム機<span class="genre-count">{game_count}</span>
  </button>
  <button class="genre-btn" data-genre="advanced" role="tab" aria-selected="false" aria-controls="genre-advanced">
    <span class="genre-icon">&#128269;</span>上級者向け<span class="genre-count">{adv_total}</span>
  </button>
  <button class="genre-btn" data-genre="surge" role="tab" aria-selected="false" aria-controls="genre-surge">
    <span class="genre-icon">&#9889;</span>急騰/急落{surge_badge}
  </button>
  <button class="genre-btn" data-genre="ranking" role="tab" aria-selected="false" aria-controls="genre-ranking">
    <span class="genre-icon">&#127942;</span>ランキング
  </button>
</nav>
</div>
<div id="tab-beginner" style="display:none" aria-hidden="true"></div>
<div id="tab-advanced" style="display:none" aria-hidden="true"></div>
<div id="genre-all" class="genre-panel active" role="tabpanel">
{all_html}
</div>
<div id="genre-iphone" class="genre-panel" role="tabpanel">
{iphone_html}
</div>
<div id="genre-camera" class="genre-panel" role="tabpanel">
{camera_html}
</div>
<div id="genre-game_console" class="genre-panel" role="tabpanel">
{game_html}
</div>
<div id="genre-advanced" class="genre-panel" role="tabpanel">
{advanced_html}
</div>
<div id="genre-surge" class="genre-panel" role="tabpanel">
{surge_html}
</div>
<div id="genre-ranking" class="genre-panel" role="tabpanel">
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

    def _tab_all(self, easy_deals, watch_deals, buyback_by_product: dict = None) -> str:
        """全案件タブ（初級者向け・要確認）"""
        bybp = buyback_by_product or {}
        parts = []
        if easy_deals:
            parts.append('<div class="section-header"><h2>低難度 &mdash; すぐ動ける案件</h2>'
                         + f'<span class="section-count">{len(easy_deals)}件</span></div>')
            for d in easy_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, 'badge-easy', '低難度', buyback_rows=rows))
        else:
            parts.append('<div class="section-header"><h2>低難度 &mdash; すぐ動ける案件</h2></div>'
                         + '<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす案件はありません。</div>')
        if watch_deals:
            parts.append('<div class="section-header"><h2>要確認 &mdash; 様子見案件</h2>'
                         + f'<span class="section-count">{len(watch_deals)}件</span></div>')
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
        """案件カード HTML を生成する（v3 プレミアムUI）。"""
        pid  = _esc(d.product_id)
        shop = _esc(d.best_buyback_shop or '—')
        links = ''
        if hasattr(d, 'official_url') and d.official_url:
            links += (f'<a href="{_esc(d.official_url)}" target="_blank" rel="noopener" '
                      f'class="card-link" data-track="product_click" data-product-id="{pid}">公式購入ページ &rarr;</a>')
        elif hasattr(d, 'best_official_url') and d.best_official_url:
            links += (f'<a href="{_esc(d.best_official_url)}" target="_blank" rel="noopener" '
                      f'class="card-link" data-track="product_click" data-product-id="{pid}">公式購入ページ &rarr;</a>')
        verified_buyback_url = ''
        if hasattr(d, 'best_buyback_url') and d.best_buyback_url:
            _skip = ('mobileno1.com', 'kaitori-1chome.com')
            if not any(dom in d.best_buyback_url for dom in _skip):
                verified_buyback_url = d.best_buyback_url
        if verified_buyback_url:
            links += (f'<a href="{_esc(verified_buyback_url)}" target="_blank" rel="noopener" '
                      f'class="card-link" data-track="product_click" data-product-id="{pid}" data-shop="{shop}">買取ページ &rarr;</a>')
        updated_str = ''
        if hasattr(d, 'scanned_at') and d.scanned_at:
            updated_str = f'<div class="updated-ts">&#128336; 最終更新：{_esc(_jst_str(d.scanned_at))}</div>'
        compare_html = ''
        if buyback_rows:
            official_price = d.official_price_jpy or 0
            rows_html = []
            for i, r in enumerate(buyback_rows[:5], start=1):
                bp = r.get('buyback_price', 0)
                sname = _esc(r.get('shop_name', ''))
                profit = bp - official_price
                profit_str = f'+¥{profit:,}' if profit >= 0 else f'-¥{abs(profit):,}'
                url_val = r.get('buyback_url', '')
                verified = r.get('link_verified', False)
                if url_val and verified:
                    shop_display = (f'<a href="{_esc(url_val)}" target="_blank" rel="noopener" '
                                    f'data-track="buyback_click" data-product-id="{pid}" '
                                    f'data-shop="{sname}">{sname}</a>')
                else:
                    shop_display = sname
                rank_cls = 'r1' if i == 1 else ('r2' if i == 2 else '')
                profit_cls = ' neg' if profit < 0 else ''
                rows_html.append(
                    f'<div class="shop-row">'
                    f'<span class="shop-rank {rank_cls}">{i}</span>'
                    f'<span class="shop-name">{shop_display}</span>'
                    f'<span class="shop-price">¥{bp:,}</span>'
                    f'<span class="shop-profit{profit_cls}">{_esc(profit_str)}</span>'
                    f'</div>'
                )
            first_freshness = self._freshness_label(
                buyback_rows[0].get('observed_at', ''), buyback_rows[0].get('data_source', 'manual_today')
            )
            compare_html = (
                f'<div class="buyback-compare">'
                f'<div class="compare-header"><span>買取店比較（最大5店舗）</span>{first_freshness}</div>'
                + ''.join(rows_html)
                + '</div>'
            )
        genre_cls = genre or (d.category if hasattr(d, 'category') else '')
        profit_rate_str = _esc(fmt_rate(d.net_profit_rate))
        return f"""<div class="deal-card {_esc(genre_cls)}" data-user-level="{_esc(d.user_level)}">
  <div class="card-head">
    <div class="card-title">{_esc(d.product_name)}</div>
    <div class="card-badges"><span class="badge {badge_cls}">{label}</span></div>
  </div>
  <div class="profit-banner">
    <div>
      <div class="profit-label">実質利益（推定コスト差引後）</div>
      <div class="profit-main">
        <span class="profit-amount">{_esc(fmt_profit(d.net_profit_jpy))}</span>
        <span class="profit-rate">{profit_rate_str}</span>
      </div>
    </div>
  </div>
  <div class="price-grid">
    <div class="price-cell">
      <div class="price-cell-label">公式価格</div>
      <div class="price-cell-value">{_esc(fmt_price(d.official_price_jpy))}</div>
    </div>
    <div class="price-cell">
      <div class="price-cell-label">最高買取価格</div>
      <div class="price-cell-value">{_esc(fmt_price(d.best_buyback_price))}</div>
    </div>
  </div>
  <div class="card-body">
    <div class="condition-row">
      <span class="cond-icon">&#9888;</span>
      <span>買取条件：{_esc(d.buyback_condition or '新品未開封')}　推定コスト：-{_esc(fmt_price(d.estimated_costs_jpy))}</span>
    </div>
    {updated_str}
    {compare_html}
    <div class="card-links">{links}</div>
  </div>
</div>"""


    def _tab_advanced(self, advanced_deals, advanced_snaps, watch_candidates) -> str:
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
