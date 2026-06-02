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
        self._resale_status: dict = self._load_resale_status()

    def _load_resale_status(self) -> dict:
        """resale_collection_status.json を読み込む。

        eBay等のプラットフォームごとの取得ステータスを LP 表示に使う。
        ファイルが存在しない場合は空dictを返す。
        """
        try:
            import json as _json
            status_path = PROJECT_ROOT / "exports" / "resale_collection_status.json"
            if status_path.exists():
                data = _json.loads(status_path.read_text(encoding="utf-8"))
                self._product_resale_status = data.get("products", {})
                return data
        except Exception:
            pass
        self._product_resale_status = {}
        return {}

    # プラットフォームステータス → 表示ラベルの対応表
    _PENDING_LABEL_MAP: dict = {
        "blocked":          "Cloud IP制限中",
        "blocked_cloud_ip": "Cloud IP制限中",
        "ok_html":          "自動取得済（HTML）",
        "ok_api":           "自動取得済（API）",
        "html_failed":      "HTML取得失敗",
        "no_data":          "該当商品なし",
        "api_key_missing":  "APIキー未設定",
        "not_supported":    "未対応",
        "skipped":          "自動取得外",
        "error":            "取得エラー",
    }

    def _label_from_status(self, status: str) -> str:
        """ステータス文字列 → 表示ラベルに変換する。"""
        return self._PENDING_LABEL_MAP.get(status, "自動取得外")

    def _get_platform_pending_label(self, platform: str, product_id: str = "") -> str:
        """プラットフォーム別の未取得理由ラベルを返す。

        platform: "ebay" / "mercari" / "yahoo" / "amazon" / "rakuten" / "rakuma" / "stockx"
        product_id: 商品別ステータスがあればそちらを優先（省略可）
        """
        # per-product ステータスが存在する場合は優先
        if product_id and hasattr(self, '_product_resale_status'):
            prod_st = self._product_resale_status.get(product_id, {}).get(platform, "")
            if prod_st:
                return self._label_from_status(prod_st)

        p_status_obj = self._resale_status.get("platforms", {}).get(platform, {})
        st = p_status_obj.get("status", "skipped")

        base = self._PENDING_LABEL_MAP.get(st, "自動取得外")

        # eBay は EBAY_APP_ID があれば解決できる旨を追加
        if platform == "ebay" and st in ("blocked", "blocked_cloud_ip"):
            needs_key = p_status_obj.get("needs_ebay_app_id", False)
            if needs_key:
                return "Cloud IP制限中（EBAY_APP_ID推奨）"
            return "Cloud IP制限中"

        return base

    def _get_ebay_pending_label(self) -> str:
        """後方互換ラッパー: _get_platform_pending_label("ebay") を呼ぶ。"""
        return self._get_platform_pending_label("ebay")

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
        beginner_easy  = self.repo.list_beginner_deals(user_level="beginner_easy",  min_profit=0,       limit=15)
        beginner_watch = self.repo.list_beginner_deals(user_level="beginner_watch", min_profit=0,       limit=10)
        advanced_deals = self.repo.list_beginner_deals(user_level="advanced",       min_profit=0,       limit=15)
        # 監視中（赤字）・取得失敗商品（min_profit=-9999999 で全件取得）
        monitoring_deals    = self.repo.list_beginner_deals(user_level="monitoring",    min_profit=-9999999, limit=30)
        fetch_failed_deals  = self.repo.list_beginner_deals(user_level="fetch_failed",  min_profit=-9999999, limit=30)

        # 上級者向けスナップショット
        advanced_snaps = self.repo.list_premium_candidates_with_snapshots(limit=15, user_level="advanced")

        # 上級者向けフォールバック：監視候補（camera + game_console）
        watch_candidates = self.repo.list_watch_candidates(genres=["camera", "game_console"], limit=20)

        # 商品別買取店一覧（複数店舗比較用）- product_id → [buyback_rows]
        buyback_by_product: dict = {}
        _all_products = self.repo.list_products()
        for _p in _all_products:
            _rows = self.repo.list_buyback_prices_by_product(_p.id, limit=10)
            if _rows:
                buyback_by_product[_p.id] = _rows

        # sale_prices (新品/未使用条件) を buyback_by_product に追加（二次流通価格の表示用）
        # resale_market ソースとして buyback_rows に注入することで売却先比較テーブルに反映する
        _RESALE_NEW_CONDS = {'new_unopened', 'new_unopened_simfree', 'new', 'unused'}
        try:
            for _p in _all_products:
                _sp_rows = self.repo.list_sale_prices(product_id=_p.id, active_only=True, limit=20)
                _resale_rows = []
                for _sp in _sp_rows:
                    _sp_cond = (getattr(_sp, 'condition', '') or '').strip()
                    if _sp_cond not in _RESALE_NEW_CONDS:
                        continue
                    if not _sp.sale_price or _sp.sale_price <= 0:
                        continue
                    # dict 形式で buyback_rows に追加（_deal_card の行形式に合わせる）
                    _obs_str = _sp.observed_at.isoformat() if _sp.observed_at else ''
                    _resale_rows.append({
                        'shop_id':       f"resale_{(_sp.shop_id or _sp.shop_name or '').replace(' ', '_')[:20]}",
                        'shop_name':     _sp.shop_name or _sp.shop_id or '二次流通',
                        'buyback_price': _sp.sale_price,
                        'condition':     'new_unopened',
                        'buyback_url':   _sp.url or '',
                        'observed_at':   _obs_str,
                        'data_source':   'resale_market',
                        'link_verified': bool(getattr(_sp, 'link_verified', False)),
                        'confidence':    'high',
                    })
                if _resale_rows:
                    if _p.id not in buyback_by_product:
                        buyback_by_product[_p.id] = []
                    # buyback_rows に追加（価格降順でソート後）
                    buyback_by_product[_p.id] = sorted(
                        buyback_by_product[_p.id] + _resale_rows,
                        key=lambda r: r.get('buyback_price', 0),
                        reverse=True
                    )
        except Exception:
            pass

        # 取得種別統計（ページ上部表示用）
        _all_buyback_rows_flat = [row for rows in buyback_by_product.values() for row in rows]
        collection_stats = {
            "auto":   sum(1 for r in _all_buyback_rows_flat if r.get("data_source") == "auto_scraped"),
            "failed": sum(1 for r in _all_buyback_rows_flat if r.get("data_source") == "fetch_failed"),
            "manual": sum(1 for r in _all_buyback_rows_flat if str(r.get("data_source", "")).startswith("manual")),
        }

        # 急騰・急落
        buyback_alerts = self.repo.list_buyback_alerts(limit=20)

        # ランキング用 + カテゴリ別
        all_deals    = self.repo.list_beginner_deals(min_profit=0, limit=50)

        # ── 中央集約 enrich（中古・二次流通価格を完全除外）──
        # 初心者タブだけでなくランキング・せどりも同じ補完済み deal を参照させ、
        # 「初心者は補完あり / ランキング・せどりは補完なし」の不整合を解消する。
        def _enrich_list(_lst):
            return [self._enrich_deal(_d, buyback_by_product.get(_d.product_id, []))
                    for _d in (_lst or [])]
        all_deals        = _enrich_list(all_deals)
        beginner_easy    = _enrich_list(beginner_easy)
        beginner_watch   = _enrich_list(beginner_watch)
        monitoring_deals = _enrich_list(monitoring_deals)

        # enrich により DB では monitoring（赤字）だったが net>0 に昇格した商品も
        # ランキング・せどりへ反映するため、全リストを product_id で統合する。
        # （初心者タブは昇格 deal を表示するが、ランキング/せどりが DB クエリ由来の
        #   別リストを見ているため伝播せず空になる不整合を解消）
        _union = {}
        for _src in (all_deals, beginner_easy, beginner_watch, monitoring_deals):
            for _d in (_src or []):
                _pid = getattr(_d, 'product_id', None)
                if _pid is None:
                    continue
                _ex = _union.get(_pid)
                if _ex is None or (getattr(_d, 'net_profit_jpy', 0) or 0) > (getattr(_ex, 'net_profit_jpy', 0) or 0):
                    _union[_pid] = _d
        all_deals = list(_union.values())

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

        # 商品別市場価格（国内中古＋海外相場）— Pro向けカード用
        market_prices_by_product: dict = {}
        try:
            for _p in _all_products:
                _mrows = self.repo.list_price_history_by_product(
                    _p.id, price_types=["used", "overseas", "market", "flea_market"], limit=20
                )
                if _mrows:
                    market_prices_by_product[_p.id] = _mrows
        except Exception:
            market_prices_by_product = {}

        # Proカード fallback: watch_candidates=0件でも price_history データがある商品を表示
        if not watch_candidates and market_prices_by_product:
            _prod_meta = {_p.id: _p for _p in _all_products}
            _fallback_candidates = []
            for _prod_id, _rows in market_prices_by_product.items():
                _p = _prod_meta.get(_prod_id)
                if not _p:
                    continue
                _genre = getattr(_p, "genre", "")
                # Pro向け対象ジャンルのみ（camera / game_console）
                if _genre not in ("camera", "game_console"):
                    continue
                _has_used = any(r.get("price_type") in ("used", "market", "flea_market") for r in _rows)
                _has_ovs  = any(r.get("price_type") == "overseas" for r in _rows)
                if not (_has_used or _has_ovs):
                    continue
                _fallback_candidates.append({
                    "product_id":    _prod_id,
                    "product_name":  _p.name,
                    "genre":         _genre,
                    "official_price": getattr(_p, "official_price", None),
                    "buyback_price": None,
                    "shop_name":     None,
                    "flags":         [],
                    "sale_method":   "unknown",
                })
            if _fallback_candidates:
                watch_candidates = _fallback_candidates

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
            market_prices_by_product=market_prices_by_product,
            collection_stats=collection_stats,
            monitoring_deals=monitoring_deals,
            fetch_failed_deals=fetch_failed_deals,
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
                     buyback_by_product: dict = None, sedori_routes: list = None,
                     market_prices_by_product: dict = None,
                     collection_stats: dict = None,
                     monitoring_deals: list = None,
                     fetch_failed_deals: list = None) -> str:

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
            lottery_events = list(self.repo.list_lottery_events(status="active", limit=20))
        except Exception:
            lottery_events = []

        # CSV から auto_scraped イベントを追加（product_code で重複排除、CSV が優先）
        _csv_events = self._load_csv_lottery_events()
        if _csv_events:
            _db_codes = {ev.get("product_code", "") for ev in lottery_events if ev.get("product_code")}
            _db_names = {ev.get("product_name", "") for ev in lottery_events}
            for _csv_ev in _csv_events:
                _code = _csv_ev.get("product_code", "")
                _name = _csv_ev.get("product_name", "")
                # product_code または product_name で重複チェック
                if _code and _code in _db_codes:
                    continue
                if _name and _name in _db_names:
                    continue
                lottery_events.append(_csv_ev)

        # ── 件数の整合：全表示箇所で同一の定義を使う ──────────────────────────
        # カメラも初心者タブに表示する（overseas price で利益確認可能）
        _beginner_easy_disp  = list(beginner_easy)
        _beginner_watch_disp = list(beginner_watch)
        _monitoring_disp    = list(monitoring_deals or [])
        _fetch_failed_disp  = list(fetch_failed_deals or [])
        _beginner_disp_count = (len(_beginner_easy_disp) + len(_beginner_watch_disp)
                                + len(_monitoring_disp) + len(_fetch_failed_disp))

        # 抽選情報カウント: Section A（受付中 + 日付あり + reference_only でない）のみ
        # ・reference_only=True（X100VI/PS5/Switch2 等）は除外
        # ・entry_end_at なし（旧DB エントリ等）は除外
        def _count_as_active(raw_it) -> bool:
            it = raw_it if isinstance(raw_it, dict) else dict(raw_it)
            if it.get("reference_only", False):
                return False
            if self._lottery_status_from_dates(it) != "active":
                return False
            v = it.get("entry_end_at") or it.get("entry_end") or ""
            return bool(str(v).strip())

        _all_lottery_for_count = list(lottery_events) + list(self._LOTTERY_REFERENCE_ITEMS)
        _lottery_active_count = sum(1 for it in _all_lottery_for_count if _count_as_active(it))

        # セクション生成
        hero_html    = self._section_hero(date_str, time_str, latest_buyback_at, lp_generated_at,
                                           all_deals=all_deals, iphone_deals=iphone_deals,
                                           camera_deals=camera_deals or [], game_deals=game_deals,
                                           beginner_display_count=_beginner_disp_count)
        stale_html   = self._section_stale_warning(latest_buyback_at, latest_deals_at, lp_generated_at)
        category_nav_html = self._section_category_nav(lottery_count=_lottery_active_count)

        # タブバッジ計算（_section_tab_nav 用）
        _adv_total_for_nav = len(advanced_deals) + len(advanced_snaps) + len(watch_candidates)
        _surge_count_for_nav = len([a for a in buyback_alerts if a.get('alert_type') in ('buyback_surge', 'buyback_drop')])
        tab_nav_html = self._section_tab_nav(
            beginner_count=_beginner_disp_count,
            adv_total=_adv_total_for_nav,
            surge_count=_surge_count_for_nav,
            lottery_count=_lottery_active_count,
        )

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
            market_prices_by_product=market_prices_by_product or {},
            beginner_display_count=_beginner_disp_count,
            lottery_display_count=_lottery_active_count,
            latest_buyback_at=latest_buyback_at,
            monitoring_deals=monitoring_deals or [],
            fetch_failed_deals=fetch_failed_deals or [],
        )
        caution_html = self._section_caution()
        cta_html     = self._section_cta()
        footer_html  = self._section_footer()
        # Task 6: アラートポップアップHTML を生成（右下固定表示）
        alert_popup_html = self._section_alert_popup(buyback_alerts)

        # collector report: 取得失敗警告バナー（一定数以上の場合のみ表示）
        _collector_warn_html = self._collector_warn_bar_html()

        # topbar用の日時文字列（_render_page スコープで利用）
        _buyback_str_top = _jst_str(latest_buyback_at) if latest_buyback_at else "—"
        _lp_str_top = lp_generated_at.strftime("%m/%d %H:%M") if lp_generated_at else "—"

        # 取得統計バー HTML（_topbar_date_html より先に定義する必要あり）
        _cs = collection_stats or {}
        _cs_auto   = _cs.get("auto",   0)
        _cs_failed = _cs.get("failed", 0)
        _cs_manual = _cs.get("manual", 0)
        _cs_manual_html = f'<span class="cs-manual">手動 {_cs_manual}件</span>' if _cs_manual > 0 else ''
        _collection_stats_html = (
            f'<span class="collection-stats-bar" title="買取価格の取得種別内訳">'
            f'<span class="cs-ok">自動取得 {_cs_auto}件</span>'
            f'<span style="color:var(--ink4)">／</span>'
            f'<span class="cs-fail">取得失敗 {_cs_failed}件</span>'
            + (f'<span style="color:var(--ink4)">／</span>{_cs_manual_html}' if _cs_manual_html else '')
            + f'</span>'
        )

        # topbar-date: 24h以内のデータのみ表示（古い日付をトップに出さない）
        _buyback_age_hours = 0.0
        if latest_buyback_at:
            try:
                _ba = latest_buyback_at if latest_buyback_at.tzinfo else latest_buyback_at.replace(tzinfo=JST)
                _buyback_age_hours = (datetime.now(tz=JST) - _ba.astimezone(JST)).total_seconds() / 3600
            except Exception:
                _buyback_age_hours = 999.0
        _topbar_date_html = (
            f'<div class="topbar-date" data-buyback-updated title="DBに記録された最新の買取価格データ取得日時">'
            f'最終更新: {_esc(_buyback_str_top)}{_collection_stats_html}</div>'
            if _buyback_age_hours <= 24 else ''
        )
        # アナウンスバー用
        # announce bar: 実際に初心者タブに表示するカード数（カメラ除外後）
        _beginner_count_top = _beginner_disp_count
        _max_profit_top = max((d.net_profit_jpy or 0) for d in _beginner_easy_disp) if _beginner_easy_disp else 0
        _max_profit_str_top = f'+¥{_max_profit_top:,}' if _max_profit_top > 0 else '—'
        # announce bar フォールバック: 利益0件でも「0件」を大きく出さない
        if _beginner_count_top > 0:
            _announce_bar_inner = (
                f'&#127919; 最終確認 {_beginner_count_top} 件の初心者向け案件（手動確認データ）'
                f'&mdash; 最大利益 {html_mod.escape(_max_profit_str_top)}'
            )
        else:
            _announce_bar_inner = (
                '&#127919; 参考データを掲載中 &mdash; '
                '本日の自動取得 0件 / 前回・手動データで表示中（公式サイトで必ずご確認ください）'
            )

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
   COLLECTOR WARN BAR（取得失敗件数が多い場合のみ表示）
   ============================================================ */
