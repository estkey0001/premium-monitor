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
/* ================================================================
   PREMIUM MONITOR v4 ULTRA — by Manus Design
   Inspired by: Vercel, Linear, Stripe, Raycast
   ================================================================ */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Space+Grotesk:wght@400;500;600;700&display=swap');
:root {{
  --bg-base:#02040a; --bg-elevated:#080c14; --bg-card:#0c1220; --bg-card-hover:#101828;
  --border-subtle:rgba(255,255,255,0.06); --border-default:rgba(255,255,255,0.10); --border-strong:rgba(255,255,255,0.18);
  --text-primary:#f8fafc; --text-secondary:#94a3b8; --text-tertiary:#475569;
  --brand:#6366f1; --brand-bright:#818cf8; --brand-glow:rgba(99,102,241,0.25); --brand-subtle:rgba(99,102,241,0.08);
  --profit:#00e5a0; --profit-glow:rgba(0,229,160,0.3); --profit-subtle:rgba(0,229,160,0.08); --profit-mid:rgba(0,229,160,0.15);
  --warn:#f59e0b; --warn-subtle:rgba(245,158,11,0.08);
  --danger:#f43f5e; --danger-subtle:rgba(244,63,94,0.08);
  --iphone:#007aff; --iphone-glow:rgba(0,122,255,0.25); --iphone-subtle:rgba(0,122,255,0.08);
  --camera:#bf5af2; --camera-glow:rgba(191,90,242,0.25); --camera-subtle:rgba(191,90,242,0.08);
  --game:#30d158; --game-glow:rgba(48,209,88,0.25); --game-subtle:rgba(48,209,88,0.08);
  --font-display:'Space Grotesk','Inter',sans-serif;
  --font-body:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  --radius-sm:8px; --radius-md:14px; --radius-lg:20px; --radius-xl:28px; --radius-full:9999px;
  --shadow-sm:0 1px 2px rgba(0,0,0,0.5);
  --shadow-md:0 4px 16px rgba(0,0,0,0.4),0 1px 3px rgba(0,0,0,0.3);
  --shadow-lg:0 8px 32px rgba(0,0,0,0.5),0 2px 8px rgba(0,0,0,0.3);
}}
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;-webkit-font-smoothing:antialiased;}}
html{{scroll-behavior:smooth;}}
body{{font-family:var(--font-body);background:var(--bg-base);color:var(--text-primary);line-height:1.6;font-size:15px;overflow-x:hidden;}}
/* Topbar */
.topbar{{position:sticky;top:0;z-index:100;background:rgba(2,4,10,0.85);backdrop-filter:blur(24px) saturate(180%);-webkit-backdrop-filter:blur(24px) saturate(180%);border-bottom:1px solid var(--border-subtle);height:56px;display:flex;align-items:center;padding:0 24px;gap:16px;}}
.topbar-brand{{font-family:var(--font-display);font-size:0.95rem;font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:10px;text-decoration:none;}}
.logo-mark{{width:28px;height:28px;background:linear-gradient(135deg,var(--brand) 0%,var(--profit) 100%);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:0.75rem;font-weight:900;color:#fff;box-shadow:0 0 16px var(--brand-glow);flex-shrink:0;}}
.topbar-live{{display:flex;align-items:center;gap:6px;font-size:0.72rem;font-weight:600;color:var(--profit);background:var(--profit-subtle);border:1px solid rgba(0,229,160,0.2);padding:3px 10px;border-radius:var(--radius-full);}}
.topbar-live .pulse{{width:6px;height:6px;border-radius:50%;background:var(--profit);box-shadow:0 0 8px var(--profit);animation:pulse-anim 2s ease-in-out infinite;}}
@keyframes pulse-anim{{0%,100%{{opacity:1;box-shadow:0 0 8px var(--profit);}}50%{{opacity:0.5;box-shadow:0 0 4px var(--profit);}}}}
.topbar-spacer{{flex:1;}}
.topbar-meta{{display:flex;align-items:center;gap:20px;font-size:0.72rem;color:var(--text-tertiary);font-variant-numeric:tabular-nums;}}
/* Layout */
.container{{max-width:960px;margin:0 auto;padding:0 20px 80px;position:relative;z-index:1;}}
/* Hero */
.hero{{position:relative;padding:80px 0 60px;text-align:center;overflow:hidden;}}
.hero-glow-1{{position:absolute;width:600px;height:400px;top:-100px;left:50%;transform:translateX(-50%);background:radial-gradient(ellipse,rgba(99,102,241,0.12) 0%,transparent 70%);pointer-events:none;}}
.hero-glow-2{{position:absolute;width:400px;height:300px;bottom:0;left:10%;background:radial-gradient(ellipse,rgba(0,229,160,0.07) 0%,transparent 70%);pointer-events:none;}}
.hero-glow-3{{position:absolute;width:400px;height:300px;bottom:0;right:10%;background:radial-gradient(ellipse,rgba(191,90,242,0.06) 0%,transparent 70%);pointer-events:none;}}
.hero-tag{{display:inline-flex;align-items:center;gap:8px;background:var(--brand-subtle);border:1px solid rgba(99,102,241,0.25);color:var(--brand-bright);font-size:0.72rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;padding:6px 16px;border-radius:var(--radius-full);margin-bottom:28px;position:relative;}}
.hero-title{{font-family:var(--font-display);font-size:clamp(2.2rem,6vw,3.8rem);font-weight:800;letter-spacing:-0.04em;line-height:1.05;color:var(--text-primary);margin-bottom:20px;position:relative;animation:fadeInUp 0.6s ease both;}}
.hero-title .grad{{background:linear-gradient(135deg,#fff 0%,var(--brand-bright) 40%,var(--profit) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;}}
.hero-subtitle{{font-size:1.05rem;color:var(--text-secondary);max-width:560px;margin:0 auto 40px;line-height:1.75;position:relative;animation:fadeInUp 0.6s 0.1s ease both;}}
.hero-stats{{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;margin-bottom:36px;position:relative;animation:fadeInUp 0.6s 0.2s ease both;}}
.hero-stat-card{{background:var(--bg-card);border:1px solid var(--border-default);border-radius:var(--radius-md);padding:14px 20px;text-align:center;min-width:120px;position:relative;overflow:hidden;transition:border-color 0.2s,transform 0.2s;}}
.hero-stat-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,0.1),transparent);}}
.hero-stat-card:hover{{border-color:var(--border-strong);transform:translateY(-2px);}}
.hero-stat-num{{font-family:var(--font-display);font-size:1.6rem;font-weight:800;color:var(--profit);line-height:1;margin-bottom:4px;font-variant-numeric:tabular-nums;}}
.hero-stat-label{{font-size:0.68rem;color:var(--text-tertiary);font-weight:600;letter-spacing:0.05em;text-transform:uppercase;}}
.hero-timestamps{{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;position:relative;animation:fadeInUp 0.6s 0.3s ease both;}}
.ts-pill{{display:inline-flex;align-items:center;gap:7px;background:var(--bg-card);border:1px solid var(--border-subtle);color:var(--text-secondary);font-size:0.78rem;padding:7px 16px;border-radius:var(--radius-full);font-variant-numeric:tabular-nums;transition:border-color 0.2s;}}
.ts-pill:hover{{border-color:var(--border-default);}}
.ts-dot{{width:7px;height:7px;border-radius:50%;background:var(--profit);box-shadow:0 0 6px var(--profit);flex-shrink:0;}}
.ts-dot.blue{{background:var(--brand);box-shadow:0 0 6px var(--brand);}}
/* Stale Warning */
.stale-warning-block{{display:flex;align-items:flex-start;gap:12px;background:linear-gradient(135deg,rgba(245,158,11,0.08),rgba(245,158,11,0.04));border:1px solid rgba(245,158,11,0.2);border-left:3px solid var(--warn);border-radius:0 var(--radius-md) var(--radius-md) 0;padding:14px 20px;margin:20px 0;font-size:0.875rem;color:#fcd34d;line-height:1.6;}}
.warn-icon{{font-size:1.1rem;flex-shrink:0;margin-top:1px;}}
/* Genre Navigation */
.genre-section{{margin:48px 0 0;}}
.genre-label{{font-size:0.68rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--text-tertiary);margin-bottom:14px;}}
.genre-pills{{display:flex;gap:8px;flex-wrap:wrap;padding-bottom:24px;border-bottom:1px solid var(--border-subtle);}}
.genre-pill{{display:inline-flex;align-items:center;gap:8px;background:var(--bg-card);border:1px solid var(--border-default);border-radius:var(--radius-full);padding:9px 18px;font-size:0.875rem;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all 0.2s cubic-bezier(0.4,0,0.2,1);position:relative;overflow:hidden;white-space:nowrap;}}
.genre-pill:hover{{border-color:var(--border-strong);color:var(--text-primary);transform:translateY(-1px);box-shadow:var(--shadow-md);}}
.genre-pill.active{{color:var(--text-primary);font-weight:700;transform:translateY(-1px);box-shadow:var(--shadow-md);}}
.genre-pill.active.all{{background:linear-gradient(135deg,var(--brand-subtle),rgba(0,229,160,0.05));border-color:rgba(99,102,241,0.4);box-shadow:0 0 20px var(--brand-glow);}}
.genre-pill.active.iphone{{background:var(--iphone-subtle);border-color:rgba(0,122,255,0.4);box-shadow:0 0 20px var(--iphone-glow);color:#60a5fa;}}
.genre-pill.active.camera{{background:var(--camera-subtle);border-color:rgba(191,90,242,0.4);box-shadow:0 0 20px var(--camera-glow);color:#c084fc;}}
.genre-pill.active.game{{background:var(--game-subtle);border-color:rgba(48,209,88,0.4);box-shadow:0 0 20px var(--game-glow);color:#4ade80;}}
.genre-pill.active.advanced{{background:rgba(245,158,11,0.08);border-color:rgba(245,158,11,0.4);box-shadow:0 0 20px rgba(245,158,11,0.2);color:#fbbf24;}}
.genre-pill.active.surge{{background:rgba(244,63,94,0.08);border-color:rgba(244,63,94,0.4);box-shadow:0 0 20px rgba(244,63,94,0.2);color:#fb7185;}}
.genre-pill.active.ranking{{background:rgba(0,229,160,0.08);border-color:rgba(0,229,160,0.4);box-shadow:0 0 20px var(--profit-glow);color:var(--profit);}}
.genre-icon{{font-size:1rem;line-height:1;}}
.genre-count{{font-size:0.68rem;font-weight:800;background:rgba(255,255,255,0.08);padding:2px 7px;border-radius:var(--radius-full);color:var(--text-tertiary);min-width:20px;text-align:center;}}
.genre-pill.active .genre-count{{background:rgba(255,255,255,0.15);color:inherit;}}
.genre-panel{{display:none;padding-top:32px;}}
.genre-panel.active{{display:block;}}
/* Section Header */
.section-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid var(--border-subtle);}}
.section-title{{font-family:var(--font-display);font-size:0.8rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-tertiary);display:flex;align-items:center;gap:8px;}}
.section-title::before{{content:'';width:3px;height:14px;border-radius:2px;background:var(--brand);}}
.section-badge{{font-size:0.68rem;font-weight:700;background:var(--bg-card);border:1px solid var(--border-default);color:var(--text-tertiary);padding:3px 10px;border-radius:var(--radius-full);}}
/* Deal Cards */
.cards-grid{{display:grid;gap:16px;}}
.deal-card{{background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);overflow:hidden;box-shadow:var(--shadow-md);transition:all 0.25s cubic-bezier(0.4,0,0.2,1);position:relative;}}
.deal-card::after{{content:'';position:absolute;inset:0;border-radius:inherit;background:linear-gradient(135deg,rgba(255,255,255,0.02) 0%,transparent 50%);pointer-events:none;}}
.deal-card:hover{{border-color:var(--border-default);box-shadow:var(--shadow-lg),0 0 40px rgba(0,229,160,0.1);transform:translateY(-3px);}}
.deal-card.iphone-card:hover{{box-shadow:var(--shadow-lg),0 0 40px var(--iphone-glow);}}
.deal-card.camera-card:hover{{box-shadow:var(--shadow-lg),0 0 40px var(--camera-glow);}}
.deal-card.game-card:hover{{box-shadow:var(--shadow-lg),0 0 40px var(--game-glow);}}
.card-accent{{height:2px;background:linear-gradient(90deg,var(--profit),transparent);}}
.deal-card.iphone-card .card-accent{{background:linear-gradient(90deg,var(--iphone),transparent);}}
.deal-card.camera-card .card-accent{{background:linear-gradient(90deg,var(--camera),transparent);}}
.deal-card.game-card .card-accent{{background:linear-gradient(90deg,var(--game),transparent);}}
.card-header{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:20px 22px 16px;}}
.card-name{{font-family:var(--font-display);font-size:1.05rem;font-weight:700;color:var(--text-primary);line-height:1.3;flex:1;}}
.card-tags{{display:flex;gap:6px;flex-shrink:0;flex-wrap:wrap;justify-content:flex-end;}}
.tag{{display:inline-flex;align-items:center;gap:4px;font-size:0.65rem;font-weight:800;letter-spacing:0.05em;text-transform:uppercase;padding:4px 10px;border-radius:var(--radius-full);}}
.tag-easy{{background:var(--profit-subtle);color:var(--profit);border:1px solid rgba(0,229,160,0.2);}}
.tag-watch{{background:var(--warn-subtle);color:var(--warn);border:1px solid rgba(245,158,11,0.2);}}
.tag-iphone{{background:var(--iphone-subtle);color:var(--iphone);border:1px solid rgba(0,122,255,0.2);}}
.tag-camera{{background:var(--camera-subtle);color:var(--camera);border:1px solid rgba(191,90,242,0.2);}}
.tag-game{{background:var(--game-subtle);color:var(--game);border:1px solid rgba(48,209,88,0.2);}}
.tag-adv{{background:rgba(245,158,11,0.08);color:var(--warn);border:1px solid rgba(245,158,11,0.2);}}
.tag-exp{{background:var(--danger-subtle);color:var(--danger);border:1px solid rgba(244,63,94,0.2);}}
/* Profit Showcase */
.profit-showcase{{margin:0 22px 0;padding:20px 22px;background:linear-gradient(135deg,rgba(0,229,160,0.08) 0%,rgba(0,229,160,0.04) 50%,rgba(99,102,241,0.04) 100%);border:1px solid rgba(0,229,160,0.15);border-radius:var(--radius-md);display:flex;align-items:center;justify-content:space-between;gap:16px;position:relative;overflow:hidden;}}
.profit-showcase::before{{content:'';position:absolute;top:-50%;right:-20%;width:200px;height:200px;background:radial-gradient(circle,rgba(0,229,160,0.08),transparent 70%);pointer-events:none;}}
.profit-label-text{{font-size:0.68rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:rgba(0,229,160,0.6);margin-bottom:4px;}}
.profit-value{{font-family:var(--font-display);font-size:2.4rem;font-weight:900;color:var(--profit);line-height:1;letter-spacing:-0.04em;text-shadow:0 0 30px var(--profit-glow);}}
.profit-right{{text-align:right;}}
.profit-rate-badge{{display:inline-block;font-family:var(--font-display);font-size:1.1rem;font-weight:800;color:var(--profit);background:rgba(0,229,160,0.12);border:1px solid rgba(0,229,160,0.25);padding:6px 14px;border-radius:var(--radius-sm);margin-bottom:6px;}}
.profit-note{{font-size:0.7rem;color:var(--text-tertiary);}}
/* Price Compare */
.price-compare{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border-subtle);margin:16px 22px 0;border-radius:var(--radius-md);overflow:hidden;}}
.price-box{{background:var(--bg-elevated);padding:14px 16px;}}
.price-box-label{{font-size:0.65rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-tertiary);margin-bottom:6px;}}
.price-box-value{{font-family:var(--font-display);font-size:1.15rem;font-weight:800;color:var(--text-primary);font-variant-numeric:tabular-nums;}}
/* Card Body */
.card-body{{padding:16px 22px 20px;}}
.condition-strip{{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,0.03);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:9px 14px;margin-bottom:14px;font-size:0.8rem;color:var(--text-secondary);}}
.condition-icon{{color:var(--warn);font-size:0.85rem;flex-shrink:0;}}
.updated-row{{display:flex;align-items:center;gap:6px;font-size:0.72rem;color:var(--text-tertiary);margin-bottom:14px;}}
/* Shop Table */
.shop-table{{border:1px solid var(--border-subtle);border-radius:var(--radius-md);overflow:hidden;margin-bottom:16px;}}
.shop-table-header{{display:flex;align-items:center;justify-content:space-between;padding:9px 16px;background:rgba(255,255,255,0.03);border-bottom:1px solid var(--border-subtle);font-size:0.65rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-tertiary);}}
.shop-row{{display:flex;align-items:center;padding:10px 16px;border-bottom:1px solid var(--border-subtle);transition:background 0.15s;gap:10px;}}
.shop-row:last-child{{border:none;}}
.shop-row:hover{{background:rgba(255,255,255,0.02);}}
.shop-rank{{font-size:0.72rem;font-weight:800;color:var(--text-tertiary);min-width:20px;text-align:center;}}
.shop-rank.gold{{color:#f59e0b;}}
.shop-rank.silver{{color:#94a3b8;}}
.shop-name-cell{{flex:1;font-size:0.875rem;color:var(--text-secondary);}}
.shop-name-cell a{{color:var(--brand-bright);text-decoration:none;transition:color 0.15s;}}
.shop-name-cell a:hover{{color:var(--text-primary);}}
.shop-price-cell{{font-family:var(--font-display);font-size:0.9rem;font-weight:700;color:var(--text-primary);font-variant-numeric:tabular-nums;text-align:right;min-width:80px;}}
.shop-diff-cell{{font-size:0.78rem;font-weight:700;color:var(--profit);text-align:right;min-width:70px;}}
.shop-diff-cell.neg{{color:var(--danger);}}
/* Card Actions */
.card-actions{{display:flex;gap:8px;flex-wrap:wrap;}}
.btn{{display:inline-flex;align-items:center;gap:6px;font-size:0.8rem;font-weight:600;padding:8px 16px;border-radius:var(--radius-sm);text-decoration:none;transition:all 0.2s;cursor:pointer;border:none;}}
.btn-outline{{background:transparent;color:var(--brand-bright);border:1px solid rgba(99,102,241,0.3);}}
.btn-outline:hover{{background:var(--brand-subtle);border-color:rgba(99,102,241,0.5);color:var(--text-primary);}}
.btn-ghost{{background:rgba(255,255,255,0.04);color:var(--text-secondary);border:1px solid var(--border-subtle);}}
.btn-ghost:hover{{background:rgba(255,255,255,0.08);color:var(--text-primary);border-color:var(--border-default);}}
/* Watch Table */
.watch-table-wrap{{border:1px solid var(--border-subtle);border-radius:var(--radius-lg);overflow:hidden;background:var(--bg-card);}}
.watch-table-wrap table{{width:100%;border-collapse:collapse;font-size:0.875rem;}}
.watch-table-wrap thead tr{{background:rgba(255,255,255,0.03);border-bottom:1px solid var(--border-subtle);}}
.watch-table-wrap th{{padding:11px 14px;text-align:left;font-size:0.65rem;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-tertiary);white-space:nowrap;}}
.watch-table-wrap td{{padding:11px 14px;border-bottom:1px solid var(--border-subtle);color:var(--text-secondary);vertical-align:middle;}}
.watch-table-wrap tbody tr:last-child td{{border:none;}}
.watch-table-wrap tbody tr:hover td{{background:rgba(255,255,255,0.02);}}
.td-product-name{{font-weight:600;color:var(--text-primary);}}
.td-profit{{color:var(--profit);font-weight:700;font-variant-numeric:tabular-nums;}}
/* Ranking */
.ranking-card{{background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);overflow:hidden;margin-bottom:24px;}}
.ranking-card-header{{padding:16px 20px;border-bottom:1px solid var(--border-subtle);display:flex;align-items:center;gap:10px;background:rgba(255,255,255,0.02);}}
.ranking-card-title{{font-family:var(--font-display);font-size:0.85rem;font-weight:700;color:var(--text-primary);}}
.ranking-row{{display:flex;align-items:center;padding:12px 20px;border-bottom:1px solid var(--border-subtle);gap:14px;transition:background 0.15s;}}
.ranking-row:last-child{{border:none;}}
.ranking-row:hover{{background:rgba(255,255,255,0.02);}}
.rank-num{{font-family:var(--font-display);font-size:1rem;font-weight:900;color:var(--text-tertiary);min-width:28px;text-align:center;}}
.rank-num.r1{{color:#f59e0b;text-shadow:0 0 10px rgba(245,158,11,0.5);}}
.rank-num.r2{{color:#94a3b8;}}
.rank-num.r3{{color:#cd7c2f;}}
.rank-product{{flex:1;}}
.rank-product-name{{font-weight:600;color:var(--text-primary);font-size:0.9rem;}}
.rank-product-meta{{font-size:0.72rem;color:var(--text-tertiary);margin-top:2px;}}
.rank-profit{{font-family:var(--font-display);font-size:1.1rem;font-weight:800;color:var(--profit);font-variant-numeric:tabular-nums;text-align:right;}}
.rank-rate{{font-size:0.72rem;color:var(--text-tertiary);text-align:right;margin-top:2px;}}
/* Alert Cards */
.alert-card{{background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:var(--radius-lg);padding:20px 22px;margin-bottom:14px;position:relative;overflow:hidden;}}
.alert-card.surge{{border-left:3px solid var(--profit);background:linear-gradient(135deg,rgba(0,229,160,0.04),transparent);}}
.alert-card.drop{{border-left:3px solid var(--danger);background:linear-gradient(135deg,rgba(244,63,94,0.04),transparent);}}
/* Empty State */
.empty-state{{text-align:center;padding:60px 24px;color:var(--text-tertiary);}}
.empty-icon{{font-size:2.5rem;margin-bottom:16px;opacity:0.3;display:block;}}
/* Caution */
.caution-block{{background:linear-gradient(135deg,rgba(245,158,11,0.05),rgba(245,158,11,0.02));border:1px solid rgba(245,158,11,0.15);border-left:3px solid var(--warn);border-radius:0 var(--radius-md) var(--radius-md) 0;padding:22px 26px;margin:48px 0;}}
.caution-title{{font-family:var(--font-display);font-size:0.85rem;font-weight:700;color:var(--warn);margin-bottom:12px;display:flex;align-items:center;gap:8px;}}
.caution-list{{list-style:none;padding:0;}}
.caution-list li{{font-size:0.875rem;color:var(--text-secondary);padding:4px 0 4px 16px;position:relative;line-height:1.7;}}
.caution-list li::before{{content:'·';position:absolute;left:4px;color:var(--text-tertiary);}}
/* CTA */
.cta-section{{position:relative;margin:56px 0;padding:48px 40px;border-radius:var(--radius-xl);text-align:center;overflow:hidden;background:var(--bg-card);border:1px solid var(--border-default);}}
.cta-section::before{{content:'';position:absolute;inset:0;background:radial-gradient(ellipse 80% 60% at 50% 0%,rgba(99,102,241,0.1) 0%,transparent 60%),radial-gradient(ellipse 40% 40% at 80% 100%,rgba(0,229,160,0.06) 0%,transparent 60%);pointer-events:none;}}
.cta-section::after{{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(99,102,241,0.5),transparent);}}
.cta-eyebrow{{font-size:0.68rem;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:var(--brand-bright);margin-bottom:16px;position:relative;}}
.cta-title{{font-family:var(--font-display);font-size:1.6rem;font-weight:800;color:var(--text-primary);margin-bottom:12px;letter-spacing:-0.02em;position:relative;}}
.cta-desc{{font-size:0.95rem;color:var(--text-secondary);max-width:460px;margin:0 auto 28px;line-height:1.7;position:relative;}}
.cta-buttons{{display:flex;justify-content:center;gap:12px;flex-wrap:wrap;position:relative;}}
.btn-cta-primary{{display:inline-flex;align-items:center;gap:8px;background:linear-gradient(135deg,var(--brand) 0%,#8b5cf6 100%);color:#fff;font-family:var(--font-display);font-size:0.9rem;font-weight:700;padding:13px 28px;border-radius:var(--radius-md);text-decoration:none;border:none;cursor:pointer;box-shadow:0 4px 20px var(--brand-glow),0 1px 3px rgba(0,0,0,0.3);transition:all 0.2s;}}
.btn-cta-primary:hover{{transform:translateY(-2px);box-shadow:0 8px 30px var(--brand-glow),0 2px 6px rgba(0,0,0,0.3);}}
.btn-cta-secondary{{display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,0.06);color:var(--text-secondary);font-size:0.9rem;font-weight:600;padding:13px 28px;border-radius:var(--radius-md);text-decoration:none;border:1px solid var(--border-default);cursor:pointer;transition:all 0.2s;}}
.btn-cta-secondary:hover{{background:rgba(255,255,255,0.1);color:var(--text-primary);border-color:var(--border-strong);}}
/* Footer */
.footer{{border-top:1px solid var(--border-subtle);padding:40px 0 24px;text-align:center;margin-top:48px;}}
.footer-text{{font-size:0.78rem;color:var(--text-tertiary);line-height:2.2;}}
/* Freshness */
.freshness-live{{color:var(--profit);font-size:0.7rem;font-weight:700;}}
.freshness-recent{{color:var(--warn);font-size:0.7rem;font-weight:700;}}
.freshness-stale{{color:var(--danger);font-size:0.7rem;font-weight:700;}}
.freshness-unknown{{color:var(--text-tertiary);font-size:0.7rem;}}
/* Hidden anchors */
#tab-beginner,#tab-advanced{{display:none;}}
/* Animations */
@keyframes fadeInUp{{from{{opacity:0;transform:translateY(20px);}}to{{opacity:1;transform:translateY(0);}}}}
/* Responsive */
@media(max-width:768px){{
  .hero{{padding:56px 0 44px;}}
  .hero-title{{font-size:2rem;}}
  .hero-subtitle{{font-size:0.95rem;}}
  .hero-stat-card{{padding:10px 14px;min-width:90px;}}
  .hero-stat-num{{font-size:1.3rem;}}
  .profit-value{{font-size:2rem;}}
  .profit-showcase{{flex-direction:column;gap:12px;}}
  .profit-right{{text-align:left;}}
  .genre-pills{{gap:6px;}}
  .genre-pill{{padding:8px 14px;font-size:0.82rem;}}
  .card-header{{padding:16px 18px 12px;}}
  .card-body{{padding:14px 18px 18px;}}
  .profit-showcase{{margin:0 18px;padding:16px 18px;}}
  .price-compare{{margin:14px 18px 0;}}
  .cta-section{{padding:36px 24px;}}
  .cta-title{{font-size:1.3rem;}}
  .topbar-meta{{display:none;}}
  .shop-diff-cell{{display:none;}}
}}
@media(max-width:480px){{
  .container{{padding:0 14px 60px;}}
  .hero-title{{font-size:1.7rem;}}
  .profit-value{{font-size:1.7rem;}}
  .price-compare{{grid-template-columns:1fr;}}
  .cta-buttons{{flex-direction:column;align-items:stretch;}}
  .btn-cta-primary,.btn-cta-secondary{{justify-content:center;}}
}}
/* noscript */
.noscript-all .genre-panel{{display:block!important;}}
.noscript-all .genre-pills{{display:none;}}
</style>

</head>
<body>
<header class="topbar">
  <a href="/" class="topbar-brand">
    <div class="logo-mark">P</div>
    プレ値速報
  </a>
  <div class="topbar-live"><span class="pulse"></span>LIVE</div>
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
  var pills=document.querySelectorAll(".genre-pill");
  var panels=document.querySelectorAll(".genre-panel");
  if(pills.length){{
    pills.forEach(function(pill){{
      pill.addEventListener("click",function(){{
        pills.forEach(function(p){{p.classList.remove("active");p.setAttribute("aria-selected","false");}});
        panels.forEach(function(p){{p.classList.remove("active");}});
        pill.classList.add("active");
        pill.setAttribute("aria-selected","true");
        var panel=document.getElementById("genre-"+pill.dataset.genre);
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
<noscript><style>.genre-pills{{display:none;}}.genre-panel{{display:block!important;}}</style></noscript>
</body>
</html>"""

    # ----- Hero -----

    def _section_hero(self, date_str, time_str, latest_buyback_at, lp_generated_at,
                       all_deals=None, iphone_deals=None, camera_deals=None, game_deals=None) -> str:
        variant_key = self.settings.get('headline_variant', 'A')
        variants    = self.settings.get('variants', {})
        variant     = variants.get(variant_key, {})
        headline    = _esc(variant.get('headline', self.settings.get('site_title', 'プレ値速報')))
        buyback_str = _jst_str(latest_buyback_at)
        lp_str      = _jst_str(lp_generated_at)
        stale_cls   = 'stale' if _hours_ago(latest_buyback_at) > 24 else ''
        # Stats
        all_count    = len(all_deals)    if all_deals    else 0
        iphone_count = len(iphone_deals) if iphone_deals else 0
        camera_count = len(camera_deals) if camera_deals else 0
        game_count   = len(game_deals)   if game_deals   else 0
        # Max profit
        max_profit = 0
        if all_deals:
            max_profit = max((d.net_profit_jpy or 0) for d in all_deals)
        max_profit_str = f'+¥{max_profit:,}' if max_profit > 0 else '—'
        return f"""<div class="hero">
  <div class="hero-glow-1"></div>
  <div class="hero-glow-2"></div>
  <div class="hero-glow-3"></div>
  <div class="hero-tag"><span>&#9679;</span> 毎日更新 &mdash; プレ値監視情報</div>
  <h1 class="hero-title"><span class="grad">公式価格</span>と買取価格の差額を、毎日チェック。</h1>
  <p class="hero-subtitle">iPhone・カメラ・ゲーム機の公式価格と買取価格の差額を毎日監視。ジャンル別に整理された、せどり情報の決定版。</p>
  <div class="hero-stats">
    <div class="hero-stat-card">
      <div class="hero-stat-num">{all_count}</div>
      <div class="hero-stat-label">本日の案件</div>
    </div>
    <div class="hero-stat-card">
      <div class="hero-stat-num" style="color:var(--iphone)">{iphone_count}</div>
      <div class="hero-stat-label">iPhone案件</div>
    </div>
    <div class="hero-stat-card">
      <div class="hero-stat-num" style="color:var(--camera)">{camera_count}</div>
      <div class="hero-stat-label">カメラ案件</div>
    </div>
    <div class="hero-stat-card">
      <div class="hero-stat-num" style="color:var(--game)">{game_count}</div>
      <div class="hero-stat-label">ゲーム機案件</div>
    </div>
    <div class="hero-stat-card">
      <div class="hero-stat-num" style="color:#f59e0b;font-size:1.3rem">{_esc(max_profit_str)}</div>
      <div class="hero-stat-label">最大利益</div>
    </div>
  </div>
  <div class="hero-timestamps">
    <span class="ts-pill {_esc(stale_cls)}" data-buyback-updated>
      <span class="ts-dot"></span>買取価格更新：{_esc(buyback_str)}
    </span>
    <span class="ts-pill" data-lp-generated>
      <span class="ts-dot blue"></span>LP生成：{_esc(lp_str)}
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
        all_html      = self._tab_all(beginner_easy, beginner_watch, bybp)
        iphone_html   = self._tab_genre(iphone_deals, iphone_watch, 'iphone', 'iPhone', bybp)
        camera_html   = self._tab_genre(camera_deals, camera_watch, 'camera', 'カメラ', bybp)
        game_html     = self._tab_genre(game_deals, game_watch, 'game_console', 'ゲーム機', bybp)
        advanced_html = self._tab_advanced(advanced_deals, advanced_snaps, watch_candidates)
        surge_html    = self._tab_surge(buyback_alerts)
        ranking_html  = self._tab_ranking(all_deals, iphone_deals, game_deals)
        all_count    = len(beginner_easy) + len(beginner_watch)
        iphone_count = len(iphone_deals)
        camera_count = len(camera_deals)
        game_count   = len(game_deals)
        adv_total    = len(advanced_deals) + len(advanced_snaps) + len(watch_candidates)
        surge_count  = len([a for a in buyback_alerts if a.get('alert_type') in ('buyback_surge','buyback_drop')])
        surge_badge  = f'<span class="genre-count">{surge_count}</span>' if surge_count else ''
        return f"""<div class="genre-section">
  <div class="genre-label">カテゴリを選択</div>
  <div class="genre-pills" role="tablist">
    <button class="genre-pill all active" data-genre="all" role="tab" aria-selected="true">
      <span class="genre-icon">&#128202;</span>全案件<span class="genre-count">{all_count}</span>
    </button>
    <button class="genre-pill iphone" data-genre="iphone" role="tab">
      <span class="genre-icon">&#128241;</span>iPhone<span class="genre-count">{iphone_count}</span>
    </button>
    <button class="genre-pill camera" data-genre="camera" role="tab">
      <span class="genre-icon">&#128247;</span>カメラ<span class="genre-count">{camera_count}</span>
    </button>
    <button class="genre-pill game" data-genre="game_console" role="tab">
      <span class="genre-icon">&#127918;</span>ゲーム機<span class="genre-count">{game_count}</span>
    </button>
    <button class="genre-pill advanced" data-genre="advanced" role="tab">
      <span class="genre-icon">&#128269;</span>上級者向け<span class="genre-count">{adv_total}</span>
    </button>
    <button class="genre-pill surge" data-genre="surge" role="tab">
      <span class="genre-icon">&#9889;</span>急騰/急落{surge_badge}
    </button>
    <button class="genre-pill ranking" data-genre="ranking" role="tab">
      <span class="genre-icon">&#127942;</span>ランキング
    </button>
  </div>
</div>
<div id="tab-beginner" aria-hidden="true" style="display:none"></div>
<div id="tab-advanced" aria-hidden="true" style="display:none"></div>
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
        bybp = buyback_by_product or {}
        parts = []
        if easy_deals:
            parts.append('<div class="section-head"><div class="section-title">低難度 &mdash; すぐ動ける案件</div>'
                         + f'<div class="section-badge">{len(easy_deals)}件</div></div>')
            parts.append('<div class="cards-grid">')
            for d in easy_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, 'tag-easy', '低難度', buyback_rows=rows))
            parts.append('</div>')
        else:
            parts.append('<div class="section-head"><div class="section-title">低難度 &mdash; すぐ動ける案件</div></div>'
                         + '<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす案件はありません。</div>')
        if watch_deals:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">要確認 &mdash; 様子見案件</div>'
                         + f'<div class="section-badge">{len(watch_deals)}件</div></div>')
            parts.append('<div class="cards-grid">')
            for d in watch_deals:
                rows = bybp.get(d.product_id, [])
                parts.append(self._deal_card(d, 'tag-watch', '要確認', buyback_rows=rows))
            parts.append('</div>')
        else:
            parts.append('<div class="section-head" style="margin-top:40px"><div class="section-title">要確認 &mdash; 様子見案件</div></div>'
                         + '<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす案件はありません。</div>')
        return '\n'.join(parts)

    def _tab_genre(self, deals, watch_list, genre_key: str, genre_label: str,
                   buyback_by_product: dict = None) -> str:
        bybp = buyback_by_product or {}
        parts = []
        if deals:
            parts.append(f'<div class="section-head"><div class="section-title">{_esc(genre_label)} &mdash; 買取利益案件</div>'
                         + f'<div class="section-badge">{len(deals)}件</div></div>')
            parts.append('<div class="cards-grid">')
            for d in deals:
                rows = bybp.get(d.product_id, [])
                label = '低難度' if d.user_level == 'beginner_easy' else '要確認'
                badge = 'tag-easy' if d.user_level == 'beginner_easy' else 'tag-watch'
                parts.append(self._deal_card(d, badge, label, buyback_rows=rows, genre=genre_key))
            parts.append('</div>')
        else:
            parts.append(f'<div class="section-head"><div class="section-title">{_esc(genre_label)} &mdash; 買取利益案件</div></div>'
                         + '<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、買取利益案件はありません。</div>')
        if watch_list:
            parts.append(f'<div class="section-head" style="margin-top:40px"><div class="section-title">{_esc(genre_label)} &mdash; 監視候補</div>'
                         + f'<div class="section-badge">{len(watch_list)}件</div></div>')
            parts.append(self._watch_candidates_table(watch_list))
        return '\n'.join(parts)

    def _deal_card(self, d, badge_cls: str, label: str, buyback_rows: list = None, genre: str = None) -> str:
        pid  = _esc(d.product_id)
        shop = _esc(d.best_buyback_shop or '—')
        links = ''
        if hasattr(d, 'official_url') and d.official_url:
            links += f'<a href="{_esc(d.official_url)}" target="_blank" rel="noopener" class="btn btn-outline" data-track="product_click" data-product-id="{pid}">公式購入ページ &rarr;</a>'
        elif hasattr(d, 'best_official_url') and d.best_official_url:
            links += f'<a href="{_esc(d.best_official_url)}" target="_blank" rel="noopener" class="btn btn-outline" data-track="product_click" data-product-id="{pid}">公式購入ページ &rarr;</a>'
        verified_url = ''
        if hasattr(d, 'best_buyback_url') and d.best_buyback_url:
            _skip = ('mobileno1.com', 'kaitori-1chome.com')
            if not any(dom in d.best_buyback_url for dom in _skip):
                verified_url = d.best_buyback_url
        if verified_url:
            links += f'<a href="{_esc(verified_url)}" target="_blank" rel="noopener" class="btn btn-ghost" data-track="product_click" data-product-id="{pid}" data-shop="{shop}">買取ページ &rarr;</a>'
        updated_str = ''
        if hasattr(d, 'scanned_at') and d.scanned_at:
            updated_str = f'<div class="updated-row"><span>&#128336;</span>最終更新：{_esc(_jst_str(d.scanned_at))}</div>'
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
                    shop_display = f'<a href="{_esc(url_val)}" target="_blank" rel="noopener" data-track="buyback_click" data-product-id="{pid}" data-shop="{sname}">{sname}</a>'
                else:
                    shop_display = sname
                rank_cls = 'gold' if i == 1 else ('silver' if i == 2 else '')
                diff_cls = ' neg' if profit < 0 else ''
                rows_html.append(
                    f'<div class="shop-row">'
                    f'<div class="shop-rank {rank_cls}">{i}</div>'
                    f'<div class="shop-name-cell">{shop_display}</div>'
                    f'<div class="shop-price-cell">¥{bp:,}</div>'
                    f'<div class="shop-diff-cell{diff_cls}">{_esc(profit_str)}</div>'
                    f'</div>'
                )
            first_freshness = self._freshness_label(
                buyback_rows[0].get('observed_at', ''), buyback_rows[0].get('data_source', 'manual_today')
            )
            compare_html = (
                f'<div class="shop-table">'
                f'<div class="shop-table-header"><span>買取店比較（最大10店舗）</span>{first_freshness}</div>'
                + ''.join(rows_html)
                + '</div>'
            )
        genre_cls = genre or (d.category if hasattr(d, 'category') else '')
        genre_card_cls = {'iphone': 'iphone-card', 'camera': 'camera-card', 'game_console': 'game-card'}.get(genre_cls, '')
        genre_tag = {'iphone': '<span class="tag tag-iphone">iPhone</span>', 'camera': '<span class="tag tag-camera">カメラ</span>', 'game_console': '<span class="tag tag-game">ゲーム機</span>'}.get(genre_cls, '')
        profit_rate_str = _esc(fmt_rate(d.net_profit_rate))
        is_watch = d.user_level == 'beginner_watch'
        profit_style = '' if not is_watch else 'background:linear-gradient(135deg,rgba(245,158,11,0.06),rgba(245,158,11,0.02));border-color:rgba(245,158,11,0.15);'
        profit_val_style = '' if not is_watch else 'color:var(--warn);text-shadow:0 0 30px rgba(245,158,11,0.3);'
        profit_rate_style = '' if not is_watch else 'color:var(--warn);background:rgba(245,158,11,0.12);border-color:rgba(245,158,11,0.25);'
        profit_label_style = '' if not is_watch else 'color:rgba(245,158,11,0.6);'
        return f"""<div class="deal-card {_esc(genre_card_cls)}" data-user-level="{_esc(d.user_level)}">
  <div class="card-accent"></div>
  <div class="card-header">
    <div class="card-name">{_esc(d.product_name)}</div>
    <div class="card-tags"><span class="tag {badge_cls}">{label}</span>{genre_tag}</div>
  </div>
  <div class="profit-showcase" style="{profit_style}">
    <div class="profit-left">
      <div class="profit-label-text" style="{profit_label_style}">実質利益（推定コスト差引後）</div>
      <div class="profit-value" style="{profit_val_style}">{_esc(fmt_profit(d.net_profit_jpy))}</div>
    </div>
    <div class="profit-right">
      <div class="profit-rate-badge" style="{profit_rate_style}">{profit_rate_str}</div>
      <div class="profit-note">推定コスト -{_esc(fmt_price(d.estimated_costs_jpy))}</div>
    </div>
  </div>
  <div class="price-compare">
    <div class="price-box">
      <div class="price-box-label">公式価格</div>
      <div class="price-box-value">{_esc(fmt_price(d.official_price_jpy))}</div>
    </div>
    <div class="price-box">
      <div class="price-box-label">最高買取価格</div>
      <div class="price-box-value" style="color:var(--profit)">{_esc(fmt_price(d.best_buyback_price))}</div>
    </div>
  </div>
  <div class="card-body">
    <div class="condition-strip">
      <span class="condition-icon">&#9888;</span>
      買取条件：{_esc(d.buyback_condition or '新品未開封')}
    </div>
    {updated_str}
    {compare_html}
    <div class="card-actions">{links}</div>
  </div>
</div>"""

    def _tab_advanced(self, advanced_deals, advanced_snaps, watch_candidates) -> str:
        parts = []
        _link_res = get_resolver()

        if advanced_deals:
            parts.append('<div class="section-head"><div class="section-title">高利益案件</div><div class="section-badge">' + str(len(advanced_deals)) + '件</div></div>')
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
            parts.append('<div class="section-head"><div class="section-title">プレ値・価格差候補</div><div class="section-badge">スナップショット分析</div></div>')
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
                parts.append("""<div class="adv-fallback-notice">
<span class="adv-fallback-icon">ℹ️</span>
<div><strong>現在、上級者向けの確定候補は少ないため、価格差・希少性・海外相場差が大きい監視候補を表示しています。</strong><br>
<span>中古市場や海外相場のデータが入り次第、確定候補として昇格します。</span></div>
</div>""")
            parts.append('<div class="section-head"><div class="section-title">上級者向け監視候補</div><div class="section-badge">価格差・希少性スコア上位</div></div>')
            parts.append(self._watch_candidates_table(watch_candidates))

        if not advanced_deals and not advanced_snaps and not watch_candidates:
            parts.append('<div class="section-head"><div class="section-title">上級者向け候補</div></div><div class="empty-state"><span class="empty-icon">&#128269;</span>現在、条件を満たす候補はありません。</div>')

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

        return f"""<div class="watch-table-wrap">
<table>
<thead><tr><th>商品</th><th>公式価格</th><th>最新買取店</th><th>注目ポイント</th><th>リンク</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>

<p style="color:var(--text-tertiary);font-size:0.78rem;margin-top:10px;padding:0 4px;">
※ 監視候補は価格差・希少性スコアが高い商品です。中古市場データ入手後に確定候補へ昇格します。
</p>
</div>"""

    # ----- Tab: 急騰/急落 -----

    def _tab_surge(self, alerts) -> str:
        surge = [a for a in alerts if a.get("alert_type") == "buyback_surge"]
        drop  = [a for a in alerts if a.get("alert_type") == "buyback_drop"]

        parts = []

        if surge:
            parts.append('<div class="section-head"><div class="section-title">本日の急騰</div></div>')
            for a in surge:
                parts.append(self._alert_card(a, "surge"))
        else:
            parts.append('<div class="section-head"><div class="section-title">本日の急騰</div></div><div class="empty-state"><span class="empty-icon">&#9989;</span>急騰は検出されていません（閃値：¥5,000+）</div>')

        if drop:
            parts.append('<div class="section-head"><div class="section-title">本日の急落</div></div>')
            for a in drop:
                parts.append(self._alert_card(a, "drop"))
        else:
            parts.append('<div class="section-head"><div class="section-title">本日の急落</div></div><div class="empty-state"><span class="empty-icon">&#9989;</span>急落は検出されていません（閃値：¥5,000−）</div>')

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
            parts.append('<div class="section-head"><div class="section-title">実質利益ランキング</div><div class="section-badge">全カテゴリ</div></div>')
            parts.append(self._ranking_table(profitable[:10], show_category=True))
        else:
            parts.append('<div class="section-head"><div class="section-title">実質利益ランキング</div></div><div class="empty-state">データなし</div>')

        # iPhoneランキング
        iphone_profitable = sorted([d for d in iphone_deals if d.net_profit_jpy > 0],
                                    key=lambda d: d.net_profit_jpy, reverse=True)
        if iphone_profitable:
            parts.append('<div class="section-head"><div class="section-title">iPhone ランキング</div></div>')
            parts.append(self._ranking_table(iphone_profitable[:5]))

        # ゲーム機ランキング
        game_profitable = sorted([d for d in game_deals if d.net_profit_jpy > 0],
                                  key=lambda d: d.net_profit_jpy, reverse=True)
        if game_profitable:
            parts.append('<div class="section-head"><div class="section-title">ゲーム機 ランキング</div></div>')
            parts.append(self._ranking_table(game_profitable[:5]))

        # 買取店別ランキング
        shop_totals: dict = {}
        for d in all_deals:
            if d.best_buyback_shop and d.net_profit_jpy > 0:
                shop_totals[d.best_buyback_shop] = shop_totals.get(d.best_buyback_shop, 0) + 1
        if shop_totals:
            parts.append('<div class="section-head"><div class="section-title">買取店別 案件数ランキング</div></div>')
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
        if self.settings.get('enable_note_cta'):
            note_url = (self.settings.get('note_url') or '').strip()
            if note_url and note_url != '#':
                parts.append(f"""<div class="cta-section">
<div class="cta-eyebrow">詳細レポート</div>
<div class="cta-title">全案件・詳細レポートを見る</div>
<p class="cta-desc">仕入れ条件・複数買取店の詳細比較・全案件一覧はnoteで公開中です。</p>
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
        if self.settings.get('enable_line_cta'):
            line_url = (self.settings.get('line_url') or '').strip()
            if line_url and line_url != '#':
                parts.append(f'<div class="cta-section"><div class="cta-eyebrow">LINE速報</div><div class="cta-title">LINEで速報を受け取る</div><div class="cta-buttons"><a href="{_esc(line_url)}" class="btn-cta-primary" style="background:#06c755" data-track="line_click">LINE登録で速報を受け取る</a></div></div>')
        if self.settings.get('enable_telegram_cta'):
            tg_url = (self.settings.get('telegram_url') or '').strip()
            if tg_url and tg_url != '#':
                parts.append(f'<div class="cta-section"><div class="cta-eyebrow">Telegram速報</div><div class="cta-title">Telegramチャンネルに参加する</div><div class="cta-buttons"><a href="{_esc(tg_url)}" class="btn-cta-primary" data-track="telegram_click">Telegramチャンネルに参加する</a></div></div>')
        return '\n'.join(parts)

    def _section_footer(self) -> str:
        now = datetime.now()
        return f"""<footer class="footer">
<div class="footer-text">
<p>価格情報は参考値です。購入前に必ず公式サイト・買取店でご確認ください。</p>
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
