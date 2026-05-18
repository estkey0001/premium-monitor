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

        # 急騰・急落
        buyback_alerts = self.repo.list_buyback_alerts(limit=20)

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
            buyback_alerts=buyback_alerts,
            all_deals=all_deals,
            iphone_deals=iphone_deals,
            game_deals=game_deals,
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

        if not variant:
            (out_dir / "index.html").write_text(page_html, encoding="utf-8")
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
                     buyback_alerts, all_deals, iphone_deals, game_deals) -> str:

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
            buyback_alerts,
            all_deals, iphone_deals, game_deals,
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
{analytics_head}
<style>
:root {{
  --bg:#0f1117; --card:#1a1d27; --border:#2a2d37;
  --text:#e4e4e7; --muted:#9ca3af; --accent:#3b82f6;
  --green:#22c55e; --yellow:#eab308; --orange:#f97316; --red:#ef4444;
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.7;}}
.container{{max-width:820px;margin:0 auto;padding:20px 16px;}}
h1{{font-size:1.6rem;margin-bottom:8px;}}
h2{{font-size:1.2rem;margin:24px 0 14px;padding-bottom:6px;border-bottom:1px solid var(--border);}}
h3{{font-size:1rem;margin:14px 0 8px;}}
/* Hero */
.hero{{text-align:center;padding:36px 0 20px;}}
.hero .timestamps{{display:flex;flex-wrap:wrap;justify-content:center;gap:12px;margin-top:10px;}}
.hero .ts-item{{color:var(--muted);font-size:0.8rem;background:var(--card);padding:4px 12px;border-radius:99px;border:1px solid var(--border);}}
/* Stale Warning */
.stale-warning-block{{background:#2d1a00;border-left:4px solid var(--orange);padding:12px 16px;border-radius:0 8px 8px 0;margin:12px 0;font-size:0.88rem;color:#fbbf24;}}
/* Tabs */
.tab-nav{{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0 0;border-bottom:2px solid var(--border);padding-bottom:0;}}
.tab-btn{{background:transparent;border:none;border-bottom:3px solid transparent;padding:10px 18px;font-size:0.9rem;color:var(--muted);cursor:pointer;transition:all .2s;margin-bottom:-2px;border-radius:8px 8px 0 0;white-space:nowrap;}}
.tab-btn:hover{{color:var(--text);background:var(--card);}}
.tab-btn.active{{color:var(--accent);border-bottom-color:var(--accent);background:var(--card);font-weight:600;}}
.tab-panel{{display:none;padding:8px 0;}}
.tab-panel.active{{display:block;}}
/* noscript fallback: show all panels */
.noscript-all .tab-panel{{display:block!important;}}
.noscript-all .tab-btn{{display:none;}}
.noscript-all .tab-nav::before{{content:"※ JavaScript が無効です。全タブを表示しています。";display:block;color:var(--muted);font-size:0.8rem;padding:8px 0;width:100%;}}
/* Cards */
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;margin:10px 0;}}
.badge{{display:inline-block;padding:2px 10px;border-radius:99px;font-size:0.72rem;font-weight:600;}}
.badge-easy{{background:#22c55e22;color:var(--green);}}
.badge-watch{{background:#eab30822;color:var(--yellow);}}
.badge-adv{{background:#f9731622;color:var(--orange);}}
.badge-exp{{background:#ef444422;color:var(--red);}}
.badge-surge{{background:#22c55e22;color:var(--green);}}
.badge-drop{{background:#ef444422;color:var(--red);}}
/* Price rows */
.price-row{{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border);font-size:0.92rem;}}
.price-row:last-child{{border:none;}}
.price-label{{color:var(--muted);}}
.price-value{{font-weight:600;}}
.profit{{color:var(--green);font-size:1.15rem;font-weight:700;}}
/* Links */
.links{{margin-top:12px;display:flex;flex-wrap:wrap;gap:8px;}}
.links a{{color:var(--accent);text-decoration:none;font-size:0.85rem;padding:4px 12px;border:1px solid var(--accent);border-radius:6px;}}
.links a:hover{{background:var(--accent);color:#fff;}}
/* Table */
table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:0.88rem;}}
th,td{{padding:7px 10px;text-align:left;border-bottom:1px solid var(--border);}}
th{{color:var(--muted);font-weight:500;white-space:nowrap;}}
td{{word-break:break-word;}}
/* Misc */
.empty-msg{{color:var(--muted);padding:16px 0;font-size:0.9rem;}}
.cta{{text-align:center;padding:28px 0;}}
.cta a{{display:inline-block;background:var(--accent);color:#fff;padding:13px 36px;border-radius:8px;text-decoration:none;font-weight:600;font-size:0.95rem;}}
.caution{{background:#1c1c22;border-left:4px solid var(--yellow);padding:14px 18px;margin:24px 0;border-radius:0 8px 8px 0;font-size:0.88rem;color:var(--muted);line-height:1.8;}}
.footer{{text-align:center;color:var(--muted);font-size:0.78rem;padding:36px 0 20px;line-height:2;}}
@media(max-width:600px){{
  .tab-btn{{padding:8px 12px;font-size:0.82rem;}}
  table{{font-size:0.8rem;}}
  th,td{{padding:5px 7px;}}
}}
</style>
</head>
<body>
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

        return f"""<div class="hero">
<h1>{headline}</h1>
<p style="color:var(--muted);font-size:0.9rem;margin-top:6px;">公式価格と買取価格の差額を毎日監視・更新しています</p>
<div class="timestamps">
  <span class="ts-item" data-buyback-updated>📦 買取価格更新：{_esc(buyback_str)}</span>
  <span class="ts-item" data-lp-generated>🕐 LP生成：{_esc(lp_str)}</span>
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
⚠️ <strong>注意：{detail}が24時間以上前のデータです。</strong><br>
購入前に必ず買取店公式ページで最新価格をご確認ください。
</div>"""

    # ----- Tabs -----

    def _section_tabs(self, beginner_easy, beginner_watch,
                      advanced_deals, advanced_snaps,
                      buyback_alerts, all_deals, iphone_deals, game_deals) -> str:
        # カメラ・ゲーム機カテゴリ抽出
        camera_snaps = [s for s in advanced_snaps if getattr(s, "category", "") == "camera"]
        game_snaps   = [s for s in advanced_snaps if getattr(s, "category", "") == "game_console"]

        beginner_html = self._tab_beginner(beginner_easy, beginner_watch)
        advanced_html = self._tab_advanced(advanced_deals, advanced_snaps)
        surge_html    = self._tab_surge(buyback_alerts)
        ranking_html  = self._tab_ranking(all_deals, iphone_deals, game_deals)

        surge_count = len([a for a in buyback_alerts if a.get("alert_type") in ("buyback_surge", "buyback_drop")])
        surge_label = f"急騰/急落{'(' + str(surge_count) + ')' if surge_count else ''}"

        return f"""<nav class="tab-nav" role="tablist">
  <button class="tab-btn active" data-tab="beginner" role="tab" aria-selected="true" aria-controls="tab-beginner">🟢 初級者向け（{len(beginner_easy)+len(beginner_watch)}件）</button>
  <button class="tab-btn" data-tab="advanced" role="tab" aria-selected="false" aria-controls="tab-advanced">🟠 上級者向け（{len(advanced_deals)+len(advanced_snaps)}件）</button>
  <button class="tab-btn" data-tab="surge" role="tab" aria-selected="false" aria-controls="tab-surge">📊 {_esc(surge_label)}</button>
  <button class="tab-btn" data-tab="ranking" role="tab" aria-selected="false" aria-controls="tab-ranking">💰 買取ランキング</button>
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

    # ----- Tab: 初級者向け -----

    def _tab_beginner(self, easy_deals, watch_deals) -> str:
        parts = []

        if easy_deals:
            parts.append('<h2>🟢 低難度・すぐ動ける案件（beginner_easy）</h2>')
            for d in easy_deals:
                parts.append(self._deal_card(d, "badge-easy", "低難度"))
        else:
            parts.append('<h2>🟢 低難度案件</h2><p class="empty-msg">現在、条件を満たす案件はありません。</p>')

        if watch_deals:
            parts.append('<h2>🟡 要確認・様子見案件（beginner_watch）</h2>')
            for d in watch_deals:
                parts.append(self._deal_card(d, "badge-watch", "要確認"))
        else:
            parts.append('<h2>🟡 要確認案件</h2><p class="empty-msg">現在、条件を満たす案件はありません。</p>')

        return "\n".join(parts)

    def _deal_card(self, d, badge_cls: str, label: str) -> str:
        pid  = _esc(d.product_id)
        shop = _esc(d.best_buyback_shop)
        links = ""
        if d.official_url:
            links += (f'<a href="{_esc(d.official_url)}" target="_blank" rel="noopener" '
                      f'data-track="product_click" data-product-id="{pid}">公式購入ページ →</a>')
        if d.best_buyback_url:
            links += (f'<a href="{_esc(d.best_buyback_url)}" target="_blank" rel="noopener" '
                      f'data-track="product_click" data-product-id="{pid}" data-shop="{shop}">買取ページ →</a>')

        updated_str = ""
        if hasattr(d, "scanned_at") and d.scanned_at:
            updated_str = f'<div class="price-row"><span class="price-label">最終更新</span><span class="price-value" style="font-size:0.82rem;color:var(--muted)">{_esc(_jst_str(d.scanned_at))}</span></div>'

        return f"""<div class="card" data-user-level="{_esc(d.user_level)}">
<h3>{_esc(d.product_name)} <span class="badge {badge_cls}">{label}</span></h3>
<div class="price-row"><span class="price-label">公式価格</span><span class="price-value">{_esc(fmt_price(d.official_price_jpy))}</span></div>
<div class="price-row"><span class="price-label">最新買取価格（{shop}）</span><span class="price-value">{_esc(fmt_price(d.best_buyback_price))}</span></div>
<div class="price-row"><span class="price-label">推定コスト</span><span class="price-value">-{_esc(fmt_price(d.estimated_costs_jpy))}</span></div>
<div class="price-row"><span class="price-label">実質利益</span><span class="profit">{_esc(fmt_profit(d.net_profit_jpy))}</span></div>
<div class="price-row"><span class="price-label">利益率</span><span class="price-value">{_esc(fmt_rate(d.net_profit_rate))}</span></div>
<div class="price-row"><span class="price-label">買取条件</span><span class="price-value">{_esc(d.buyback_condition or '新品未開封')}</span></div>
{updated_str}
<div class="links">{links}</div>
</div>"""

    # ----- Tab: 上級者向け -----

    def _tab_advanced(self, advanced_deals, advanced_snaps) -> str:
        parts = []

        if advanced_deals:
            parts.append('<h2>🟠 高利益案件（advanced_high_profit / expert_only）</h2>')
            for d in advanced_deals:
                badge_cls = "badge-exp" if d.user_level == "expert_only" else "badge-adv"
                label = "上級者限定" if d.user_level == "expert_only" else "高利益"
                parts.append(self._deal_card(d, badge_cls, label))
        else:
            parts.append('<h2>🟠 高利益案件</h2><p class="empty-msg">現在、条件を満たす候補はありません。</p>')

        if advanced_snaps:
            parts.append('<h2>📈 プレ値・価格差候補（スナップショット分析）</h2>')
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
            parts.append(f"""<div class="card">
<table>
<tr><th>商品</th><th>定価</th><th>国内中古</th><th>海外</th><th>価格差</th><th>方式</th><th>難易度</th></tr>
{"".join(rows)}
</table>
<p style="color:var(--muted);font-size:0.8rem;margin-top:10px;">※ 難易度0.0〜1.0（低いほど入手しやすい）</p>
</div>""")
        else:
            parts.append('<h2>📈 プレ値候補</h2><p class="empty-msg">現在、該当する候補はありません。</p>')

        return "\n".join(parts)

    # ----- Tab: 急騰/急落 -----

    def _tab_surge(self, alerts) -> str:
        surge = [a for a in alerts if a.get("alert_type") == "buyback_surge"]
        drop  = [a for a in alerts if a.get("alert_type") == "buyback_drop"]

        parts = []

        if surge:
            parts.append('<h2>📈 本日の急騰</h2>')
            for a in surge:
                parts.append(self._alert_card(a, "surge"))
        else:
            parts.append('<h2>📈 本日の急騰</h2><p class="empty-msg">急騰は検出されていません（閾値: ¥5,000+）</p>')

        if drop:
            parts.append('<h2>📉 本日の急落</h2>')
            for a in drop:
                parts.append(self._alert_card(a, "drop"))
        else:
            parts.append('<h2>📉 本日の急落</h2><p class="empty-msg">急落は検出されていません（閾値: ¥5,000−）</p>')

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
            parts.append('<h2>💰 実質利益ランキング（全カテゴリ）</h2>')
            parts.append(self._ranking_table(profitable[:10], show_category=True))
        else:
            parts.append('<h2>💰 実質利益ランキング</h2><p class="empty-msg">データなし</p>')

        # iPhoneランキング
        iphone_profitable = sorted([d for d in iphone_deals if d.net_profit_jpy > 0],
                                    key=lambda d: d.net_profit_jpy, reverse=True)
        if iphone_profitable:
            parts.append('<h2>📱 iPhoneランキング</h2>')
            parts.append(self._ranking_table(iphone_profitable[:5]))

        # ゲーム機ランキング
        game_profitable = sorted([d for d in game_deals if d.net_profit_jpy > 0],
                                  key=lambda d: d.net_profit_jpy, reverse=True)
        if game_profitable:
            parts.append('<h2>🎮 ゲーム機ランキング</h2>')
            parts.append(self._ranking_table(game_profitable[:5]))

        # 買取店別ランキング
        shop_totals: dict = {}
        for d in all_deals:
            if d.best_buyback_shop and d.net_profit_jpy > 0:
                shop_totals[d.best_buyback_shop] = shop_totals.get(d.best_buyback_shop, 0) + 1
        if shop_totals:
            parts.append('<h2>🏪 買取店別 案件数ランキング</h2>')
            rows = []
            for i, (shop, cnt) in enumerate(
                sorted(shop_totals.items(), key=lambda x: x[1], reverse=True)[:8], 1
            ):
                rows.append(f"<tr><td>{i}</td><td>{_esc(shop)}</td><td>{cnt}件</td></tr>")
            parts.append(f"""<div class="card"><table>
<tr><th>#</th><th>買取店</th><th>案件数</th></tr>{"".join(rows)}</table></div>""")

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
                f"<td style='color:var(--green);font-weight:600'>{_esc(fmt_profit(d.net_profit_jpy))}</td>"
                f"<td>{_esc(fmt_rate(d.net_profit_rate))}</td>"
                f"<td>{_esc(d.best_buyback_shop)}</td></tr>"
            )
        cat_th = "<th>カテゴリ</th>" if show_category else ""
        return f"""<div class="card"><table>
<tr><th>#</th><th>商品</th>{cat_th}<th>定価</th><th>買取</th><th>実質利益</th><th>率</th><th>買取店</th></tr>
{"".join(rows)}
</table></div>"""

    # ----- Caution / CTA / Footer -----

    def _section_caution(self) -> str:
        return """<div class="caution">
<strong>⚠️ 注意事項</strong><br>
・本ページは価格差の監視結果であり、購入を推奨するものではありません。<br>
・価格・在庫・買取条件は常に変動します。<br>
・購入前に必ず公式サイトと買取店で最新の条件を確認してください。<br>
・買取条件（新品未開封・SIMフリー等）を満たさない場合、買取価格が下がります。<br>
・利益を保証するものではありません。条件が合えば利益が出る可能性がある情報です。
</div>"""

    def _section_cta(self) -> str:
        parts = []
        if self.settings.get("enable_note_cta"):
            note_url = (self.settings.get("note_url") or "").strip()
            if note_url and note_url != "#":
                parts.append(f"""<div class="cta">
<p style="margin-bottom:12px;">詳しい仕入れ条件・買取店比較・全案件一覧はnoteで公開中</p>
<a href="{_esc(note_url)}" data-track="note_click">noteで詳細レポートを読む →</a>
</div>""")
            else:
                parts.append("""<div class="cta">
<p style="margin-bottom:12px;">詳しい仕入れ条件・買取店比較はnoteで公開予定</p>
<p style="color:var(--muted);font-size:0.88rem;">詳細レポート準備中です。公開時にこのページでお知らせします。</p>
</div>""")
        if self.settings.get("enable_line_cta"):
            line_url = (self.settings.get("line_url") or "").strip()
            if line_url and line_url != "#":
                parts.append(f'<div class="cta"><a href="{_esc(line_url)}" style="background:var(--green)" data-track="line_click">LINE登録で速報を受け取る</a></div>')
        if self.settings.get("enable_telegram_cta"):
            tg_url = (self.settings.get("telegram_url") or "").strip()
            if tg_url and tg_url != "#":
                parts.append(f'<div class="cta"><a href="{_esc(tg_url)}" style="background:var(--accent)" data-track="telegram_click">Telegramチャンネルに参加する</a></div>')
        return "\n".join(parts)

    def _section_footer(self) -> str:
        now = datetime.now()
        return f"""<div class="footer">
<p>今後、LINE / Telegram での速報配信も予定しています。</p>
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