.collector-warn-bar {{
  background: #3b1f08;
  border-bottom: 1px solid #7c4a1a;
  color: #fbbf24;
  text-align: center;
  padding: 6px 16px;
  font-size: 0.78rem;
  font-weight: 600;
}}
.collector-warn-bar a {{
  color: #fcd34d;
  text-decoration: underline;
  margin-left: 4px;
}}
.collector-warn-bar a:hover {{ color: #fff; }}
.collector-warn-soft {{
  background: rgba(245, 158, 11, 0.7);
}}
.collector-warn-info {{
  background: rgba(99, 102, 241, 0.15);
  color: var(--ink2, #444);
  border-left: 3px solid rgba(99, 102, 241, 0.4);
}}
.collector-warn-info a {{
  color: var(--accent, #7C5CFC);
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
/* ── モバイルドロワー ── */
.mobile-drawer-overlay {{
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.45);
  z-index: 1000;
}}
.mobile-drawer-overlay.open {{ display: block; }}
.mobile-drawer {{
  position: fixed;
  top: 0; left: 0; bottom: 0;
  width: 260px;
  background: #fff;
  z-index: 1001;
  transform: translateX(-100%);
  transition: transform 0.25s ease;
  overflow-y: auto;
  box-shadow: 4px 0 16px rgba(0,0,0,0.15);
  padding: 0;
}}
.mobile-drawer.open {{ transform: translateX(0); }}
.mobile-drawer-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid #e5e7eb;
  font-weight: 700;
  font-size: 0.9rem;
  color: #374151;
}}
.mobile-drawer-close {{
  background: none;
  border: none;
  font-size: 1.4rem;
  cursor: pointer;
  color: #6b7280;
  padding: 4px 8px;
}}
.mobile-drawer-nav {{
  display: flex;
  flex-direction: column;
  padding: 8px 0;
}}
.mobile-drawer-nav-btn {{
  background: none;
  border: none;
  text-align: left;
  padding: 14px 20px;
  font-size: 0.9rem;
  cursor: pointer;
  color: #374151;
  border-bottom: 1px solid #f3f4f6;
  display: flex;
  align-items: center;
  gap: 10px;
  transition: background 0.15s;
}}
.mobile-drawer-nav-btn:hover {{ background: #f9fafb; }}
.mobile-drawer-nav-btn.active {{
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 600;
}}
.mobile-hamburger {{
  display: none;
  background: none;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  color: #374151;
  font-size: 1.2rem;
  align-items: center;
  justify-content: center;
}}
@media (max-width: 640px) {{
  .mobile-hamburger {{ display: flex; }}
  .tab-nav {{ display: none !important; }}
  .tab-wrap {{ position: relative; }}
  .mobile-tab-topbar {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    background: #fff;
    border-bottom: 2px solid #e5e7eb;
    position: sticky;
    top: 0;
    z-index: 100;
  }}
  .mobile-tab-current-label {{
    font-size: 0.85rem;
    font-weight: 600;
    color: #374151;
    flex: 1;
  }}
}}
@media (min-width: 641px) {{
  .mobile-hamburger {{ display: none !important; }}
  .mobile-tab-topbar {{ display: none !important; }}
  .mobile-drawer {{ display: none !important; }}
  .mobile-drawer-overlay {{ display: none !important; }}
}}
/* ジャンルトグルボタン */
.tab-btn.genre-toggle-btn.active {{
  background: #F0F4FF; color: #4338CA;
}}
/* ジャンルドロップダウン */
.genre-dropdown {{
  display: none;
  border-top: 1px solid var(--card-border);
  padding: 10px 0 8px;
  background: rgba(250,251,255,0.98);
}}
.genre-panel-row {{
  display: flex; gap: 6px; overflow-x: auto;
  padding: 0 0 8px; scrollbar-width: none;
}}
.genre-panel-row::-webkit-scrollbar {{ display: none; }}
.genre-btn {{
  flex-shrink: 0; padding: 6px 14px; border-radius: 99px;
  font-size: 0.8rem; font-weight: 700;
  background: var(--surface-2); color: var(--text-2);
  border: 1px solid #E5E7EB; cursor: pointer;
  transition: all 0.15s; white-space: nowrap;
}}
.genre-btn:hover {{ background: #EEF2FF; color: #4338CA; }}
.genre-btn.active {{ background: #4338CA; color: #fff; border-color: #4338CA; }}
.maker-group-wrap {{
  padding: 2px 0 0; overflow-x: auto; scrollbar-width: none;
  min-height: 28px;
}}
.maker-group-wrap::-webkit-scrollbar {{ display: none; }}
.maker-group {{
  display: none; flex-wrap: wrap; gap: 5px; padding: 4px 0;
}}
.maker-group.active {{ display: flex; }}
.maker-chip {{
  display: inline-flex; align-items: center;
  padding: 4px 12px; border-radius: 99px;
  font-size: 0.76rem; font-weight: 700;
  background: #EEF2FF; color: #4338CA;
  border: 1px solid #C7D2FE; cursor: pointer;
  white-space: nowrap; text-decoration: none;
  transition: all 0.15s;
}}
.maker-chip:hover {{ background: #E0E7FF; border-color: #A5B4FC; }}
@media (max-width: 640px) {{
  .genre-btn {{ font-size: 0.74rem; padding: 5px 11px; }}
  .maker-chip {{ font-size: 0.72rem; padding: 3px 10px; }}
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

/* 最高買取店を大きく表示するブロック（初心者カード） */
.best-buyback-block {{
  margin: 10px 0 4px;
  padding: 12px 16px;
  background: linear-gradient(90deg, #F0FDF8 0%, #F7FFFE 100%);
  border: 1px solid #B8F0DC;
  border-left: 4px solid #00C896;
  border-radius: 12px;
}}
.best-buyback-block .bb-shop-lbl {{
  font-size: 0.72rem; font-weight: 800; letter-spacing: 0.04em;
  color: var(--ink3); margin-bottom: 2px;
}}
.best-buyback-block .bb-shop-val {{
  font-size: 1.35rem; font-weight: 800; color: var(--ink1);
  line-height: 1.25;
}}
.best-buyback-block .bb-shop-val .bb-shop-price {{
  font-size: 1.5rem; font-weight: 900; color: #00A37A;
  font-variant-numeric: tabular-nums; margin-left: 6px;
}}

/* 最高買取店ヒーローブロック（Task 5: カード内で最も目立たせる） */
.best-buyback-hero {{
  margin: 12px 0 6px;
  padding: 14px 18px;
  background: linear-gradient(90deg, #E7FBF2 0%, #F3FFFB 100%);
  border: 1px solid #9DEBC9;
  border-left: 5px solid #00C896;
  border-radius: 14px;
  box-shadow: 0 2px 10px rgba(0,200,150,0.10);
}}
.best-buyback-hero .bb-shop-val {{
  font-size: 1.25rem; font-weight: 800; color: var(--ink1); line-height: 1.2;
}}
.best-buyback-hero .bb-shop-price {{
  display: block; margin-top: 2px;
  font-size: 1.85rem; font-weight: 900; color: #00A37A;
  font-variant-numeric: tabular-nums; letter-spacing: -0.01em;
}}
.best-buyback-hero .bb-compared-note {{
  margin-top: 4px; font-size: 0.7rem; color: var(--ink3); font-weight: 600;
}}
.best-buyback-hero .bb-runnerup-note {{
  margin-top: 6px; font-size: 0.86rem; color: var(--ink2); font-weight: 700;
}}
.best-buyback-hero .bb-runnerup-note strong {{ color: #00A37A; }}
.best-buyback-hero .bb-runnerup-note .bb-compared-sub {{
  margin-left: 6px; font-size: 0.68rem; color: var(--ink3); font-weight: 500;
}}

/* compact card 用の詳細折りたたみ（買取店比較を見る） */
.card-detail-fold {{
  margin-top: 10px;
  border-top: 1px solid #EEF0F6;
}}
.card-detail-fold > summary.card-detail-summary {{
  cursor: pointer; list-style: none;
  padding: 9px 12px; margin-top: 2px;
  font-size: 0.8rem; font-weight: 700;
  color: #5B6BD6; text-align: center;
  background: #F7F8FC; border-radius: 8px;
  user-select: none;
}}
.card-detail-fold > summary.card-detail-summary::-webkit-details-marker {{ display: none; }}
.card-detail-fold > summary.card-detail-summary::after {{ content: " ▾"; }}
.card-detail-fold[open] > summary.card-detail-summary::after {{ content: " ▴"; }}
.card-detail-fold > summary.card-detail-summary:hover {{ color: #3B4BB6; }}
.card-detail-fold .card-detail-body {{ padding-top: 8px; }}

/* 初心者の買取店比較：スマホで読みやすい1店舗1カード形式（余白広め） */
.shop-card {{
  display: flex !important; flex-direction: column; gap: 8px;
  padding: 16px 16px; margin: 12px 0;
  border: 1px solid #E6E9F2; border-radius: 14px; background: #fff;
  box-shadow: 0 2px 8px rgba(20,30,80,0.06);
}}
.shop-card .shop-card-top {{ display: flex; align-items: center; gap: 10px; }}
.shop-card .shop-rank {{
  flex: 0 0 auto; min-width: auto; width: auto;
  display: inline-flex; align-items: center; justify-content: center;
  padding: 2px 11px; border-radius: 999px;
  font-size: 0.74rem; font-weight: 800;
  background: #EEF1FA; color: #4A57B5;
}}
.shop-card .shop-rank.gold {{ background: #FFF4D6; color: #B8860B; }}
.shop-card .shop-rank.silver {{ background: #EEF0F3; color: #6B7280; }}
.shop-card .shop-name-col {{
  flex: 1 1 auto; min-width: 0;
  font-size: 1.0rem; font-weight: 700; color: var(--ink1);
  text-align: left; white-space: normal; line-height: 1.3;
}}
.shop-card .shop-card-mid {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
.shop-card .shop-price-col {{
  font-size: 1.32rem; font-weight: 900; color: var(--ink1);
  font-variant-numeric: tabular-nums; text-align: left; min-width: 0; letter-spacing: -0.01em;
}}
.shop-card .shop-diff-col {{
  font-size: 0.9rem; font-weight: 800; color: #00A37A; text-align: left; min-width: 0;
}}
/* マイナス差益は小さく控えめに表示 */
.shop-card .shop-diff-col.neg {{ color: #C2453A; font-size: 0.74rem; font-weight: 600; opacity: 0.85; }}
.shop-card .shop-link-col {{ margin-top: 4px; text-align: left; min-width: 0; }}
/* 確認リンクをボタン化（タップしやすい） */
.shop-card .shop-link-col .shop-check-btn {{
  display: block; width: 100%; box-sizing: border-box;
  padding: 11px 16px; border-radius: 10px;
  font-size: 0.92rem; font-weight: 800; text-align: center;
  background: #3B4BB6; color: #fff; text-decoration: none;
  box-shadow: 0 2px 6px rgba(59,75,182,0.22);
}}
.shop-card .shop-link-col .shop-check-btn.best {{ background: #00A37A; box-shadow: 0 2px 6px rgba(0,163,122,0.25); }}
.shop-card .shop-link-col .shop-check-btn:hover {{ filter: brightness(1.05); }}
.shop-card.shop-row-failed {{ opacity: 0.92; background: #FAFAFB; }}
.shop-card.shop-row-failed .shop-price-col {{ font-size: 0.92rem; font-weight: 600; color: var(--ink3); }}
.shop-card.shop-row-failed .shop-link-col .shop-check-btn {{
  background: #EEF0F5; color: #5B6677; box-shadow: none;
}}

/* compact card 全体（縦の詰まりを緩和） */
.deal-card-compact .card-body {{ padding-top: 10px; }}
.deal-card-compact .card-actions {{ margin-top: 0; }}

/* 監視中カード（超コンパクト：Task 3） */
.monitoring-compact-row {{
  display: flex; flex-wrap: wrap; gap: 10px 18px;
  padding: 8px 4px 2px;
}}
.monitoring-compact-row .mon-cell {{ display: flex; flex-direction: column; gap: 1px; }}
.monitoring-compact-row .mon-lbl {{ font-size: 0.68rem; color: var(--ink3); font-weight: 600; }}
.monitoring-compact-row .mon-val {{ font-size: 0.95rem; font-weight: 800; color: var(--ink1); font-variant-numeric: tabular-nums; }}
.monitoring-compact-row .mon-val-muted {{ color: var(--ink3); }}
.monitoring-compact-row .mon-status-badge {{
  display: inline-block; font-size: 0.75rem; font-weight: 700;
  color: #CC2200; background: #FFF0F0; border: 1px solid #FFC9C9;
  border-radius: 999px; padding: 1px 10px;
}}

/* 監視中グローバル折りたたみセクション（Task 4） */
.monitoring-global-section {{ margin: 28px 0 8px; }}
.monitoring-global-section > summary.monitoring-global-summary {{
  cursor: pointer; list-style: none;
  padding: 12px 16px;
  font-size: 0.92rem; font-weight: 800;
  color: #99502A; background: #FFF6EE;
  border: 1px solid #F2D2B6; border-radius: 12px;
  user-select: none;
}}
.monitoring-global-section > summary.monitoring-global-summary::-webkit-details-marker {{ display: none; }}
.monitoring-global-section > summary.monitoring-global-summary::after {{ content: " ▾"; }}
.monitoring-global-section[open] > summary.monitoring-global-summary::after {{ content: " ▴"; }}
.monitoring-global-section .mon-count-badge {{
  display: inline-block; margin-left: 6px;
  font-size: 0.78rem; font-weight: 700; color: #fff; background: #C77B3E;
  border-radius: 999px; padding: 1px 9px;
}}
.monitoring-global-section > .cards-grid {{ margin-top: 14px; }}
.monitoring-genre-groups {{ margin-top: 14px; }}
.monitoring-genre-group {{ margin-bottom: 18px; }}
.monitoring-genre-group .monitoring-genre-head {{
  font-size: 0.86rem; font-weight: 800; color: var(--ink2);
  padding: 4px 2px 8px; border-bottom: 1px solid #EEE3D6; margin-bottom: 10px;
}}
.monitoring-genre-group .mon-genre-count {{
  display: inline-block; margin-left: 6px;
  font-size: 0.72rem; font-weight: 700; color: #99502A;
}}
/* 取得失敗・未掲載店舗の別 details（価格「—」店舗を通常のもっと見るに混ぜない） */
.shop-failed-details > summary.shop-failed-summary {{ color: var(--ink3); }}
.shop-failed-details > summary.shop-failed-summary:hover {{ color: #99502A; }}

/* 4店舗目以降の折りたたみ（details） */
.shop-more-details {{
  border-top: 1px solid #F0F1F7;
}}
.shop-more-details > summary.shop-more-summary {{
  cursor: pointer; list-style: none;
  padding: 10px 14px;
  font-size: 0.78rem; font-weight: 700;
  color: #5B6BD6; text-align: center;
  user-select: none;
}}
.shop-more-details > summary.shop-more-summary::-webkit-details-marker {{ display: none; }}
.shop-more-details > summary.shop-more-summary::after {{ content: " ▾"; }}
.shop-more-details[open] > summary.shop-more-summary::after {{ content: " ▴"; }}
.shop-more-details > summary.shop-more-summary:hover {{ color: #3B4BB6; text-decoration: underline; }}

/* 価格確認行の「要更新」表示（控えめ） */
.confirm-line .confirm-stale {{
  color: #C2701A; font-weight: 700; margin-left: 2px;
}}
/* 7日以上前の参考値（控えめ補足） */
.confirm-line .confirm-stale7 {{
  color: #C2701A; font-weight: 600; font-size: 0.92em;
}}
/* 14日超降格カードの「価格情報が古い（要再確認）」バナー */
.mon-stale14-note {{
  margin: 6px 0 2px; padding: 6px 10px;
  font-size: 0.8rem; font-weight: 800; color: #99502A;
  background: #FFF3E6; border: 1px solid #F0CDA0; border-radius: 8px;
}}

/* 初心者カードの取得方法ラベル（行末の極薄補足 — 店名・価格・差益より目立たせない） */
.shop-source-col-mini {{
  min-width: 0 !important; flex-shrink: 1;
  text-align: right; margin-left: 4px;
}}
.shop-source-col .shop-source-mini,
.shop-source-col-mini .shop-source-mini {{
  font-size: 0.58rem; font-weight: 400;
  color: var(--ink3); opacity: 0.55;
  white-space: nowrap;
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

.shop-name-col {{
  flex: 1; color: var(--ink2); font-weight: 600;
  word-break: keep-all; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
  min-width: 0;
}}

.shop-link-col {{
  min-width: 52px; text-align: right; flex-shrink: 0;
}}

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
.freshness-warn {{
  color: #B45309; font-size: 0.7rem; font-weight: 700;
  background: rgba(180,83,9,0.10); padding: 2px 7px; border-radius: 99px;
  border: 1px solid rgba(180,83,9,0.20);
}}

/* 自動取得鮮度ラベル (緑) */
.freshness-auto {{
  color: #0A7C4F; font-size: 0.7rem; font-weight: 700;
  background: rgba(0,200,150,0.12); padding: 2px 7px; border-radius: 99px;
  border: 1px solid rgba(0,200,150,0.25);
}}

/* 取得種別バッジ */
.badge-auto-scraped {{
  font-size: 0.66rem; font-weight: 700; padding: 2px 6px; border-radius: 99px;
  background: rgba(0,200,150,0.12); color: #0A7C4F;
  border: 1px solid rgba(0,200,150,0.25); white-space: nowrap;
}}
.badge-not-listed {{
  font-size: 0.66rem; font-weight: 700; padding: 2px 6px; border-radius: 99px;
  background: rgba(100,116,139,0.10); color: #475569;
  border: 1px solid rgba(100,116,139,0.28); white-space: nowrap;
}}
.freshness-not-listed {{
  color: #475569; font-size: 0.7rem; font-weight: 700;
  background: rgba(100,116,139,0.10); padding: 2px 7px; border-radius: 99px;
  border: 1px solid rgba(100,116,139,0.25);
}}
.badge-fetch-failed {{
  font-size: 0.66rem; font-weight: 700; padding: 2px 6px; border-radius: 99px;
  background: rgba(255,59,92,0.10); color: #B91C1C;
  border: 1px solid rgba(255,59,92,0.25); white-space: nowrap;
}}
.badge-manual {{
  font-size: 0.66rem; font-weight: 700; padding: 2px 6px; border-radius: 99px;
  background: var(--surface2); color: var(--ink3);
  border: 1px solid var(--card-border); white-space: nowrap;
}}

/* 買取比較テーブル: 取得種別列 */
.shop-source-col {{
  min-width: 60px; text-align: center; flex-shrink: 0;
}}

/* 取得統計バー (ページ上部) */
.collection-stats-bar {{
  font-size: 0.72rem; color: var(--ink3);
  display: inline-flex; gap: 6px; align-items: center; margin-left: 6px;
}}
.cs-ok   {{ color: #0A7C4F; font-weight: 700; }}
.cs-fail {{ color: #B91C1C; font-weight: 700; }}
.cs-manual {{ color: var(--ink3); font-weight: 600; }}

/* 初心者タブ サマリバー */
.beginner-summary-bar {{
  font-size: 0.8rem; color: var(--ink2); padding: 8px 12px;
  background: var(--surface2); border-radius: 8px; margin: 8px 0 16px;
}}
.beginner-summary-bar strong {{ color: var(--ink); }}

/* ジャンル別データなし通知 */
.collector-empty-notice {{
  padding: 16px;
  background: #f8f8f8;
  border-left: 3px solid #ccc;
  border-radius: 4px;
  margin: 8px 0 16px;
  font-size: 0.85rem;
  color: var(--ink3, #666);
}}
.collector-empty-notice a {{
  color: var(--accent, #7C5CFC);
  text-decoration: underline;
}}

/* 監視中カード */
.badge-monitoring {{
  font-size: 0.66rem; font-weight: 700; padding: 2px 6px; border-radius: 99px;
  background: #FFF0F0; color: #CC2200; border: 1px solid #FFBBBB; white-space: nowrap;
}}
.deal-card.stripe-monitoring {{ border-left: 3px solid #CC3300; }}
.deal-card.stripe-monitoring .card-stripe {{ background: linear-gradient(135deg, #CC3300, #FF6644); }}
.monitoring-section {{
  background: #FFF8F8; border: 1px solid #FFDDDD; border-radius: 6px;
  padding: 12px; margin: 8px 0;
}}
.monitoring-label {{ font-weight: 700; color: #CC2200; font-size: 0.9rem; }}
.monitoring-detail {{ color: var(--ink2); font-size: 0.85rem; margin-top: 4px; }}
.monitoring-diff {{ color: #CC2200; font-size: 0.85rem; font-weight: 600; margin-top: 2px; }}

/* 取得失敗カード */
.badge-fetch-failed-card {{
  font-size: 0.66rem; font-weight: 700; padding: 2px 6px; border-radius: 99px;
  background: #F5F5F5; color: #888; border: 1px solid #DDD; white-space: nowrap;
}}
.deal-card.stripe-fetch-failed {{ opacity: 0.8; border-left: 3px solid #CCC; }}
.deal-card.stripe-fetch-failed .card-stripe {{ background: #CCC; }}
.fetch-failed-section {{
  background: #F8F8F8; border: 1px solid #E0E0E0; border-radius: 6px;
  padding: 12px; margin: 8px 0; color: #888; font-size: 0.85rem;
}}
.fetch-failed-timestamp {{ font-size: 0.78rem; color: #AAA; margin-top: 4px; }}

/* 失敗理由バッジ (Task 8) */
.shop-failure-detail {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
.failure-reason-badge {{
  font-size: 0.68rem; padding: 2px 5px; border-radius: 3px;
  font-weight: 600; white-space: nowrap;
}}
.failure-legend {{ font-size: 0.72rem; color: var(--ink3); font-weight: 400; }}
.failure-reason-rate_limit_429     {{ background: #FFF3CD; color: #856404; border: 1px solid #FFE08A; }}
.failure-reason-cloudflare_block   {{ background: #FFE8E8; color: #B91C1C; border: 1px solid #FCA5A5; }}
.failure-reason-site_blocked       {{ background: #FFE8E8; color: #B91C1C; border: 1px solid #FCA5A5; }}
.failure-reason-parsing_failed     {{ background: #E8F0FF; color: #1D4ED8; border: 1px solid #93C5FD; }}
.failure-reason-service_unavailable{{ background: #FFF7E6; color: #B45309; border: 1px solid #FDE68A; }}
.failure-reason-url_not_found      {{ background: #F3E8FF; color: #7C3AED; border: 1px solid #C4B5FD; }}
.failure-reason-empty_result       {{ background: #F0FDF4; color: #15803D; border: 1px solid #86EFAC; }}
.failure-reason-product_not_listed {{ background: #F0FDF4; color: #15803D; border: 1px solid #86EFAC; }}
.failure-reason-ssl_error          {{ background: #FFE8E8; color: #B91C1C; border: 1px solid #FCA5A5; }}
.failure-reason-connection_error   {{ background: #FFE8E8; color: #B91C1C; border: 1px solid #FCA5A5; }}
.failure-reason-empty_html         {{ background: #E8F0FF; color: #1D4ED8; border: 1px solid #93C5FD; }}
.failure-reason-price_not_found    {{ background: #E8F0FF; color: #1D4ED8; border: 1px solid #93C5FD; }}
.failure-reason-requires_js        {{ background: #E8F0FF; color: #1D4ED8; border: 1px solid #93C5FD; }}
.failure-reason-no_url             {{ background: #F0FDF4; color: #15803D; border: 1px solid #86EFAC; }}
.failure-reason-unknown            {{ background: #F3F4F6; color: #6B7280; border: 1px solid #D1D5DB; }}

/* monitoring カード説明文 */
.monitoring-note {{
  font-size: 0.78rem; color: #7A4500; background: #FFF7E6;
  border-left: 3px solid #F59E0B; padding: 5px 9px; border-radius: 0 4px 4px 0;
  margin-top: 6px;
}}

/* fetch-failed カード説明文 */
.fetch-failed-label {{ font-weight: 700; color: #888; margin-bottom: 2px; }}
.fetch-failed-note {{
  font-size: 0.77rem; color: #666; background: #F8F8F8;
  border-left: 3px solid #CCC; padding: 5px 9px; border-radius: 0 4px 4px 0;
  margin-bottom: 6px;
}}

/* 「さらに表示」ボタン (Task 2) */
.ff-more-btn {{
  display: block; width: 100%; margin-top: 4px; padding: 6px 0;
  background: none; border: 1px dashed #CCC; border-radius: 4px;
  font-size: 0.8rem; color: #666; cursor: pointer; text-align: center;
  transition: background 0.15s;
}}
.ff-more-btn:hover {{ background: #F5F5F5; }}
.ff-more-btn.ff-more-open {{ border-color: #AAA; color: #444; }}
.ff-shop-table .shop-table-hd {{ display: flex; justify-content: space-between; align-items: center; }}

/* ジャンル内サブセクション（v7: 第一階層=ジャンル、第二階層=状態）*/
.status-subsection {{ margin: 16px 0 24px; }}
.status-subhead {{
  font-size: 0.8rem; font-weight: 700; letter-spacing: 0.06em;
  padding: 4px 10px; border-radius: 4px; margin-bottom: 10px;
  display: inline-block;
}}
.status-subhead.status-profit   {{ background: #F0FDF8; color: var(--profit-dark); border: 1px solid #B2F0DC; }}
.status-subhead.status-monitoring {{ background: #FFF0F0; color: #CC2200; border: 1px solid #FFBBBB; }}
.status-subhead.status-fetch-failed {{ background: #F5F5F5; color: #888; border: 1px solid #DDD; }}

/* 取得失敗セクション — <details> 折りたたみスタイル */
.fetch-failed-details {{ margin: 16px 0 24px; }}
.fetch-failed-details > .cards-grid {{ margin-top: 10px; }}
.fetch-failed-summary {{
  cursor: pointer; list-style: none; display: flex;
  align-items: center; gap: 8px; user-select: none;
}}
.fetch-failed-summary::-webkit-details-marker {{ display: none; }}
.fetch-failed-summary::before {{
  content: "▶"; font-size: 0.7rem; color: #AAA;
  transition: transform 0.15s;
}}
details[open] > .fetch-failed-summary::before {{ transform: rotate(90deg); }}
.ff-count-badge {{
  font-size: 0.72rem; font-weight: 700; padding: 1px 6px;
  border-radius: 99px; background: #F0F0F0; color: #999; border: 1px solid #DDD;
}}
.ff-expand-hint {{ font-size: 0.72rem; color: #BBB; font-weight: 400; }}

/* ジャンル内利益サマリ */
.genre-status-summary {{
  font-size: 0.75rem; color: var(--ink3); margin: 2px 0 12px;
}}

/* Pro向け価格テーブル */
.pro-price-table {{
  width: 100%; border-collapse: collapse;
  font-size: 0.82rem; margin: 6px 0 4px;
  border-radius: 8px; overflow: hidden;
}}
.pro-price-table thead tr {{
  background: var(--surface-2); color: var(--ink2);
}}
.pro-price-table th, .pro-price-table td {{
  padding: 6px 10px; text-align: left;
  border-bottom: 1px solid var(--border-1);
}}
.pro-price-table tbody tr:hover {{
  background: var(--surface-1);
}}
.pro-domestic-price-table .price-value {{
  font-weight: 700; color: var(--ink1);
}}
/* Pro: 国内仕入れ候補 / 国内売却候補(買取店) のセクションラベル */
.pro-subsection-label {{
  font-size: 0.82rem; font-weight: 800; margin: 12px 0 4px; padding: 4px 8px;
  border-radius: 6px; letter-spacing: 0.02em;
}}
.pro-subsection-label.pro-buy-label {{
  color: #1F5FA8; background: #EEF5FF; border-left: 3px solid #3B82C4;
}}
.pro-subsection-label.pro-buyback-label {{
  color: #176B4D; background: #ECFBF4; border-left: 3px solid #00A37A;
}}
.pro-subsection-label.pro-overseas-label {{
  color: #0369A1; background: #EBF6FE; border-left: 3px solid #2E8FD0;
}}
.pro-buyback-table .pro-bb-rank {{
  display: inline-block; min-width: 1.3em; margin-right: 5px;
  font-weight: 800; color: #00A37A; font-variant-numeric: tabular-nums;
}}
.pro-buyback-table .pro-row-buyback .price-value {{ color: #00A37A; }}
.pro-bb-reason-note {{
  font-size: 0.74rem; color: #99502A; background: #FFF6EE;
  border: 1px dashed #E6C29E; border-radius: 6px;
  padding: 5px 9px; margin: 4px 0 6px;
}}
.pro-overseas-price-table .price-value {{
  font-weight: 700; color: #0369A1;
}}
.pro-jpy-note {{
  font-size: 0.68rem; color: var(--ink3); font-weight: 400; margin-left: 2px;
}}
.pro-overseas-note {{
  font-size: 0.72rem; color: var(--ink3); margin: 2px 0 6px; padding: 0 2px;
}}
.pro-price-link {{
  color: var(--link); text-decoration: none; font-weight: 600;
}}
.pro-price-link:hover {{ text-decoration: underline; }}
.pcc-chips-label {{
  font-size: 0.72rem; color: var(--ink3); margin: 6px 0 3px; padding: 0 2px;
}}
/* Pro価格テーブル：確認ボタン列 */
.pro-link-btn {{
  display: inline-block; font-size: 0.73rem; font-weight: 700;
  padding: 3px 10px; border-radius: 6px;
  background: var(--profit); color: #fff;
  text-decoration: none; white-space: nowrap;
  transition: opacity 0.15s;
}}
.pro-link-btn:hover {{ opacity: 0.82; text-decoration: none; }}
.pro-link-btn-dim {{
  background: var(--surface-2); color: var(--ink2);
  border: 1px solid var(--border-1);
}}
.pro-link-btn-dim:hover {{ background: var(--surface-1); }}
.pro-no-price {{
  font-size: 0.75rem; color: var(--ink3);
}}
.pro-src-name {{ font-weight: 600; font-size: 0.82rem; }}
.pro-row-has-price {{ background: rgba(0,200,150,0.04); }}
.pro-action-cell {{ text-align: right; white-space: nowrap; }}
.pro-meta-cell {{ font-size: 0.73rem; color: var(--ink3); white-space: nowrap; }}
.pro-basis-cell {{ white-space: nowrap; }}
.pro-method-cell {{ white-space: nowrap; font-size: 0.72rem; }}
/* collector_method バッジ */
.collector-method-badge {{
  display: inline-block; font-size: 0.68rem; font-weight: 600;
  padding: 2px 7px; border-radius: 99px; white-space: nowrap;
}}
.cm-api     {{ background: #d1fae5; color: #065f46; border: 1px solid #6ee7b7; }}
.cm-manual  {{ background: #fef3c7; color: #92400e; border: 1px solid #fcd34d; }}
.cm-blocked {{ background: #f3f4f6; color: #4b5563; border: 1px solid #d1d5db; }}
.cm-unknown {{ background: var(--surface-2); color: var(--ink3); border: 1px solid var(--border-1); }}
.pro-price-basis {{
  display: inline-block; font-size: 0.72rem; padding: 2px 7px;
  border-radius: 99px; background: #EEF2FF; color: #4338CA;
  font-weight: 600; white-space: nowrap;
}}
.pro-price-basis-unknown {{ background: var(--surface-2); color: var(--ink3); }}
.pro-price-basis-disclaimer {{
  font-size: 0.78rem; color: var(--ink2);
  background: #FFFBEB; border: 1px solid #FDE68A;
  border-radius: 6px; padding: 7px 12px;
  margin: 10px 4px 4px; line-height: 1.5;
}}
/* Pro価格表: 未取得チップエリア */
.pro-no-price-section {{
  margin: 6px 0 0; padding: 6px 0 2px;
  border-top: 1px dashed var(--border-1);
}}
.pro-no-price-label {{
  display: block; font-size: 0.7rem; color: var(--ink3); margin-bottom: 4px; padding: 0 2px;
}}
.pro-no-price-chips {{
  display: flex; flex-wrap: wrap; gap: 5px; padding: 0 2px;
}}
.pro-no-price-chip {{
  display: inline-block; font-size: 0.72rem; padding: 2px 9px;
  border-radius: 99px; border: 1px solid var(--border-1);
  background: var(--surface-1); color: var(--link);
  text-decoration: none; white-space: nowrap;
}}
.pro-no-price-chip:hover {{ background: var(--surface-2); text-decoration: none; }}
.pro-no-data-note {{
  font-size: 0.75rem; color: var(--ink3); padding: 6px 2px;
}}
/* Pro価格カード要約ボックス */
.pro-card-summary {{
  display: flex; flex-wrap: wrap; gap: 8px 16px;
  background: var(--surface-1); border: 1px solid var(--border-1);
  border-radius: 8px; padding: 10px 14px;
  margin: 8px 0 12px;
}}
.pro-summary-item {{
  display: flex; align-items: baseline; gap: 5px; flex-wrap: wrap;
}}
.pro-summary-lbl {{
  font-size: 0.72rem; color: var(--ink3); white-space: nowrap;
}}
.pro-summary-val {{
  font-size: 0.95rem; font-weight: 800; color: var(--ink);
  font-variant-numeric: tabular-nums;
}}
.pro-summary-gap-pos {{ color: var(--profit-dark); }}
.pro-summary-gap-neg {{ color: var(--danger); }}
.pro-summary-sub {{
  font-size: 0.7rem; color: var(--ink3);
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

/* 取得レポートリンク：管理者向け、控えめに表示 */
.admin-report-link {{ color: rgba(255,255,255,0.2); font-size: 0.72rem; }}
.admin-report-link:hover {{ color: rgba(255,255,255,0.5); }}

.footer-text {{
  font-size: 0.75rem; color: rgba(255,255,255,0.25);
  line-height: 2;
}}
/* データ取得状況（簡易・控えめ） */
.data-quality-note {{
  font-size: 0.72rem; color: rgba(255,255,255,0.5);
  line-height: 1.7; margin-bottom: 14px; padding: 8px 12px;
  background: rgba(255,255,255,0.04); border-radius: 8px;
  border: 1px solid rgba(255,255,255,0.08);
}}
.data-quality-note .dq-title {{ font-weight: 800; color: rgba(255,255,255,0.7); }}
.data-quality-note strong {{ color: rgba(255,255,255,0.85); }}

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
   SOKUHOH (速報) TAB
   ============================================================ */
.sokuhoh-feed {{ display: flex; flex-direction: column; gap: 12px; padding: 8px 0; }}
.sokuhoh-card {{
  background: var(--card-bg);
  border: 1px solid var(--card-border);
  border-radius: 14px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}}
.sokuhoh-surge {{ border-left: 4px solid #22C55E; }}
.sokuhoh-drop  {{ border-left: 4px solid #EF4444; }}
.sokuhoh-change {{ border-left: 4px solid #F59E0B; }}
.sokuhoh-top {{ display: flex; gap: 6px; align-items: center; }}
.sokuhoh-badge {{ font-size: 0.68rem; font-weight: 700; padding: 2px 10px; border-radius: 99px; }}
.badge-surge {{ background: #DCFCE7; color: #16A34A; }}
.badge-drop  {{ background: #FEE2E2; color: #DC2626; }}
.badge-restock     {{ background: #DCFCE7; color: #15803D; }}
.badge-presale     {{ background: #EEF2FF; color: #4338CA; }}
.badge-lottery-start {{ background: #FEF9C3; color: #854D0E; }}
.badge-lottery-end   {{ background: #F1F5F9; color: #64748B; }}
.badge-update      {{ background: #E0F2FE; color: #075985; }}
.badge-soldout     {{ background: #FEE2E2; color: #991B1B; }}
.sokuhoh-body {{ display: flex; flex-direction: column; gap: 4px; }}
.sokuhoh-name {{ font-weight: 800; font-size: 0.92rem; color: var(--ink); }}
.sokuhoh-brand {{ font-size: 0.75rem; color: var(--ink3); }}
.sokuhoh-price-row {{ display: flex; align-items: center; gap: 8px; font-variant-numeric: tabular-nums; }}
.sokuhoh-prev {{ color: var(--ink3); font-size: 0.85rem; text-decoration: line-through; }}
.sokuhoh-arrow {{ color: var(--ink4); font-size: 0.8rem; }}
.sokuhoh-cur {{ font-weight: 800; font-size: 0.95rem; color: var(--ink); }}
.sokuhoh-diff {{ font-size: 0.8rem; color: #22C55E; font-weight: 700; }}
.sokuhoh-drop .sokuhoh-diff {{ color: #EF4444; }}
.sokuhoh-time {{ font-size: 0.72rem; color: var(--ink4); }}

/* ============================================================
   DATA STALE BANNER
   ============================================================ */
.data-stale-banner {{
  border-radius: 8px; padding: 10px 14px;
  font-size: 0.82rem; font-weight: 600;
  margin: 0 0 12px;
  display: flex; align-items: flex-start; gap: 8px;
}}
.data-stale-warn {{
  background: #FFFBEB; border: 1px solid #FDE68A; color: #92400E;
}}
.data-stale-critical {{
  background: #FEF2F2; border: 1px solid #FECACA; color: #991B1B;
}}

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
.sc-route-bb2bb-note {{
  font-size: 0.78rem; color: #99502A; background: #FFF6EE;
  border: 1px dashed #E6C29E; border-radius: 6px;
  padding: 6px 10px; margin: 14px 0 6px;
}}

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
   Pro カードフィルタバー / さらに表示ボタン
   ============================================================ */
.pro-filter-bar {{
  display: flex; flex-wrap: wrap; gap: 6px;
  padding: 12px 16px 10px; border-bottom: 1px solid #EEE8FF;
  background: #FAFAFF;
}}
.pro-filter-btn {{
  display: inline-flex; align-items: center; padding: 5px 13px;
  border-radius: 99px; font-size: 0.76rem; font-weight: 700;
  background: var(--surface-2); color: var(--text-2);
  border: 1px solid #E5E7EB; cursor: pointer;
  transition: all 0.15s cubic-bezier(0.23,1,0.32,1);
  white-space: nowrap;
}}
.pro-filter-btn:hover {{ background: #EEF2FF; color: #4338CA; border-color: #C7D2FE; }}
.pro-filter-btn.active {{
  background: #4338CA; color: #fff; border-color: #4338CA;
}}
/* 折り畳みカード（初期非表示） */
.pro-card-collapsed {{ display: none; }}
/* さらに表示ボタン */
.pro-show-more-btn {{
  display: block; width: calc(100% - 36px); margin: 10px 18px 14px;
  padding: 10px 16px; border-radius: 10px;
  border: 1px dashed #DDD6FE; background: #F5F3FF;
  color: #4338CA; font-weight: 700; font-size: 0.85rem;
  cursor: pointer; text-align: center;
  transition: background 0.15s, border-color 0.15s;
}}
.pro-show-more-btn:hover {{ background: #EEF2FF; border-color: #A5B4FC; }}
@media (max-width: 640px) {{
  .pro-filter-bar {{ padding: 8px 10px; gap: 4px; }}
  .pro-filter-btn {{ font-size: 0.72rem; padding: 4px 10px; }}
  .pro-show-more-btn {{ width: calc(100% - 20px); margin: 8px 10px 10px; }}
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
.cat-nav-wrap {{ background: var(--bg); border-bottom: 1px solid var(--card-border); padding: 6px 0; }}
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
.lottery-ref-badge {{ display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 0.72rem; font-weight: 600; background: #EEF2FF; color: #4338CA; margin-left: 6px; vertical-align: middle; }}
.lottery-no-link {{ display: inline-block; font-size: 0.82rem; color: var(--text-2); padding: 6px 10px; background: var(--surface2); border-radius: 8px; }}
.lottery-checked-at {{ display: inline-block; font-size: 0.78rem; color: var(--text-3, #94A3B8); margin-top: 6px; }}
.lottery-conflict-warning {{ margin: 8px 0 4px; padding: 7px 10px; border-radius: 8px; background: #FEF9C3; border: 1px solid #FDE047; color: #854D0E; font-size: 0.8rem; line-height: 1.4; }}
.lottery-link-btn {{ font-size: 0.85rem; padding: 7px 14px; }}

/* Ranking nav */
.rank-row-clickable:hover {{ background: var(--surface2); }}
.rank-name-link {{ color: var(--violet); }}

/* Live panel link */
.live-panel-link {{ color: inherit; text-decoration: none; }}
.live-panel-link:hover {{ text-decoration: underline; }}
</style>

</head>
<body>
{alert_popup_html}{_collector_warn_html}<header class="topbar">
  <a href="/" class="topbar-brand">
    <div class="brand-icon">S</div>
    プレ値速報
  </a>
  <div class="topbar-live"><span class="live-dot"></span><span class="topbar-update-text">毎日更新</span></div>
  {_topbar_date_html}
  <div class="topbar-spacer"></div>
  <a href="#note-cta" class="topbar-note-btn" data-track="note_click">&#128221; 詳細レポートを見る</a>
</header>
{hero_html}
{stale_html}
{tab_nav_html}
<div class="main-wrap">
{tab_html}
{caution_html}
{cta_html}
{footer_html}
</div>
<script>
(function(){{
  // ── メインタブ切り替え ──
  var btns   = document.querySelectorAll(".tab-btn:not(.genre-toggle-btn)");
  var panels = document.querySelectorAll(".tab-panel");

  function activateTab(tabId){{
    btns.forEach(function(b){{
      var active = (b.getAttribute("data-tab") === tabId);
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    }});
    panels.forEach(function(p){{
      p.classList.toggle("active", p.id === "tab-" + tabId);
    }});
    // ジャンルドロップダウンを閉じる
    var dd = document.getElementById("genre-dropdown");
    if (dd) dd.style.display = "none";
    var gBtn = document.getElementById("genre-toggle-btn");
    if (gBtn) {{ gBtn.classList.remove("active"); gBtn.setAttribute("aria-expanded","false"); }}
  }}

  if (btns.length) {{
    btns.forEach(function(btn){{
      btn.addEventListener("click", function(){{
        activateTab(btn.getAttribute("data-tab"));
      }});
    }});
  }}

  // ── ジャンルドロップダウン開閉 ──
  function toggleGenreMenu(){{
    var dd   = document.getElementById("genre-dropdown");
    var gBtn = document.getElementById("genre-toggle-btn");
    if (!dd) return;
    var isOpen = (dd.style.display !== "none" && dd.style.display !== "");
    dd.style.display = isOpen ? "none" : "block";
    if (gBtn) {{ gBtn.classList.toggle("active", !isOpen); gBtn.setAttribute("aria-expanded", !isOpen ? "true" : "false"); }}
  }}

  var gToggle = document.getElementById("genre-toggle-btn");
  if (gToggle) {{
    gToggle.addEventListener("click", function(){{ toggleGenreMenu(); }});
  }}

  // ── ジャンルボタン（第1階層）──
  function toggleMakerGroup(genre){{
    document.querySelectorAll(".maker-group").forEach(function(g){{
      g.classList.toggle("active", g.getAttribute("data-genre-panel") === genre);
    }});
    document.querySelectorAll(".genre-btn").forEach(function(b){{
      b.classList.toggle("active", b.getAttribute("data-genre") === genre);
    }});
  }}

  document.querySelectorAll(".genre-btn").forEach(function(btn){{
    btn.addEventListener("click", function(){{
      var genre    = btn.getAttribute("data-genre");
      var targetTab = btn.getAttribute("data-target-tab");
      var targetId  = btn.getAttribute("data-target-id");
      toggleMakerGroup(genre);
      // タブは切り替えず、メーカー一覧だけ表示（タブ切り替えはメーカーチップで行う）
    }});
  }});

  // ── メーカーチップ → activateCategory ──
  function activateCategory(tabName, targetId){{
    activateTab(tabName);
    var panel = document.getElementById("tab-" + tabName);
    if (panel) {{
      setTimeout(function(){{
        if (targetId) {{
          var el = document.getElementById(targetId);
          if (el) {{ el.scrollIntoView({{behavior:"smooth",block:"start"}}); return; }}
        }}
        panel.scrollIntoView({{behavior:"smooth",block:"start"}});
      }}, 100);
    }}
  }}

  document.querySelectorAll(".maker-chip").forEach(function(chip){{
    chip.addEventListener("click", function(e){{
      var targetTab = chip.getAttribute("data-target-tab");
      var targetId  = chip.getAttribute("data-target-id");
      if (targetTab) {{
        e.preventDefault();
        activateCategory(targetTab, targetId || "");
      }}
    }});
  }});

  // ── アンカーリンク（href="#tab-xxx"）からのタブ切り替え ──
  document.addEventListener("click", function(e){{
    var el = e.target.closest("a[href^='#tab-']");
    if (el) {{
      var hash  = el.getAttribute("href");
      var tabId = hash.replace("#tab-", "");
      var panel = document.getElementById("tab-" + tabId);
      if (panel) {{
        e.preventDefault();
        activateTab(tabId);
        panel.scrollIntoView({{behavior:"smooth",block:"start"}});
      }}
    }}
  }});

  // ── トラッキング ──
  document.addEventListener("click", function(e){{
    var el = e.target.closest("[data-track]");
    if (!el) return;
    var ev = el.getAttribute("data-track"), pid = el.getAttribute("data-product-id")||"", shop = el.getAttribute("data-shop")||"";
    if (typeof gtag === "function") gtag("event", ev, {{product_id:pid, shop:shop}});
    if (typeof fbq  === "function") fbq("trackCustom", ev, {{product_id:pid, shop:shop}});
  }});

  // ── ランキング内サブタブ ──
  var rbtns = document.querySelectorAll(".ranking-tab-btn");
  if (rbtns.length) {{
    rbtns.forEach(function(rb){{
      rb.addEventListener("click", function(){{
        rbtns.forEach(function(b){{ b.classList.remove("active"); }});
        document.querySelectorAll(".ranking-tab-panel").forEach(function(p){{ p.classList.remove("active"); }});
        rb.classList.add("active");
        var panel = document.getElementById("rtab-" + rb.getAttribute("data-rtab"));
        if (panel) panel.classList.add("active");
      }});
    }});
  }}

  // ── ランキング行クリックナビ ──
  document.querySelectorAll(".rank-row-clickable").forEach(function(row){{
    row.addEventListener("click", function(){{
      var tabId    = row.getAttribute("data-target-tab");
      var targetId = row.getAttribute("data-target-id");
      if (tabId) activateCategory(tabId, targetId||"");
    }});
  }});

  // ── モバイルドロワー ──
  var drawerOverlay = document.getElementById("mobile-drawer-overlay");
  var drawer = document.getElementById("mobile-drawer");
  var drawerClose = document.getElementById("mobile-drawer-close");
  var hamburger = document.getElementById("mobile-hamburger");
  var currentLabel = document.getElementById("mobile-tab-current-label");

  var drawerTabLabels = {{
    "lottery": "&#127915; 抽選情報",
    "ranking": "&#127942; ランキング",
    "sedori": "&#9636; せどりルート",
    "beginner": "&#128100; 初心者",
    "advanced": "&#9997; Pro"
  }};

  function openDrawer() {{
    if (drawer) drawer.classList.add("open");
    if (drawerOverlay) drawerOverlay.classList.add("open");
    document.body.style.overflow = "hidden";
  }}
  function closeDrawer() {{
    if (drawer) drawer.classList.remove("open");
    if (drawerOverlay) drawerOverlay.classList.remove("open");
    document.body.style.overflow = "";
  }}
  if (hamburger) hamburger.addEventListener("click", openDrawer);
  if (drawerClose) drawerClose.addEventListener("click", closeDrawer);
  if (drawerOverlay) drawerOverlay.addEventListener("click", closeDrawer);

  // ドロワーのタブボタン
  document.querySelectorAll(".mobile-drawer-nav-btn").forEach(function(btn) {{
    btn.addEventListener("click", function() {{
      var tabId = btn.getAttribute("data-drawer-tab");
      if (tabId) {{
        activateTab(tabId);
        // ドロワーのアクティブ更新
        document.querySelectorAll(".mobile-drawer-nav-btn").forEach(function(b) {{
          b.classList.toggle("active", b.getAttribute("data-drawer-tab") === tabId);
        }});
        // トップバーラベル更新
        if (currentLabel) currentLabel.innerHTML = drawerTabLabels[tabId] || tabId;
        closeDrawer();
      }}
    }});
  }});

  // activateTab にフック（PCタブ切り替え時もトップバー更新）
  var _origActivateTab = activateTab;
  activateTab = function(tabId) {{
    _origActivateTab(tabId);
    // ドロワーアクティブ更新
    document.querySelectorAll(".mobile-drawer-nav-btn").forEach(function(b) {{
      b.classList.toggle("active", b.getAttribute("data-drawer-tab") === tabId);
    }});
    if (currentLabel) currentLabel.innerHTML = drawerTabLabels[tabId] || tabId;
  }};
}})();
</script>
<noscript><style>.tab-nav{{display:none;}}.tab-panel{{display:block!important;}}</style></noscript>
</body>
</html>"""

    # ----- Hero -----

    def _section_hero(self, date_str, time_str, latest_buyback_at, lp_generated_at,
                       all_deals=None, iphone_deals=None, camera_deals=None, game_deals=None,
                       beginner_display_count=None) -> str:

        variant_key = self.settings.get('headline_variant', 'A')

        variants    = self.settings.get('variants', {})

        variant     = variants.get(variant_key, {})

        buyback_str = _jst_str(latest_buyback_at)

        lp_str      = _jst_str(lp_generated_at)

        stale_cls   = 'stale' if _hours_ago(latest_buyback_at) > 24 else ''

        # 件数: 実際に初心者タブに表示するカード数を使用（beginner_display_count 優先）
        # all_deals は limit=50 で全レベル混在のため件数として不適切
        all_count = beginner_display_count if beginner_display_count is not None else (
            len(all_deals) if all_deals else 0
        )

        iphone_count = len(iphone_deals) if iphone_deals else 0

        camera_count = len(camera_deals) if camera_deals else 0

        game_count   = len(game_deals)   if game_deals   else 0

        max_profit   = max((d.net_profit_jpy or 0) for d in all_deals) if all_deals else 0

        max_profit_str = f'+¥{max_profit:,}' if max_profit > 0 else '—'

        # Hero ボタン / social proof テキスト: 件数は鮮度に応じて出し分け
        _all_deals_total = len(all_deals) if all_deals else 0
        _buyback_fresh = _hours_ago(latest_buyback_at) <= 24  # 24h以内 = 新鮮
        if all_count > 0 and _buyback_fresh:
            _hero_btn_label     = f"&#128100; 初心者向け案件を見る ({all_count}件)"
            _hero_social_html   = (
                f"最高利益参考 <strong>{_esc(max_profit_str)}</strong>"
                f" — 公式定価 vs 最高買取店"
            )
        elif all_count > 0:
            # データあるが鮮度が古い（48h〜168h）: 件数は出さず利益のみ
            _hero_btn_label   = "&#128100; 初心者向け案件を見る"
            _hero_social_html = (
                f"最高利益参考 <strong>{_esc(max_profit_str)}</strong>"
                f" — 公式定価 vs 最高買取店（参考データ）"
            )
        elif _all_deals_total > 0:
            # 監視中・前回データのみ（利益案件なし）
            _hero_btn_label   = "&#128100; 初心者向け案件を見る"
            _hero_social_html = "公式定価 vs 最高買取店の差益を毎日チェック"
        else:
            _hero_btn_label   = "&#128100; 初心者向け案件を見る（取得中）"
            _hero_social_html = "公式定価 vs 最高買取店の差益を毎日チェック"

        # 参考DEALS パネル: all_deals の上位5件を動的生成（fetch_failed 除外済み）
        _GENRE_ICON = {
            "iphone": "&#128241;", "smartphone": "&#128241;",
            "camera": "&#128247;",
            "game_console": "&#127918;", "game": "&#127918;",
        }
        _hero_deal_items = []
        _seen_products_hero = set()
        _candidates = sorted(
            [d for d in (all_deals or []) if (d.net_profit_jpy or 0) > 0],
            key=lambda d: d.net_profit_jpy or 0, reverse=True
        )
        for _d in _candidates:
            if _d.product_id in _seen_products_hero:
                continue
            _seen_products_hero.add(_d.product_id)
            _cat = getattr(_d, "category", "") or ""
            _icon = _GENRE_ICON.get(_cat, "&#128240;")
            _icon_cls = "iphone" if "phone" in _cat or _cat == "iphone" else (
                "camera" if _cat == "camera" else (
                "game" if "game" in _cat else "default"
            ))
            _shop = _esc(getattr(_d, "best_buyback_shop", "") or "")
            _pname = _esc(getattr(_d, "product_name", "") or "")
            _profit = _d.net_profit_jpy or 0
            _profit_str = f'+¥{_profit:,}' if _profit >= 0 else f'-¥{abs(_profit):,}'
            _hero_deal_items.append(
                f'<div class="lp-item">'
                f'<div class="lp-icon {_icon_cls}">{_icon}</div>'
                f'<div class="lp-info">'
                f'<div class="lp-name">{_pname}</div>'
                f'<div class="lp-shop">{_shop}</div>'
                f'</div>'
                f'<div class="lp-profit">{_esc(_profit_str)}</div>'
                f'</div>'
            )
            if len(_hero_deal_items) >= 5:
                break
        # フォールバック: データ0件のとき空メッセージ
        if not _hero_deal_items:
            _hero_deal_items = ['<div class="lp-item" style="color:var(--ink3);font-size:0.8rem;padding:8px 0;">参考データ準備中</div>']
        _hero_live_panel_items = "\n          ".join(_hero_deal_items)

        return f"""<section class="hero">
  <div class="hero-inner">
    <div class="hero-left">
      <div class="hero-eyebrow"><span class="live-dot"></span> {_esc(date_str)} 更新</div>
      <h1 class="hero-title">最新<span class="accent">価格差</span>を<br>すぐに把握。</h1>
      <p class="hero-subtitle">新品・未使用品の公式価格と買取・海外相場を毎日チェック。iPhone・カメラ・ゲーム機の差益を一枚で確認できます。公式サイトで最新価格を必ずご確認ください。</p>
      <div class="hero-cta-row">
        <a href="#tab-lottery" class="hero-btn primary" data-track="hero_lottery_click">&#127915; 抽選情報を見る</a>
        <a href="#tab-beginner" class="hero-btn secondary" data-track="hero_beginner_click">{_hero_btn_label}</a>
        <a href="#tab-advanced" class="hero-btn violet" data-track="hero_pro_click">&#9997; Pro向け相場を見る</a>
        <a href="#tab-sedori" class="hero-btn secondary" data-track="hero_sedori_click">&#9636; せどりルートを見る</a>
      </div>
      <div class="hero-social-proof">
        <div class="social-avatars">
          <div class="social-avatar">A</div>
          <div class="social-avatar">B</div>
          <div class="social-avatar">C</div>
        </div>
        <div class="social-text">{_hero_social_html}</div>
      </div>
      <div class="hero-timestamps">
        <span class="ts-pill" data-lp-generated title="このページを生成した日時"><span class="ts-dot blue"></span>更新日：{_esc(lp_str)}</span>
      </div>
    </div>
  </div>
</section>"""

    # ----- Stale Warning -----



    def _section_stale_warning(self, latest_buyback_at, latest_deals_at, lp_generated_at) -> str:
        """トップレベルの鮮度警告バナー。
        各タブ内の freshness_banner に委譲するため、常に非表示ブロックのみ返す。
        「本日の価格データ未更新」「最終データ: YYYY-MM-DD」などはトップに表示しない。
        deploy-check 互換用の hidden ブロックのみ出力。
        """
        # deploy-check 互換: stale-warning-block は常に存在する（display:none）
        return '<div class="stale-warning-block" style="display:none"></div>'

    def _section_category_nav(self, lottery_count: int = 0) -> str:
        """カテゴリナビセクション（ジャンルタブ＋メーカーチップ）"""
        lottery_badge = f'<span class="tab-count">{lottery_count}</span>' if lottery_count else ''
        return f"""<section class="cat-nav-wrap">
  <div class="cat-nav-inner">
    <div class="cat-genre-bar" role="tablist">
      <button class="cat-genre-btn active" data-genre="smartphone" data-target-tab="beginner" data-target-id="category-beginner-iphone">&#128241; スマホ</button>
      <button class="cat-genre-btn" data-genre="tablet" data-target-tab="beginner" data-target-id="category-beginner-tablet">&#9645; タブレット</button>
      <button class="cat-genre-btn" data-genre="pc" data-target-tab="beginner" data-target-id="category-beginner-pc">&#128187; PC / Mac</button>
      <button class="cat-genre-btn" data-genre="camera" data-target-tab="beginner" data-target-id="category-beginner-camera">&#128247; カメラ</button>
      <button class="cat-genre-btn" data-genre="game" data-target-tab="beginner" data-target-id="category-beginner-game">&#127918; ゲーム機</button>
      <button class="cat-genre-btn" data-genre="lottery" data-target-tab="lottery" data-target-id="category-lottery">&#127915; 抽選情報{lottery_badge}</button>
    </div>
    <div class="cat-maker-bar">
      <div class="cat-maker-group active" data-genre-panel="smartphone">
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-iphone" href="#tab-beginner">Apple</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-iphone" href="#tab-beginner">Samsung</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-iphone" href="#tab-beginner">Google</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="tablet">
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-tablet" href="#tab-beginner">Apple</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-tablet" href="#tab-beginner">Samsung</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="pc">
        <a class="cat-maker-chip" data-target-tab="advanced" data-target-id="category-pro-pc" href="#tab-advanced">Apple</a>
        <a class="cat-maker-chip" data-target-tab="advanced" data-target-id="category-pro-pc" href="#tab-advanced">Dell</a>
        <a class="cat-maker-chip" data-target-tab="advanced" data-target-id="category-pro-pc" href="#tab-advanced">Lenovo</a>
        <a class="cat-maker-chip" data-target-tab="advanced" data-target-id="category-pro-pc" href="#tab-advanced">HP</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="camera">
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-camera" href="#tab-beginner">RICOH</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-camera" href="#tab-beginner">FUJIFILM</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-camera" href="#tab-beginner">Canon</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-camera" href="#tab-beginner">Nikon</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-camera" href="#tab-beginner">Sony</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-camera" href="#tab-beginner">Leica</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="game">
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-game" href="#tab-beginner">Nintendo</a>
        <a class="cat-maker-chip" data-target-tab="beginner" data-target-id="category-beginner-game" href="#tab-beginner">PlayStation</a>
        <a class="cat-maker-chip" data-target-tab="advanced" data-target-id="category-pro-pc" href="#tab-advanced">Xbox</a>
        <a class="cat-maker-chip" data-target-tab="lottery" data-target-id="category-lottery" href="#tab-lottery">限定・抽選</a>
      </div>
      <div class="cat-maker-group" data-genre-panel="lottery">
        <a class="cat-maker-chip" data-target-tab="lottery" data-target-id="category-lottery" href="#tab-lottery">抽選一覧へ</a>
      </div>
    </div>
  </div>
</section>"""

    @classmethod
    def _load_csv_lottery_events(cls) -> list[dict]:
        """data/lottery_events.csv から抽選情報を読み込む。"""
        csv_path = Path(__file__).resolve().parent.parent.parent / "data" / "lottery_events.csv"
        if not csv_path.exists():
            return []
        try:
            import csv
            rows = []
            with open(csv_path, encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(dict(row))
            return rows
        except Exception:
            return []

    # 抽選情報リファレンスカード（CSV/DB で管理されていない商品のみ）
    _LOTTERY_REFERENCE_ITEMS = [
        # ── 参考リンク（reference_only=True: 抽選期間なし・旧情報） ────────
        {
            "product_name": "FUJIFILM X100VI",
            "brand": "FUJIFILM",
            "status": "active",
            "reference_only": True,
            "note": "2024年2月発売。抽選受付は終了済み。公式での入手は在庫次第。",
            "url": "https://fujifilm-x.com/ja-jp/products/cameras/x100vi/",
            "sale_method": "通常販売（在庫次第）",
            "official_price": "¥230,230（税込）",
            "link_type": "product_page",
            "checked_at": "2026-05-21",
        },
        {
            "product_name": "PlayStation 5 Pro",
            "brand": "Sony Interactive Entertainment",
            "status": "active",
            "reference_only": True,
            "note": "2024年11月発売。通常販売中。限定エディションは抽選または先着順。PS Directでの購入を推奨。",
            "url": "https://direct.playstation.com/ja-jp/buy-consoles/playstation5-console",
            "sale_method": "通常販売 / 限定版は抽選",
            "official_price": "¥119,980（税込）",
            "link_type": "sale_page",
            "checked_at": "2026-05-21",
        },
        {
            "product_name": "Nintendo Switch 2 限定モデル",
            "brand": "Nintendo",
            "status": "upcoming",
            "reference_only": True,
            "note": "通常モデルは2025年6月発売済み。限定エディションの抽選は随時マイニンテンドーストアで告知予定。",
            "url": "https://store.nintendo.co.jp/category/NINTENDO_SWITCH_2",
            "sale_method": "抽選（マイニンテンドーストア予定）",
            "official_price": "未定",
            "link_type": "sale_page",
            "checked_at": "2026-05-21",
        },
    ]

    @staticmethod
    def _lottery_status_from_dates(ev: dict) -> str:
        """entry_start_at / entry_end_at / status から有効ステータスを自動判定（JST基準）。
        優先順位:
          1. entry_end_at が過去 → "closed"
          2. entry_start_at が未来 → "upcoming"
          3. entry_start_at が過去 かつ entry_end_at が未来 → "active"
          4. それ以外 → 元の status → "unknown"
        """
        import zoneinfo
        try:
            JST = zoneinfo.ZoneInfo("Asia/Tokyo")
            now = datetime.now(tz=JST).replace(tzinfo=None)
        except Exception:
            now = datetime.now()

        def _parse_dt(s: str):
            """YYYY-MM-DD HH:MM 形式の文字列を datetime に変換。失敗時は None。"""
            try:
                dt = datetime.fromisoformat(str(s)[:16])
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                return dt
            except Exception:
                return None

        end_str   = ev.get("entry_end_at")   or ev.get("entry_end")   or ""
        start_str = ev.get("entry_start_at") or ev.get("entry_start") or ""
        end_dt   = _parse_dt(end_str)   if end_str   else None
        start_dt = _parse_dt(start_str) if start_str else None

        # 受付終了
        if end_dt is not None and end_dt < now:
            return "closed"
        # 受付開始前
        if start_dt is not None and start_dt > now:
            return "upcoming"
        # 受付中（start は過去 or なし、end は未来 or なし）
        if end_dt is not None and end_dt >= now:
            return "active"

        return ev.get("status", "unknown") or "unknown"

    def _section_lottery(self, lottery_events: list) -> str:
        """抽選情報セクション（4分類: 受付中 / 近日開始 / 受付終了 / 参考リンク）。
        reference_only=True のアイテムは常に「参考リンク」折りたたみへ。
        """
        parts = []
        parts.append(
            '<div id="category-lottery" class="info-banner violet">'
            '<div class="ib-title">&#127915; 抽選情報</div>'
            '各メーカーの抽選・予約情報です。'
            '&#9888; 価格・状態は変動します。必ず公式サイトで最新情報をご確認ください。</div>'
        )

        # すべての表示対象（DB + リファレンス）を集約してステータス自動判定
        def _prep(ev_raw, is_ref: bool) -> dict:
            if not isinstance(ev_raw, dict):
                try:
                    ev_raw = dict(ev_raw)
                except Exception:
                    return {}
            ev = dict(ev_raw)
            ev["_auto_status"] = self._lottery_status_from_dates(ev)
            ev["_is_reference"] = is_ref
            return ev

        all_items: list[dict] = []
        for ev in (lottery_events or []):
            r = _prep(ev, is_ref=False)
            if r:
                all_items.append(r)
        for item in self._LOTTERY_REFERENCE_ITEMS:
            r = _prep(item, is_ref=True)
            if r:
                all_items.append(r)

        # ── 4分類 ─────────────────────────────────────────────────────────
        # A. 現在受付中: active かつ entry_end_at あり かつ reference_only でない
        #    ← entry_end_at がない「日付なし active」は Section D へ
        def _has_end_date(it: dict) -> bool:
            v = it.get("entry_end_at") or it.get("entry_end") or ""
            return bool(str(v).strip())

        # Task 2: 禁止文言リスト — note に含まれている場合は active から除外して参考リンクへ
        _LOTTERY_FORBIDDEN_NOTES = frozenset({
            "抽選情報未確認",
            "公式商品ページで要確認",
            "次回未定",
            "近日開始",
            "受付中",
            "販売中",
            "日付不明",
        })

        def _is_forbidden_note(it: dict) -> bool:
            """note フィールドに禁止文言を含む場合 True を返す。"""
            note = str(it.get("note") or "")
            return any(kw in note for kw in _LOTTERY_FORBIDDEN_NOTES)

        # A. 現在受付中: active かつ entry_end_at あり かつ reference_only でない かつ禁止文言なし
        active_items   = [it for it in all_items
                          if it["_auto_status"] == "active"
                          and _has_end_date(it)
                          and not it.get("reference_only", False)
                          and not _is_forbidden_note(it)]
        # B. 近日開始: upcoming かつ reference_only でない
        upcoming_items = [it for it in all_items
                          if it["_auto_status"] == "upcoming"
                          and not it.get("reference_only", False)]
        # C. 受付終了: closed かつ reference_only でない
        closed_items   = [it for it in all_items
                          if it["_auto_status"] == "closed"
                          and not it.get("reference_only", False)]
        # D. 参考リンク:
        #    ① reference_only=True
        #    ② 日付なし active（旧エントリ・詳細不明）
        #    ③ note に禁止文言がある active アイテム（Task 2）
        #    ※ closed は Section C で表示済みなので除外
        reference_items = [it for it in all_items
                           if it.get("reference_only", False)
                           or (it["_auto_status"] == "active"
                               and not _has_end_date(it)
                               and not it.get("reference_only", False))
                           or _is_forbidden_note(it)]

        # ── A. 現在受付中 ──────────────────────────────────────────────────
        if active_items:
            parts.append('<div class="sec-head" style="margin-top:20px">'
                         '<div class="sec-title">&#128308; 現在受付中</div></div>')
            parts.append('<div class="lottery-ref-grid">')
            for it in active_items:
                parts.append(self._lottery_card_html(it, is_reference=it["_is_reference"]))
            parts.append('</div>')
        else:
            parts.append('<p class="empty-state" style="margin-top:20px">現在受付中の抽選情報はありません。</p>')

        # ── B. 近日開始 ────────────────────────────────────────────────────
        if upcoming_items:
            parts.append('<div class="sec-head" style="margin-top:24px">'
                         '<div class="sec-title">&#128336; 近日開始</div></div>')
            parts.append('<div class="lottery-ref-grid">')
            for it in upcoming_items:
                parts.append(self._lottery_card_html(it, is_reference=it["_is_reference"]))
            parts.append('</div>')

        # ── C. 受付終了（折りたたみ） ─────────────────────────────────────
        if closed_items:
            parts.append(
                '<details class="lottery-closed-section" style="margin-top:24px">'
                '<summary style="cursor:pointer;font-size:0.82rem;color:var(--ink3);padding:8px 4px;">'
                f'&#128197; 受付終了 / 過去の情報（{len(closed_items)}件）'
                '</summary>'
                '<div class="lottery-ref-grid" style="margin-top:8px;opacity:0.65">'
            )
            for it in closed_items:
                parts.append(self._lottery_card_html(it, is_reference=it["_is_reference"]))
            parts.append('</div></details>')

        # ── D. 参考リンク（折りたたみ） ───────────────────────────────────
        if reference_items:
            parts.append(
                '<details class="lottery-reference-section" style="margin-top:24px">'
                '<summary style="cursor:pointer;font-size:0.82rem;color:var(--ink3);padding:8px 4px;">'
                f'&#128279; 参考リンク（抽選期間なし・販売中商品: {len(reference_items)}件）'
                '</summary>'
                '<div class="lottery-ref-grid" style="margin-top:8px;opacity:0.75">'
            )
            for it in reference_items:
                parts.append(self._lottery_card_html(it, is_reference=True))
            parts.append('</div></details>')

        # ── 公式ページリンク集 ──
        parts.append('''<div class="lottery-official-links" style="margin-top:20px">
<a href="https://direct.playstation.com/ja-jp/buy-consoles/playstation5-console" target="_blank" rel="noopener" class="cat-maker-chip" data-track="lottery_click">PS5 Direct購入</a>
<a href="https://store.nintendo.co.jp/category/NINTENDO_SWITCH_2" target="_blank" rel="noopener" class="cat-maker-chip" data-track="lottery_click">Switch 2 ストア</a>
<a href="https://www.apple.com/jp/shop/buy-iphone" target="_blank" rel="noopener" class="cat-maker-chip" data-track="lottery_click">Apple iPhone購入</a>
<a href="https://fujifilm-x.com/ja-jp/products/cameras/x100vi/" target="_blank" rel="noopener" class="cat-maker-chip" data-track="lottery_click">X100VI 製品ページ</a>
<a href="https://www.ricoh-imaging.co.jp/japan/products/cameras/gr/" target="_blank" rel="noopener" class="cat-maker-chip" data-track="lottery_click">RICOH GR シリーズ</a>
<a href="https://store.nintendo.co.jp/" target="_blank" rel="noopener" class="cat-maker-chip" data-track="lottery_click">マイニンテンドーストア</a>
</div>''')

        return '\n'.join(parts)

    def _lottery_card_html(self, ev: dict, is_reference: bool = False) -> str:
        """抽選情報カード HTML を生成する。_auto_status があればそちらを優先。"""
        # ステータス
        status = ev.get("_auto_status") or ev.get("status", "unknown") or "unknown"
        # sale_method が "抽選販売" なら active ラベルを "抽選受付中" に変更
        _sale_method = str(ev.get("sale_method") or "")
        _is_lottery = "抽選" in _sale_method
        status_label = {
            "active":   "抽選受付中" if _is_lottery else "現在販売中",
            "upcoming": "近日開始",
            "closed":   "終了済み",
            "unknown":  "要確認",
        }.get(status, "要確認")
        status_cls = {
            "active":   "lottery-status-open",
            "upcoming": "lottery-status-upcoming",
            "closed":   "lottery-status-closed",
            "unknown":  "lottery-status-unknown",
        }.get(status, "lottery-status-unknown")

        # link_type → 表示ラベル（新仕様5種 + 旧仕様後方互換）
        _link_type = ev.get("link_type", "official_top")
        _link_label_map = {
            "lottery_page":     "抽選ページを確認",
            "reservation_page": "予約ページを確認",
            "sale_page":        "販売ページを確認",
            "product_page":     "商品ページを確認",
            "official_top":     "公式サイトで要確認",
            # 旧仕様（後方互換）
            "lottery":     "抽選ページを確認",
            "reservation": "予約ページを確認",
            "sale":        "販売ページを確認",
            "product":     "商品ページを確認",
            "official":    "公式サイトで要確認",
        }
        _link_label = _link_label_map.get(_link_type, "公式サイトで要確認")

        url = ev.get("url") or ""
        if url:
            link_btn = (
                f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer" '
                f'class="btn btn-secondary lottery-link-btn" data-track="lottery_click" '
                f'data-link-type="{_esc(_link_type)}">&#127915; {_link_label}</a>'
            )
        else:
            # データなし: メッセージ表示
            link_btn = '<span class="lottery-no-link" style="font-size:0.75rem;color:var(--ink4);font-style:italic;">公式ページで最新情報をご確認ください。</span>'

        # 抽選フォームへの第2CTAボタン
        entry_form_url = str(ev.get("entry_form_url") or "")
        if entry_form_url:
            form_btn = (
                f'<a href="{_esc(entry_form_url)}" target="_blank" rel="noopener noreferrer" '
                f'class="btn btn-primary lottery-link-btn" data-track="lottery_form_click">'
                f'&#128221; 抽選フォームを開く</a>'
            )
        else:
            form_btn = ""

        # 各フィールド
        entry_start    = str(ev.get("entry_start_at") or ev.get("entry_start") or "")
        entry_end      = str(ev.get("entry_end_at")   or ev.get("entry_end")   or "")
        result_at      = str(ev.get("result_announcement_at") or "")
        official_price = str(ev.get("official_price") or ev.get("price") or "")
        sale_method    = str(ev.get("sale_method") or "")
        note           = str(ev.get("note") or "")
        checked_at     = str(ev.get("checked_at") or ev.get("updated_at") or "")
        brand          = str(ev.get("brand") or "")

        # 参考情報バッジ
        ref_badge = (
            '<span class="lottery-ref-badge">参考情報</span>'
            if is_reference else ''
        )

        # 受付日程
        date_row = ""
        if entry_start and entry_start not in ("", "None"):
            date_row = f'<span>&#128197; 受付開始: {_esc(entry_start[:10])}</span>'
        if entry_end and entry_end not in ("", "None"):
            end_label = "受付終了: " if entry_start else "受付終了: "
            date_row += f'<span>&#128197; 受付終了: {_esc(entry_end[:10])}</span>'

        # 各行 HTML
        result_row = f'<span>&#128220; 当選発表: {_esc(result_at[:10])}</span>' if result_at and result_at != "None" else ''
        price_row  = f'<span>&#128176; 公式価格: {_esc(official_price)}</span>'  if official_price and official_price != "None" else ''
        method_row = f'<span>&#127919; 販売方式: {_esc(sale_method)}</span>'     if sale_method and sale_method != "None" else ''
        brand_row  = f'<span>&#127468; {_esc(brand)}</span>'                     if brand else ''
        # 弱表示キーワード: reference/詳細欄でのみ出し、目立たない表示にする
        _MUTED_NOTE_KEYWORDS = {"抽選情報未確認", "公式商品ページで要確認", "受付中", "販売中"}
        _note_is_muted = note and any(kw in note for kw in _MUTED_NOTE_KEYWORDS)
        note_row   = (
            f'<div class="lottery-note lottery-note-muted" style="font-size:0.72rem;color:var(--ink4);font-style:italic;">{_esc(note)}</div>'
            if (note and note != "None" and _note_is_muted) else
            (f'<div class="lottery-note">{_esc(note)}</div>' if note and note != "None" else '')
        )
        checked_row = (
            f'<span class="lottery-checked-at">&#128204; 最終確認: {_esc(checked_at[:10])}</span>'
            if checked_at and checked_at not in ("", "None") else ''
        )

        # ステータス矛盾警告（公式ページに終了文言があるが日付上はまだ active の場合）
        conflict_warning = ""
        if str(ev.get("status_conflict", "")).lower() == "true":
            conflict_warning = (
                '<div class="lottery-conflict-warning">'
                '&#9888; 公式ページ内に終了表記もあります。'
                '応募前に必ず公式ページをご確認ください。'
                '</div>'
            )

        return f'''<div class="lottery-card{'  lottery-ref-card' if is_reference else ''}">
  <div class="lottery-card-header">
    <div class="lottery-name">{_esc(ev.get("product_name", ""))} {ref_badge}</div>
    <span class="lottery-status-badge {status_cls}">{_esc(status_label)}</span>
  </div>
  <div class="lottery-meta">
    {brand_row}
    {price_row}
    {method_row}
    {date_row}
    {result_row}
    {checked_row}
  </div>
  {note_row}
  {conflict_warning}
  <div class="lottery-btn-group">
    {form_btn}
    {link_btn}
  </div>
</div>'''

    def _section_tab_nav(self, beginner_count: int = 0, adv_total: int = 0,
                         surge_count: int = 0, lottery_count: int = 0) -> str:
        """統合ナビゲーション（タブ + ジャンルドロップダウン）。"""
        sokuhoh_badge  = f'<span class="tab-count">{surge_count}</span>' if surge_count else ''
        lottery_badge  = f'<span class="tab-count">{lottery_count}</span>' if lottery_count else ''
        return f"""<!-- モバイルドロワー -->
<div class="mobile-drawer-overlay" id="mobile-drawer-overlay"></div>
<div class="mobile-drawer" id="mobile-drawer" role="dialog" aria-label="ナビゲーション">
  <div class="mobile-drawer-header">
    <span>&#128230; メニュー</span>
    <button class="mobile-drawer-close" id="mobile-drawer-close" aria-label="閉じる">&times;</button>
  </div>
  <div class="mobile-drawer-nav">
    <button class="mobile-drawer-nav-btn active" data-drawer-tab="lottery">&#127915; 抽選情報{lottery_badge}</button>
    <button class="mobile-drawer-nav-btn" data-drawer-tab="ranking">&#127942; ランキング</button>
    <button class="mobile-drawer-nav-btn" data-drawer-tab="sedori">&#9636; せどりルート</button>
    <button class="mobile-drawer-nav-btn" data-drawer-tab="beginner">&#128100; 初心者 <span class="tab-count">{beginner_count}</span></button>
    <button class="mobile-drawer-nav-btn" data-drawer-tab="advanced">&#9997; Pro <span class="tab-count">{adv_total}</span></button>
  </div>
</div>
<div class="mobile-tab-topbar" id="mobile-tab-topbar">
  <button class="mobile-hamburger" id="mobile-hamburger" aria-label="メニューを開く">&#9776;</button>
  <span class="mobile-tab-current-label" id="mobile-tab-current-label">&#127915; 抽選情報</span>
</div>
<div class="tab-wrap" id="main-tab-nav">
<nav class="tab-nav" role="tablist">
  <button class="tab-btn active" data-tab="lottery" role="tab" aria-selected="true">&#127915; 抽選情報{lottery_badge}</button>
  <button class="tab-btn" data-tab="ranking" role="tab" aria-selected="false">&#127942; ランキング</button>
  <button class="tab-btn" data-tab="sedori" role="tab" aria-selected="false">&#9636; せどりルート</button>
  <button class="tab-btn" data-tab="beginner" role="tab" aria-selected="false">&#128100; 初心者 <span class="tab-count">{beginner_count}</span></button>
  <button class="tab-btn" data-tab="advanced" role="tab" aria-selected="false">&#9997; Pro <span class="tab-count">{adv_total}</span></button>
  <button class="tab-btn genre-toggle-btn" id="genre-toggle-btn" data-action="toggle-genre" role="button" aria-expanded="false">&#128230; ジャンル &#9660;</button>
</nav>
<div class="genre-dropdown" id="genre-dropdown">
  <div class="genre-panel-row">
    <button class="genre-btn" data-genre="smartphone" data-target-tab="beginner" data-target-id="category-beginner-iphone">&#128241; スマホ</button>
    <button class="genre-btn" data-genre="tablet" data-target-tab="beginner" data-target-id="category-beginner-tablet">&#128196; タブレット</button>
    <button class="genre-btn" data-genre="pc" data-target-tab="advanced" data-target-id="category-pro-pc">&#128187; PC</button>
    <button class="genre-btn" data-genre="camera" data-target-tab="advanced" data-target-id="category-pro-camera">&#128247; カメラ</button>
    <button class="genre-btn" data-genre="game" data-target-tab="beginner" data-target-id="category-beginner-game">&#127918; ゲーム機</button>
  </div>
  <div class="maker-group-wrap">
    <div class="maker-group" data-genre-panel="smartphone">
      <a class="maker-chip" href="#category-beginner-iphone" data-target-tab="beginner" data-target-id="category-beginner-iphone">Apple</a>
      <a class="maker-chip" href="#category-beginner-iphone" data-target-tab="beginner" data-target-id="category-beginner-iphone">Samsung</a>
      <a class="maker-chip" href="#category-beginner-iphone" data-target-tab="beginner" data-target-id="category-beginner-iphone">Google</a>
    </div>
    <div class="maker-group" data-genre-panel="tablet">
      <a class="maker-chip" href="#category-beginner-tablet" data-target-tab="beginner" data-target-id="category-beginner-tablet">Apple</a>
    </div>
    <div class="maker-group" data-genre-panel="pc">
      <a class="maker-chip" href="#category-pro-pc" data-target-tab="advanced" data-target-id="category-pro-pc">Apple</a>
      <a class="maker-chip" href="#category-pro-pc" data-target-tab="advanced" data-target-id="category-pro-pc">Dell</a>
      <a class="maker-chip" href="#category-pro-pc" data-target-tab="advanced" data-target-id="category-pro-pc">Lenovo</a>
      <a class="maker-chip" href="#category-pro-pc" data-target-tab="advanced" data-target-id="category-pro-pc">HP</a>
      <a class="maker-chip" href="#category-pro-pc" data-target-tab="advanced" data-target-id="category-pro-pc">ASUS</a>
      <a class="maker-chip" href="#category-pro-pc" data-target-tab="advanced" data-target-id="category-pro-pc">MSI</a>
    </div>
    <div class="maker-group" data-genre-panel="camera">
      <a class="maker-chip" href="#category-pro-camera-ricoh" data-target-tab="advanced" data-target-id="category-pro-camera-ricoh">RICOH</a>
      <a class="maker-chip" href="#category-pro-camera-fujifilm" data-target-tab="advanced" data-target-id="category-pro-camera-fujifilm">FUJIFILM</a>
      <a class="maker-chip" href="#category-pro-camera" data-target-tab="advanced" data-target-id="category-pro-camera">Canon</a>
      <a class="maker-chip" href="#category-pro-camera" data-target-tab="advanced" data-target-id="category-pro-camera">Nikon</a>
      <a class="maker-chip" href="#category-pro-camera" data-target-tab="advanced" data-target-id="category-pro-camera">Sony</a>
      <a class="maker-chip" href="#category-pro-camera" data-target-tab="advanced" data-target-id="category-pro-camera">Leica</a>
    </div>
    <div class="maker-group" data-genre-panel="game">
      <a class="maker-chip" href="#category-pro-game" data-target-tab="beginner" data-target-id="category-beginner-game">Nintendo</a>
      <a class="maker-chip" href="#category-pro-game" data-target-tab="beginner" data-target-id="category-beginner-game">PlayStation</a>
      <a class="maker-chip" href="#category-pro-game" data-target-tab="advanced" data-target-id="category-pro-game">Xbox</a>
    </div>
  </div>
</div>
</div>"""

    def _section_tabs(self, beginner_easy, beginner_watch,

                      advanced_deals, advanced_snaps, watch_candidates,

                      buyback_alerts, all_deals, iphone_deals, game_deals,

                      camera_deals=None, iphone_watch=None, camera_watch=None,

                      game_watch=None, buyback_by_product: dict = None,
                      sedori_routes: list = None, lottery_events: list = None,
                      market_prices_by_product: dict = None,
                      beginner_display_count: int = None,
                      lottery_display_count: int = None,
                      latest_buyback_at: Optional[datetime] = None,
                      monitoring_deals: list = None,
                      fetch_failed_deals: list = None) -> str:

        camera_deals = camera_deals or []

        camera_watch = camera_watch or []

        bybp = buyback_by_product or {}
        lottery_events = lottery_events or []

        # カメラも初心者タブに表示する（overseas price で利益確認可能）
        beginner_html    = self._tab_beginner(
            list(beginner_easy), list(beginner_watch), bybp,
            latest_buyback_at=latest_buyback_at,
            monitoring_deals=list(monitoring_deals or []),
            fetch_failed_deals=list(fetch_failed_deals or []),
            market_prices_by_product=market_prices_by_product or {},
        )
        advanced_html    = self._tab_advanced(advanced_deals, advanced_snaps, watch_candidates,
                                              camera_watch=camera_watch,
                                              camera_beginner_deals=[],
                                              market_prices_by_product=market_prices_by_product or {},
                                              buyback_by_product=buyback_by_product or {},
                                              latest_buyback_at=latest_buyback_at)
        surge_html       = self._tab_surge(buyback_alerts)
        ranking_html     = self._tab_ranking(all_deals, iphone_deals, game_deals, sedori_routes=sedori_routes)
        # Task 3: 速報タブを削除 → ポップアップ速報へ移行（_section_alert_popup 参照）
        # beginner_deals を sedori タブに渡し、初心者合成ルートを生成
        # enrich により net>0 に昇格した監視中商品も含む union（all_deals）を優先利用し、
        # easy/watch のみだと漏れる昇格 deal をせどりルートへ反映する
        _seen_pids = set()
        _all_beginner_for_sedori = []
        for _d in list(all_deals or []) + list(beginner_easy or []) + list(beginner_watch or []):
            _pid = getattr(_d, 'product_id', None)
            if _pid is None or _pid in _seen_pids:
                continue
            _seen_pids.add(_pid)
            _all_beginner_for_sedori.append(_d)
        sedori_html      = self._tab_sedori(sedori_routes or [], beginner_deals=_all_beginner_for_sedori)
        lottery_html     = self._section_lottery(lottery_events)

        # 件数整合: 外部から渡された表示件数を優先（_render_page で整合済み）
        # beginner: カメラ除外後の件数。未渡しの場合はフォールバックとして自前計算
        all_count = beginner_display_count if beginner_display_count is not None else (
            len(_beginner_easy_filtered) + len(_beginner_watch_filtered)
        )
        adv_total    = len(advanced_deals) + len(advanced_snaps) + len(watch_candidates)
        surge_count  = len([a for a in buyback_alerts if a.get('alert_type') in ('buyback_surge','buyback_drop')])
        surge_badge  = f'<span class="tab-count">{surge_count}</span>' if surge_count else ''
        # 抽選: DBイベント + リファレンスアイテム の active/upcoming/unknown 件数
        lottery_count = lottery_display_count if lottery_display_count is not None else len(lottery_events)
        lottery_badge = f'<span class="tab-count">{lottery_count}</span>' if lottery_count else ''

        return f"""<div id="tab-lottery" class="tab-panel active" role="tabpanel">
{lottery_html}
</div>

<div id="tab-ranking" class="tab-panel" role="tabpanel">
{ranking_html}
</div>

<div id="tab-sedori" class="tab-panel" role="tabpanel">
{sedori_html}
</div>

<div id="tab-beginner" class="tab-panel" role="tabpanel">
{beginner_html}
</div>

<div id="tab-advanced" class="tab-panel" role="tabpanel">
{advanced_html}
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

    def _tab_sedori(self, sedori_routes: list = None, beginner_deals: list = None) -> str:
        """せどりルート比較タブ — DBから自動算出済みルートを表示する（Phase 14/15）。
        routes が空の場合は beginner_deals から初心者ルート（公式→買取店）を合成表示する。
        """
        # 新品・未使用・未開封のみ（中古・美品・開封済み・ジャンク等は完全除外）
        _all_routes = sedori_routes or []
        routes = [
            r for r in _all_routes
            if not self._cond_is_used(getattr(r, "buy_condition", "") or "")
        ]
        # Proルート = 新品・未使用の店舗間せどり／二次流通ルート（中古は上で除外済み）。
        # 初心者ルート（公式店→買取店）は _synth_routes 側で別途生成・表示する。
        pro_routes = list(routes)

        # コスト固定値
        cost_info = "送料¥1,000 + 振込¥300 + 交通費¥500"

        # ── Beginner deals から初心者合成ルートを生成 ──
        # DB の sedori_routes が全て中古条件の場合でも、毎日取得した buyback データから
        # 「公式店 → 買取店」ルートを自動生成して表示する
        _synth_routes = []
        _COSTS = 1800
        if beginner_deals:
            for d in beginner_deals:
                _bp = getattr(d, 'best_buyback_price', None) or 0
                _op = getattr(d, 'official_price_jpy', None) or 0
                _shop = getattr(d, 'best_buyback_shop', '') or ''
                if _bp <= 0 or _op <= 0:
                    continue
                if self._is_resale_shop(_shop):
                    continue  # resale_market 由来のショップはスキップ
                _gross = _bp - _op
                _net = _gross - _COSTS
                if _net <= 0:
                    continue
                _rate = _net / _op if _op > 0 else 0.0
                _pname = getattr(d, 'product_name', '') or ''
                _cat = getattr(d, 'category', '') or ''
                _synth_routes.append({
                    'product_name': _pname,
                    'category': _cat,
                    'buy_shop_name': '公式店（定価購入）',
                    'sell_shop_name': _shop,
                    'buy_price': _op,
                    'sell_price': _bp,
                    'gross_profit': _gross,
                    'net_profit': _net,
                    'profit_rate': _rate,
                    'is_synth': True,  # 合成ルートフラグ
                    'buy_url': getattr(d, 'official_url', '') or '',
                    'sell_url': getattr(d, 'best_buyback_url', '') or '',
                })
            # 実質利益降順でソート
            _synth_routes.sort(key=lambda r: r['net_profit'], reverse=True)

        parts = []

        total_beg_routes = len(pro_routes) + len(_synth_routes)
        parts.append(f'''<div class="sc-wrap">
<div class="sc-header">
  <div class="sc-eyebrow">&#9736; Auto Calculated</div>
  <h2 class="sc-title">店舗間せどりルート比較</h2>
  <p class="sc-desc">毎日取得した価格データをもとに、新品・未使用品の利益ルートを自動算出します。価格は参考値です。実際の購入前に必ず各店舗の最新価格をご確認ください。</p>
</div>
<div class="sc-meta-row">
  <span class="sc-meta-label">&#128203; 算出ルート数</span>
  <span class="sc-meta-val sc-routes-count-badge">{total_beg_routes}ルート</span>
</div>''')

        if not pro_routes and not _synth_routes:
            # データなしフォールバック
            parts.append('''<div class="sc-no-data">
  <div class="sc-no-data-icon">&#128202;</div>
  <div class="sc-no-data-title">現在、条件を満たすルートはありません</div>
  <div class="sc-no-data-desc">不足データ（すべて揃い次第、自動表示されます）：</div>
  <ul class="sc-no-data-list">
    <li>新品・未使用の公式価格データ</li>
    <li>国内買取店の買取価格データ</li>
  </ul>
  <div class="sc-no-data-note">毎日自動収集しています。価格データが揃い次第、ルートを表示します。</div>
</div>''')
        else:
            from src.models.sale_price import CONDITION_LABELS

            # ── ルートを「初心者ルート」と「Proルート」に分類 ──
            # Proルート: ヤフオク・メルカリ・ラクマ・eBay 等の二次流通（新品・未使用・未開封）仕入れ → 別市場売却。
            # 初心者ルートは「公式店 → 買取店」の合成ルート（_synth_routes）のみを採用するため、
            # DB routes 由来の beginner_routes は使わない（買取店→買取店など公式仕入れでないルートを除外）。
            beginner_routes = []  # DB routes は初心者に使わない（合成ルートで担保）
            # pro_routes は関数冒頭で算出済み

            # 各分類でさらに「通常」と「要確認」に分割
            def _split_review(rlist):
                ok  = [r for r in rlist if not getattr(r, "needs_review", False)
                       or getattr(r, "route_quality_score", 1.0) >= 0.6]
                rev = [r for r in rlist if getattr(r, "needs_review", False)
                       and getattr(r, "route_quality_score", 1.0) < 0.6]
                return (ok if ok else rlist), rev

            beg_ok, beg_review = _split_review(beginner_routes)
            pro_ok, pro_review = _split_review(pro_routes)

            # display_routes は表示対象（Proルートのみ。生 routes は使わない＝店舗間arbitrage混入防止）
            display_routes = pro_routes
            display_label = "Proルート"

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

            # ── 初心者ルート（公式店 → 買取店）──
            if beginner_routes:
                parts.append('''<div class="sc-review-section" style="border-left:4px solid #059669;background:#f0fdf4;border-radius:8px;padding:12px 16px;margin:12px 0">
  <div class="sc-review-hd">
    <span class="sc-review-icon">&#128100;</span>
    <div>
      <div class="sc-review-title" style="color:#059669">初心者ルート（公式店 → 買取店）</div>
      <div class="sc-review-sub">公式店・正規店・量販店で定価購入 → 国内買取店へ売却。フリマ・海外販売不要のシンプルルートです。</div>
    </div>
  </div>
</div>''')
                best_beg = beg_ok[0] if beg_ok else beginner_routes[0]
                parts.append(_make_best_card(best_beg))
                rest_beg = (beg_ok[1:10] if beg_ok else beginner_routes[1:10])
                if rest_beg:
                    parts.append(_make_route_table(rest_beg, title_label="初心者ルート 2位〜"))
                if beg_review:
                    parts.append(_make_route_table(beg_review, title_label="初心者ルート 要確認"))

            # ── Proルート（店舗間せどり／二次流通仕入れ → 別市場売却）──
            # Task 4: 推奨ルートを優先し、買取店→買取店ルートは「要確認（下位）」へ。
            #   推奨: フリマ/オークション/EC新品仕入れ → eBay/StockX/海外・買取店売却
            #     ・ヤフオク未使用 → eBay / StockX
            #     ・メルカリ未使用 → eBay / StockX
            #     ・Amazon新品 / 楽天新品 → 買取店 / 海外
            _OVERSEAS_SELL_KWS = ('ebay', 'stockx', '海外')
            _RESALE_BUY_KWS = ('ヤフオク', 'yahoo', 'メルカリ', 'mercari', 'ラクマ', 'rakuma',
                               'amazon', 'アマゾン', '楽天', 'rakuten')

            def _is_overseas_sell(name):
                n = (name or '').lower()
                return any(k.lower() in n for k in _OVERSEAS_SELL_KWS)

            def _is_resale_buy(name):
                n = (name or '').lower()
                return any(k.lower() in n for k in _RESALE_BUY_KWS)

            def _is_buyback_shop_name(name):
                # フリマ/オークション/EC でも海外でもない国内店 = 買取店扱い
                return (not _is_resale_buy(name)) and (not _is_overseas_sell(name)) \
                    and (not self._is_resale_shop(name))

            def _route_pref(r):
                bs = getattr(r, 'buy_shop_name', '') or ''
                ss = getattr(r, 'sell_shop_name', '') or ''
                if _is_buyback_shop_name(bs) and _is_buyback_shop_name(ss):
                    return 2  # 買取店→買取店：下位（要確認）
                # 推奨: フリマ/オークション/EC新品仕入れ → 海外 or 買取店売却
                if _is_resale_buy(bs) and (_is_overseas_sell(ss) or _is_buyback_shop_name(ss)):
                    return 0
                return 1  # その他

            _pro_pref    = [r for r in pro_routes if _route_pref(r) == 0]
            _pro_neutral = [r for r in pro_routes if _route_pref(r) == 1]
            _pro_bb2bb   = [r for r in pro_routes if _route_pref(r) == 2]
            _pro_top = sorted(_pro_pref + _pro_neutral,
                              key=lambda r: getattr(r, 'net_profit', 0) or 0, reverse=True)
            _pro_low = sorted(_pro_bb2bb,
                              key=lambda r: getattr(r, 'net_profit', 0) or 0, reverse=True)

            if pro_routes:
                parts.append(f'''<div class="sc-review-section" style="border-left:4px solid #7c3aed;background:#faf5ff;border-radius:8px;padding:12px 16px;margin:12px 0">
  <div class="sc-review-hd">
    <span class="sc-review-icon">&#9997;&#65039;</span>
    <div>
      <div class="sc-review-title" style="color:#7c3aed">Proルート（二次流通仕入れ → 別市場売却）</div>
      <div class="sc-review-sub">新品・未使用・未開封のみ。<strong>推奨：ヤフオク/メルカリ未使用 → eBay/StockX、Amazon/楽天新品 → 買取店/海外</strong>。
出品・送料・手数料・在庫・為替リスクが発生します。経験者向けです（新品・未使用・未開封のみ）。
買取店→買取店ルートは利幅が薄く要確認のため下位に表示します。</div>
    </div>
  </div>
</div>''')
                # 推奨/通常ルート（買取店→買取店を除く）を上位表示
                if _pro_top:
                    parts.append(_make_route_table(_pro_top[:10],
                                 title_label=f"Proルート 推奨（{len(_pro_top)}件）"))
                # 買取店→買取店ルートは「要確認（下位）」セクションへ
                if _pro_low:
                    parts.append('<div class="sc-route-bb2bb-note">'
                                 '&#9888; 以下は買取店→買取店ルートです。利幅が薄く価格変動リスクがあるため要確認・参考扱いです。'
                                 '</div>')
                    parts.append(_make_route_table(_pro_low[:10],
                                 title_label="Proルート 要確認（買取店→買取店）"))

            # データなしフォールバック（DB routes は存在するが分類不能の場合）
            if not beginner_routes and not pro_routes and display_routes:
                best = display_routes[0]
                parts.append(_make_best_card(best))
                rest = display_routes[1:10]
                if rest:
                    parts.append(_make_route_table(rest, title_label=f"2位〜10位 {display_label}"))

        # ── 合成初心者ルート（DB routes が空 or 不足の場合に beginner_deals から生成）──
        if _synth_routes:
            parts.append('''<div class="sc-review-section" style="border-left:4px solid #059669;background:#f0fdf4;border-radius:8px;padding:12px 16px;margin:12px 0">
  <div class="sc-review-hd">
    <span class="sc-review-icon">&#128100;</span>
    <div>
      <div class="sc-review-title" style="color:#059669">初心者ルート（公式店 → 買取店）</div>
      <div class="sc-review-sub">毎日取得した買取価格データから自動算出。公式定価で購入して買取店に売却した場合の参考差益です。</div>
    </div>
  </div>
</div>''')
            # 合成ルートをテーブル形式で表示
            _synth_rows = []
            for i, r in enumerate(_synth_routes[:15], 1):
                _buy_a = (f'<a href="{_esc(r["buy_url"])}" target="_blank" rel="noopener noreferrer" '
                          f'class="sc-mini-link" data-track="sedori_buy_click">{_esc(r["buy_shop_name"])}</a>'
                          if r.get("buy_url") else _esc(r["buy_shop_name"]))
                _sell_a = (f'<a href="{_esc(r["sell_url"])}" target="_blank" rel="noopener noreferrer" '
                           f'class="sc-mini-link" data-track="sedori_sell_click">{_esc(r["sell_shop_name"])}</a>'
                           if r.get("sell_url") else _esc(r["sell_shop_name"]))
                _cat_badge = f'<span style="font-size:0.65rem;color:#6b7280;margin-left:4px">[{_esc(r["category"])}]</span>' if r.get("category") else ''
                _synth_rows.append(
                    f'<tr class="sc-route-row">'
                    f'<td class="sc-rank-cell">#{i}</td>'
                    f'<td class="sc-prod-cell">{_esc(r["product_name"])}{_cat_badge}</td>'
                    f'<td class="sc-shop-cell">{_buy_a}</td>'
                    f'<td class="sc-price-cell sc-col-red">¥{r["buy_price"]:,}</td>'
                    f'<td class="sc-shop-cell">{_sell_a}</td>'
                    f'<td class="sc-price-cell sc-col-green">¥{r["sell_price"]:,}</td>'
                    f'<td class="sc-profit-cell sc-col-green">+¥{r["net_profit"]:,}</td>'
                    f'<td class="sc-rate-cell"><span class="sc-rate-badge sc-rate-pos">+{r["profit_rate"]:.1%}</span></td>'
                    f'</tr>'
                )
            if _synth_rows:
                parts.append(f'''<div class="sc-list-section">
  <div class="sc-list-header">
    <span class="sc-list-title">&#128202; 初心者ルート一覧（公式定価→買取店、参考差益）</span>
    <span class="sc-list-count">{len(_synth_routes[:15])}件</span>
  </div>
  <div class="sc-table-scroll">
    <table class="sc-table">
      <thead><tr>
        <th>#</th><th>商品</th><th>仕入れ（公式定価）</th><th>定価</th>
        <th>売却先（買取店）</th><th>買取価格</th><th>参考差益</th><th>利益率</th>
      </tr></thead>
      <tbody>{"".join(_synth_rows)}</tbody>
    </table>
  </div>
</div>''')

        # ── 免責 ──
        parts.append('''<div class="sc-disclaimer">
&#9888; 価格は参考値です。実際の購入・売却前に各店舗の公式サイトで最新価格をご確認ください。
利益を保証するものではありません。転売・せどり行為に関するリスクはご自身でご判断ください。
</div>
</div>''')

        return "\n".join(parts)

    def _source_badge(self, data_source: str) -> str:
        """data_source に応じた取得種別バッジ HTML を返す。"""
        ds = str(data_source) if data_source else ""
        if ds == "auto_scraped":
            return '<span class="badge-auto-scraped">自動取得</span>'
        elif ds == "product_not_listed":
            return '<span class="badge-not-listed">現在未掲載</span>'
        elif ds == "fetch_failed":
            return '<span class="badge-fetch-failed">取得失敗</span>'
        elif ds == "resale_market":
            return '<span class="badge-manual">二次流通</span>'
        elif ds.startswith("manual"):
            return '<span class="badge-manual">手動</span>'
        elif ds == "live":
            return '<span class="badge-auto-scraped">LIVE</span>'
        else:
            return '<span class="badge-manual">—</span>'

    @staticmethod
    def _buyback_missing_reason(raw_rows) -> str:
        """新品・未使用・未開封の買取価格が無い場合の理由ラベルを返す（Task 3）。
        生の buyback 行（未フィルタ）から判定する。新品・未使用価格があれば '' を返す。
          - 新品買取価格なし / 中古価格のみ取得 / サイト制限中 / 商品未掲載 / 取得失敗
        """
        rows = raw_rows or []
        # 買取店の行のみで判定する（二次流通=resale_market・フリマ/海外店名は買取店ではないため除外）。
        _shop_rows = [
            r for r in rows
            if r.get('data_source') != 'resale_market'
            and not DailyLPGenerator._is_resale_shop(r.get('shop_name', ''))
        ]
        # 新品・未使用・未開封（中古でない）かつ価格>0 の「買取店」行があるか
        _has_new = any(
            (r.get('buyback_price', 0) or 0) > 0
            and not DailyLPGenerator._cond_is_used(r.get('condition', ''))
            for r in _shop_rows
        )
        if _has_new:
            return ''
        if not _shop_rows:
            return '新品買取価格なし'
        _priced = [r for r in _shop_rows if (r.get('buyback_price', 0) or 0) > 0]
        _used_priced = [r for r in _priced if DailyLPGenerator._cond_is_used(r.get('condition', ''))]
        def _blob(r):
            return (str(r.get('reason', '') or '') + ' ' + str(r.get('notes', '') or '')).lower()
        _blocked = any(('block' in _blob(r)) or ('429' in _blob(r)) or ('cloudflare' in _blob(r))
                       or ('rate' in _blob(r)) for r in _shop_rows)
        _notlisted = any(r.get('data_source') == 'product_not_listed' for r in _shop_rows)
        _failed = any(r.get('data_source') == 'fetch_failed' for r in _shop_rows)
        # 買取店の価格はあるが全て中古 → 中古価格のみ取得
        if _priced and _used_priced and len(_used_priced) == len(_priced):
            return '中古価格のみ取得'
        if _blocked:
            return 'サイト制限中'
        if _notlisted and not _priced:
            return '商品未掲載'
        if _failed and not _priced:
            return '取得失敗'
        return '新品買取価格なし'

    @staticmethod
    def _profit_badge(net_profit_jpy) -> tuple:
        """利益額に応じた初心者カードのバッジ (css_class, label) を返す（Task 1）。
        profit>0 のカードでは「様子見」を出さない。
          +10,000円以上    → 利益あり
          +3,000〜+9,999円 → 小幅利益
          +1〜+2,999円     → 微益
          0円以下          → 監視中（様子見）
        """
        try:
            np = int(net_profit_jpy or 0)
        except (TypeError, ValueError):
            np = 0
        if np >= 10000:
            return ('badge-easy', '利益あり')
        if np >= 3000:
            return ('badge-easy', '小幅利益')
        if np >= 1:
            return ('badge-watch', '微益')
        return ('badge-watch', '監視中')

    @staticmethod
    def _condition_label(cond) -> str:
        """内部の状態コード（new_unopened_simfree 等）を日本語表示に変換する。
        LP には内部コードを一切出さない（Task 2）。"""
        c = (str(cond or '')).strip()
        if not c:
            return '新品未開封'
        _map = {
            'new_unopened_simfree': '新品未開封 SIMフリー',
            'new_unopened':         '新品未開封',
            'new':                  '新品',
            'unused':               '未使用',
            'sealed':               '新品未開封',
            'used_a':               '中古A',
            'used_b':               '中古B',
            'used_c':               '中古C',
        }
        key = c.lower()
        if key in _map:
            return _map[key]
        # 既に日本語など、コードでなければそのまま返す
        return c

    @staticmethod
    def _source_label_jp(data_source) -> str:
        """内部の data_source コードを日本語の取得方法ラベルに変換する（Task 2）。"""
        ds = str(data_source or '')
        if ds == 'auto_scraped':
            return '自動取得'
        if ds in ('manual_today', 'manual_confirmed') or ds.startswith('manual'):
            return '手動確認'
        if ds == 'resale_market':
            return '二次流通（参考）'
        if ds == 'live':
            return 'リアルタイム'
        if ds in ('fetch_failed', 'product_not_listed'):
            return '取得失敗'
        return '参考データ'

    def _data_source_badge(self, data_source: str, shop_name: str = "") -> str:
        """data_source フィールドに基づくバッジ HTML を返す（比較テーブル用）。"""
        ds = data_source or ''
        if ds == 'auto_scraped':
            return '<span class="badge-auto">自動取得</span>'
        elif ds in ('manual_today', 'manual_confirmed'):
            return '<span class="badge-manual">手動確認</span>'
        elif ds == 'resale_market':
            return '<span class="badge-manual">二次流通</span>'
        elif ds in ('fetch_failed', 'product_not_listed'):
            return '<span class="badge-failed">取得失敗</span>'
        else:
            return '<span class="badge-manual">参考データ</span>'

    def _freshness_label(self, observed_at_str: str, data_source: str) -> str:
        """データ鮮度ラベルを返す。
        - 24h超 → 「参考値」
        - 48h超 → 「要確認」
        - 手動CSV由来 → 「手動確認データ」表示・「最新」は使わない
        - 実際に取得した価格ではない場合は「最新」と表示しない
        """
        is_not_listed = (str(data_source) == "product_not_listed")
        is_failed = (str(data_source) == "fetch_failed")
        is_auto   = (str(data_source) == "auto_scraped")   # 自動スクレイピング成功
        is_resale = (str(data_source) == "resale_market")  # 二次流通参考価格
        is_manual = bool(data_source and (str(data_source).startswith("manual") or is_resale))  # 手動CSV由来 or 二次流通
        # product_not_listed: この店舗では現在、該当商品の掲載が確認できない
        if is_not_listed:
            return '<span class="freshness-not-listed" title="この店舗では現在、該当商品の掲載が確認できません">現在未掲載</span>'
        # fetch_failed は価格取得失敗を示す特殊値
        if is_failed:
            return '<span class="freshness-warn freshness-fetch-failed" title="価格取得失敗">取得失敗 / 要確認</span>'
        try:
            if observed_at_str:
                dt = datetime.fromisoformat(str(observed_at_str))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=JST)
                dt_jst = dt.astimezone(JST)
                hours = (datetime.now(tz=JST) - dt_jst).total_seconds() / 3600
                date_label = dt_jst.strftime("%m/%d %H:%M")
                if hours < 24:
                    if is_auto:
                        # 自動取得データ: 緑バッジ + 取得時刻
                        freshness = f"価格確認: {date_label}"
                        css = "freshness-auto"
                    elif is_manual:
                        # 手動データは「最新」と表示しない。「価格確認: MM/DD HH:mm」形式で統一
                        freshness = f"価格確認: {date_label}"
                        css = "freshness-recent"
                    else:
                        if hours < 6:
                            freshness = "最新"
                            css = "freshness-live"
                        else:
                            freshness = f"{int(hours)}時間前"
                            css = "freshness-recent"
                elif hours < 48:
                    # 24h以上古い → 「要更新 / N日前」で統一（参考値表記廃止）
                    days = max(1, int(hours // 24))
                    freshness = f"要更新 / {days}日前"
                    css = "freshness-stale"
                else:
                    # 48h以上古い → 同じ「要更新 / N日前」、cssのみ強調
                    days = int(hours // 24)
                    freshness = f"要更新 / {days}日前"
                    css = "freshness-warn"
            else:
                freshness = "取得日時不明"
                css = "freshness-unknown"
        except Exception:
            freshness = "取得日時不明"
            css = "freshness-unknown"
        # 出所ラベル
        if is_auto:
            source_label = "自動取得"
        elif is_manual:
            source_label = "参考データ"
        elif data_source == "live":
            source_label = "🟢live"
        else:
            source_label = ""
        inner = f"{_esc(source_label)} / {_esc(freshness)}" if source_label else _esc(freshness)
        return f'<span class="{css}" title="observed_at: {_esc(str(observed_at_str))}">{inner}</span>'

    # ----- Tab: 初級者向け -----


    def _tab_beginner(self, easy_deals, watch_deals, buyback_by_product: dict = None,
                       latest_buyback_at: Optional[datetime] = None,
                       monitoring_deals: list = None,
                       fetch_failed_deals: list = None,
                       market_prices_by_product: dict = None) -> str:
        """初心者向けタブ（v8: 一次流通仕入れ→二次流通販売モデル、海外価格対応）"""
        bybp = buyback_by_product or {}
        mprices = market_prices_by_product or {}
        monitoring_deals   = monitoring_deals   or []
        fetch_failed_deals = fetch_failed_deals or []

        # resale_market 売却先キーワード（Beginner では表示しない）
        _RESALE_SHOP_KWS = ('ヤフオク', 'yahoo auction', 'メルカリ', 'mercari',
                            'ラクマ', 'rakuma', 'ebay', 'stockx')

        def _is_resale_shop_kw(shop_name: str) -> bool:
            """売却先が resale_market（フリマ・海外）かどうか判定。"""
            sl = (shop_name or '').lower()
            return any(kw.lower() in sl for kw in _RESALE_SHOP_KWS)

        def _enrich_from_sell_candidates(deal, rows: list):
            """buyback_rows の有効価格で deal.best_buyback_price を補完する。
            DB の best_buyback_price が resale_market ショップ由来の場合は
            buyback_rows（resale 除外済み）の最高価格で強制上書きする。
            """
            if not rows:
                # 有効な買取店行なし → resale 由来のショップ名をクリア
                stored_shop = deal.best_buyback_shop or ''
                if _is_resale_shop_kw(stored_shop):
                    return deal.copy(update={
                        'best_buyback_shop': '—',
                        'best_buyback_price': 0,
                        'net_profit_jpy': 0,
                        'gross_profit_jpy': 0,
                    })
                return deal
            valid_rows = [
                r for r in rows
                if r.get('buyback_price', 0) > 0
                and r.get('data_source', '') not in ('fetch_failed', 'product_not_listed')
                and r.get('confidence', 'high') != 'low'
            ]
            if not valid_rows:
                # resale 由来ショップをクリア
                stored_shop = deal.best_buyback_shop or ''
                if _is_resale_shop_kw(stored_shop):
                    return deal.copy(update={
                        'best_buyback_shop': '—',
                        'best_buyback_price': 0,
                        'net_profit_jpy': 0,
                        'gross_profit_jpy': 0,
                    })
                return deal
            best_row = max(valid_rows, key=lambda r: r.get('buyback_price', 0))
            best_price = best_row.get('buyback_price', 0)
            stored_bp = deal.best_buyback_price or 0
            stored_shop = deal.best_buyback_shop or ''
            # 既存値が resale 由来の場合は価格に関わらず buyback_rows の最高値で上書き
            _force_update = _is_resale_shop_kw(stored_shop)
            if best_price <= stored_bp and not _force_update:
                return deal
            # DB の値より buyback_rows の方が高い → 補完
            official = deal.official_price_jpy or 0
            costs = 1800  # 固定: 送料+振込手数料+移動コスト
            gross = best_price - official
            net = gross - costs
            # user_level 再評価
            sale_method = getattr(deal, 'sale_method', None) or 'normal'
            stock_status = getattr(deal, 'stock_status', None) or ''
            difficulty = getattr(deal, 'difficulty_score', None) or 0.0
            # 100.0 は primary_to_secondary_scanner._make_monitoring() のセンチネル値
            # → sale_method + 商品名から実際の難易度を再推定する
            if difficulty >= 100.0:
                if sale_method == 'normal':
                    difficulty = 0.0
                    _name_lower = (getattr(deal, 'product_name', '') or '').lower()
                    if any(_kw in _name_lower for _kw in ('monochrome', 'limited', '限定')):
                        difficulty += 0.15
                elif sale_method == 'lottery':
                    difficulty = 0.70
                elif sale_method == 'discontinued':
                    difficulty = 0.80
                elif sale_method == 'soldout':
                    difficulty = 0.60
                else:
                    difficulty = 0.0
                difficulty = min(1.0, difficulty)
            is_normal = sale_method == 'normal'
            stock_ok = 'SOLD' not in stock_status.upper()
            if is_normal and stock_ok and net >= 5000 and difficulty <= 0.35:
                new_level = 'beginner_easy'
            elif is_normal and net >= 3000 and difficulty <= 0.50:
                new_level = 'beginner_watch'
            elif gross >= 30000:
                new_level = 'advanced_high_profit'
            elif net > 0:
                new_level = 'beginner_watch'
            else:
                new_level = 'monitoring'
            net_rate = (net / official) if official > 0 else 0.0
            return deal.copy(update={
                'best_buyback_price': best_price,
                'best_buyback_shop': best_row.get('shop_name', deal.best_buyback_shop or ''),
                'best_buyback_url': best_row.get('buyback_url', deal.best_buyback_url or ''),
                'best_link_verified': bool(best_row.get('buyback_url', '')),
                'buyback_condition': best_row.get('condition', deal.buyback_condition or ''),
                'gross_profit_jpy': gross,
                'net_profit_jpy': net,
                'net_profit_rate': net_rate,
                'user_level': new_level,
            })

        def _get_overseas(deal) -> tuple[int | None, str, str, str]:
            """deal の海外価格（price_jpy, source, observed_at, collector_method）を取得する。"""
            pid = getattr(deal, 'product_id', '') or ''
            snap = mprices.get(pid)
            if snap:
                if isinstance(snap, list):
                    snap = snap[0] if snap else None
            if snap:
                if isinstance(snap, dict):
                    return (snap.get('overseas_price_jpy'), snap.get('overseas_source', ''),
                            snap.get('scanned_at', ''), snap.get('overseas_collector_method', ''))
                return (getattr(snap, 'overseas_price_jpy', None), getattr(snap, 'overseas_source', ''),
                        str(getattr(snap, 'scanned_at', '')), getattr(snap, 'overseas_collector_method', ''))
            return None, '', '', ''
        parts = []

        # データ鮮度バナー
        freshness_banner = ""
        if latest_buyback_at is not None:
            _now_jst = datetime.now(tz=JST)
            _lba = latest_buyback_at
            if _lba.tzinfo is None:
                _lba = _lba.replace(tzinfo=JST)
            age_h = (_now_jst - _lba.astimezone(JST)).total_seconds() / 3600
            if age_h >= 168:
                freshness_banner = (
                    '<div class="data-stale-banner data-stale-critical">'
                    f'&#128721; 買取価格データが{age_h:.0f}時間（7日超）更新されていません。'
                    '表示価格は古い情報です。必ずリンク先で最新価格を確認してください。'
                    '</div>'
                )
            elif age_h >= 48:
                freshness_banner = (
                    '<div class="data-stale-banner data-stale-warn">'
                    f'&#9888;&#65039; 参考データを表示中（最終取得：{age_h:.0f}時間前）。'
                    '価格は参考値です。リンク先で最新価格をご確認ください。'
                    '</div>'
                )
            elif age_h >= 24:
                freshness_banner = (
                    '<div class="data-stale-banner data-stale-warn">'
                    '&#9888;&#65039; 買取価格が24時間以上更新されていません。'
                    '「要更新」案件の価格はリンク先で要確認です。'
                    '</div>'
                )

        # ── Info banner ──
        parts.append('<div class="info-banner blue">\n'
                     '<div class="ib-title">&#128100; 初心者向け：公式店定価購入 &rarr; 最高買取価格との差益</div>\n'
                     '<strong>公式店・正規店で定価購入した新品・未使用品を、買取店で売却した場合の差益を比較します。</strong>'
                     'フリマ出品・海外販売・個人間取引は不要です。<strong>公式で買って買取店に売るだけです。</strong>\n'
                     '<strong>対象は新品・未使用・未開封のみです。</strong>\n'
                     '<strong>掲載価格は更新時点の参考値です。差益は保証されません。購入前に必ず各店舗の最新価格をご確認ください。</strong>\n'
                     '</div>')

        # deal.scanned_at ベースで鮮度判定（buyback_prices.observed_at ではなくスキャン日時で統一）
        # ランキングも同じ beginner_deals テーブルを参照するため、スキャン日時で整合を保つ
        def _bybp_age_h(deal):
            """deal.scanned_at からの経過時間（h）を返す。
            スキャンが新しければ、利用した buyback 価格の観測日時に関わらず表示する。
            scanned_at がない場合は 0.0（除外しない）。
            """
            scanned_at = getattr(deal, 'scanned_at', None)
            if scanned_at:
                try:
                    if isinstance(scanned_at, str):
                        dt = datetime.fromisoformat(scanned_at)
                    else:
                        dt = scanned_at
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=JST)
                    return (datetime.now(tz=JST) - dt.astimezone(JST)).total_seconds() / 3600
                except Exception:
                    pass
            return 0.0  # scanned_at なし → 除外しない

        # ── 手動価格の2段階鮮度管理（observed_at 基準）──
        #   7日超(WARNING_STALE_H)  : 利益判定に使用可。ただしカードに「要更新」を表示。
        #   14日超(EXCLUDE_STALE_H) : 利益判定から除外し、監視中へ降格（カードは残す）。
        WARNING_STALE_H = 168.0   # 7日
        EXCLUDE_STALE_H = 336.0   # 14日
        _STALE_EXCLUDE_H = EXCLUDE_STALE_H  # 後方互換（参照用）

        def _price_obs_age_h(deal):
            """deal を裏付ける手動買取価格の observed_at（最新）からの経過時間(h)。
            manual_today / manual_confirmed の observed_at を優先。無ければ scanned_at。"""
            rows = bybp.get(getattr(deal, 'product_id', '') or '', [])
            newest = None
            for r in rows:
                if (r.get('buyback_price', 0) or 0) <= 0:
                    continue
                if r.get('data_source') in ('fetch_failed', 'product_not_listed', 'resale_market'):
                    continue
                o = r.get('observed_at', '')
                if not o:
                    continue
                try:
                    dt = datetime.fromisoformat(str(o))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=JST)
                    dt = dt.astimezone(JST)
                    if newest is None or dt > newest:
                        newest = dt
                except Exception:
                    pass
            if newest is not None:
                return (datetime.now(tz=JST) - newest).total_seconds() / 3600
            return _bybp_age_h(deal)

        def _apply_stale_downgrade(deal):
            """14日超の手動価格は利益判定から除外し、監視中へ降格する（カードは残す）。
            降格理由は notes に '||STALE14' を付与して後段の監視中カードで表示する。"""
            try:
                age = _price_obs_age_h(deal)
            except Exception:
                age = 0.0
            if age > EXCLUDE_STALE_H:
                return deal.copy(update={
                    'best_buyback_price': 0,
                    'best_buyback_shop': '—',
                    'best_buyback_url': '',
                    'net_profit_jpy': 0,
                    'gross_profit_jpy': 0,
                    'net_profit_rate': 0.0,
                    'user_level': 'monitoring',
                    'notes': ((getattr(deal, 'notes', '') or '') + '||STALE14'),
                })
            return deal

        # 14日超は「除外」せず監視中へ降格するため、ここでは全件保持する（降格は enrich 後に適用）。
        _easy_filtered  = list(easy_deals)
        _watch_filtered = list(watch_deals)

        # 中古条件チェック: 新品/未使用/未開封以外の条件は初心者メイン表示から除外
        # 中古A / 美品 / 良品 / used / B品 / C品 / ジャンク / 開封済 などはNG
        _USED_COND_KEYWORDS = ('中古', '美品', '良品', 'used', 'b品', 'c品', 'ジャンク', '開封済')
        def _is_used_cond(deal):
            cond = (getattr(deal, 'buyback_condition', '') or '').lower()
            return any(kw in cond for kw in _USED_COND_KEYWORDS)

        _easy_main   = [d for d in _easy_filtered  if not _is_used_cond(d)]
        _watch_main  = [d for d in _watch_filtered if not _is_used_cond(d)]
        # 中古条件案件は「参考データ」fold に回す（価格根拠を要確認）
        _used_cond_deals = (
            [d for d in _easy_filtered  if _is_used_cond(d)] +
            [d for d in _watch_filtered if _is_used_cond(d)]
        )

        # product_id で重複除去（同じ商品が複数レベルで来る場合の対策）
        # 利益降順でソートして重複除去
        _all_combined = (
            list(_easy_main) +
            list(_watch_main) +
            list(monitoring_deals) +
            list(fetch_failed_deals)
        )
        seen_pids = set()
        deduped_all = []
        for d in sorted(_all_combined, key=lambda x: x.net_profit_jpy or 0, reverse=True):
            if d.product_id not in seen_pids:
                seen_pids.add(d.product_id)
                deduped_all.append(d)

        # ── sell_candidates 補完: buyback_rows の最高価格で deal を補完 ──
        # 売却先比較テーブルに有効価格があれば DB の best_buyback_price より優先して使う。
        # これにより「比較テーブルに価格あり → メイン価格未取得」の不整合を防ぐ。
        # 共通メソッドで補完（中古・二次流通価格は完全除外）。
        # 補完で user_level が monitoring に降格した場合は再分類するため、後段で再フィルタする。
        deduped_all = [self._enrich_deal(d, bybp.get(d.product_id, [])) for d in deduped_all]
        # 補完後に中古条件へ変化した deal を main から除外（_is_used_cond 再適用）
        deduped_all = [d for d in deduped_all if not _is_used_cond(d)]
        # 14日超の手動価格は enrich 後に監視中へ降格（再昇格を防ぐため最後に適用）。
        deduped_all = [_apply_stale_downgrade(d) for d in deduped_all]

        # ── サマリバー（利益あり件数 / 監視中件数 / 取得失敗件数）──
        _profit_deals_all  = [d for d in deduped_all if (d.net_profit_jpy or 0) > 0]
        _monitor_deals_all = [d for d in deduped_all if getattr(d, 'user_level', '') == 'monitoring']
        _failed_deals_all  = [d for d in deduped_all if getattr(d, 'user_level', '') == 'fetch_failed']
        parts.append(
            f'<div class="beginner-summary-bar">'
            f'利益あり: <strong>{len(_profit_deals_all)}</strong>件 ／ '
            f'監視中: <strong>{len(_monitor_deals_all)}</strong>件 ／ '
            f'取得失敗: <strong>{len(_failed_deals_all)}</strong>件'
            f'</div>'
        )

        # ── ジャンル定義 ──
        # genre値: iphone/tablet/pc/wearable/audio/game_console/camera
        KNOWN_GENRES = {'iphone', 'tablet', 'pc', 'wearable', 'audio', 'game_console', 'camera'}
        GENRE_GROUPS = [
            ('iphone',       '&#128241; iPhone / スマホ',    'category-beginner-iphone'),
            ('tablet',       '&#9645; タブレット / iPad',     'category-beginner-tablet'),
            ('pc',           '&#128187; PC / Mac',            'category-beginner-pc'),
            ('camera',       '&#128247; カメラ',              'category-beginner-camera'),
            ('wearable',     '&#8987; ウェアラブル',           'category-beginner-wearable'),
            ('audio',        '&#127911; オーディオ',           'category-beginner-audio'),
            ('game_console', '&#127918; ゲーム機',             'category-beginner-game'),
            ('other',        '&#128230; その他',               'category-beginner-other'),
        ]

        # ── 監視中 / 取得失敗カードはジャンルを横断して下部に集約（Task 4）──
        # 上部＝利益ありカードのみ。監視中・取得失敗は最下部の折りたたみセクションへ。
        _global_monitoring_html = []
        _global_monitoring_count = 0  # 監視中カードの総数（ジャンル横断）
        _global_failed_html = []

        genre_rendered = False
        for genre_key, genre_label, anchor_id in GENRE_GROUPS:
            # このジャンルの全案件を抽出
            if genre_key == 'other':
                genre_deals = [d for d in deduped_all
                               if getattr(d, 'category', '') not in KNOWN_GENRES]
            else:
                genre_deals = [d for d in deduped_all if getattr(d, 'category', '') == genre_key]

            if not genre_deals:
                continue

            genre_rendered = True

            # 状態別分類
            profit_deals    = [d for d in genre_deals if (d.net_profit_jpy or 0) > 0]
            monitoring_genre = [d for d in genre_deals if getattr(d, 'user_level', '') == 'monitoring']
            ff_genre        = [d for d in genre_deals if getattr(d, 'user_level', '') == 'fetch_failed']

            # 有効カード判定: beginner_easy / beginner_watch が1件もない場合は空状態とみなす
            _has_beginner_cards = any(
                getattr(d, 'user_level', '') in ('beginner_easy', 'beginner_watch')
                for d in genre_deals
            )

            # ジャンルヘッダー（件数・内訳付き）
            total_in_genre = len(genre_deals)
            summary_text = (
                f'利益あり {len(profit_deals)} / '
                f'監視中 {len(monitoring_genre)} / '
                f'取得失敗 {len(ff_genre)}'
            )

            margin_top = '' if anchor_id == 'category-beginner-iphone' else ' style="margin-top:40px;scroll-margin-top:80px"'
            parts.append(
                f'<div id="{anchor_id}"{margin_top}>'
                f'<div class="sec-head">'
                f'<div class="sec-title">{genre_label}</div>'
                f'<div class="sec-badge">{total_in_genre}件</div>'
                f'</div>'
                f'<div class="genre-status-summary">{summary_text}</div>'
            )

            # 利益あり
            if profit_deals:
                parts.append('<div class="status-subsection"><div class="status-subhead status-profit">利益あり</div><div class="cards-grid">')
                for d in profit_deals:
                    rows = bybp.get(d.product_id, [])
                    # 利益額に応じてバッジを段階化（Task 1）。
                    # profit>0 のカードでは「様子見」を出さない。
                    _np = d.net_profit_jpy or 0
                    badge_cls, label = self._profit_badge(_np)
                    _ovs_p, _ovs_s, _ovs_obs, _ovs_method = _get_overseas(d)
                    parts.append(self._deal_card(d, badge_cls, label, buyback_rows=rows,
                                                 overseas_price_jpy=_ovs_p, overseas_source=_ovs_s,
                                                 overseas_observed_at=_ovs_obs, overseas_collector_method=_ovs_method))
                parts.append('</div></div>')

            # 監視中 / 赤字 → 下部のグローバル折りたたみへジャンル別に集約（Task 3）
            if monitoring_genre:
                _mon_cards = [
                    self._deal_card_monitoring(d, buyback_rows=bybp.get(d.product_id, []))
                    for d in monitoring_genre
                ]
                _global_monitoring_count += len(_mon_cards)
                _global_monitoring_html.append(
                    f'<div class="monitoring-genre-group">'
                    f'<div class="monitoring-genre-head">{genre_label}'
                    f'<span class="mon-genre-count">{len(_mon_cards)}件</span></div>'
                    f'<div class="cards-grid">' + ''.join(_mon_cards) + '</div>'
                    f'</div>'
                )

            # 取得失敗 → 下部のグローバル折りたたみへ集約
            for d in ff_genre:
                rows = bybp.get(d.product_id, [])
                _global_failed_html.append(self._deal_card_fetch_failed(d, buyback_rows=rows))

            # beginner_easy / beginner_watch カードが0件（fetch_failed のみ）の場合は空状態メッセージを表示
            if not _has_beginner_cards:
                parts.append(
                    '<div class="collector-empty-notice">'
                    '<p>現在、十分な自動取得データがありません。取得成功店舗が増え次第、案件を表示します。</p>'
                    '<p><a href="collector_report.html">取得状況の詳細はこちら</a></p>'
                    '</div>'
                )

            # 中古条件案件（参考データ fold）: このジャンルの中古条件案件を折りたたみで表示
            if genre_key == 'other':
                _used_genre = [d for d in _used_cond_deals if getattr(d, 'category', '') not in KNOWN_GENRES]
            else:
                _used_genre = [d for d in _used_cond_deals if getattr(d, 'category', '') == genre_key]
            # 中古条件案件は非表示（新品・未使用・未開封のみ方針）
            if False and _used_genre:  # noqa: Dead code – 中古データ表示は無効化
                parts.append(
                    f'<details class="status-subsection used-cond-details" style="margin-top:16px">'
                    f'<summary class="status-subhead" style="cursor:pointer;color:var(--ink3);font-size:0.82rem;">'
                    f'&#128218; 参考データ（中古・開封済み条件） '
                    f'<span class="ff-count-badge">{len(_used_genre)}件</span>'
                    f'<span class="ff-expand-hint">（クリックで展開）</span>'
                    f'</summary>'
                    f'<div style="font-size:0.78rem;color:var(--ink3);padding:6px 12px 2px;">&#9888; 以下は中古・開封済みなど新品以外の買取条件が付いた参考データです。初心者向け利益計算には含まれていません。</div>'
                    f'<div class="cards-grid">'
                )
                for d in _used_genre:
                    rows = bybp.get(d.product_id, [])
                    badge_cls = 'badge-easy' if getattr(d, 'user_level', '') == 'beginner_easy' else 'badge-watch'
                    label = '低難度（参考）' if getattr(d, 'user_level', '') == 'beginner_easy' else '様子見（参考）'
                    _ovs_p, _ovs_s, _ovs_obs, _ovs_method = _get_overseas(d)
                    parts.append(self._deal_card(d, badge_cls, label, buyback_rows=rows,
                                                 overseas_price_jpy=_ovs_p, overseas_source=_ovs_s,
                                                 overseas_observed_at=_ovs_obs, overseas_collector_method=_ovs_method))
                parts.append('</div></details>')

            # ゲーム機への注釈
            if genre_key == 'game_console':
                parts.append('<div class="caution" style="margin-top:16px;font-size:0.82rem;">'
                             '&#128204; <strong>限定・抽選モデル</strong>（Nintendo Switch 2 抽選など）は '
                             '<a href="#tab-lottery" class="inline-link">抽選情報タブ</a> または '
                             '<a href="#tab-advanced" class="inline-link">Pro向けタブ</a> をご確認ください。</div>')

            parts.append('</div>')  # genre block end

        # ── 監視中カードを下部のグローバル折りたたみセクションに表示（Task 4）──
        #   利益ありカード（上部）より下に配置し、デフォルト折りたたみ。
        if _global_monitoring_html:
            parts.append(
                f'<details class="monitoring-global-section">'
                f'<summary class="monitoring-global-summary">'
                f'&#128064; 監視中の商品を見る '
                f'<span class="mon-count-badge">{_global_monitoring_count}件</span>'
                f'<span class="ff-expand-hint">（クリックで展開）</span>'
                f'</summary>'
                f'<div class="monitoring-genre-groups">'
                + ''.join(_global_monitoring_html)
                + '</div></details>'
            )

        # ── 取得失敗カードも下部のグローバル折りたたみセクションに表示 ──
        if _global_failed_html:
            parts.append(
                f'<details class="status-subsection fetch-failed-details">'
                f'<summary class="status-subhead status-fetch-failed fetch-failed-summary">'
                f'取得失敗 / 要確認 '
                f'<span class="ff-count-badge">{len(_global_failed_html)}件</span>'
                f'<span class="ff-expand-hint">（クリックで展開）</span>'
                f'</summary>'
                f'<div class="cards-grid">'
                + ''.join(_global_failed_html)
                + '</div></details>'
            )

        # 全案件が表示不能な場合の空状態表示
        if not genre_rendered:
            parts.append(
                '<div class="empty-state" style="padding:40px 16px;text-align:center;">'
                '<span style="font-size:2rem;">&#128683;</span>'
                '<p style="margin:12px 0 4px;font-weight:700;color:var(--ink)">表示できる案件がありません</p>'
                '<p style="font-size:0.85rem;color:var(--ink2)">表示できる案件がありません。データが揃い次第、自動で案件を表示します。</p>'
                '<p style="font-size:0.85rem;color:var(--ink2)">価格データが取得できていない可能性があります。しばらくお待ちください。</p>'
                '</div>'
            )

        return freshness_banner + '\n'.join(parts)

    def _deal_card_monitoring(self, d, buyback_rows: list = None) -> str:
        """監視中（赤字・データ取得中）案件カード HTML を生成する。
        Task 5: easy/watch カードと同じ UI 構造に統一。
        Task 6: price=0 は利益計算に使わない（「未取得」表示）。
        """
        # 新品・未使用買取価格が無い理由は、フィルタ前の生データから判定する（Task 3）
        # 14日超で監視中へ降格された商品（notes に '||STALE14'）は鮮度理由を優先表示。
        _is_stale14 = 'STALE14' in (getattr(d, 'notes', '') or '')
        _missing_reason = ('手動確認データが14日以上前' if _is_stale14
                           else self._buyback_missing_reason(buyback_rows))
        # 中古(used)・二次流通(resale_market/フリマ・海外店名)行は買取店比較から完全除外
        if buyback_rows:
            buyback_rows = [
                r for r in buyback_rows
                if r.get('data_source') != 'resale_market'
                and not self._cond_is_used(r.get('condition', ''))
                and not self._is_resale_shop(r.get('shop_name', ''))
            ]
        pid       = _esc(d.product_id)
        _raw_pid  = getattr(d, 'product_id', '') or ''
        pid_alias = _raw_pid[len('prod_'):] if _raw_pid.startswith('prod_') else _raw_pid
        card_id_attr = f' id="product-{_esc(pid_alias)}"' if pid_alias else ''
        brand_val = _esc(getattr(d, 'brand', '') or '')
        brand_attr = f' data-brand="{brand_val}"' if brand_val else ''
        genre_cls = getattr(d, 'category', '') or ''
        stripe_cls = {'iphone': 'iphone', 'camera': 'camera', 'game_console': 'game'}.get(genre_cls, 'monitoring')
        genre_badge = {
            'iphone':       '<span class="badge badge-iphone">iPhone</span>',
            'tablet':       '<span class="badge badge-iphone">タブレット</span>',
            'pc':           '<span class="badge badge-iphone">PC / Mac</span>',
            'wearable':     '<span class="badge badge-iphone">ウェアラブル</span>',
            'audio':        '<span class="badge badge-iphone">オーディオ</span>',
            'camera':       '<span class="badge badge-camera">カメラ</span>',
            'game_console': '<span class="badge badge-game">ゲーム機</span>',
        }.get(genre_cls, '')
        name     = _esc(d.product_name or '—')
        official = d.official_price_jpy or 0
        # price=0 は未取得として扱う（Task 6）
        best_bp  = d.best_buyback_price if (d.best_buyback_price and d.best_buyback_price > 0) else None
        best_bp_str = f'¥{best_bp:,}' if best_bp else '未取得'
        best_shop = _esc(d.best_buyback_shop or '—')

        # 差益: price=0 があっても赤字判定しない。未取得なら「差益未確定」
        if best_bp and official > 0:
            diff = best_bp - official
            diff_str = (f'+¥{diff:,}' if diff >= 0 else f'−¥{abs(diff):,}')
            diff_cls = '' if diff >= 0 else ' neg'
            # profit > 0: 利益あり表示 / profit == 0: ほぼ同値 / profit < 0: 赤字
            if diff > 0:
                monitoring_profit_note = '定価購入→最高買取（参考値）'
            elif diff == 0:
                diff_str = '±¥0'
                monitoring_profit_note = 'ほぼ同値 / 価格変動を監視中'
            else:
                monitoring_profit_note = '現在は差益なし / 価格変動を監視中'
        else:
            diff_str = '計算不可（未取得）'
            diff_cls = ''
            monitoring_profit_note = '買取価格取得中 / 監視中'

        # 最終確認日（buyback_rows の最新 observed_at）
        updated_str = ''
        _ts_rows = [r for r in (buyback_rows or []) if r.get('data_source') != 'fetch_failed' and r.get('buyback_price', 0) > 0]
        if _ts_rows:
            _obs = _ts_rows[0].get('observed_at', '')
            if _obs:
                try:
                    _dt = datetime.fromisoformat(str(_obs))
                    if _dt.tzinfo is None:
                        _dt = _dt.replace(tzinfo=JST)
                    updated_str = (
                        f'<div class="updated-row"><span>&#128336;</span>'
                        f'価格確認：{_esc(_dt.astimezone(JST).strftime("%Y-%m-%d %H:%M JST"))}</div>'
                    )
                except Exception:
                    pass
        if not updated_str and hasattr(d, 'scanned_at') and d.scanned_at:
            updated_str = f'<div class="updated-row"><span>&#128336;</span>スキャン：{_esc(_jst_str(d.scanned_at))}</div>'

        # 公式リンク
        official_url = _esc(getattr(d, 'official_url', '') or '')
        official_btn = ''
        if official_url:
            icon = '&#128241;' if genre_cls == 'iphone' else ('&#128247;' if genre_cls == 'camera' else '&#127918;')
            lbl  = 'Apple Store で確認' if genre_cls == 'iphone' else '公式で確認'
            official_btn = f'<a href="{official_url}" target="_blank" rel="noopener" class="btn btn-secondary" data-track="product_click" data-product-id="{pid}">{icon} {lbl}</a>'

        # 売却先比較テーブル（買取店のみ）
        compare_html = ''
        rows_html = []
        # 監視中カードも resale_market（フリマ）行を除外してから評価
        if buyback_rows:
            buyback_rows = [r for r in buyback_rows if r.get('data_source') != 'resale_market']
        if buyback_rows:
            _normal_rows  = [r for r in buyback_rows if r.get('buyback_price', 0) > 0 and r.get('confidence', 'high') != 'low'][:5]
            _failed_rows_r = [r for r in buyback_rows if r.get('data_source') == 'fetch_failed']
            rank = 1
            for r in _normal_rows:
                r_price = r.get('buyback_price', 0)
                r_name  = _esc(r.get('shop_name') or r.get('shop_id') or '—')
                rank_cls = {1:'gold', 2:'silver', 3:'bronze'}.get(rank, 'other')
                r_url   = r.get('buyback_url', '') or ''
                r_link_verified = bool(r.get('link_verified', False))
                link_cell = (
                    f'<a href="{_esc(r_url)}" target="_blank" rel="noopener noreferrer" class="shop-check-btn normal" data-track="buyback_click" data-product-id="{pid}">確認</a>'
                    if (r_url and r_link_verified)
                    else '<span class="shop-check-btn normal" style="opacity:0.5;cursor:default;">公式で確認</span>'
                )
                rows_html.append(
                    f'<div class="shop-row">'
                    f'<div class="shop-rank {rank_cls}">{rank}</div>'
                    f'<div class="shop-name-col">{r_name}</div>'
                    f'<div class="shop-price-col">¥{r_price:,}</div>'
                    f'<div class="shop-diff-col"></div>'
                    f'<div class="shop-source-col"></div>'
                    f'<div class="shop-link-col">{link_cell}</div>'
                    f'</div>'
                )
                rank += 1
            for r in _failed_rows_r[:2]:
                r_name = _esc(r.get('shop_name') or r.get('shop_id') or '—')
                r_url  = r.get('buyback_url', '') or ''
                link_cell = (
                    f'<a href="{_esc(r_url)}" target="_blank" rel="noopener noreferrer" class="shop-check-btn normal" data-track="buyback_click" data-product-id="{pid}">確認</a>'
                    if r_url else '<span class="shop-check-btn normal" style="opacity:0.4;cursor:default;">確認不可</span>'
                )
                rows_html.append(
                    f'<div class="shop-row shop-row-failed">'
                    f'<div class="shop-rank" style="color:var(--ink3)">—</div>'
                    f'<div class="shop-name-col">{r_name}</div>'
                    f'<div class="shop-price-col" style="color:var(--ink3)">—</div>'
                    f'<div class="shop-diff-col"></div><div class="shop-source-col"></div>'
                    f'<div class="shop-link-col">{link_cell}</div>'
                    f'</div>'
                )
        if rows_html:
            compare_html = (
                '<div class="shop-table buyback-shop-table buyback-table" style="margin-top:8px">'
                '<div class="shop-table-hd"><span>買取店比較</span></div>'
                + ''.join(rows_html)
                + '</div>'
            )

        # ── 監視中カードは超コンパクト表示（Task 3）──
        # 初期表示：商品名・公式価格・最高買取価格(未取得)・ステータスのみ。
        # 差益 / 買取店比較 / 確認時刻 / 公式リンクは <details> に格納。
        _has_bp = (getattr(d, 'best_buyback_price', 0) or 0) > 0
        # 新品・未使用買取価格が無い理由（Task 3）。価格があれば理由なし。
        _reason = '' if _has_bp else (_missing_reason or '買取価格取得待ち')
        _mon_status = '価格変動を監視中' if _has_bp else _reason
        # 最高買取価格セルの表示（未取得時は理由を併記）
        _bp_cell = (_esc(best_bp_str) if _has_bp
                    else (f'未取得（{_esc(_reason)}）' if _reason and _reason != '買取価格取得待ち' else '未取得'))
        # 14日超で降格した商品は「価格情報が古い（要再確認）」を明示
        _stale14_banner = ('<div class="mon-stale14-note">&#9888; 価格情報が古い（要再確認）</div>'
                           if _is_stale14 else '')
        _mon_fold_inner = (
            f'<div class="profit-section amber" style="margin-top:6px">'
            f'<div class="profit-left">'
            f'<div class="profit-lbl amber">差益（定価購入→最高買取）</div>'
            f'<div class="profit-num amber">{_esc(diff_str)}</div>'
            f'</div>'
            f'<div class="profit-right"><div class="profit-note">{monitoring_profit_note}</div></div>'
            f'</div>'
            + updated_str + compare_html
            + (f'<div class="card-actions">{official_btn}</div>' if official_btn else '')
        )
        _mon_fold = (
            f'<details class="card-detail-fold">'
            f'<summary class="card-detail-summary">詳細を見る</summary>'
            f'<div class="card-detail-body">{_mon_fold_inner}</div>'
            f'</details>'
        )
        return f"""<div class="deal-card deal-card-compact deal-card-monitoring stripe-{stripe_cls}"{card_id_attr}{brand_attr} data-user-level="monitoring" data-genre="{_esc(genre_cls)}">
  <div class="card-stripe monitoring"></div>
  <div class="card-hd">
    <div class="card-name">{name}</div>
    <div class="card-tags">
      <span class="badge badge-monitoring">監視中</span>
      {genre_badge}
    </div>
  </div>
  {_stale14_banner}
  <div class="monitoring-compact-row">
    <div class="mon-cell"><span class="mon-lbl">公式価格</span><span class="mon-val">{"¥{:,}".format(official) if official > 0 else "未取得"}</span></div>
    <div class="mon-cell"><span class="mon-lbl">最高買取価格</span><span class="mon-val mon-val-muted">{_bp_cell}</span></div>
    <div class="mon-cell"><span class="mon-lbl">ステータス</span><span class="mon-status-badge">{_mon_status}</span></div>
  </div>
  <div class="card-body">
    {_mon_fold}
  </div>
</div>"""

    # 内部失敗コード → ユーザー向け日本語表示ラベル（Task 1）
    REASON_DISPLAY_LABELS: dict = {
        'rate_limit_429':      'アクセス集中',
        'cloudflare_block':    'サイト制限中',
        'site_blocked':        'サイト制限中',
        'parsing_failed':      '情報確認中',
        'service_unavailable': '一時メンテ中',
        'product_not_listed':  '現在未掲載',
        'ssl_error':           '接続エラー',
        'empty_html':          '情報取得待機',
        'price_not_found':     '情報確認中',
        'url_not_found':       '情報確認中',
        'empty_result':        '現在未掲載',
        'requires_js':         '情報取得待機',
        'unknown':             '情報確認中',
        'connection_error':    '接続エラー',
        'no_url':              '現在未掲載',
        # 取得失敗の具体理由（毎日更新パイプライン用に追加）
        'timeout':             'タイムアウト',
        'ip_blocked':          'IPブロック',
        'rate_limited_429':    'IPブロック',
        'api_not_configured':  'API未設定',
        'manual_only':         '手動データのみ',
        'used_only':           '中古価格のみ取得',
        'no_new_price':        '新品/未使用価格なし',
    }

    # 店舗別の既知の失敗理由（Task 1: ユーザー向け表示ラベルに更新）
    _SHOP_FAILURE_REASONS: dict = {
        'src_janpara':         ('rate_limit_429',   'じゃんぱら'),
        'src_kaitori_shouten': ('site_blocked',      '買取商店'),
        'src_kaitori_itchome': ('parsing_failed',    '買取一丁目'),
        'src_mobile_ichiban':  ('parsing_failed',    'モバイル一番'),
        'src_iosys':           ('url_not_found',     'イオシス'),
        'src_geo':             ('empty_result',      'ゲオ'),
        'src_sofmap':          ('service_unavailable', 'ソフマップ'),
        'src_bookoff':         ('unknown',           'ブックオフ'),
        'src_surugaya':        ('site_blocked',      '駿河屋'),
        'src_tsutaya':         ('unknown',           'TSUTAYA'),
        # 新規追加店舗
        'src_hardoff':         ('parsing_failed',    'ハードオフ'),
        'src_geo_mobile':      ('site_blocked',      'ゲオモバイル'),
        'src_dosupara':        ('parsing_failed',    'ドスパラ'),
        'src_pasoko':          ('parsing_failed',    'パソコン工房'),
        'src_2ndstreet':       ('parsing_failed',    'セカンドストリート'),
        'src_netoff':          ('parsing_failed',    'ネットオフ'),
    }

    def _deal_card_fetch_failed(self, d, buyback_rows: list = None) -> str:
        """取得失敗案件カード HTML を生成する。"""
        pid       = _esc(d.product_id)
        _raw_pid  = getattr(d, 'product_id', '') or ''
        pid_alias = _raw_pid[len('prod_'):] if _raw_pid.startswith('prod_') else _raw_pid
        card_id_attr = f' id="product-{_esc(pid_alias)}"' if pid_alias else ''
        brand_val = _esc(getattr(d, 'brand', '') or '')
        brand_attr = f' data-brand="{brand_val}"' if brand_val else ''
        genre_cls = getattr(d, 'category', '') or ''
        genre_badge = {
            'iphone':       '<span class="badge badge-iphone">iPhone</span>',
            'tablet':       '<span class="badge badge-iphone">タブレット</span>',
            'pc':           '<span class="badge badge-iphone">PC</span>',
            'camera':       '<span class="badge badge-camera">カメラ</span>',
            'game_console': '<span class="badge badge-game">ゲーム機</span>',
            'wearable':     '<span class="badge">ウェアラブル</span>',
            'audio':        '<span class="badge">オーディオ</span>',
        }.get(genre_cls, '')
        name    = _esc(d.product_name or '—')
        official = d.official_price_jpy or 0

        # 最終試行時刻
        last_attempt_str = ''
        if hasattr(d, 'scanned_at') and d.scanned_at:
            try:
                from datetime import timezone, timedelta
                _jst = timezone(timedelta(hours=9))
                _sa = d.scanned_at
                if hasattr(_sa, 'astimezone'):
                    _sa = _sa.astimezone(_jst)
                last_attempt_str = f'最終試行: {_sa.strftime("%m/%d %H:%M")}'
            except Exception:
                pass

        # 取得失敗行のリンクリスト（失敗理由を付与）Task 1+2
        failed_rows_html = ''
        if buyback_rows:
            failed_links = []
            for r in buyback_rows:
                r_shop_id = r.get('shop_id', '')
                r_name = _esc(r.get('shop_name') or r.get('shop_id') or '—')
                r_url  = r.get('buyback_url', '')
                r_link_verified = bool(r.get('link_verified', False))
                # 失敗理由ラベル — ユーザー向け日本語に変換（Task 1）
                _reason_info = self._SHOP_FAILURE_REASONS.get(r_shop_id)
                _reason_cls, _shop_display = _reason_info if _reason_info else ('unknown', r_name)
                _display_label = self.REASON_DISPLAY_LABELS.get(_reason_cls, '情報確認中')
                reason_badge = (
                    f'<span class="failure-reason-badge failure-reason-{_esc(_reason_cls)}">'
                    f'{_esc(_display_label)}</span>'
                )
                if r_url and r_link_verified:
                    failed_links.append(
                        f'<div class="shop-row shop-row-failed">'
                        f'<div class="shop-name-col">{_esc(_shop_display)}</div>'
                        f'<div class="shop-price-col shop-price-failed">—</div>'
                        f'<div class="shop-failure-detail">'
                        f'{reason_badge}'
                        f'<a href="{_esc(r_url)}" target="_blank" rel="noopener noreferrer" class="shop-link-col" data-track="buyback_click" data-product-id="{pid}">公式で確認</a>'
                        f'</div>'
                        f'</div>'
                    )
                else:
                    failed_links.append(
                        f'<div class="shop-row shop-row-failed">'
                        f'<div class="shop-name-col">{_esc(_shop_display)}</div>'
                        f'<div class="shop-price-col shop-price-failed">—</div>'
                        f'<div class="shop-failure-detail">{reason_badge}</div>'
                        f'</div>'
                    )
            if failed_links:
                # Task 2: 3件を初期表示、残りは「さらに表示」で展開
                _ff_card_id = f'ff-shops-{_esc(pid_alias)}'
                _visible   = ''.join(failed_links[:3])
                _hidden    = ''.join(failed_links[3:])
                _more_btn  = ''
                if _hidden:
                    _more_btn = (
                        f'<div class="ff-more-wrap" id="ff-more-wrap-{_esc(pid_alias)}">'
                        f'<div class="ff-hidden-rows" id="ff-hidden-{_esc(pid_alias)}" style="display:none">'
                        f'{_hidden}'
                        f'</div>'
                        f'<button class="ff-more-btn" onclick="'
                        f'var h=document.getElementById(\'ff-hidden-{_esc(pid_alias)}\');'
                        f'var b=this;'
                        f'if(h.style.display===\'none\'){{h.style.display=\'\';b.textContent=\'表示を減らす\';b.classList.add(\'ff-more-open\');}}'
                        f'else{{h.style.display=\'none\';b.textContent=\'さらに{len(failed_links)-3}件を表示\';b.classList.remove(\'ff-more-open\');}}'
                        f'" aria-expanded="false">さらに{len(failed_links)-3}件を表示</button>'
                        f'</div>'
                    )
                failed_rows_html = (
                    '<div class="shop-compare buyback-shop-table ff-shop-table" style="margin-top:8px">'
                    '<div class="shop-table-hd">取得待ち店舗 <span class="failure-legend">状態</span></div>'
                    + _visible + _more_btn + '</div>'
                )

        last_attempt_html = (
            f'<div class="fetch-failed-timestamp">&#128336; {_esc(last_attempt_str)}</div>'
            if last_attempt_str else ''
        )

        return (
            f'<div class="deal-card stripe-fetch-failed"{card_id_attr}{brand_attr}'
            f' data-user-level="fetch_failed" data-genre="{_esc(genre_cls)}">'
            f'<div class="card-stripe fetch-failed-stripe"></div>'
            f'<div class="card-hd">'
            f'<div class="card-name">{name}</div>'
            f'<div class="card-tags">'
            f'<span class="badge badge-fetch-failed-card">取得失敗</span>'
            f'{genre_badge}'
            f'</div></div>'
            f'<div class="fetch-failed-section">'
            f'<div class="fetch-failed-label">価格取得失敗 / 要確認</div>'
            f'<div class="fetch-failed-note">一部ショップはアクセス制限等により価格取得できません。公式サイトで最新価格をご確認ください。</div>'
            f'<div>公式価格: ¥{official:,}</div>'
            f'<div>買取価格: —（全店舗取得失敗）</div>'
            f'{last_attempt_html}'
            f'</div>'
            f'{failed_rows_html}'
            f'</div>'
        )

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


    def _deal_card(self, d, badge_cls: str, label: str, buyback_rows: list = None, genre: str = None, pro_mode: bool = False, overseas_price_jpy: int = None, overseas_source: str = None, overseas_observed_at: str = None, overseas_collector_method: str = None) -> str:
        """案件カード HTML を生成する（v6 Primary/Secondary Arbitrage）。"""
        # 初心者モード（non-pro）では中古(used)・二次流通(resale_market/フリマ・海外店名)行を
        # 表示・タイムスタンプ・取得方法ラベルの算出前に除外する（新品・未使用のみ）。
        if not pro_mode and buyback_rows:
            buyback_rows = [
                r for r in buyback_rows
                if r.get('data_source') != 'resale_market'
                and not self._cond_is_used(r.get('condition', ''))
                and not self._is_resale_shop(r.get('shop_name', ''))
            ]
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
            'tablet':       '<span class="badge badge-iphone">タブレット</span>',
            'pc':           '<span class="badge badge-iphone">PC / Mac</span>',
            'wearable':     '<span class="badge badge-iphone">ウェアラブル</span>',
            'audio':        '<span class="badge badge-iphone">オーディオ</span>',
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
        _best_buyback_verified = False
        if hasattr(d, 'best_buyback_url') and d.best_buyback_url:
            verified_url = d.best_buyback_url
            _best_buyback_verified = bool(getattr(d, 'best_buyback_link_verified', False))
        if verified_url:
            if _best_buyback_verified:
                _bb_label = '買取価格を確認'
            else:
                _bb_label = '公式サイトで確認'
            buyback_btn = f'<a href="{_esc(verified_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary" data-track="product_click" data-product-id="{pid}" data-shop="{shop}">&#128176; {_bb_label}</a>'
        else:
            fallback = {'iphone': ('https://www.janpara.co.jp/sell/iphone/', 'じゃんぱら'), 'game_console': ('https://www.janpara.co.jp/sell/', 'じゃんぱら'), 'camera': ('https://www.kitamura.co.jp/', 'カメラのキタムラ')}
            fb_url, fb_name = fallback.get(genre_cls, ('https://www.janpara.co.jp/sell/', 'じゃんぱら'))
            buyback_btn = f'<a href="{fb_url}" target="_blank" rel="noopener noreferrer" class="btn btn-primary" data-track="buyback_click" data-product-id="{pid}">&#128176; {fb_name}で売る</a>'
        # Updated timestamp — fetch_failed以外の最新buyback行のobserved_atを優先表示
        updated_str = ''
        _ts_rows = [r for r in (buyback_rows or []) if r.get('data_source') != 'fetch_failed' and r.get('buyback_price', 0) > 0]
        if _ts_rows:
            _obs = _ts_rows[0].get('observed_at', '')
            if _obs:
                try:
                    _dt = datetime.fromisoformat(str(_obs))
                    if _dt.tzinfo is None:
                        _dt = _dt.replace(tzinfo=JST)
                    updated_str = (
                        f'<div class="updated-row"><span>&#128336;</span>'
                        f'価格確認：{_esc(_dt.astimezone(JST).strftime("%Y-%m-%d %H:%M JST"))}</div>'
                    )
                except Exception:
                    pass
        if not updated_str and hasattr(d, 'scanned_at') and d.scanned_at:
            updated_str = f'<div class="updated-row"><span>&#128336;</span>スキャン：{_esc(_jst_str(d.scanned_at))}</div>'
        # Shop compare
        compare_html = ''
        _compare_shop_count = 0  # 比較対象の有効買取店数（「他N店舗と比較済み」表示用）
        _runnerup_diff = None    # 最高買取店と2位の差額（初心者ヒーローに表示）
        # 初心者モード（non-pro）では resale_market（フリマ・オークション）行を除外
        if not pro_mode and buyback_rows:
            buyback_rows = [r for r in buyback_rows if r.get('data_source') != 'resale_market']
        if buyback_rows:
            official_price = d.official_price_jpy or 0
            # confidence=low は誤価格防止のためLPから除外（Task 7）
            _normal_rows  = [r for r in buyback_rows if r.get('buyback_price', 0) > 0 and r.get('confidence', 'high') != 'low']
            _failed_rows  = [r for r in buyback_rows if r.get('data_source') == 'fetch_failed']
            n_shops = len(_normal_rows) + len(_failed_rows)
            _compare_shop_count = len(_normal_rows)

            def _render_shop_row(r, rank_counter):
                """1店舗ぶんの shop-row HTML を返す。rank_counter=None なら取得失敗行。"""
                bp = r.get('buyback_price', 0)
                sname = _esc(r.get('shop_name', ''))
                url_val = r.get('buyback_url', '') or r.get('url', '')
                freshness = self._freshness_label(r.get('observed_at', ''), r.get('data_source', 'manual_today'))
                source_badge = self._data_source_badge(r.get('data_source', ''), r.get('shop_name', ''))
                if rank_counter is None:
                    link_col = (
                        f'<a href="{_esc(url_val)}" target="_blank" rel="noopener noreferrer" '
                        f'class="shop-check-btn normal" data-track="buyback_click" '
                        f'data-product-id="{pid}">確認</a>'
                        if url_val else
                        '<span class="shop-check-btn normal" style="opacity:0.4;cursor:default;">確認不可</span>'
                    )
                    _failed_source_col = (
                        f'<div class="shop-source-col">{source_badge}</div>' if pro_mode else ''
                    )
                    if not pro_mode:
                        # スマホ向け縦カード（取得失敗・未掲載店舗）
                        return (
                            f'<div class="shop-row shop-card shop-row-failed">'
                            f'<div class="shop-card-top">'
                            f'<div class="shop-rank" style="color:var(--ink3)">—</div>'
                            f'<div class="shop-name-col">{sname}</div></div>'
                            f'<div class="shop-card-mid">'
                            f'<div class="shop-price-col" style="color:var(--ink3)">価格未取得</div>'
                            f'<div class="shop-diff-col">{freshness}</div></div>'
                            f'<div class="shop-link-col">{link_col}</div>'
                            f'</div>'
                        )
                    return (
                        f'<div class="shop-row shop-row-failed">'
                        f'<div class="shop-rank" style="color:var(--ink3)">—</div>'
                        f'<div class="shop-name-col">{sname}</div>'
                        f'<div class="shop-price-col" style="color:var(--ink3)">—</div>'
                        f'<div class="shop-diff-col">{freshness}</div>'
                        f'{_failed_source_col}'
                        f'<div class="shop-link-col">{link_col}</div>'
                        f'</div>'
                    )
                profit = bp - official_price
                profit_str = f'+¥{profit:,}' if profit >= 0 else f'-¥{abs(profit):,}'
                btn_cls = 'best' if rank_counter == 1 else 'normal'
                link_col = (
                    f'<a href="{_esc(url_val)}" target="_blank" rel="noopener noreferrer" '
                    f'class="shop-check-btn {btn_cls}" data-track="buyback_click" '
                    f'data-product-id="{pid}">確認</a>'
                    if url_val else
                    '<span class="shop-check-btn normal" style="opacity:0.4;cursor:default;">確認不可</span>'
                )
                rank_cls = 'gold' if rank_counter == 1 else ('silver' if rank_counter == 2 else '')
                diff_cls = ' neg' if profit < 0 else ''
                # 初心者モードでは「自動取得/手動確認」を行内から完全に消す。
                # 主表示は 順位・店名・価格・差益・確認リンクのみ。
                # 取得方法はカード下部の confirm-line（取得方法行）にだけ集約する。
                if pro_mode:
                    source_col_html = f'<div class="shop-source-col">{source_badge}</div>'
                    return (
                        f'<div class="shop-row">'
                        f'<div class="shop-rank {rank_cls}">{rank_counter}</div>'
                        f'<div class="shop-name-col">{sname}</div>'
                        f'<div class="shop-price-col">¥{bp:,}</div>'
                        f'<div class="shop-diff-col{diff_cls}">{_esc(profit_str)}</div>'
                        f'<div class="shop-link-col">{link_col}</div>'
                        f'{source_col_html}'
                        f'</div>'
                    )
                # 初心者モード：スマホで読みやすい縦カード形式（順位/店名 → 価格 → 差益 → 確認）
                return (
                    f'<div class="shop-row shop-card">'
                    f'<div class="shop-card-top">'
                    f'<div class="shop-rank {rank_cls}">{rank_counter}位</div>'
                    f'<div class="shop-name-col">{sname}</div></div>'
                    f'<div class="shop-card-mid">'
                    f'<div class="shop-price-col">¥{bp:,}</div>'
                    f'<div class="shop-diff-col{diff_cls}">差益 {_esc(profit_str)}</div></div>'
                    f'<div class="shop-link-col">{link_col}</div>'
                    f'</div>'
                )

            # 2位との差額（最高買取店ヒーローに小さく添える）
            if len(_normal_rows) >= 2:
                _runnerup_diff = (_normal_rows[0].get('buyback_price', 0)
                                  - _normal_rows[1].get('buyback_price', 0))

            if pro_mode:
                # Pro：従来どおり上位3店舗を常時表示 + 4位以降/失敗を details に折りたたみ
                _TOP_N = 3
                visible_html = []
                more_priced_html = []
                failed_html = []
                for i, r in enumerate(_normal_rows):
                    row = _render_shop_row(r, i + 1)
                    (visible_html if i < _TOP_N else more_priced_html).append(row)
                for r in _failed_rows:
                    failed_html.append(_render_shop_row(r, None))
                details_html = ''
                if more_priced_html:
                    details_html += (
                        f'<details class="shop-more-details">'
                        f'<summary class="shop-more-summary">価格取得済み店舗を見る（残り{len(more_priced_html)}店舗）</summary>'
                        + ''.join(more_priced_html) + '</details>'
                    )
                if failed_html:
                    details_html += (
                        f'<details class="shop-more-details shop-failed-details">'
                        f'<summary class="shop-more-summary shop-failed-summary">取得失敗・未掲載店舗を見る（{len(failed_html)}店舗）</summary>'
                        + ''.join(failed_html) + '</details>'
                    )
                compare_html = (
                    f'<div class="shop-table buyback-shop-table buyback-table">'
                    f'<div class="shop-table-hd"><span>参考買取価格（補助情報）（上位{min(_TOP_N, len(_normal_rows))}店舗 / 全{n_shops}店舗）</span></div>'
                    + ''.join(visible_html) + details_html + '</div>'
                )
            else:
                # 初心者：初期表示は最高買取店＋2位差額のみ。買取店比較は全店舗を
                # 「買取店比較を見る」details に格納（価格取得済み → 取得失敗の順）。
                _priced_cards = ''.join(_render_shop_row(r, i + 1) for i, r in enumerate(_normal_rows))
                _failed_sub = ''
                if _failed_rows:
                    _failed_cards = ''.join(_render_shop_row(r, None) for r in _failed_rows)
                    _failed_sub = (
                        f'<details class="shop-more-details shop-failed-details">'
                        f'<summary class="shop-more-summary shop-failed-summary">取得失敗・未掲載店舗を見る（{len(_failed_rows)}店舗）</summary>'
                        + _failed_cards + '</details>'
                    )
                compare_html = (
                    f'<details class="card-detail-fold shop-compare-fold">'
                    f'<summary class="card-detail-summary">買取店比較を見る（全{n_shops}店舗）</summary>'
                    f'<div class="card-detail-body">'
                    f'<div class="shop-table buyback-shop-table buyback-table">'
                    + _priced_cards + _failed_sub
                    + '</div></div></details>'
                )
        # ── 海外価格セル（Pro モードのみ表示）──
        # 初心者タブでは eBay 等海外参考価格は不要（公式定価購入 → 買取店売却に専念）
        # Pro モードでも overseas_price_cell は現状不使用（overseas_html チップスで代替）
        overseas_price_cell_html = ''

        # Overseas links（Pro モードのみ表示。初心者は買取店売却に専念するため非表示）
        overseas_html = ''
        if pro_mode:
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
        # Profit section style — 初心者は利益額ベースで判定（profit>0 では「様子見」を出さない）
        is_watch = d.user_level == 'beginner_watch'
        if pro_mode:
            _amber = is_watch
            profit_note_text = '価格差（参考値）'
        else:
            _np = d.net_profit_jpy or 0
            _has_price = (d.best_buyback_price or 0) > 0
            if not _has_price:
                profit_note_text = '買取価格取得待ち'; _amber = True
            elif _np >= 10000:
                profit_note_text = '定価購入→最高買取（参考値）'; _amber = False
            elif _np >= 3000:
                profit_note_text = '小幅利益（定価購入→最高買取・参考値）'; _amber = False
            elif _np >= 1:
                profit_note_text = '微益（定価購入→最高買取・参考値）'; _amber = True
            else:
                profit_note_text = '現在は差益なし'; _amber = True
        profit_section_cls = 'profit-section amber' if _amber else 'profit-section'
        profit_lbl_cls = 'profit-lbl amber' if _amber else 'profit-lbl'
        profit_num_cls = 'profit-num amber' if _amber else 'profit-num'
        profit_rate_cls = 'profit-rate amber' if _amber else 'profit-rate'
        # 内部の状態コード（new_unopened_simfree 等）は日本語へ変換して表示（Task 2）
        condition_text = _esc(self._condition_label(d.buyback_condition))
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
            profit_main_lbl = '差益（定価購入→最高買取）'
            pro_mode_note = ''
            buyback_compare_hd = '買取店比較'

        # 買取店テーブルのヘッダーラベルを再構築（Pro向けは「参考」表記）
        if compare_html and pro_mode:
            compare_html = compare_html.replace(
                '<div class="shop-table-hd"><span>売却先比較',
                f'<div class="shop-table-hd"><span>{buyback_compare_hd}',
            )

        # 取得方法・最終確認日・データ鮮度（古いデータは「（要更新）」を最終確認行に小さく付与：Task 3）
        _src_label = '—'
        _src_date  = '—'
        _src_stale = False   # 24h超で True
        _src_stale7 = False  # 168h(7日)超で True → 「7日以上前の参考値」表示
        if _ts_rows:
            _ds = _ts_rows[0].get('data_source', '')
            _src_label = self._source_label_jp(_ds)
            _obs_raw = _ts_rows[0].get('observed_at', '')
            if _obs_raw:
                try:
                    _obs_dt = datetime.fromisoformat(str(_obs_raw))
                    if _obs_dt.tzinfo is None:
                        _obs_dt = _obs_dt.replace(tzinfo=JST)
                    _obs_dt = _obs_dt.astimezone(JST)
                    _src_date = _obs_dt.strftime('%Y-%m-%d')
                    _src_age_h = (datetime.now(tz=JST) - _obs_dt).total_seconds() / 3600
                    _src_stale = _src_age_h >= 24
                    _src_stale7 = _src_age_h >= 168
                except Exception:
                    _src_date = _esc(str(_obs_raw)[:10])

        # ── 最高買取店を一番目立つブロックで表示（Task 5）──
        _best_shop_disp = _esc(d.best_buyback_shop or '—')
        _best_price_disp = _esc(fmt_price(d.best_buyback_price))
        # 「他◯店舗と比較済み」（最高買取店以外の比較対象数）
        _other_shops = max(0, _compare_shop_count - 1)
        # 2位との差額（初期表示はこれだけ。詳細比較は「買取店比較を見る」に格納）
        if _runnerup_diff is not None and _runnerup_diff > 0:
            _runnerup_note = (
                f'<div class="bb-runnerup-note">2位との差額 '
                f'<strong>+¥{_runnerup_diff:,}</strong>'
                f'<span class="bb-compared-sub">（他{_other_shops}店舗と比較済み）</span></div>'
            )
        elif _other_shops > 0:
            _runnerup_note = f'<div class="bb-compared-note">他{_other_shops}店舗と比較済み</div>'
        else:
            _runnerup_note = ''
        best_buyback_block_html = (
            f'<div class="best-buyback-block best-buyback-hero">'
            f'<div class="bb-shop-lbl">&#127978; 最高買取店</div>'
            f'<div class="bb-shop-val"><strong>{_best_shop_disp}</strong></div>'
            f'<div class="bb-shop-price">{_best_price_disp}</div>'
            f'{_runnerup_note}'
            f'</div>'
        ) if not pro_mode else ''

        # ── 価格確認行（小さく・古いデータ表示も控えめにここへ）──
        # 7日超は「要更新」＋「7日以上前の参考値」を表示（利益判定には引き続き使用）。
        _stale_suffix = '<span class="confirm-stale">（要更新）</span>' if _src_stale else ''
        _stale7_note = ('<span class="confirm-stale7">7日以上前の参考値</span>'
                        if _src_stale7 else '')
        price_source_row_html = (
            f'<div class="price-source-row confirm-line" '
            f'style="display:flex;gap:14px;flex-wrap:wrap;'
            f'font-size:0.72rem;color:var(--ink3);padding:4px 0 2px;margin-top:2px;">'
            f'<span>&#9989; 状態：<strong>{condition_text}</strong></span>'
            f'<span>&#128203; 取得方法：{_src_label}</span>'
            f'<span>&#128197; 最終確認：{_src_date}{_stale_suffix}</span>'
            f'{_stale7_note}'
            f'</div>'
        ) if not pro_mode else ''

        # 注意書き（買取条件）— 折りたたみ内に収納
        condition_notice_html = (
            f'<div class="condition-row buyback-notice">'
            f'<span class="cond-icon">&#9888;</span>'
            f'<div><strong>買取条件：{condition_text}</strong>&nbsp;'
            f'<span style="font-size:0.72rem;color:var(--gray-400)">掲載価格は参考値です。'
            f'売却前に必ず各社の公式買取ページで確認してください。</span></div>'
            f'</div>'
        )

        if pro_mode:
            # Pro カードは従来レイアウトを維持
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
  <div class="price-row-wrap">
    <div class="price-cell">
      <div class="price-cell-lbl">{official_price_lbl}</div>
      <div class="price-cell-val">{_esc(fmt_price(d.official_price_jpy))}</div>
    </div>
    <div class="price-cell">
      <div class="price-cell-lbl">{buyback_price_lbl}</div>
      <div class="{buyback_price_val_cls}">{_esc(fmt_price(d.best_buyback_price))}</div>
    </div>
    {overseas_price_cell_html}
  </div>
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
  {best_buyback_block_html}
  <div class="card-body">
    {compare_html}
    {price_source_row_html}
    {condition_notice_html}
    {updated_str}
    <div class="card-actions">
      {official_btn}
      {buyback_btn}
    </div>
    {overseas_html}
  </div>
</div>"""

        # ── 初心者モード：compact card レイアウト（買取店上位3店舗は初期表示）──
        # 初期表示：商品名・バッジ・公式価格・最高買取価格・差益・最高買取店・
        #           買取店比較（上位3店舗＋もっと見る）・CTA。
        # 折りたたみ（<details>）には 取得方法 / 最終確認 / 注意書き のみ格納。
        # （4店舗目以降・取得失敗店舗は compare_html 内の「もっと見る」details に既に格納済み）
        _fold_inner = price_source_row_html + condition_notice_html + updated_str
        detail_fold_html = (
            f'<details class="card-detail-fold">'
            f'<summary class="card-detail-summary">取得方法・注意事項を見る</summary>'
            f'<div class="card-detail-body">{_fold_inner}</div>'
            f'</details>'
        ) if _fold_inner.strip() else ''

        return f"""<div class="deal-card deal-card-compact stripe-{stripe_cls}"{card_id_attr}{brand_attr} data-user-level="{_esc(d.user_level)}">
  <div class="card-stripe {stripe_cls}"></div>
  <div class="card-hd">
    <div class="card-name">{_esc(d.product_name)}</div>
    <div class="card-tags">
      <span class="badge {badge_cls}">{label}</span>
      {genre_badge}
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
  {best_buyback_block_html}
  <div class="card-body">
    <div class="card-actions">
      {official_btn}
      {buyback_btn}
    </div>
    {compare_html}
    {detail_fold_html}
  </div>
</div>"""

    def _tab_advanced(self, advanced_deals, advanced_snaps, watch_candidates, camera_watch=None, camera_beginner_deals=None, market_prices_by_product: dict = None,
                       buyback_by_product: dict = None,
                       latest_buyback_at: Optional[datetime] = None) -> str:
        camera_watch = camera_watch or []
        camera_beginner_deals = camera_beginner_deals or []
        parts = []

        # データ鮮度バナー
        freshness_banner = ""
        if latest_buyback_at is not None:
            _now_jst = datetime.now(tz=JST)
            _lba = latest_buyback_at
            if _lba.tzinfo is None:
                _lba = _lba.replace(tzinfo=JST)
            age_h = (_now_jst - _lba.astimezone(JST)).total_seconds() / 3600
            if age_h >= 48:
                freshness_banner = (
                    '<div class="data-stale-banner data-stale-critical">'
                    '&#128721; 買取価格データが48時間以上更新されていません。価格は古い情報です。リンク先で最新価格を確認してください。'
                    '</div>'
                )
            elif age_h >= 24:
                freshness_banner = (
                    '<div class="data-stale-banner data-stale-warn">'
                    '&#9888;&#65039; 買取価格が24時間以上更新されていません。リンク先で最新価格を要確認です。'
                    '</div>'
                )
        if freshness_banner:
            parts.append(freshness_banner)

        # ── Pro向けタブ説明バナー ──
        parts.append("""<div class="info-banner violet">
<div class="ib-title">&#9997; Pro向け：二次流通仕入れ &rarr; 海外/国内売却比較</div>
ヤフオク・メルカリ・国内中古店などで新品/未使用品を仕入れ、eBay・StockX・海外相場・国内買取店などで売却する価格差を確認します。
<strong>フリマ出品・海外発送・手数料・為替リスクが発生します。経験者向けの参考情報です。価格は参考値です。</strong>
</div>""")

        # ── PC セクション（anchor: category-pro-pc）──
        pc_deals = [d for d in (advanced_deals or []) if getattr(d, 'category', '') == 'pc']
        parts.append('<div class="section-header" id="category-pro-pc"><h2>&#128187; PC &mdash; 二次流通・海外相場</h2></div>')
        if pc_deals:
            parts.append('<div class="cards-grid">')
            for d in pc_deals:
                parts.append(self._deal_card(d, 'badge-adv', 'Pro向け', pro_mode=True))
            parts.append('</div>')
        else:
            parts.append(
                '<div class="empty-state" style="background:var(--surface-1);border:1.5px dashed var(--border-1);border-radius:12px;padding:28px 20px;text-align:center;margin-bottom:8px">'
                '<span class="empty-icon">&#128187;</span>'
                '<div style="font-weight:700;color:var(--ink1);margin:8px 0 4px">PC（Mac / Windows）— 現在監視中</div>'
                '<div style="font-size:0.82rem;color:var(--ink3)">中古PC・Mac・Windowsノートの海外相場・国内価格差を監視しています。<br>'
                'データが取得でき次第、案件として掲載します。</div>'
                '</div>'
            )

        if advanced_deals:
            parts.append('<div class="section-header"><h2>&#128269; Pro向け確定案件</h2><span class="section-count">' + str(len(advanced_deals)) + '件</span></div>')
            for d in advanced_deals:
                badge_cls = "badge-exp" if d.user_level == "expert_only" else "badge-adv"
                label = "Proのみ" if d.user_level == "expert_only" else "Pro向け"
                parts.append(self._deal_card(d, badge_cls, label, pro_mode=True))

        # 価格差・プレ値候補セクション（advanced_snaps）は非表示
        # 中古・開封済み・旧スナップショット比較はメインから除外

        # ----- Pro向け監視候補（フォールバック含む） -----
        if watch_candidates:
            has_confirmed = bool(advanced_deals or advanced_snaps)
            # fallback candidate かどうかは flags が空で product_id のみ持つ辞書か確認
            is_fallback = (
                not has_confirmed
                and all(
                    isinstance(c, dict) and not c.get("flags")
                    and c.get("product_id") and not c.get("buyback_price")
                    for c in watch_candidates
                )
            )
            if is_fallback:
                parts.append(
                    '<div class="caution adv-fallback-notice" style="margin:16px 0 20px;">'
                    '&#128204; <strong>参考価格データ表示</strong><br>'
                    'price_history に価格データがある商品を表示しています。'
                    '最新価格は各リンク先でご確認ください。'
                    '</div>'
                )
            elif not has_confirmed:
                parts.append("""<div class="caution adv-fallback-notice" style="margin:16px 0 20px;">
&#8505;&#65039; <strong>現在、Pro向けの確定候補は少ないため、価格差・希少性・海外相場差が大きい監視候補を表示しています。</strong><br>
新品・未使用の二次流通価格や海外相場データが揃い次第、確定候補として昇格します。
</div>""")
            parts.append('<div class="section-header" id="category-pro-camera"><h2>&#128204; Pro向け市場価格</h2><span class="section-count">二次流通・海外相場</span></div>')
            parts.append(self._watch_candidates_table(watch_candidates, market_prices_by_product=market_prices_by_product or {}, buyback_by_product=buyback_by_product or {}))

        # カメラBeginnerDealを追加表示
        if camera_beginner_deals:
            parts.append('<div class="section-header" id="category-pro-camera"><h2>&#128247; カメラ案件</h2><span class="section-count">' + str(len(camera_beginner_deals)) + '件</span></div>')
            parts.append('<div class="cards-grid">')
            for d in camera_beginner_deals:
                parts.append(self._deal_card(d, 'badge-adv', 'Pro向け', pro_mode=True))
            parts.append('</div>')

        if not advanced_deals and not watch_candidates and not camera_beginner_deals:
            parts.append("""<div class="section-header"><h2>Pro向け候補</h2></div>
<div class="empty-state"><span class="empty-icon">&#128202;</span>現在、条件を満たす候補はありません。</div>""")

        return "\n".join(parts)

    # source_id → 表示名（Pro向け価格テーブル用）
    _SRC_LABEL: dict = {
        "src_mercari":       "メルカリ",
        "src_yahoo_auction": "ヤフオク",
        "src_rakuten":       "ラクマ",
        "src_kitamura":      "カメラのキタムラ",
        "src_fujiya":        "フジヤカメラ",
        "src_map_camera":    "マップカメラ",
        "src_sofmap":        "ソフマップ",
        "src_janpara":       "じゃんぱら",
        "src_iosys":         "イオシス",
        "src_kakaku":        "価格.com",
        "src_ebay":          "eBay",
        "src_stockx":        "StockX",
        "src_bhphoto":       "B&H Photo",
        "src_adorama":       "Adorama",
        "src_mpb":           "MPB",
        "src_keh":           "KEH",
        "src_amazon_us":     "Amazon US",
        "src_mobile_ichiban":   "モバイル一番",
        "src_kaitori_shouten":  "買取商店",
        "src_kaitori_ichome":   "買取一丁目",
    }

    # source_id → URL テンプレート（{enc} = URL-encoded 商品名）— 国内二次流通
    _SRC_URL_DOMESTIC: dict = {
        "src_mercari":       "https://jp.mercari.com/search?keyword={enc}",
        "src_yahoo_auction": "https://auctions.yahoo.co.jp/search/search?p={enc}",
        "src_rakuten":       "https://fril.jp/search?query={enc}",
        "src_kitamura":      "https://www.kitamura.co.jp/ec/special/camera/used/?q={enc}",
        "src_fujiya":        "https://www.fujiyacamera.com/shopbrand/ct10/?q={enc}",
        "src_map_camera":    "https://www.mapcamera.com/ec/search?q={enc}",
        "src_sofmap":        "https://www.sofmap.com/product_list.aspx?q={enc}",
        "src_janpara":       "https://www.janpara.co.jp/sale/search/?keyword={enc}",
        "src_iosys":         "https://iosys.co.jp/search/?keyword={enc}",
        "src_kakaku":        "https://kakaku.com/search_results/{enc}/",
    }

    # source_id → URL テンプレート — 海外相場
    _SRC_URL_OVERSEAS: dict = {
        "src_ebay":      "https://www.ebay.com/sch/i.html?_nkw={enc}&LH_Sold=1&LH_Complete=1",
        "src_stockx":    "https://stockx.com/search?s={enc}",
        "src_bhphoto":   "https://www.bhphotovideo.com/c/search?Ntt={enc}",
        "src_adorama":   "https://www.adorama.com/l/?searchinfo={enc}",
        "src_mpb":       "https://www.mpb.com/en-us/cameras/?q={enc}",
        "src_keh":       "https://www.keh.com/search#{enc}",
        "src_amazon_us": "https://www.amazon.com/s?k={enc}",
    }

    def _watch_candidates_table(self, candidates: list, market_prices_by_product: dict = None, buyback_by_product: dict = None) -> str:
        """監視候補テーブルを生成する（products テーブル由来）。
        market_prices_by_product: {product_id: [{source_id, price_type, price, currency, recorded_at}]}
        実際の価格データがある場合は価格テーブルを表示し、ない場合は検索チップのみ表示。
        並び順: 国内外価格差大 → 海外sold → 海外価格あり → 国内価格あり
        初期表示は上位6件、それ以降は「さらに表示」で展開。
        """
        mdata = market_prices_by_product or {}
        bybp  = buyback_by_product or {}
        INITIAL_VISIBLE = 6  # 初期表示件数

        # overseas_prices/latest.json から collector_method を読み込む
        # {product_id: collector_method} のマッピングを構築
        _overseas_cm: dict[str, str] = {}
        try:
            import json as _json_mod
            _ovs_latest = (
                Path(__file__).resolve().parent.parent.parent
                / "exports" / "overseas_prices" / "latest.json"
            )
            if _ovs_latest.exists():
                _ovs_data = _json_mod.loads(_ovs_latest.read_text(encoding="utf-8"))
                for _entry in _ovs_data.get("prices", []):
                    _pid = _entry.get("product_id", "")
                    _cm  = _entry.get("collector_method", "")
                    if _pid and _cm:
                        _overseas_cm[_pid] = _cm
        except Exception:
            pass  # 読み込み失敗時はバッジ非表示で続行

        # Pass 1: 全カードのデータ計算 → ソートキー付きリストに格納
        card_data = []  # [(sort_key_tuple, card_html_str)]
        for c in candidates:
            price     = c["official_price"]
            bp        = c["buyback_price"]
            shop      = c["shop_name"] or "—"
            _raw_flags = [f for f in (c["flags"] or []) if f != "中古プレ値あり"]
            flags = "・".join(_raw_flags) if _raw_flags else "監視中"
            pname_raw = c["product_name"]
            pname_esc = _esc(pname_raw)
            pname_enc = _urllib_parse.quote(pname_raw)
            prod_id    = c.get("product_id", "")
            genre_attr = c.get("genre", "other")

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
                "lottery":     '<span class="badge badge-lottery">抽選</span>',
                "soldout":     '<span class="badge badge-soldout">SOLD OUT</span>',
                "waiting":     '<span class="badge badge-soldout">入荷待ち</span>',
                "reservation": '<span class="badge badge-adv">予約受付</span>',
            }
            sale_badge = sale_badge_map.get(sale_method, '<span class="badge badge-adv">公式購入困難</span>')

            # ── 実際の価格データ（DB から取得） ──
            price_rows = mdata.get(prod_id, [])
            domestic_rows = [r for r in price_rows if r.get("price_type") in ("used", "market", "flea_market")]
            overseas_rows = [r for r in price_rows if r.get("price_type") == "overseas"]

            # ── 国内二次流通 ── 価格あり/なし分離 → 安い順ソート
            dom_by_src: dict = {r.get("source_id", ""): r for r in domestic_rows}
            all_domestic_sites = [
                ("src_mercari",       "メルカリ",       f"https://jp.mercari.com/search?keyword={pname_enc}"),
                ("src_yahoo_auction", "ヤフオク",       f"https://auctions.yahoo.co.jp/search/search?p={pname_enc}"),
                ("src_rakuten",       "ラクマ",         f"https://fril.jp/search?query={pname_enc}"),
                ("src_map_camera",    "マップカメラ",   f"https://www.mapcamera.com/ec/search?q={pname_enc}"),
                ("src_kitamura",      "カメラのキタムラ", f"https://www.kitamura.co.jp/ec/special/camera/used/?q={pname_enc}"),
                ("src_fujiya",        "フジヤカメラ",   f"https://www.fujiyacamera.com/shopbrand/ct10/?q={pname_enc}"),
                ("src_kakaku",        "価格.com",      f"https://kakaku.com/search_results/{pname_enc}/"),
                ("src_sofmap",        "ソフマップ中古",  f"https://www.sofmap.com/product_list.aspx?q={pname_enc}&st=1"),
            ]
            dom_has = []  # (sid, slabel, surl, db_row) — 価格あり（新品・未使用・未開封のみ）
            dom_no  = []  # (sid, slabel, surl) — 価格未取得
            _dom_used_filtered = 0  # 中古条件で除外した件数（fallback 文言判定用）
            for sid, slabel, surl in all_domestic_sites:
                db_row = dom_by_src.get(sid)
                if db_row:
                    # Pro でも中古販売価格・中古・used・美品・開封済み・ジャンク等は表示しない（新品・未使用・未開封のみ）
                    _basis = db_row.get("price_basis") or ""
                    if self._cond_is_used(_basis):
                        _dom_used_filtered += 1
                        dom_no.append((sid, slabel, surl))
                        continue
                    dom_has.append((sid, slabel, surl, db_row))
                else:
                    dom_no.append((sid, slabel, surl))
            # 安い順（新品・未使用の国内二次流通相場は低い＝買いやすい）
            dom_has.sort(key=lambda x: x[3].get("price", 0))
            dom_min_price = dom_has[0][3].get("price", 0) if dom_has else 0
            dom_min_label = dom_has[0][1] if dom_has else ""

            # 価格あり行のみテーブル生成
            dtrows = []
            for sid, slabel, surl, db_row in dom_has:
                pprice = db_row.get("price", 0)
                pbasis = db_row.get("price_basis") or ""
                freshness = self._freshness_label(
                    db_row.get("recorded_at") or db_row.get("observed_at", ""),
                    db_row.get("data_source", "")
                )
                basis_cell = (
                    f'<span class="pro-price-basis">{_esc(pbasis)}</span>'
                    if pbasis else '<span class="pro-price-basis pro-price-basis-unknown">—</span>'
                )
                dtrows.append(
                    f'<tr class="pro-domestic-row pro-row-has-price">'
                    f'<td class="pro-src-cell"><strong class="pro-src-name">{_esc(slabel)}</strong></td>'
                    f'<td class="pro-price-cell"><strong class="price-value">¥{pprice:,}</strong></td>'
                    f'<td class="pro-basis-cell">{basis_cell}</td>'
                    f'<td class="pro-meta-cell">{freshness}</td>'
                    f'<td class="pro-action-cell"><a href="{_esc(surl)}" target="_blank" rel="noopener noreferrer" '
                    f'class="pro-link-btn" data-track="pro_domestic_click">相場確認</a></td>'
                    f'</tr>'
                )

            # ── 国内買取店価格（新品・未使用・未開封のみ）を「国内売却候補 / 買取店」として
            #    仕入れ候補とは別セクションに表示（Pro から買取店候補を消さない）。
            #    中古・二次流通(resale_market)・低信頼は除外。
            _bb_rows = bybp.get(prod_id, [])
            _bb_seen = set()
            _bb_valid = []
            # 除外理由カウンタ（候補が3件未満のとき理由を表示するため）
            _bb_reason = {'failed': 0, 'not_listed': 0, 'blocked': 0, 'used': 0, 'lowconf': 0}
            for r in _bb_rows:
                _bp = r.get("buyback_price", 0) or 0
                _sname = (r.get("shop_name", "") or "").strip()
                _ds = r.get("data_source", "")
                _reason_raw = (r.get("reason", "") or r.get("failure_reason", "") or "").lower()
                # 取得失敗・未掲載・サイト制限の分類
                if _ds == 'fetch_failed' or _bp <= 0:
                    if _ds == 'product_not_listed' or 'not_listed' in _reason_raw or 'not_found' in _reason_raw:
                        _bb_reason['not_listed'] += 1
                    elif ('429' in _reason_raw) or ('block' in _reason_raw) or ('cloudflare' in _reason_raw) or ('rate' in _reason_raw):
                        _bb_reason['blocked'] += 1
                    elif _ds == 'fetch_failed':
                        _bb_reason['failed'] += 1
                if _ds == 'product_not_listed':
                    _bb_reason['not_listed'] += 1
                if _bp <= 0 or not _sname:
                    continue
                if r.get("data_source") == "resale_market":
                    continue
                if r.get("confidence", "high") == "low":
                    _bb_reason['lowconf'] += 1
                    continue
                if self._cond_is_used(r.get("condition", "")):
                    _bb_reason['used'] += 1
                    continue
                if self._is_resale_shop(_sname):
                    continue
                if _sname in _bb_seen:
                    continue
                _bb_seen.add(_sname)
                _bb_valid.append(r)
            # 買取は高い順（売却先として有利）
            _bb_valid.sort(key=lambda x: x.get("buyback_price", 0), reverse=True)
            bbrows = []
            for _i_bb, r in enumerate(_bb_valid[:5], start=1):
                _bp = r.get("buyback_price", 0)
                _sname = _esc(r.get("shop_name", ""))
                _burl = r.get("buyback_url", "") or r.get("url", "")
                _bfresh = self._freshness_label(r.get("observed_at", ""), r.get("data_source", "manual_today"))
                _baction = (
                    f'<a href="{_esc(_burl)}" target="_blank" rel="noopener noreferrer" '
                    f'class="pro-link-btn" data-track="pro_buyback_click">買取確認</a>'
                    if _burl else '<span class="pro-link-btn" style="opacity:0.4;cursor:default;">—</span>'
                )
                bbrows.append(
                    f'<tr class="pro-domestic-row pro-row-has-price pro-row-buyback">'
                    f'<td class="pro-src-cell"><span class="pro-bb-rank">{_i_bb}</span>'
                    f'<strong class="pro-src-name">{_sname}</strong></td>'
                    f'<td class="pro-price-cell"><strong class="price-value">¥{_bp:,}</strong></td>'
                    f'<td class="pro-basis-cell"><span class="pro-price-basis">買取価格</span></td>'
                    f'<td class="pro-meta-cell">{_bfresh}</td>'
                    f'<td class="pro-action-cell">{_baction}</td>'
                    f'</tr>'
                )
            # ── 候補が3件未満のときの理由文言を生成（Pro：買取候補が少ない理由を明示）──
            _bb_reason_note = ""
            if len(bbrows) < 3:
                _reasons = []
                if _bb_reason['failed'] > 0:
                    _reasons.append(f'取得失敗 {_bb_reason["failed"]}件')
                if _bb_reason['not_listed'] > 0:
                    _reasons.append(f'対象商品未掲載 {_bb_reason["not_listed"]}件')
                if _bb_reason['blocked'] > 0:
                    _reasons.append(f'サイト制限中 {_bb_reason["blocked"]}件')
                if _bb_reason['used'] > 0:
                    _reasons.append(f'新品/未使用価格なし（中古のみ）{_bb_reason["used"]}件')
                if _bb_reason['lowconf'] > 0:
                    _reasons.append(f'価格信頼度低 {_bb_reason["lowconf"]}件')
                if not _reasons:
                    # 生データが全く無い＝対象商品が買取対象外/未掲載
                    if not _bb_rows:
                        _reasons.append('対象商品未掲載（買取データ未取得）')
                    else:
                        _reasons.append('新品/未使用価格なし')
                _bb_reason_note = (
                    f'<div class="pro-bb-reason-note">'
                    f'&#9888; 買取店候補が少ない理由：{_esc(" / ".join(_reasons))}'
                    f'</div>'
                )

            # 「国内売却候補 / 買取店」セクション（仕入れ候補と分離）
            # 候補が0件でもセクション見出しと理由を表示する（買取店候補を完全に消さない）。
            buyback_table_html = ""
            _bb_label_count = len(bbrows)
            if bbrows:
                buyback_table_html = (
                    f'<div class="pro-subsection-label pro-buyback-label">'
                    f'&#127974; 国内売却候補 / 買取店（{_bb_label_count}件）</div>'
                    f'<table class="pro-price-table pro-domestic-price-table pro-buyback-table">'
                    f'<thead><tr><th>買取店</th><th>買取価格</th><th>種別</th><th>確認日</th><th></th></tr></thead>'
                    f'<tbody>{"".join(bbrows)}</tbody>'
                    f'</table>'
                    + _bb_reason_note
                )
            else:
                # 候補0件 → 見出し＋理由のみ（セクション自体は残す）
                buyback_table_html = (
                    f'<div class="pro-subsection-label pro-buyback-label">'
                    f'&#127974; 国内売却候補 / 買取店（0件）</div>'
                    + (_bb_reason_note or
                       '<div class="pro-bb-reason-note">&#9888; 買取店候補が少ない理由：対象商品未掲載（買取データ未取得）</div>')
                )

            # 価格未取得 → チップ
            dom_no_html = ""
            if dom_no:
                chips = "".join(
                    f'<a href="{_esc(surl)}" class="pro-no-price-chip" target="_blank" rel="noopener noreferrer" '
                    f'data-track="pro_domestic_click">{_esc(slabel)}</a>'
                    for _, slabel, surl in dom_no
                )
                dom_no_html = (
                    f'<div class="pro-no-price-section">'
                    f'<span class="pro-no-price-label">相場確認リンク（価格未取得）</span>'
                    f'<div class="pro-no-price-chips">{chips}</div>'
                    f'</div>'
                )
            # 国内仕入れ候補（新品・未使用の国内二次流通価格）
            if dtrows:
                _domestic_buy_html = (
                    f'<div class="pro-subsection-label pro-buy-label">'
                    f'&#128722; 国内仕入れ候補（新品・未使用）</div>'
                    f'<table class="pro-price-table pro-domestic-price-table">'
                    f'<thead><tr><th>サイト</th><th>参考価格</th><th>種別</th><th>確認日</th><th></th></tr></thead>'
                    f'<tbody>{"".join(dtrows)}</tbody>'
                    f'</table>'
                    + dom_no_html
                )
            else:
                # 中古データのみで新品・未使用・未開封が無い場合は明示する（中古価格は出さない方針）
                _no_data_msg = ('新品・未使用価格未取得' if _dom_used_filtered > 0
                                else '国内価格データ未取得')
                _domestic_buy_html = (
                    f'<div class="pro-subsection-label pro-buy-label">'
                    f'&#128722; 国内仕入れ候補（新品・未使用）</div>'
                    f'<div class="pro-no-data-note">{_no_data_msg}</div>'
                    + dom_no_html
                )
            # 仕入れ候補 + 売却候補(買取店) を結合
            domestic_table_html = _domestic_buy_html + buyback_table_html

            # ── 海外相場 ── 価格あり/なし分離 → 高い順ソート
            ovs_by_src: dict = {r.get("source_id", ""): r for r in overseas_rows}
            all_overseas_sites = [
                ("src_ebay",      "eBay",      f"https://www.ebay.com/sch/i.html?_nkw={pname_enc}&LH_Sold=1&LH_Complete=1"),
                ("src_stockx",    "StockX",    f"https://stockx.com/search?s={pname_enc}"),
                ("src_bhphoto",   "B&H Photo", f"https://www.bhphotovideo.com/c/search?Ntt={pname_enc}"),
                ("src_adorama",   "Adorama",   f"https://www.adorama.com/l/?searchinfo={pname_enc}"),
                ("src_mpb",       "MPB",       f"https://www.mpb.com/en-us/cameras/?q={pname_enc}"),
                ("src_keh",       "KEH",       f"https://www.keh.com/search#{pname_enc}"),
                ("src_amazon_us", "Amazon US", f"https://www.amazon.com/s?k={pname_enc}"),
            ]
            ovs_has = []  # (sid, slabel, surl, db_row) — 価格あり
            ovs_no  = []  # (sid, slabel, surl) — 価格未取得
            for sid, slabel, surl in all_overseas_sites:
                db_row = ovs_by_src.get(sid)
                if db_row:
                    ovs_has.append((sid, slabel, surl, db_row))
                else:
                    ovs_no.append((sid, slabel, surl))
            # 高い順（海外で高く売れる相場を上に）
            ovs_has.sort(key=lambda x: x[3].get("price", 0), reverse=True)
            ovs_max_price = ovs_has[0][3].get("price", 0) if ovs_has else 0
            ovs_max_label = ovs_has[0][1] if ovs_has else ""

            otrows = []
            for sid, slabel, surl, db_row in ovs_has:
                pprice = db_row.get("price", 0)
                pbasis = db_row.get("price_basis") or ""
                freshness = self._freshness_label(
                    db_row.get("recorded_at") or db_row.get("observed_at", ""),
                    db_row.get("data_source", "")
                )
                basis_cell = (
                    f'<span class="pro-price-basis">{_esc(pbasis)}</span>'
                    if pbasis else '<span class="pro-price-basis pro-price-basis-unknown">—</span>'
                )
                # collector_method バッジ（overseas_prices/latest.json から）
                _cm = _overseas_cm.get(prod_id, "")
                if _cm == "api":
                    _cm_badge = '<span class="collector-method-badge cm-api">API取得</span>'
                elif _cm == "manual":
                    _cm_badge = '<span class="collector-method-badge cm-manual">eBay 手動確認</span>'
                elif _cm == "html_blocked":
                    _cm_badge = '<span class="collector-method-badge cm-blocked">自動取得制限中</span>'
                elif _cm == "html":
                    _cm_badge = '<span class="collector-method-badge cm-unknown">HTML取得</span>'
                else:
                    _cm_badge = '<span class="collector-method-badge cm-unknown">取得方法未確認</span>'
                otrows.append(
                    f'<tr class="pro-overseas-row pro-row-has-price">'
                    f'<td class="pro-src-cell"><strong class="pro-src-name">{_esc(slabel)}</strong></td>'
                    f'<td class="pro-price-cell"><strong class="price-value">¥{pprice:,}</strong>'
                    f'<small class="pro-jpy-note">（円換算）</small></td>'
                    f'<td class="pro-basis-cell">{basis_cell}</td>'
                    f'<td class="pro-method-cell">{_cm_badge}</td>'
                    f'<td class="pro-meta-cell">{freshness}</td>'
                    f'<td class="pro-action-cell"><a href="{_esc(surl)}" target="_blank" rel="noopener noreferrer" '
                    f'class="pro-link-btn" data-track="pro_overseas_click">相場確認</a></td>'
                    f'</tr>'
                )
            # 価格未取得 → チップ
            ovs_no_html = ""
            if ovs_no:
                chips = "".join(
                    f'<a href="{_esc(surl)}" class="pro-no-price-chip" target="_blank" rel="noopener noreferrer" '
                    f'data-track="pro_overseas_click">{_esc(slabel)}</a>'
                    for _, slabel, surl in ovs_no
                )
                ovs_no_html = (
                    f'<div class="pro-no-price-section">'
                    f'<span class="pro-no-price-label">海外相場確認リンク（価格未取得）</span>'
                    f'<div class="pro-no-price-chips">{chips}</div>'
                    f'</div>'
                )
            _ovs_label = ('<div class="pro-subsection-label pro-overseas-label">'
                          '&#127758; 海外売却候補</div>')
            if otrows:
                overseas_table_html = (
                    _ovs_label
                    + f'<table class="pro-price-table pro-overseas-price-table">'
                    f'<thead><tr><th>サイト</th><th>参考価格（円換算）</th><th>種別</th><th>取得方法</th><th>確認日</th><th></th></tr></thead>'
                    f'<tbody>{"".join(otrows)}</tbody>'
                    f'</table>'
                    + ovs_no_html
                    + f'<p class="pro-overseas-note">※ メルカリ・eBay等は販売手数料、送料、為替変動、関税が発生します。表示利益は参考値です。（eBay販売手数料 約13% / メルカリ 10%）</p>'
                )
            else:
                overseas_table_html = (
                    _ovs_label
                    + f'<div class="pro-no-data-note">海外相場データ未取得</div>'
                    + ovs_no_html
                    + f'<p class="pro-overseas-note">※ メルカリ・eBay等は販売手数料、送料、為替変動、関税が発生します。表示利益は参考値です。（eBay販売手数料 約13% / メルカリ 10%）</p>'
                )

            # ── カード上部：要約ボックス ──
            summary_parts = []
            if dom_min_price and dom_min_label:
                summary_parts.append(
                    f'<div class="pro-summary-item">'
                    f'<span class="pro-summary-lbl">国内最安</span>'
                    f'<span class="pro-summary-val">¥{dom_min_price:,}</span>'
                    f'<span class="pro-summary-sub">({_esc(dom_min_label)} / {len(dom_has)}サイト確認)</span>'
                    f'</div>'
                )
            if ovs_max_price and ovs_max_label:
                summary_parts.append(
                    f'<div class="pro-summary-item">'
                    f'<span class="pro-summary-lbl">海外最高</span>'
                    f'<span class="pro-summary-val">¥{ovs_max_price:,}</span>'
                    f'<span class="pro-summary-sub">({_esc(ovs_max_label)} / {len(ovs_has)}サイト確認)</span>'
                    f'</div>'
                )
            if dom_min_price and ovs_max_price:
                price_gap = ovs_max_price - dom_min_price
                gap_str = f'+¥{price_gap:,}' if price_gap >= 0 else f'-¥{abs(price_gap):,}'
                gap_cls = "pro-summary-gap-pos" if price_gap > 0 else "pro-summary-gap-neg"
                summary_parts.append(
                    f'<div class="pro-summary-item">'
                    f'<span class="pro-summary-lbl">国内外価格差</span>'
                    f'<span class="pro-summary-val {gap_cls}">{gap_str}</span>'
                    f'<span class="pro-summary-sub">(海外最高−国内最安)</span>'
                    f'</div>'
                )
            summary_html = (
                f'<div class="pro-card-summary">{"".join(summary_parts)}</div>'
                if summary_parts else ""
            )

            # ── ソートキー・フィルタ属性の計算 ──
            # price_gap は summary_parts 内で計算済みなので再計算
            _price_gap = (ovs_max_price - dom_min_price) if (dom_min_price and ovs_max_price) else 0
            _has_ovs_sold = any(
                (r.get("price_basis") or "").strip() == "海外sold"
                for r in overseas_rows
            )
            _needs_check = not domestic_rows or not overseas_rows
            sort_key = (
                _price_gap,                           # 1位: 国内外価格差 大きい順
                1 if _has_ovs_sold else 0,            # 2位: eBay soldあり
                1 if overseas_rows else 0,            # 3位: 海外価格あり
                1 if domestic_rows else 0,            # 4位: 国内価格あり
            )
            _data_attrs = (
                f'data-genre="{genre_attr}" '
                f'data-has-overseas-sold="{1 if _has_ovs_sold else 0}" '
                f'data-has-price-gap="{1 if _price_gap > 0 else 0}" '
                f'data-has-overseas="{1 if overseas_rows else 0}" '
                f'data-has-domestic="{1 if domestic_rows else 0}" '
                f'data-needs-check="{1 if _needs_check else 0}"'
            )

            card_html = f"""<div class="watch-candidate-card pro-candidate-card" {_data_attrs}>
  <div class="pcc-header">
    <div class="pcc-name">{pname_esc}</div>
    <div class="pcc-badges">{sale_badge}</div>
  </div>
  {summary_html}
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
    {domestic_table_html}
  </div>
  <div class="pcc-links-section" style="margin-top:12px">
    <div class="pcc-links-label">&#127758; 海外相場</div>
    {overseas_table_html}
  </div>
</div>"""
            _brand = c.get("brand", "") or ""
            card_data.append((sort_key, _brand, card_html))

        # ── Pass 2: ソート（価格差大 → 海外sold → 海外あり → 国内あり）──
        card_data.sort(key=lambda x: x[0], reverse=True)

        # ── Pass 3: ブランド別 ID 付与 + 初期6件以降に pro-card-collapsed 付与 ──
        _BRAND_ID_MAP = {
            "RICOH": "category-pro-camera-ricoh",
            "FUJIFILM": "category-pro-camera-fujifilm",
            "Canon": "category-pro-camera-canon",
            "Nikon": "category-pro-camera-nikon",
            "Sony": "category-pro-camera-sony",
            "Leica": "category-pro-camera-leica",
            "Nintendo": "category-pro-game",
            "Sony Interactive Entertainment": "category-pro-game",
            "Microsoft": "category-pro-game",
        }
        assigned_brand_ids = set()
        rendered_cards = []
        hidden_count = 0
        for i, (_, brand, ch) in enumerate(card_data):
            # ブランドIDを最初の出現時にカードに付与
            _bid = _BRAND_ID_MAP.get(brand, "")
            if _bid and _bid not in assigned_brand_ids:
                ch = ch.replace(
                    'class="watch-candidate-card pro-candidate-card"',
                    f'id="{_bid}" class="watch-candidate-card pro-candidate-card"',
                    1,
                )
                assigned_brand_ids.add(_bid)
            if i >= INITIAL_VISIBLE:
                ch = ch.replace(
                    ' class="watch-candidate-card pro-candidate-card"',
                    ' class="watch-candidate-card pro-candidate-card pro-card-collapsed"',
                    1,
                )
                hidden_count += 1
            rendered_cards.append(ch)

        # ── フィルタバー ──
        filter_bar_html = """<div class="pro-filter-bar">
  <button class="pro-filter-btn active" data-filter="all">すべて</button>
  <button class="pro-filter-btn" data-filter="camera">&#128247; カメラ</button>
  <button class="pro-filter-btn" data-filter="game_console">&#127918; ゲーム機</button>
  <button class="pro-filter-btn" data-filter="pc">&#128187; PC</button>
  <button class="pro-filter-btn" data-filter="overseas-sold">&#127758; 海外soldあり</button>
  <button class="pro-filter-btn" data-filter="price-gap">&#128200; 価格差あり</button>
  <button class="pro-filter-btn" data-filter="needs-check">&#9888; 要確認</button>
</div>"""

        # ── さらに表示ボタン ──
        show_more_html = ""
        if hidden_count > 0:
            show_more_html = (
                f'<button class="pro-show-more-btn" id="pro-show-more-btn">'
                f'&#9660; さらに{hidden_count}件を表示</button>'
            )

        # ── フィルタ + さらに表示 JS ──
        js_block = """<script>
(function(){
  var bar  = document.querySelector('.pro-filter-bar');
  var grid = document.getElementById('pro-cards-grid');
  var mBtn = document.getElementById('pro-show-more-btn');
  if (!bar || !grid) return;
  /* さらに表示 */
  if (mBtn) {
    mBtn.addEventListener('click', function(){
      grid.querySelectorAll('.pro-card-collapsed').forEach(function(c){
        c.classList.remove('pro-card-collapsed');
      });
      mBtn.style.display = 'none';
      var emptyEl = document.getElementById('pro-filter-empty-state');
      if(emptyEl) emptyEl.style.display = 'none';
    });
  }
  /* フィルタ */
  bar.addEventListener('click', function(e){
    var btn = e.target.closest('.pro-filter-btn');
    if (!btn) return;
    bar.querySelectorAll('.pro-filter-btn').forEach(function(b){ b.classList.remove('active'); });
    btn.classList.add('active');
    var f = btn.getAttribute('data-filter');
    var cards = grid.querySelectorAll('.watch-candidate-card');
    cards.forEach(function(c){
      var show = false;
      if (f === 'all') {
        show = !c.classList.contains('pro-card-collapsed');
      } else if (f === 'camera') {
        show = c.getAttribute('data-genre') === 'camera';
      } else if (f === 'game_console') {
        show = c.getAttribute('data-genre') === 'game_console';
      } else if (f === 'pc') {
        show = c.getAttribute('data-genre') === 'pc';
      } else if (f === 'overseas-sold') {
        show = c.getAttribute('data-has-overseas-sold') === '1';
      } else if (f === 'price-gap') {
        show = c.getAttribute('data-has-price-gap') === '1';
      } else if (f === 'needs-check') {
        show = c.getAttribute('data-needs-check') === '1';
      }
      c.style.display = show ? '' : 'none';
    });
    /* フィルタ適用中はさらに表示ボタンを隠す */
    if (mBtn) mBtn.style.display = (f === 'all') ? '' : 'none';
    /* 空状態チェック */
    var visCount = 0;
    grid.querySelectorAll('.watch-candidate-card').forEach(function(c){
      if(c.style.display !== 'none') visCount++;
    });
    var emptyEl = document.getElementById('pro-filter-empty-state');
    if(emptyEl) emptyEl.style.display = (visCount === 0) ? '' : 'none';
  });
})();
</script>"""

        cards_html = "\n".join(rendered_cards) if rendered_cards else '<p class="empty-state">候補商品がありません。</p>'

        return f"""<div class="watch-card pro-watch-card">
{filter_bar_html}
<div class="pro-cards-grid" id="pro-cards-grid">
{cards_html}
</div>
{show_more_html}
<div class="pro-filter-empty-state" id="pro-filter-empty-state" style="display:none">
  <div class="empty-state" style="padding:32px 16px;text-align:center;">
    <span class="empty-icon">&#128270;</span>
    <p style="margin:8px 0 4px;font-weight:700;color:var(--text-1);">該当するPro案件は現在ありません。</p>
    <p style="font-size:0.82rem;color:var(--text-3);">価格データ取得後にここへ表示されます。</p>
  </div>
</div>
<p class="pro-price-basis-disclaimer">
&#9888; 出品価格・成約価格・販売価格は意味が異なります。売買判断時は必ずリンク先で最新条件をご確認ください。
</p>
<p style="color:var(--text-3);font-size:0.78rem;margin-top:6px;padding:0 4px;">
&#9888; リンク先は外部サービスです。相場確認のみを目的としています。売買判断はご自身でご確認ください。
</p>
{js_block}
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

    # フリマ・海外オークション系の売却先キーワード（ランキングから除外）
    _RESALE_SHOP_KEYWORDS = ('ebay', 'ヤフオク', 'メルカリ', 'mercari', 'ラクマ', 'rakuma', 'stockx', 'amazon', '楽天')

    @staticmethod
    def _is_resale_shop(shop_name: str) -> bool:
        """売却先が resale_market（フリマ・海外オークション）かどうか判定する。"""
        if not shop_name:
            return False
        sl = shop_name.lower()
        return any(kw.lower() in sl for kw in DailyLPGenerator._RESALE_SHOP_KEYWORDS)

    # 中古・状態不良を示す買取条件キーワード（新品・未使用・未開封のみ採用）
    _USED_COND_KEYWORDS = ('中古', '美品', '良品', 'used', 'b品', 'c品', 'ジャンク', '開封済')

    @staticmethod
    def _cond_is_used(cond) -> bool:
        """買取条件が中古・状態不良かどうか判定する（新品/未使用/未開封以外）。"""
        c = (cond or '').lower()
        return any(kw in c for kw in DailyLPGenerator._USED_COND_KEYWORDS)

    def _enrich_deal(self, deal, rows):
        """買取行の「新品・未使用・非resale」価格のみで deal を補完する。

        中古(used_a 等)・二次流通(resale_market / フリマ・海外店名)価格は完全除外。
        有効な新品/未使用行が存在せず、既存値が中古/resale 由来（tainted）の場合は
        買取価格をクリアして monitoring 扱いにする（誤った差益表示を防ぐ）。
        全タブ（初心者 / ランキング / せどり）で一貫した補完を行うための共通メソッド。
        """
        def _clear(d):
            return d.copy(update={
                'best_buyback_shop': '—',
                'best_buyback_price': 0,
                'net_profit_jpy': 0,
                'gross_profit_jpy': 0,
                'net_profit_rate': 0.0,
                'user_level': 'monitoring',
            })

        stored_shop = deal.best_buyback_shop or ''
        stored_cond = getattr(deal, 'buyback_condition', '') or ''
        # 既存値が中古条件 or resale 店名由来なら「汚染」とみなし、強制的に再評価
        _tainted = self._is_resale_shop(stored_shop) or self._cond_is_used(stored_cond)

        valid_rows = [
            r for r in (rows or [])
            if r.get('buyback_price', 0) > 0
            and r.get('data_source', '') not in ('fetch_failed', 'product_not_listed', 'resale_market')
            and r.get('confidence', 'high') != 'low'
            and not self._cond_is_used(r.get('condition', ''))
            and not self._is_resale_shop(r.get('shop_name', ''))
        ]
        if not valid_rows:
            return _clear(deal) if _tainted else deal

        best_row = max(valid_rows, key=lambda r: r.get('buyback_price', 0))
        best_price = best_row.get('buyback_price', 0)
        stored_bp = deal.best_buyback_price or 0
        # 汚染されていなければ、より高い有効価格がある場合のみ更新
        if best_price <= stored_bp and not _tainted:
            return deal

        official = deal.official_price_jpy or 0
        costs = 1800  # 送料+振込手数料+移動コスト（固定）
        gross = best_price - official
        net = gross - costs

        # user_level 再評価
        sale_method = getattr(deal, 'sale_method', None) or 'normal'
        stock_status = getattr(deal, 'stock_status', None) or ''
        difficulty = getattr(deal, 'difficulty_score', None) or 0.0
        if difficulty >= 100.0:  # センチネル値 → 再推定
            if sale_method == 'normal':
                difficulty = 0.0
                _name_lower = (getattr(deal, 'product_name', '') or '').lower()
                if any(_kw in _name_lower for _kw in ('monochrome', 'limited', '限定')):
                    difficulty += 0.15
            elif sale_method == 'lottery':
                difficulty = 0.70
            elif sale_method == 'discontinued':
                difficulty = 0.80
            elif sale_method == 'soldout':
                difficulty = 0.60
            else:
                difficulty = 0.0
            difficulty = min(1.0, difficulty)
        is_normal = sale_method == 'normal'
        stock_ok = 'SOLD' not in stock_status.upper()
        if is_normal and stock_ok and net >= 5000 and difficulty <= 0.35:
            new_level = 'beginner_easy'
        elif is_normal and net >= 3000 and difficulty <= 0.50:
            new_level = 'beginner_watch'
        elif gross >= 30000:
            new_level = 'advanced_high_profit'
        elif net > 0:
            new_level = 'beginner_watch'
        else:
            new_level = 'monitoring'
        net_rate = (net / official) if official > 0 else 0.0
        return deal.copy(update={
            'best_buyback_price': best_price,
            'best_buyback_shop': best_row.get('shop_name', deal.best_buyback_shop or ''),
            'best_buyback_url': best_row.get('buyback_url', deal.best_buyback_url or ''),
            'best_link_verified': bool(best_row.get('buyback_url', '')),
            'buyback_condition': best_row.get('condition', deal.buyback_condition or ''),
            'gross_profit_jpy': gross,
            'net_profit_jpy': net,
            'net_profit_rate': net_rate,
            'user_level': new_level,
        })

    def _tab_ranking(self, all_deals, iphone_deals, game_deals, sedori_routes=None) -> str:
        # 各カテゴリのデータ準備（resale_market 売却先を除外して買取店のみランキング）
        def _buyback_only(deals):
            return [d for d in deals
                    if d.net_profit_jpy > 0
                    and not self._is_resale_shop(getattr(d, 'best_buyback_shop', '') or '')]

        profitable = sorted(_buyback_only(all_deals),
                            key=lambda d: d.net_profit_jpy, reverse=True)
        iphone_profitable = sorted(_buyback_only(iphone_deals),
                                    key=lambda d: d.net_profit_jpy, reverse=True)
        game_profitable = sorted(_buyback_only(game_deals),
                                  key=lambda d: d.net_profit_jpy, reverse=True)
        camera_profitable = sorted(_buyback_only([d for d in all_deals if getattr(d, 'category', '') == 'camera']),
                                    key=lambda d: d.net_profit_jpy, reverse=True)

        def _rank_rows_html(deals, show_cat=False):
            rows = []
            for i, d in enumerate(deals, 1):
                row_cls = ' rank-1' if i == 1 else ''
                rank_cls = 'r1' if i == 1 else ('r2' if i == 2 else ('r3' if i == 3 else ''))
                crown = '&#128081;' if i == 1 else str(i)
                cat_td = f'<td style="font-size:0.75rem;color:var(--ink3)">{_esc(d.category)}</td>' if show_cat else ''
                # user_level が beginner_easy/watch → beginnerタブ、それ以外はcategoryで判定
                _ul = getattr(d, 'user_level', '') or ''
                if _ul in ('beginner_easy', 'beginner_watch'):
                    _target_tab = "beginner"
                elif _ul in ('advanced', 'expert_only', 'advanced_high_profit'):
                    _target_tab = "advanced"
                else:
                    _target_tab = "advanced" if getattr(d, 'category', '') == 'camera' else "beginner"
                _raw_pid = getattr(d, 'product_id', '') or ''
                _pid_alias = _raw_pid[len('prod_'):] if _raw_pid.startswith('prod_') else _raw_pid
                rows.append(
                    f'<div class="rank-row{row_cls} rank-row-clickable" '
                    f'data-target-tab="{_target_tab}" data-target-id="product-{_esc(_pid_alias)}" style="cursor:pointer">'
                    f'<div class="rank-num {rank_cls}">{crown}</div>'
                    f'<div class="rank-info"><div class="rank-name rank-name-link">{_esc(d.product_name)}</div>'
                    f'<div class="rank-meta">{_esc(d.best_buyback_shop or "—")} → 最高買取店'
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

        # 注: せどりルート（店舗間/二次流通仕入れ）はランキングに混在させない。
        # ランキングは初心者ランキング（公式価格 → 最高買取店、差益順）のみを表示し、
        # せどりルートは専用の「せどりタブ」で Pro/初心者 を分けて表示する。

        return f"""<div class="sec-head"><div class="sec-title">&#127942; 差益ランキング</div></div>
<div class="ranking-card">
  <div class="ranking-note" style="font-size:0.78rem;color:var(--ink3);padding:0 4px 8px;">公式価格で購入 &rarr; 最高買取店で売却した場合の差益順（新品・未使用のみ）。せどりルートは <a href="#tab-sedori" class="inline-link">せどりタブ</a> をご覧ください。</div>
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



    # 取得失敗が一定件数以上のとき表示する上部バー
    _COLLECTOR_WARN_THRESHOLD: int = 5  # failed >= この件数で表示

    def _collector_warn_bar_html(self) -> str:
        """collector_report/latest.json を読み、失敗件数・精度問題に応じた警告バー HTMLを返す。
        shop_detail を参照し、required店舗とoptional店舗の失敗を区別して3段階で表示する。"""
        import json as _json
        from pathlib import Path as _Path

        # optional扱いの店舗ID（これらの失敗は軽微）
        # check_collector_quality.py の OPTIONAL_SHOPS と同期すること
        _OPTIONAL_SHOP_IDS = {
            "2ndstreet", "bookoff", "dosupara",
            "geo",        # iPhone17/PS5Pro未掲載（geo_mobileがiPhone担当）
            "geo_mobile", "hardoff",
            "pasoko", "janpara", "sofmap", "surugaya",
            "tsutaya",    # オンライン自動見積もり非対応（NOT_SUPPORTED_SHOPS）
        }

        _report_path = _Path(__file__).resolve().parent.parent.parent / "exports" / "collector_report" / "latest.json"
        if not _report_path.exists():
            return ""
        try:
            _data = _json.loads(_report_path.read_text(encoding="utf-8"))
            _suspicious = len(_data.get("suspicious_prices", []))
            _low_conf = _data.get("summary", {}).get("low_confidence_count", 0)

            # shop_detail から required / optional の失敗数を集計
            _shop_detail = _data.get("shop_detail", [])
            _required_failed = 0
            _optional_failed = 0
            for _shop in _shop_detail:
                _sid = _shop.get("shop_id", "")
                _f = _shop.get("failed", 0)
                if _sid in _OPTIONAL_SHOP_IDS:
                    _optional_failed += _f
                else:
                    _required_failed += _f
        except Exception:
            return ""

        _link = '<a href="collector_report.html" data-track="collector_warn_click">取得レポートを確認</a>'

        # 強警告: 価格精度に問題あり（suspicious or low_confidence）
        if _suspicious > 0 or _low_conf > 0:
            _parts = []
            if _suspicious > 0:
                _parts.append(f'疑わしい価格 {_suspicious}件')
            if _low_conf > 0:
                _parts.append(f'低信頼度 {_low_conf}件')
            _detail = " / ".join(_parts)
            return (
                f'<div class="collector-warn-bar collector-warn-strong" id="collector-warn-bar">'
                f'⚠️ 価格精度に問題があります（{_esc(_detail)}） — {_link}'
                f'</div>\n'
            )

        # 控えめ警告: required店舗の失敗が閾値以上
        if _required_failed >= self._COLLECTOR_WARN_THRESHOLD:
            return (
                f'<div class="collector-warn-bar collector-warn-soft" id="collector-warn-bar">'
                f'⚠️ 一部店舗データ取得失敗あり（{_required_failed}件） — {_link}'
                f'</div>\n'
            )

        # optional店舗のみの失敗 → ユーザー向けLPには表示しない（LP品質に影響なし）
        # （collector_report.html で確認可能）
        if _optional_failed >= self._COLLECTOR_WARN_THRESHOLD:
            return ""

        # 非表示
        return ""

    def _data_quality_summary_html(self) -> str:
        """LP下部の簡易データ取得状況ブロック（Task 4）。
        exports/data_quality_report/latest.json を読んで小さく表示する。"""
        try:
            import json as _jdq
            from pathlib import Path as _P
            _p = _P(__file__).resolve().parent.parent.parent / "exports" / "data_quality_report" / "latest.json"
            with open(_p, encoding="utf-8") as _f:
                dq = _jdq.load(_f)
        except Exception:
            return ""
        col = dq.get("collection", {}) or {}
        ok = col.get("ok_jobs", 0)
        total = col.get("total_jobs", 0)
        rate = col.get("success_rate_pct", 0)
        top = (dq.get("comparison", {}) or {}).get("top5_failure_reasons", []) or dq.get("failure_reasons", [])[:3]
        reasons_str = ", ".join(f"{r.get('reason')} {r.get('count')}" for r in top[:3]) or "なし"
        ovs = dq.get("overseas", {}) or {}
        _ebay = "eBay API設定済" if ovs.get("ebay_app_id_configured") else "eBay API未設定"
        # カメラ買取の自動取得状況（camera_buyback_status.json）
        _cam_state = ""
        try:
            _cp = _P(__file__).resolve().parent.parent.parent / "exports" / "camera_buyback_status.json"
            with open(_cp, encoding="utf-8") as _cf:
                _cam = _jdq.load(_cf)
            _cam_ok = (_cam.get("summary", {}) or {}).get("ok", 0)
            _cam_state = ("自動取得" if _cam_ok > 0 else "手動確認 fallback中")
        except Exception:
            _cam_state = "手動確認 fallback中"
        _cmp = dq.get("comparison", {}) or {}
        _trend = _cmp.get("trend", "")
        _delta = _cmp.get("delta_pct")
        _trend_str = (f" ・前回比 {'+' if (_delta or 0) > 0 else ''}{_delta}pt（{_trend}）"
                      if _delta is not None else "")
        return (
            f'<div class="data-quality-note">'
            f'<span class="dq-title">&#128202; データ取得状況</span> '
            f'成功 <strong>{ok} / {total}</strong>（{rate}%）{_trend_str} ／ '
            f'主な失敗理由: {_esc(reasons_str)} ／ 海外価格: {_esc(_ebay)} ／ '
            f'カメラ買取: {_esc(_cam_state)}'
            f'</div>'
        )

    def _section_footer(self) -> str:

        now = datetime.now()
        _dq_html = self._data_quality_summary_html()

        return f"""<footer class="footer">
<div class="footer-inner">
  {_dq_html}
  <div class="footer-logo">
    <div class="footer-logo-icon">S</div>
    <div class="footer-logo-name">プレ値速報</div>
    <div class="footer-live"><span class="live-dot"></span>毎日更新</div>
  </div>
  <div class="footer-links">
    <a href="#tab-lottery" class="footer-link">抽選情報</a>
    <a href="#tab-ranking" class="footer-link">ランキング</a>
    <a href="#tab-sedori" class="footer-link">せどりルート</a>
    <a href="#tab-beginner" class="footer-link">初心者向け</a>
    <a href="#tab-advanced" class="footer-link">Pro向け</a>
    <a href="#tab-surge" class="footer-link">急騰/急落アラート</a>
    <a href="#note-cta" class="footer-link">詳細レポート</a>
    <a href="collector_report.html" class="footer-link admin-report-link" data-track="collector_report_click">取得レポート</a>
  </div>
  <div class="footer-text">
    <p>掛載価格は取得・入力時点の参考値です。購入前に必ず公式サイト・買取店でご確認ください。</p>
    <p>&copy; {now.year} プレ値速報 &mdash; 情報は自動取得・分析されたものです</p>
  </div>
</div>
</footer>"""



    def _section_new_products(self) -> str:
        """後方互換のため残す（_section_sokuhohに委譲）。"""
        return self._section_sokuhoh([])

    def _section_sokuhoh(self, buyback_alerts: list = None) -> str:
        """速報タブ：買取急騰/急落アラート・価格変化フィードを表示する。"""
        alerts = buyback_alerts or []
        # alert_type が buyback_surge / buyback_drop のものを抽出
        feed_items = [a for a in alerts if a.get('alert_type') in (
            'buyback_surge', 'buyback_drop', 'restock', 'presale',
            'lottery_start', 'lottery_end', 'buyback_update', 'soldout',
            'stock_recover', 'price_diff',
        )]

        # バッジの種別マップ
        _type_badge = {
            'buyback_surge':   ('<span class="sokuhoh-badge badge-surge">買取急騰</span>', 'sokuhoh-surge'),
            'buyback_drop':    ('<span class="sokuhoh-badge badge-drop">買取急落</span>', 'sokuhoh-drop'),
            'restock':         ('<span class="sokuhoh-badge badge-restock">再入荷</span>', 'sokuhoh-change'),
            'presale':         ('<span class="sokuhoh-badge badge-presale">予約開始</span>', 'sokuhoh-change'),
            'lottery_start':   ('<span class="sokuhoh-badge badge-lottery-start">抽選開始</span>', 'sokuhoh-change'),
            'lottery_end':     ('<span class="sokuhoh-badge badge-lottery-end">抽選終了</span>', 'sokuhoh-change'),
            'buyback_update':  ('<span class="sokuhoh-badge badge-update">買取価格更新</span>', 'sokuhoh-change'),
            'soldout':         ('<span class="sokuhoh-badge badge-soldout">SOLD OUT</span>', 'sokuhoh-drop'),
            'stock_recover':   ('<span class="sokuhoh-badge badge-restock">在庫復活</span>', 'sokuhoh-surge'),
            'price_diff':      ('<span class="sokuhoh-badge badge-surge">価格差速報</span>', 'sokuhoh-surge'),
        }

        cards = []
        for a in feed_items[:20]:
            atype = a.get('alert_type', '')
            badge_html, card_cls = _type_badge.get(atype, ('<span class="sokuhoh-badge">価格急変</span>', 'sokuhoh-change'))
            prod_name = _esc(a.get('product_name') or a.get('product_id', ''))
            brand = _esc(a.get('brand', ''))
            price_before = a.get('price_before') or a.get('prev_price')
            price_after  = a.get('price_after') or a.get('new_price') or a.get('buyback_price')
            diff = (price_after - price_before) if (price_before and price_after) else None
            diff_str = ''
            if diff is not None:
                sign = '+' if diff >= 0 else ''
                diff_str = f'{sign}¥{diff:,}'
            price_row = ''
            if price_before and price_after:
                price_row = (f'<div class="sokuhoh-price-row">'
                             f'<span class="sokuhoh-prev">¥{price_before:,}</span>'
                             f'<span class="sokuhoh-arrow">→</span>'
                             f'<span class="sokuhoh-cur">¥{price_after:,}</span>'
                             f'<span class="sokuhoh-diff">({diff_str})</span>'
                             f'</div>')
            elif price_after:
                price_row = f'<div class="sokuhoh-price-row"><span class="sokuhoh-cur">¥{price_after:,}</span></div>'
            occurred_at = _esc(str(a.get('occurred_at') or a.get('created_at') or ''))
            time_row = f'<div class="sokuhoh-time">&#128336; {occurred_at}</div>' if occurred_at else ''
            url = a.get('url') or a.get('buyback_url') or ''
            link_html = ''
            if url:
                link_html = (f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer" '
                             f'class="btn btn-secondary" style="font-size:0.75rem;padding:4px 12px" '
                             f'data-track="sokuhoh_click">詳細を確認</a>')
            cards.append(
                f'<div class="sokuhoh-card {card_cls}">'
                f'<div class="sokuhoh-top">{badge_html}</div>'
                f'<div class="sokuhoh-body">'
                f'<div class="sokuhoh-name">{prod_name}</div>'
                + (f'<div class="sokuhoh-brand">{brand}</div>' if brand else '')
                + price_row
                + time_row
                + link_html
                + '</div></div>'
            )

        if not cards:
            # データなし表示
            return (
                '<div class="sec-head"><div class="sec-title">&#128248; 速報</div></div>'
                '<div class="info-banner" style="margin:24px 0;text-align:center;padding:40px 16px">'
                '&#128248; 本日の速報（再入荷・予約開始・買取急変等）はありません。'
                '</div>'
            )

        return (
            '<div class="sec-head">'
            f'<div class="sec-title">&#9889; 速報</div>'
            f'<div class="sec-badge">{len(cards)}件</div>'
            '</div>'
            '<div class="sokuhoh-feed">' + ''.join(cards) + '</div>'
        )

    def _section_alert_popup(self, buyback_alerts: list = None) -> str:
        """速報ポップアップ — ページ右下に最大3件表示 (severity high優先)。
        data/alerts.csv を読み込んで高優先アラートを表示する。
        localStorage で同日再表示なし。
        """
        import csv as _csv_mod
        from datetime import datetime as _dt

        # alerts.csv から高優先アラートを読み込む
        alerts_csv_path = PROJECT_ROOT / "data" / "alerts.csv"
        popup_items = []

        try:
            now_jst = _dt.now(tz=JST)
            if alerts_csv_path.exists():
                with open(alerts_csv_path, encoding="utf-8", newline="") as f:
                    reader = _csv_mod.DictReader(f)
                    for row in reader:
                        # expires_at チェック
                        expires = row.get("expires_at", "")
                        if expires:
                            try:
                                exp_dt = _dt.strptime(expires[:16], "%Y-%m-%d %H:%M").replace(tzinfo=JST)
                                if exp_dt < now_jst:
                                    continue
                            except Exception:
                                pass
                        # severity high/medium のみ表示
                        sev = row.get("severity", "low")
                        if sev not in ("high", "medium"):
                            continue
                        popup_items.append(row)
        except Exception:
            pass

        # buyback_alerts からも surge/drop を追加（alerts.csv がない場合のフォールバック）
        if not popup_items and buyback_alerts:
            for a in (buyback_alerts or [])[:3]:
                atype = a.get("alert_type", "")
                if atype in ("buyback_surge", "buyback_drop"):
                    popup_items.append({
                        "alert_id": str(a.get("id", "")),
                        "alert_type": atype,
                        "product_name": a.get("product_name", ""),
                        "title": "買取急騰" if atype == "buyback_surge" else "買取急落",
                        "message": f"¥{a.get('price_after', 0):,}",
                        "severity": "medium",
                        "product_url": a.get("url", ""),
                        "expires_at": "",
                    })

        if not popup_items:
            return ""

        # 最大3件、severity high 優先にソート
        _sev_order = {"high": 0, "medium": 1, "low": 2}
        popup_items.sort(key=lambda x: _sev_order.get(x.get("severity", "low"), 2))
        popup_items = popup_items[:3]

        # ポップアップカード生成
        cards_html = []
        for item in popup_items:
            atype = item.get("alert_type", "")
            sev = item.get("severity", "medium")
            title = _esc(item.get("title") or atype)
            msg = _esc(item.get("message", ""))
            prod_name = _esc(item.get("product_name", ""))
            url = item.get("product_url") or item.get("action_url") or ""
            alert_id = _esc(item.get("alert_id", ""))

            sev_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sev, "🟡")
            link_html = (
                f'<a href="{_esc(url)}" target="_blank" rel="noopener" class="popup-alert-link">'
                f'詳細を確認 ›</a>'
            ) if url else ""

            cards_html.append(
                f'<div class="popup-alert-card popup-sev-{_esc(sev)}" data-alert-id="{alert_id}">\n'
                f'  <div class="popup-alert-top">\n'
                f'    <span class="popup-alert-icon">{sev_icon}</span>\n'
                f'    <span class="popup-alert-title">{title}</span>\n'
                f'    <button class="popup-alert-close" onclick="dismissPopupAlert(this)" aria-label="閉じる">&#10005;</button>\n'
                f'  </div>\n'
                + (f'  <div class="popup-alert-product">{prod_name}</div>\n' if prod_name else '')
                + (f'  <div class="popup-alert-msg">{msg}</div>\n' if msg else '')
                + (link_html + '\n' if link_html else '')
                + '</div>'
            )

        if not cards_html:
            return ""

        return f'''<div id="alert-popup-container" class="alert-popup-container">
{''.join(cards_html)}
</div>
<style>
.alert-popup-container {{
  position: fixed; bottom: 20px; right: 16px; z-index: 9999;
  display: flex; flex-direction: column; gap: 8px;
  max-width: 320px; width: calc(100vw - 32px);
}}
.popup-alert-card {{
  background: #fff; border-radius: 12px; padding: 12px 14px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.15);
  border-left: 4px solid #F59E0B;
  display: flex; flex-direction: column; gap: 4px;
  animation: popupSlideIn 0.3s ease;
}}
.popup-sev-high {{ border-left-color: #EF4444; }}
.popup-sev-medium {{ border-left-color: #F59E0B; }}
.popup-sev-low {{ border-left-color: #22C55E; }}
@keyframes popupSlideIn {{
  from {{ transform: translateX(100%); opacity: 0; }}
  to   {{ transform: translateX(0); opacity: 1; }}
}}
.popup-alert-top {{ display: flex; align-items: center; gap: 6px; }}
.popup-alert-icon {{ font-size: 0.9rem; }}
.popup-alert-title {{ font-weight: 700; font-size: 0.85rem; flex: 1; color: #1e293b; }}
.popup-alert-close {{
  background: none; border: none; cursor: pointer; padding: 2px 6px;
  font-size: 0.75rem; color: #94a3b8; border-radius: 4px;
}}
.popup-alert-close:hover {{ background: #f1f5f9; }}
.popup-alert-product {{ font-size: 0.8rem; font-weight: 600; color: #334155; }}
.popup-alert-msg {{ font-size: 0.78rem; color: #64748b; }}
.popup-alert-link {{
  font-size: 0.75rem; color: #7C3AED; text-decoration: none; font-weight: 600;
}}
.popup-alert-link:hover {{ text-decoration: underline; }}
@media (max-width: 480px) {{
  .alert-popup-container {{ bottom: 12px; right: 8px; max-width: 90vw; }}
}}
</style>
<script>
(function() {{
  var todayKey = 'popupDismissed_' + new Date().toISOString().slice(0, 10);
  var dismissed = JSON.parse(localStorage.getItem(todayKey) || '[]');
  document.querySelectorAll('.popup-alert-card').forEach(function(card) {{
    var aid = card.getAttribute('data-alert-id');
    if (aid && dismissed.indexOf(aid) >= 0) card.style.display = 'none';
  }});
  var container = document.getElementById('alert-popup-container');
  if (container) {{
    var visible = container.querySelectorAll('.popup-alert-card:not([style*="none"])');
    if (!visible.length) container.style.display = 'none';
  }}
}})();
function dismissPopupAlert(btn) {{
  var card = btn.closest('.popup-alert-card');
  if (!card) return;
  var aid = card.getAttribute('data-alert-id');
  card.style.display = 'none';
  if (aid) {{
    var todayKey = 'popupDismissed_' + new Date().toISOString().slice(0, 10);
    var dismissed = JSON.parse(localStorage.getItem(todayKey) || '[]');
    if (dismissed.indexOf(aid) < 0) dismissed.push(aid);
    localStorage.setItem(todayKey, JSON.stringify(dismissed));
  }}
  var container = document.getElementById('alert-popup-container');
  if (container) {{
    var visible = container.querySelectorAll('.popup-alert-card:not([style*="display: none"])');
    if (!visible.length) container.style.display = 'none';
  }}
}}
</script>'''

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
