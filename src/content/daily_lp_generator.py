"""日次LP自動生成エンジン (Phase 10.5)。

buyback_premium_check 完了後に呼ばれ、
exports/lp/daily/index.html を生成する。
1ページ完結型：初心者/上級者候補・急変情報・利益ランキング・note導線。
"""

import html as html_mod
import logging
import shutil
from datetime import datetime
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


def _esc(text: str) -> str:
    """HTML escape helper."""
    return html_mod.escape(str(text)) if text else ""


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

        # データ取得
        beginner_deals = self.repo.list_beginner_deals(user_level="beginner", min_profit=3000, limit=10)
        advanced_snaps = self.repo.list_premium_candidates_with_snapshots(limit=10, user_level="advanced")
        buyback_alerts = self.repo.list_buyback_alerts(limit=10)
        all_deals = self.repo.list_beginner_deals(min_profit=0, limit=20)

        # HTML生成
        page_html = self._render_page(
            date_str=date_str,
            time_str=time_str,
            beginner_deals=beginner_deals,
            advanced_snaps=advanced_snaps,
            buyback_alerts=buyback_alerts,
            all_deals=all_deals,
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
        md_path = out_dir / "latest.md"

        index_path.write_text(page_html, encoding="utf-8")
        dated_path.write_text(page_html, encoding="utf-8")

        # デフォルト(variant無指定)の場合のみindex.html + latest.md上書き
        if not variant:
            (out_dir / "index.html").write_text(page_html, encoding="utf-8")
            md_content = self._render_markdown(date_str, time_str, beginner_deals, advanced_snaps, buyback_alerts)
            md_path.write_text(md_content, encoding="utf-8")

        # 元に戻す
        self.settings["headline_variant"] = orig_variant

        return {
            "index_path": str(index_path),
            "dated_path": str(dated_path),
            "md_path": str(md_path),
            "variant": variant or orig_variant,
            "date": date_str,
            "time": time_str,
            "beginner_count": len(beginner_deals),
            "advanced_count": len(advanced_snaps),
            "alerts_count": len(buyback_alerts),
            "char_count": len(page_html),
            "forbidden_found": forbidden,
        }

    # ===== HTML Rendering =====

    def _render_page(self, date_str, time_str, beginner_deals, advanced_snaps, buyback_alerts, all_deals) -> str:
        site_title = _esc(self.settings.get("site_title", "プレ値速報"))
        ga_id = self.settings.get("analytics", {}).get("google_analytics_id", "")
        meta_pixel = self.settings.get("analytics", {}).get("meta_pixel_id", "")

        x_pixel = self.settings.get("analytics", {}).get("x_pixel_id", "")

        analytics_head = ""
        if ga_id:
            analytics_head += f'<script async src="https://www.googletagmanager.com/gtag/js?id={_esc(ga_id)}"></script>\n'
            analytics_head += f'<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}gtag("js",new Date());gtag("config","{_esc(ga_id)}");</script>\n'
        if meta_pixel:
            analytics_head += (
                f'<script>!function(f,b,e,v,n,t,s){{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?'
                f'n.callMethod.apply(n,arguments):n.queue.push(arguments)}};if(!f._fbq)f._fbq=n;'
                f'n.push=n;n.loaded=!0;n.version="2.0";n.queue=[];t=b.createElement(e);t.async=!0;'
                f't.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}}(window,'
                f'document,"script","https://connect.facebook.net/en_US/fbevents.js");'
                f'fbq("init","{_esc(meta_pixel)}");fbq("track","PageView");</script>\n'
            )
        if x_pixel:
            analytics_head += f'<!-- X Pixel {_esc(x_pixel)} -->\n'

        # カテゴリ別分類
        iphone_deals = [d for d in beginner_deals if d.category == "iphone"]
        mac_ipad_deals = [d for d in beginner_deals if d.category in ("mac", "ipad")]
        game_deals = [d for d in beginner_deals if d.category == "game_console"]
        camera_snaps = [s for s in advanced_snaps if s.category == "camera"]

        sections = [
            self._section_hero(date_str, time_str),
            self._section_beginner(beginner_deals),
            self._section_category("📱 今日のiPhone案件", iphone_deals, max_items=3),
            self._section_category("💻 今日のMac / iPad案件", mac_ipad_deals, max_items=3),
            self._section_category("🎮 今日のゲーム機案件", game_deals, max_items=3),
            self._section_advanced(advanced_snaps),
            self._section_category_advanced("📷 今日の上級者向けカメラ案件", camera_snaps, max_items=3),
            self._section_alerts(buyback_alerts),
            self._section_ranking(all_deals),
            self._section_caution(),
            self._section_cta(),
            self._section_footer(),
        ]

        body = "\n".join(sections)

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title}</title>
{analytics_head}
<style>
:root {{
  --bg: #0f1117; --card: #1a1d27; --border: #2a2d37;
  --text: #e4e4e7; --muted: #9ca3af; --accent: #3b82f6;
  --green: #22c55e; --yellow: #eab308; --orange: #f97316; --red: #ef4444;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; background:var(--bg); color:var(--text); line-height:1.7; }}
.container {{ max-width:800px; margin:0 auto; padding:20px 16px; }}
h1 {{ font-size:1.6rem; margin-bottom:8px; }}
h2 {{ font-size:1.25rem; margin:32px 0 16px; padding-bottom:8px; border-bottom:1px solid var(--border); }}
h3 {{ font-size:1.05rem; margin:16px 0 8px; }}
.hero {{ text-align:center; padding:40px 0 24px; }}
.hero .update {{ color:var(--muted); font-size:0.85rem; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; margin:12px 0; }}
.badge {{ display:inline-block; padding:2px 10px; border-radius:99px; font-size:0.75rem; font-weight:600; }}
.badge-easy {{ background:#22c55e22; color:var(--green); }}
.badge-watch {{ background:#eab30822; color:var(--yellow); }}
.badge-adv {{ background:#f9731622; color:var(--orange); }}
.badge-exp {{ background:#ef444422; color:var(--red); }}
.badge-surge {{ background:#22c55e22; color:var(--green); }}
.badge-drop {{ background:#ef444422; color:var(--red); }}
.price-row {{ display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border); }}
.price-row:last-child {{ border:none; }}
.price-label {{ color:var(--muted); }}
.price-value {{ font-weight:600; }}
.profit {{ color:var(--green); font-size:1.2rem; font-weight:700; }}
.links {{ margin-top:12px; }}
.links a {{ color:var(--accent); text-decoration:none; font-size:0.85rem; margin-right:16px; }}
.links a:hover {{ text-decoration:underline; }}
.cta {{ text-align:center; padding:32px 0; }}
.cta a {{ display:inline-block; background:var(--accent); color:#fff; padding:14px 40px; border-radius:8px; text-decoration:none; font-weight:600; font-size:1rem; }}
.caution {{ background:#1c1c22; border-left:4px solid var(--yellow); padding:16px 20px; margin:24px 0; border-radius:0 8px 8px 0; font-size:0.9rem; color:var(--muted); }}
.footer {{ text-align:center; color:var(--muted); font-size:0.8rem; padding:40px 0 20px; }}
table {{ width:100%; border-collapse:collapse; margin:8px 0; }}
th, td {{ padding:8px 12px; text-align:left; border-bottom:1px solid var(--border); font-size:0.9rem; }}
th {{ color:var(--muted); font-weight:500; }}
</style>
</head>
<body>
<div class="container">
{body}
</div>
<script>
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
</body>
</html>"""

    def _section_hero(self, date_str, time_str) -> str:
        # A/Bテスト対応ヘッドライン
        variant_key = self.settings.get("headline_variant", "A")
        variants = self.settings.get("variants", {})
        variant = variants.get(variant_key, {})
        headline = _esc(variant.get("headline", self.settings.get("site_title", "プレ値速報")))

        return f"""<div class="hero">
<h1>{headline}</h1>
<p class="update">{_esc(date_str)} {_esc(time_str)} 更新</p>
<p style="color:var(--muted);font-size:0.9rem;margin-top:8px;">公式価格と買取価格の差額を毎日監視・更新しています</p>
</div>"""

    def _section_beginner(self, deals) -> str:
        if not deals:
            return '<h2>🟢 初心者向け・低難度プレ値候補</h2><p style="color:var(--muted)">現在、条件を満たす案件はありません。</p>'

        cards = []
        for d in deals:
            badge = "badge-easy" if d.user_level == "beginner_easy" else "badge-watch"
            label = "低難度" if d.user_level == "beginner_easy" else "要確認"
            pid = _esc(d.product_id)
            shop = _esc(d.best_buyback_shop)
            links = ""
            if d.official_url:
                links += f'<a href="{_esc(d.official_url)}" target="_blank" rel="noopener" data-track="product_click" data-product-id="{pid}">公式購入ページ →</a> '
            if d.best_buyback_url:
                links += f'<a href="{_esc(d.best_buyback_url)}" target="_blank" rel="noopener" data-track="product_click" data-product-id="{pid}" data-shop="{shop}">買取ページ →</a>'

            cards.append(f"""<div class="card">
<h3>{_esc(d.product_name)} <span class="badge {badge}">{label}</span></h3>
<div class="price-row"><span class="price-label">公式価格</span><span class="price-value">{_esc(fmt_price(d.official_price_jpy))}</span></div>
<div class="price-row"><span class="price-label">買取価格（{_esc(d.best_buyback_shop)}）</span><span class="price-value">{_esc(fmt_price(d.best_buyback_price))}</span></div>
<div class="price-row"><span class="price-label">推定コスト</span><span class="price-value">-{_esc(fmt_price(d.estimated_costs_jpy))}</span></div>
<div class="price-row"><span class="price-label">実質利益</span><span class="profit">{_esc(fmt_profit(d.net_profit_jpy))}</span></div>
<div class="price-row"><span class="price-label">利益率</span><span class="price-value">{_esc(fmt_rate(d.net_profit_rate))}</span></div>
<div class="price-row"><span class="price-label">条件</span><span class="price-value">{_esc(d.buyback_condition or '新品未開封')}</span></div>
<div class="links">{links}</div>
</div>""")

        return f'<h2>🟢 初心者向け・低難度プレ値候補（{len(deals)}件）</h2>\n' + "\n".join(cards)

    def _section_advanced(self, snaps) -> str:
        if not snaps:
            return '<h2>🟠 上級者向け・高利益プレ値候補</h2><p style="color:var(--muted)">現在、条件を満たす候補はありません。</p>'

        rows = []
        for s in snaps:
            method = {"lottery": "抽選", "soldout": "SOLD OUT", "discontinued": "終了"}.get(s.sale_method, s.sale_method)
            rows.append(
                f"<tr><td>{_esc(s.product_name)}</td><td>{_esc(fmt_price(s.official_price_jpy))}</td>"
                f"<td>{_esc(fmt_price(s.domestic_used_price_jpy))}</td>"
                f"<td>{_esc(fmt_profit(s.premium_gap_jpy))}</td>"
                f"<td>{_esc(method)}</td><td>{s.difficulty_score:.2f}</td></tr>"
            )

        return f"""<h2>🟠 上級者向け・高利益プレ値候補（{len(snaps)}件）</h2>
<div class="card">
<table>
<tr><th>商品</th><th>定価</th><th>中古</th><th>価格差</th><th>方式</th><th>難易度</th></tr>
{"".join(rows)}
</table>
</div>"""

    def _section_alerts(self, alerts) -> str:
        if not alerts:
            return '<h2>📊 買取価格 急騰・急落</h2><p style="color:var(--muted)">直近の急変動はありません（閾値: ±¥5,000）</p>'

        items = []
        for a in alerts:
            badge = "badge-surge" if a["alert_type"] == "buyback_surge" else "badge-drop"
            icon = "📈" if a["alert_type"] == "buyback_surge" else "📉"
            label = "急騰" if a["alert_type"] == "buyback_surge" else "急落"
            items.append(
                f'<div class="card" style="padding:12px 20px;">{icon} '
                f'<strong>{_esc(a["product_name"])}</strong> @ {_esc(a["shop_name"])} '
                f'<span class="badge {badge}">{label} {a["price_change"]:+,}円</span> '
                f'（¥{a["previous_price"]:,} → ¥{a["current_price"]:,}）</div>'
            )
        return f'<h2>📊 買取価格 急騰・急落</h2>\n' + "\n".join(items)

    def _section_category(self, title: str, deals: list, max_items: int = 3) -> str:
        """カテゴリ別初心者向けセクション（上位N件）。"""
        if not deals:
            return ""
        items = deals[:max_items]
        rows = []
        for d in items:
            rows.append(
                f"<tr><td>{_esc(d.product_name)}</td>"
                f"<td>{_esc(fmt_price(d.official_price_jpy))}</td>"
                f"<td>{_esc(fmt_price(d.best_buyback_price))}</td>"
                f"<td style='color:var(--green)'>{_esc(fmt_profit(d.net_profit_jpy))}</td>"
                f"<td>{_esc(d.best_buyback_shop)}</td></tr>"
            )
        return f"""<h2>{title}（{len(items)}件）</h2>
<div class="card">
<table><tr><th>商品</th><th>定価</th><th>買取</th><th>実質利益</th><th>買取店</th></tr>
{"".join(rows)}
</table></div>"""

    def _section_category_advanced(self, title: str, snaps: list, max_items: int = 3) -> str:
        """カテゴリ別上級者向けセクション。"""
        if not snaps:
            return ""
        items = snaps[:max_items]
        rows = []
        for s in items:
            method = {"lottery": "抽選", "soldout": "SOLD OUT"}.get(s.sale_method, s.sale_method)
            rows.append(
                f"<tr><td>{_esc(s.product_name)}</td>"
                f"<td>{_esc(fmt_price(s.official_price_jpy))}</td>"
                f"<td>{_esc(fmt_price(s.domestic_used_price_jpy))}</td>"
                f"<td>{_esc(fmt_profit(s.premium_gap_jpy))}</td>"
                f"<td>{_esc(method)}</td></tr>"
            )
        return f"""<h2>{title}（{len(items)}件）</h2>
<div class="card">
<table><tr><th>商品</th><th>定価</th><th>中古</th><th>価格差</th><th>方式</th></tr>
{"".join(rows)}
</table></div>"""

    def _section_ranking(self, all_deals) -> str:
        profitable = [d for d in all_deals if d.net_profit_jpy > 0]
        profitable.sort(key=lambda d: d.net_profit_jpy, reverse=True)
        if not profitable:
            return '<h2>💰 実質利益ランキング</h2><p style="color:var(--muted)">データなし</p>'

        rows = []
        for i, d in enumerate(profitable[:10], 1):
            badge_cls = "badge-easy" if d.user_level == "beginner_easy" else ("badge-watch" if d.user_level == "beginner_watch" else "badge-adv")
            rows.append(
                f"<tr><td>{i}</td><td>{_esc(d.product_name)}</td>"
                f"<td>{_esc(fmt_price(d.official_price_jpy))}</td>"
                f"<td>{_esc(fmt_price(d.best_buyback_price))}</td>"
                f"<td style='color:var(--green);font-weight:600'>{_esc(fmt_profit(d.net_profit_jpy))}</td>"
                f"<td>{_esc(fmt_rate(d.net_profit_rate))}</td>"
                f"<td>{_esc(d.best_buyback_shop)}</td></tr>"
            )
        return f"""<h2>💰 実質利益ランキング</h2>
<div class="card">
<table>
<tr><th>#</th><th>商品</th><th>定価</th><th>買取</th><th>実質利益</th><th>率</th><th>買取店</th></tr>
{"".join(rows)}
</table>
</div>"""

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
                # URLが設定済み → リンクボタン表示
                parts.append(f"""<div class="cta">
<p style="margin-bottom:12px;">詳しい仕入れ条件・買取店比較・全案件一覧はnoteで公開中</p>
<a href="{_esc(note_url)}" data-track="note_click">noteで詳細レポートを読む →</a>
</div>""")
            else:
                # URL未設定 → 「準備中」表示（空リンクは出さない）
                parts.append("""<div class="cta">
<p style="margin-bottom:12px;">詳しい仕入れ条件・買取店比較・全案件一覧はnoteで公開予定</p>
<p style="color:var(--muted);font-size:0.9rem;">詳細レポート準備中です。公開時にこのページでお知らせします。</p>
</div>""")

        if self.settings.get("enable_line_cta"):
            line_url = (self.settings.get("line_url") or "").strip()
            if line_url and line_url != "#":
                parts.append(f'<div class="cta"><a href="{_esc(line_url)}" style="background:var(--green)" data-track="line_click">LINE登録で速報を受け取る</a></div>')

        if self.settings.get("enable_telegram_cta"):
            tg_url = (self.settings.get("telegram_url") or "").strip()
            if tg_url and tg_url != "#":
                parts.append(f'<div class="cta"><a href="{_esc(tg_url)}" style="background:var(--accent)" data-track="telegram_click">Telegramチャンネルに参加する</a></div>')

        if not parts:
            return ""
        return "\n".join(parts)

    def _section_footer(self) -> str:
        now = datetime.now()
        return f"""<div class="footer">
<p>今後、LINE / Telegram での速報配信も予定しています。</p>
<p style="margin-top:8px;">© {now.year} プレ値速報 — 情報は自動取得・分析されたものです</p>
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
            lines.append(f"- **{d.product_name}**: 公式{fmt_price(d.official_price_jpy)} → 買取{fmt_price(d.best_buyback_price)} = 実質{fmt_profit(d.net_profit_jpy)} ({fmt_rate(d.net_profit_rate)})")
        if not beginner_deals:
            lines.append("条件を満たす案件なし")

        lines.extend(["", "## 上級者向け候補", ""])
        for s in advanced_snaps:
            lines.append(f"- **{s.product_name}**: 定価{fmt_price(s.official_price_jpy)} / 中古{fmt_price(s.domestic_used_price_jpy)} / 差{fmt_profit(s.premium_gap_jpy)} / {s.sale_method}")
        if not advanced_snaps:
            lines.append("条件を満たす候補なし")

        lines.extend(["", DISCLAIMER_FULL])
        return "\n".join(lines)
