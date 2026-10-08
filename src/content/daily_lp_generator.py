"""日次LP自動生成エンジン。

buyback_premium_check 完了後に呼ばれ、exports/lp/daily/index.html（と日付のファイル・latest.md）を生成する。

公開するページは新UI（src/content/ui/）だけ。UI Phase 10 で旧UI（タブ・ランキング・初心者・Pro・せどり・
Health などの DOM・CSS・JS と、その描画関数）を削除した。ここでは新UIに渡すデータ（案件・買取価格・抽選・
生成物）を集め、判定（opportunity.py）を通したうえで新UIを組み立てる。新UIの生成に失敗したら例外にする
（白い画面を公開しない。前回の公開が残る）。
"""

import html as html_mod
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.content.safety import (
    check_forbidden, sanitize_text, fmt_price, fmt_profit, fmt_rate,
    DISCLAIMER_FULL,
)
from src.db.repository import Repository
from src.market import price_evidence as _pe
from src.market import price_types as _pt
from src.market import official_shipping as _official_shipping
from src.market import stock_state as _stock
# 確定利益・利益ルートを出してよいかの判定の正本（新UIと同じ。旧UI用に二重に書かない）
from src.content.ui import opportunity as _ui_opp

logger = logging.getLogger(__name__)


def _official_label(product_id, price=None) -> str:
    """公式の価格の呼び方（定価 / 公式直販価格 / 参考価格。official_registry.official_price_label）。"""
    from src.market.official_registry import official_price_label
    return official_price_label(product_id, price)

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


def _generation_time() -> datetime:
    """LP の生成時刻（JST の aware datetime）。

    実行環境のローカル時刻（CI のランナーは既定で UTC）を JST に変換する。
    タイムゾーン無しの datetime.now() に「JST」と付けると、CI では9時間ずれる（08:49 UTC → 「08:49 JST」）。
    """
    return datetime.now().astimezone(JST)


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

    def generate(self, date_str: Optional[str] = None, variant: Optional[str] = None,
                 notifications: bool = False) -> dict:
        """LP HTMLを生成して保存する。

        notifications: 今すぐ行動の通知（候補・台帳・dry-run の計画）を作るか。CI の「Generate daily LP」の CLI
        （generate-daily-lp）だけが True にする。ほかの呼び出し（買取のプレ値のジョブの途中の生成など）は台帳を
        読み書きしない（1回の CI で2回判定して、後の判定の候補が消えないように。レビュー H-1）。
        """
        self._notifications_enabled = bool(notifications)
        now = _generation_time()
        date_str = date_str or now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")
        # 案件の確定の判定（_gate_and_merge_deals・_nu_profit_deals）に使う時刻（新UIの判定と同じ時刻）
        self._gate_now = self._nu_now(now)

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
        # 監視中（赤字。min_profit=-9999999 で全件取得）
        monitoring_deals    = self.repo.list_beginner_deals(user_level="monitoring",    min_profit=-9999999, limit=30)

        # 上級者向けスナップショット（latest.md に使う）
        advanced_snaps = self.repo.list_premium_candidates_with_snapshots(limit=15, user_level="advanced")

        # 商品別買取店一覧（複数店舗比較用）- product_id → [buyback_rows]
        buyback_by_product: dict = {}
        _all_products = self.repo.list_products()
        # 商品ごとの定価の根拠（確認日不明の設定値で「確定利益」を強調しないため）
        self._msrp_evidence = {_p.id: _pe.classify_product_msrp(_p, now) for _p in _all_products}
        # 利益商品の内部診断（exports/opportunity_diagnostics）に渡す商品の値
        self._diag_products = [{
            "id": _p.id, "name": _p.name, "genre": getattr(_p, "genre", "") or "",
            "official_price": getattr(_p, "official_price", None), "retail_price": getattr(_p, "retail_price", None),
            "official_price_source": getattr(_p, "official_price_source", "") or "",
            "official_price_updated_at": (_p.official_price_updated_at.isoformat()
                                          if getattr(_p, "official_price_updated_at", None) else ""),
            "official_stock_status": getattr(_p, "official_stock_status", "") or "",
            "official_stock_observed_at": getattr(_p, "official_stock_observed_at", "") or "",
            "is_lottery": bool(getattr(_p, "is_lottery", False)),
        } for _p in _all_products if getattr(_p, "is_active", True)]
        # 新UIのジャンル（スマホ・カメラ…）の判定に使う
        self._product_genres = {_p.id: (getattr(_p, "genre", "") or "") for _p in _all_products}
        # 新UIの利益商品の表示に使う商品の情報（型番・定価を確認した日時）
        self._product_info = {
            _p.id: {"genre": getattr(_p, "genre", "") or "", "model": getattr(_p, "model_number", "") or "",
                    "brand": getattr(_p, "brand", "") or "",
                    # 商品詳細（UI Phase 6）に使う。商品の一覧の正本は products（新しい ID は作らない）
                    "name": getattr(_p, "name", "") or "", "jan": getattr(_p, "jan_code", "") or "",
                    # 商品に登録済みの検索用キーワード（PS5 Pro・CFI-7000 など。商品検索に使う。Phase 14）
                    "keywords": [str(k) for k in (getattr(_p, "keywords", None) or []) if k],
                    "official_price": getattr(_p, "official_price", None) or getattr(_p, "retail_price", 0) or 0,
                    "official_checked_at": (_p.official_price_updated_at.isoformat()
                                            if getattr(_p, "official_price_updated_at", None) else ""),
                    # 公式の在庫表示を確認した日時（価格の確認日時とは別。根拠が無ければ空）
                    "stock_checked_at": getattr(_p, "official_stock_observed_at", "") or ""}
            for _p in _all_products}
        for _p in _all_products:
            _rows = self.repo.list_buyback_prices_by_product(_p.id, limit=10)
            if _rows:
                buyback_by_product[_p.id] = _rows

        # 異常 manual 買取の除外（auto_scraped high の +30% 超）。
        # 同一商品に信頼できる auto_scraped high 買取があるのに manual がそれを大幅に上回る場合、
        # 手動入力ミス/販売・相場価格の転記ミスの可能性が高い。auto を信頼し manual を除外する。
        # （normalized_prices.MANUAL_OVER_AUTO_RATIO と同一ルール）。全表示・全計算へ波及。
        for _pid, _rws in list(buyback_by_product.items()):
            _auto_hi = max(
                [(_r.get('buyback_price', 0) or 0) for _r in _rws
                 if _r.get('data_source') == 'auto_scraped'
                 and (_r.get('confidence', 'high') or 'high') == 'high'
                 and (_r.get('buyback_price', 0) or 0) > 0],
                default=0,
            )
            if _auto_hi > 0:
                buyback_by_product[_pid] = [
                    _r for _r in _rws
                    if not (str(_r.get('data_source', '')).startswith('manual')
                            and (_r.get('buyback_price', 0) or 0) > _auto_hi * 1.3)
                ]

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
                    # flea_sold は Pro 仕入れ側データ。beginner の売却先(買取)比較には注入しない。
                    if getattr(_sp, 'data_source', '') == 'flea_sold':
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

        # 新UIと同じ判定を通らない案件の降格と、一覧の統合（_gate_and_merge_deals）
        (all_deals, beginner_easy, beginner_watch, monitoring_deals,
         advanced_deals) = self._gate_and_merge_deals(all_deals, beginner_easy, beginner_watch,
                                                      monitoring_deals, advanced_deals, buyback_by_product)

        # HTML生成（新UIだけ。UI Phase 10 で旧UIのランキング・初心者・Pro・せどり・監視候補の描画と、
        # そのためだけの取得（ジャンル別の一覧・監視候補・市場価格・せどりルートの DB 一覧）を削除した）
        page_html = self._render_page(
            lp_generated_at=lp_generated_at,
            all_deals=all_deals,
            buyback_by_product=buyback_by_product,
            collection_stats=collection_stats,
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

    def _render_page(self, *, lp_generated_at, all_deals, buyback_by_product: dict = None,
                     collection_stats: dict = None) -> str:
        """公開する LP の HTML（新UIだけ。UI Phase 10 で旧UIの DOM・CSS・JS を削除した）。

        新UIの生成に失敗したときは例外にする（旧UIの受け皿は無いので、白い画面を公開しない。前回の公開が残る）。
        """
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

        # 抽選情報（DB の受付中 + CSV の自動取得。product_code・商品名で重複を除き、CSV が優先）
        lottery_events = []
        try:
            lottery_events = list(self.repo.list_lottery_events(status="active", limit=20))
        except Exception:
            lottery_events = []
        _csv_events = self._load_csv_lottery_events()
        if _csv_events:
            _db_codes = {ev.get("product_code", "") for ev in lottery_events if ev.get("product_code")}
            _db_names = {ev.get("product_name", "") for ev in lottery_events}
            for _csv_ev in _csv_events:
                _code = _csv_ev.get("product_code", "")
                _name = _csv_ev.get("product_name", "")
                if _code and _code in _db_codes:
                    continue
                if _name and _name in _db_names:
                    continue
                lottery_events.append(_csv_ev)
        # 新UIの「旧来の抽選」（カメラ・ゲーム機）。状態は新UI側で TCG と同じ判定に通す
        lottery_items = list(lottery_events) + list(self._LOTTERY_REFERENCE_ITEMS)

        head, root = self._new_ui_parts(
            lottery_items=lottery_items, lp_generated_at=lp_generated_at,
            collection_stats=collection_stats,
            site_title=self.settings.get("site_title", "プレ値速報"),
            # 新UIには判定前の案件（生成の最初に保存）を渡す。新UIは同じ判定を自分でかける
            all_deals=(self._nu_source_deals if getattr(self, "_nu_source_deals", None) is not None
                       else all_deals),
            buyback_by_product=buyback_by_product)
        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_title}</title>
<meta name="description" content="{_esc(self.settings.get('site_description', ''))}">
{analytics_head}
{head}
</head>
<body>
{root}
</body>
</html>"""

    # ----- 新UI（?ui=new） -----

    @staticmethod
    def _nu_now(lp_generated_at):
        """新UIの判定に使う生成時刻（JST）。

        generate() は JST の aware datetime を渡す。タイムゾーン無しで渡された場合は
        実行環境のローカル時刻（CI は UTC）として解釈してから JST に直す（JST とみなすと CI で9時間ずれる）。
        """
        from src.tcg.models import JST as _JST
        from src.tcg.models import now_jst as _now_jst
        if not isinstance(lp_generated_at, datetime):
            return _now_jst()
        return lp_generated_at.astimezone(_JST)


    @staticmethod
    def _nu_data_checked_text(report: dict) -> str:
        """新UIのヘッダーに出す「情報確認」の時刻。

        TCG の取得元（source_health）のうち、取得に成功した最新の時刻（last_success）を使う。
        generated_at は収集を実行した時刻で、全部の取得元が失敗しても更新されるので使わない。
        どこも成功していなければ空（時刻を出さない）。
        """
        from src.tcg.models import JST as _JST
        from src.tcg.models import parse_dt as _parse_dt
        health = (report or {}).get("source_health")
        times = [_parse_dt(h.get("last_success")) for h in (health if isinstance(health, list) else [])
                 if isinstance(h, dict) and h.get("last_success")]
        times = [t for t in times if t]
        return max(times).astimezone(_JST).strftime("%m/%d %H:%M") if times else ""


    @staticmethod
    def _load_export_json(*parts: str) -> dict:
        """exports/ 以下の JSON を読む。無い・壊れているときは空 dict（新UIは空状態を出す）。"""
        path = Path(__file__).resolve().parent.parent.parent / "exports"
        for part in parts:
            path = path / part
        if not path.exists():
            return {}
        try:
            import json as _json
            data = _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _confirmed_sell_keys(self) -> set:
        """確定利益の売値に使える買取価格の (商品ID, 店名, 価格)。正規化の観測（exports/normalized_price_observations）
        に normalized_prices.confirmed_sell_keys をかけたもの（商品詳細・新UIの判定と同じデータ・同じ判定）。
        読めないときは空（未照合の価格で利益を出さない）。"""
        keys = getattr(self, "_sell_keys_cache", None)
        if keys is None:
            from src.market.normalized_prices import confirmed_sell_keys
            obs = self._load_export_json("normalized_price_observations", "latest.json").get("observations") or []
            keys = self._sell_keys_cache = confirmed_sell_keys(obs)
        return keys


    def _nu_profit_deals(self, all_deals, buyback_by_product: dict | None = None) -> list[dict]:
        """新UIの「利益商品」の候補（定価で買って買取店に売る案件）を、判定に必要な元の値ごと渡す。

        掲載してよいかの判定は src/content/ui/opportunity.py の eligibility だけで行う
        （定価の根拠・売り先・鮮度・費用・ROI など）。ここでは値を集めるだけで、利益は計算し直さない。
        買取価格の確認日時は、最高買取店の行（店名・価格が一致する行）の observed_at。分からなければ空。
        """
        bybp = buyback_by_product or {}
        info = getattr(self, "_product_info", None) or {}
        ev_map = getattr(self, "_msrp_evidence", None) or {}

        def _checked_at(d):
            shop = getattr(d, "best_buyback_shop", "") or ""
            price = getattr(d, "best_buyback_price", 0) or 0
            for r in bybp.get(getattr(d, "product_id", "") or "", []) or []:
                if (r.get("shop_name") or "") == shop and int(r.get("buyback_price") or 0) == int(price):
                    return str(r.get("observed_at") or "")
            return ""

        out: list[dict] = []
        for d in all_deals or []:
            net = getattr(d, "net_profit_jpy", 0) or 0
            if net <= 0:
                continue
            pid = getattr(d, "product_id", "") or ""
            shop = getattr(d, "best_buyback_shop", "") or ""
            p = info.get(pid, {})
            ship = _official_shipping.purchase_shipping(pid, getattr(d, "official_url", "") or "",
                                                        getattr(d, "official_price_jpy", 0) or 0)
            out.append({
                "product_id": pid, "title": getattr(d, "product_name", "") or "",
                "genre": p.get("genre") or getattr(d, "category", "") or "", "model": p.get("model", ""),
                "brand": p.get("brand") or getattr(d, "brand", "") or "",
                "condition": getattr(d, "buyback_condition", "") or "",
                "official_price": getattr(d, "official_price_jpy", 0) or 0,
                "official_checked_at": p.get("official_checked_at", ""),
                "msrp_evidence": ev_map.get(pid, _pe.UNKNOWN),
                "official_url": getattr(d, "official_url", "") or "",
                "stock_status": getattr(d, "stock_status", "") or "",
                "stock_checked_at": p.get("stock_checked_at", ""),
                "sale_method": getattr(d, "sale_method", "") or "",
                "sell_shop": shop, "sell_price": getattr(d, "best_buyback_price", 0) or 0,
                "sell_checked_at": _checked_at(d), "sell_url": getattr(d, "best_buyback_url", "") or "",
                # 売却価格の商品の同一性（normalized_prices.sell_confirmation_reasons。商品ID・店名・価格で照合）
                "sell_identity_verified": (pid, shop, int(getattr(d, "best_buyback_price", 0) or 0))
                in self._confirmed_sell_keys(),
                # 購入送料（公式の一次情報で確認したものだけ。分からなければ None）
                "purchase_shipping": ship["fee"], "purchase_shipping_status": ship["status"],
                "net_profit": net, "user_level": getattr(d, "user_level", "") or "",
                "resale_sell": bool(shop) and self._is_resale_shop(shop),
            })
        return out

    @staticmethod
    def _merge_by_product(*lists) -> list:
        """product_id ごとに純利益の大きい案件を1件残す。"""
        union: dict = {}
        for src in lists:
            for d in (src or []):
                pid = getattr(d, 'product_id', None)
                if pid is None:
                    continue
                ex = union.get(pid)
                if ex is None or (getattr(d, 'net_profit_jpy', 0) or 0) > (getattr(ex, 'net_profit_jpy', 0) or 0):
                    union[pid] = d
        return list(union.values())

    def _gate_and_merge_deals(self, all_deals, beginner_easy, beginner_watch, monitoring_deals,
                              advanced_deals, buyback_by_product: dict | None = None):
        """補完済みの案件の一覧に新UIと同じ判定をかけ、統合する。

        - 新UIには判定前の統合を渡す（self._nu_source_deals。新UIは自分で同じ判定をかけ、外した理由を診断に残す）
        - 判定後の一覧は latest.md（docs/latest.md）と生成の件数（CLI の表示）に使う。判定（opportunity.deal_reasons）を
          通らない案件は確定利益として出さず監視中へ降格する。定価の根拠だけが未確認の案件は「参考差額」として残す
        - 補完で利益ありに戻った監視中の案件も含め、統合の前にすべての一覧にかける
          （統合は純利益の大きい方を残すので、判定前の版が判定後の版に勝たないようにする）
        - 上級者向けの案件は確定だけ（参考差額・降格した案件は入れない）
        """
        self._nu_source_deals = self._merge_by_product(all_deals, beginner_easy, beginner_watch, monitoring_deals)

        def _gate_list(lst):
            return [self._canonical_deal_gate(d, buyback_by_product) for d in (lst or [])]
        all_deals = _gate_list(all_deals)
        beginner_easy = _gate_list(beginner_easy)
        beginner_watch = _gate_list(beginner_watch)
        monitoring_deals = _gate_list(monitoring_deals)
        advanced_deals = [d for d in _gate_list(advanced_deals)
                          if (d.net_profit_jpy or 0) > 0 and not self._msrp_is_reference(d)]
        all_deals = self._merge_by_product(all_deals, beginner_easy, beginner_watch, monitoring_deals)
        return all_deals, beginner_easy, beginner_watch, monitoring_deals, advanced_deals

    # 降格した理由（降格した案件の notes に残す一般向けの言葉。内部の理由名は出さない。deploy-check #464 が検査）
    _UNCONFIRMED_LABELS = (
        ("sell_identity_unverified", "買取価格の商品照合が未完了（店のトップ・一覧の価格など）"),
        ("stale_sell_price", "買取価格の確認が14日より前か、確認時刻が不明"),
        ("resale_sell", "売り先が二次流通（買取店ではない）"),
        ("purchase_shipping_unknown", "購入送料が分からない（公式で未確認）"),
        ("costs_unknown", "費用が分からない"),
        ("breakdown_mismatch", "利益の内訳が合わない"),
        ("roi_out_of_range", "利益率が表示できる範囲の外"),
    )

    def _canonical_deal_gate(self, d, buyback_by_product: dict | None = None):
        """定価→買取の案件を、新UIと同じ判定（src/content/ui/opportunity.deal_reasons）に通す。

        - 確定として出せる: そのまま
        - 定価の根拠だけが未確認: そのまま（「参考差額」。確定の利益・一覧には使わない）
        - それ以外（買取価格が古い・費用・ROI・売り先など）: 監視中へ降格する（利益・差額は出さない）
        """
        rows = self._nu_profit_deals([d], buyback_by_product)
        if not rows:            # 利益が無い案件はそのまま（もともと利益を出さない）
            return d
        why = _ui_opp.deal_reasons(rows[0], getattr(self, "_gate_now", None) or self._nu_now(None))
        if not why or _ui_opp.is_msrp_reference_only(why):
            return d
        label = next((lbl for key, lbl in self._UNCONFIRMED_LABELS if key in why), "確定の条件を満たさない")
        return d.model_copy(update={
            'best_buyback_price': 0,
            'best_buyback_shop': '—',
            'best_buyback_url': '',
            'net_profit_jpy': 0,
            'gross_profit_jpy': 0,
            'net_profit_rate': 0.0,
            'user_level': 'monitoring',
            'notes': ((getattr(d, 'notes', '') or '') + f'||UNCONFIRMED:{label}'),
        })


    def _new_ui_parts(self, *, lottery_items, lp_generated_at, collection_stats, site_title,
                      all_deals=None, buyback_by_product=None) -> tuple[str, str]:
        """新UIの <head> 部分と #new-ui-root を返す。

        失敗したら例外にする（UI Phase 10 で旧UIを削除したので受け皿は無い。白い画面や空のページを公開しない。
        CI はここで止まり、前回の公開が残る）。
        """
        from src.content.ui import shell as _ui_shell
        report = self._load_tcg_report()
        report = report if isinstance(report, dict) else {}
        cov = report.get("lottery_coverage")
        cov = cov if isinstance(cov, dict) else {}
        health = report.get("source_health")
        health = health if isinstance(health, list) else []
        source_issue = bool(
            (cov.get("blocked_sources") or 0) or (cov.get("unreachable_sources") or 0)
            or any(isinstance(h, dict) and h.get("errors") for h in health)
            or (collection_stats or {}).get("failed", 0))
        ctx = _ui_shell.ShellContext(
            tcg_report=report,
            opportunities=self._load_export_json("ai_opportunities", "latest.json"),
            profit_routes=self._load_export_json("profit_routes", "latest.json"),
            # 旧来の抽選（カメラ・ゲーム機）。状態は新UI側で TCG と同じ判定に通す
            legacy_lotteries=[it if isinstance(it, dict) else dict(it) for it in lottery_items],
            # ヘッダーの時刻は「データを確認した時刻」（TCG の収集時刻）。ページの生成時刻にしない
            updated_text=self._nu_data_checked_text(report),
            source_issue=source_issue,
            site_title=str(site_title or "プレ値速報"),
            now=self._nu_now(lp_generated_at),
            profit_deals=self._nu_profit_deals(all_deals, buyback_by_product),
            product_genres=getattr(self, "_product_genres", None) or {},
            stock_history=self._load_export_json("stock_history", "latest.json"),
            price_observations=self._load_export_json("normalized_price_observations", "latest.json").get(
                "observations") or [],
            products=self._nu_products(),
            price_history=self._load_export_json("price_history", "latest.json"),
            notifications=self._nu_notifications(),
            admin_data=self._nu_admin_data(),
            cta_links=self._nu_cta_links(),
        )
        # 候補の診断（内部用）を先に作り、運営者向けのページにも同じ生成のものを渡す（前回の生成を読まない）
        diag = self._write_opportunity_diagnostics(ctx)
        if diag is not None:
            ctx.admin_data["diagnostics"] = diag
            # 診断の直後に、行動できるようになった商品の通知の候補・重複の抑制・配信の計画（dry-run。Phase 19）
            notif = (self._write_actionable_notifications(diag, ctx.now)
                     if getattr(self, "_notifications_enabled", False) else None)
            if notif is not None:
                ctx.admin_data["actionable_notifications"] = notif
        elif getattr(self, "_notifications_enabled", False):
            # 診断に失敗したら、通知も今回は作れなかったと記録する（前回の件数を今回のものとして読ませない。監査 L-3）
            self._write_notification_failure(ctx.now, None, "DiagnosticsFailed")
        root = _ui_shell.render_root(ctx)
        return _ui_shell.render_head(), root

    def _nu_cta_links(self) -> list:
        """新UIのフッターの外部リンク（旧UIの _section_cta と同じ設定。URL が無いもの・「#」は出さない）。"""
        out = []
        for flag, key, label, track in (("enable_note_cta", "note_url", "詳細レポート（note）", "note_click"),
                                        ("enable_line_cta", "line_url", "LINE速報", "line_click"),
                                        ("enable_telegram_cta", "telegram_url", "Telegram速報", "telegram_click")):
            url = str(self.settings.get(key) or "").strip()
            if self.settings.get(flag) and url and url != "#":
                out.append((label, url, track))
        return out

    def _nu_admin_data(self) -> dict:
        """運営者向けのページ（UI Phase 9）に渡す生成物。どの項目を出すかは admin.build が決める（ここでは読むだけ）。
        アカウントの集計（exports/admin）・秘密の値は渡さない。"""
        root = Path(__file__).resolve().parent.parent.parent
        data: dict = {}
        for key, parts in (("collector", ("collector_report", "latest.json")),
                           ("dq_report", ("data_quality_report", "latest.json")),
                           ("diagnostics", ("opportunity_diagnostics", "latest.json")),
                           ("ai", ("ai_opportunities", "latest.json")), ("allocation", ("allocation", "latest.json")),
                           ("execution", ("execution", "latest.json")),
                           ("execution_history", ("execution", "execution_history.json")),
                           ("notifications_latest", ("notifications", "latest.json")),
                           ("api", ("api_automation", "latest.json")), ("coverage", ("coverage", "latest.json")),
                           ("resale_status", ("resale_collection_status.json",)),
                           ("camera_status", ("camera_buyback_status.json",))):
            data[key] = self._load_export_json(*parts)
        try:
            import json as _json_ad
            data["health"] = _json_ad.loads((root / "audit_health" / "health_report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data["health"] = {}
        for key, name in (("deploy_check", "deploy_check_latest.txt"), ("prelaunch_check", "prelaunch_check_latest.txt")):
            try:
                from src.content.ui import admin as _ui_admin
                data[key] = _ui_admin.check_text((root / "exports" / name).read_text(encoding="utf-8"))
            except OSError:
                data[key] = ""
        data["flea_sold"] = {n: self._load_export_json("flea_sold_prices", f"{n}_sold.json")
                             for n in ("mercari", "yahoo", "rakuma")}
        # 旧表示の取得の警告バーと同じ閾値・成約の件数の下限（運営者向けページの説明に使う）
        data["warn_threshold"] = self._COLLECTOR_WARN_THRESHOLD
        data["min_sold_samples"] = _pt.MIN_SOLD_SAMPLES
        # 任意の店（取得できなくても公開に影響しない）。正本は scripts/check_collector_quality.OPTIONAL_SHOPS
        try:
            import importlib.util as _iu_ad
            _sp = _iu_ad.spec_from_file_location("_ccq_for_admin", root / "scripts" / "check_collector_quality.py")
            _m = _iu_ad.module_from_spec(_sp)
            _sp.loader.exec_module(_m)
            data["optional_shops"] = sorted(getattr(_m, "OPTIONAL_SHOPS", {}) or {})
        except Exception:                                   # noqa: BLE001
            data["optional_shops"] = []
        return data

    def _nu_notifications(self) -> list[dict]:
        """マイページの通知の履歴（exports/notifications の latest と直近7日の history。読むだけで書き換えない）。
        どれを出すか（利用者向けの種類・今も確定のルートか）はマイページ（mypage.build_events）が決める。"""
        import json as _json_nn
        base = Path(__file__).resolve().parent.parent.parent / "exports" / "notifications"
        events: list[dict] = []
        try:
            files = [base / "latest.json"] + sorted((base / "history").glob("*.json"), reverse=True)[:7]
        except OSError:
            return events
        for f in files:
            try:
                d = _json_nn.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for e in (d.get("events") or []) if isinstance(d, dict) else []:
                if isinstance(e, dict) and e not in events:
                    events.append(e)
        return events

    def _nu_products(self) -> list[dict]:
        """商品詳細の対象（products の登録順）。公式の URL は product_source_config の登録（_official_meta）。"""
        meta = self._official_meta()
        # 販売方式（公式の販売終了など。案件の記録から。旧UIの「参考定価（公式販売終了）」の後継）
        sale = {getattr(d, "product_id", ""): getattr(d, "sale_method", "") or ""
                for d in (getattr(self, "_nu_source_deals", None) or [])}
        return [{"product_id": pid, "name": p.get("name") or pid, "genre": p.get("genre", ""),
                 "brand": p.get("brand", ""), "model": p.get("model", ""), "jan": p.get("jan", ""),
                 "keywords": list(p.get("keywords") or []),
                 "official_price": p.get("official_price") or 0,
                 "official_url": (meta.get(pid) or {}).get("url", ""), "sale_method": sale.get(pid, "")}
                for pid, p in (getattr(self, "_product_info", None) or {}).items()]

    def _official_meta(self) -> dict:
        """公式の定価の登録（product_source_config の extra_config）。商品ID → URL・確認・販売終了などの情報。"""
        import json as _json
        out: dict = {}
        try:
            rows = self.repo.db.connection.execute(
                "SELECT product_id, source_id, target_url, extra_config FROM product_source_config").fetchall()
        except Exception:  # noqa: BLE001
            return out
        from src.market.official_price_validator import OFFICIAL_DOMAINS
        for r in rows:
            if r["source_id"] not in OFFICIAL_DOMAINS and r["source_id"] != "src_nintendo_store":
                continue
            try:
                extra = _json.loads(r["extra_config"] or "{}")
            except (TypeError, ValueError):
                extra = {}
            cur = out.get(r["product_id"], {})
            # 確認済み（verified）の登録を優先して残す
            if cur.get("verified") and not extra.get("verified"):
                continue
            out[r["product_id"]] = {"source_id": r["source_id"], "url": r["target_url"] or "", **extra}
        return out

    @staticmethod
    def _diagnostics_dir() -> Path:
        import os as _os
        return Path(_os.environ.get("OPPORTUNITY_DIAGNOSTICS_DIR")
                    or Path(__file__).resolve().parent.parent.parent / "exports" / "opportunity_diagnostics")

    def _prev_actionable(self) -> list | None:
        """前回の診断の「今すぐ行動できる」商品（読めなければ None = 基準日。Phase 18 の通知の候補の比較に使う）。"""
        import json as _json
        try:
            d = _json.loads((self._diagnostics_dir() / "latest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        act = (d.get("actionable") or {}).get("products") if isinstance(d, dict) else None
        return act if isinstance(act, list) else None

    @staticmethod
    def _actionable_notifications_dir() -> Path:
        import os as _os
        return Path(_os.environ.get("ACTIONABLE_NOTIFICATIONS_DIR")
                    or Path(__file__).resolve().parent.parent.parent / "exports" / "notifications" / "actionable")

    def _write_actionable_notifications(self, diag: dict, now) -> dict | None:
        """今すぐ行動できるようになった商品を通知の outbox に入れる（src/notifiers/outbox。Phase 20）。

        ここでは候補を PENDING で記録して保存するだけ（配信しない）。配信の直前の確認・配信は、保存の後の
        dispatch-notifications の手順で行う。台帳（state.json）が読めないときは基準日（候補を出さない）。
        """
        import os as _os
        from src.notifiers import actionable as _an
        from src.notifiers import outbox as _ob
        # CI で台帳を main の最新に合わせられなかったら、候補を作らない（古い台帳から同じ通知を作り直さない）
        if str(_os.environ.get("NOTIFICATION_OUTBOX_SYNCED", "true")).strip().lower() != "true":
            self._write_notification_failure(now, diag, "OutboxNotSynced")
            return None
        try:
            return _ob.run_observe(self._actionable_notifications_dir(), diag, now=now, dry_run=_an.is_dry_run())
        except Exception as exc:  # noqa: BLE001
            logger.warning("actionable notifications failed: %s", exc)
            self._write_notification_failure(now, diag, type(exc).__name__)
            return None

    def _write_notification_failure(self, now, diag, error: str) -> None:
        """失敗を latest.json に残す（前回の件数を今回のものとして読まれないように。台帳は変えない。監査 L-4）。"""
        from src.utils.atomic_write import write_json_atomic
        out = self._actionable_notifications_dir()
        try:
            out.mkdir(parents=True, exist_ok=True)
            write_json_atomic(out / "latest.json", {
                "generated_at": now.isoformat(timespec="seconds"), "failed": True, "error": error,
                "dry_run": True, "diagnostics_generated_at": str((diag or {}).get("generated_at") or ""),
                "notification_candidates": 0, "dispatch_planned": 0, "dispatch_sent": 0, "candidates": []})
        except Exception:  # noqa: BLE001
            pass

    def _write_opportunity_diagnostics(self, ctx) -> dict | None:
        """利益商品が何件・なぜ除外されたかを exports/opportunity_diagnostics/latest.json に書く（内部用）。"""
        try:
            from src.content.ui import shell as _ui_shell
            from src.market import opportunity_diagnostics as _diag
            _model, catalog = _ui_shell.build_catalog(ctx)
            npo = self._load_export_json("normalized_price_observations", "latest.json")
            sold = {n: self._load_export_json("flea_sold_prices", f"{n}_sold.json")
                    for n in ("yahoo", "mercari", "rakuma")}
            report = _diag.build(
                products=getattr(self, "_diag_products", None) or [],
                msrp_evidence=getattr(self, "_msrp_evidence", None) or {},
                official_meta=self._official_meta(),
                observations=npo.get("observations") or [],
                opportunity_set=catalog.opportunity_set,
                home_count=catalog.count("opportunities"),
                list_count=len(catalog.items["opportunities"]),
                sold_exports=sold, now=ctx.now, prev_actionable=self._prev_actionable())
            # 出力先は環境変数で変えられる（テストは一時フォルダに向け、リポジトリの exports/ を上書きしない）
            out = self._diagnostics_dir()
            out.mkdir(parents=True, exist_ok=True)
            import json as _json
            (out / "latest.json").write_text(_json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report
        except Exception as exc:  # noqa: BLE001
            logger.warning("opportunity diagnostics failed: %s", exc)
            return None

    # ----- 定価の根拠 -----


    def _msrp_is_reference(self, d) -> bool:
        """案件の仕入れ値（定価）が、確定利益の計算に使えない値か（設定値で確認日不明・古い・不明）。

        True の案件は「最高利益」「利益あり」「ランキング1位」などの強い表示に使わず、
        「参考差額」「参考定価（確認日不明）」として確定利益と区別して出す。
        """
        ev_map = getattr(self, "_msrp_evidence", None) or {}
        ev = ev_map.get(getattr(d, "product_id", "") or "", _pe.UNKNOWN)
        return not _pe.is_profit_eligible(ev)

    # ----- Hero -----


    # ----- Stale Warning -----


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
    def _load_tcg_report() -> dict:
        """exports/tcg/latest.json を読み込む。無ければ空 dict。"""
        path = (Path(__file__).resolve().parent.parent.parent
                / "exports" / "tcg" / "latest.json")
        if not path.exists():
            return {}
        try:
            import json as _json
            return _json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}


    # ---- せどりルート共通ヘルパー ----


    # ----- Tab: 初級者向け -----


    # ----- Tab: 急騰/急落 -----


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
        keys = self._confirmed_sell_keys()
        # 既存値が中古条件 or resale 店名由来、または商品の照合が済んでいない買取価格なら「汚染」とみなし、強制的に再評価
        _stored_unverified = bool(stored_shop) and stored_shop != '—' and (
            (deal.product_id, stored_shop, int(deal.best_buyback_price or 0)) not in keys)
        _tainted = self._is_resale_shop(stored_shop) or self._cond_is_used(stored_cond) or _stored_unverified

        # 候補は、商品の同一性が確認済みの買取価格だけ（normalized_prices.sell_confirmation_reasons。
        # 店のトップ・検索結果の価格は、より高くても使わない）
        valid_rows = [
            r for r in (rows or [])
            if r.get('buyback_price', 0) > 0
            and r.get('data_source', '') not in ('fetch_failed', 'product_not_listed', 'resale_market')
            and r.get('confidence', 'high') != 'low'
            and not self._cond_is_used(r.get('condition', ''))
            and not self._is_resale_shop(r.get('shop_name', ''))
            and (deal.product_id, r.get('shop_name', '') or '', int(r.get('buyback_price', 0) or 0)) in keys
        ]
        if not valid_rows:
            return _clear(deal) if _tainted else deal

        # auto_scraped(confidence=high) がある場合、それより30%超高い manual 価格は
        # 過大の疑い → 利益判定/ランキングの「最高買取」選定から除外（Task 3）。
        _auto_high = [r for r in valid_rows
                      if r.get('data_source') == 'auto_scraped'
                      and r.get('confidence', 'high') == 'high']
        if _auto_high:
            _auto_high_max = max(r.get('buyback_price', 0) or 0 for r in _auto_high)
            if _auto_high_max > 0:
                valid_rows = [
                    r for r in valid_rows
                    if not (str(r.get('data_source', '')).startswith('manual')
                            and (r.get('buyback_price', 0) or 0) > _auto_high_max * 1.3)
                ]

        best_row = max(valid_rows, key=lambda r: r.get('buyback_price', 0))
        best_price = best_row.get('buyback_price', 0)
        stored_bp = deal.best_buyback_price or 0
        # 汚染されていなければ、より高い有効価格がある場合のみ更新
        if best_price <= stored_bp and not _tainted:
            return deal

        official = deal.official_price_jpy or 0
        costs = 1800  # 送料+振込手数料+移動コスト（固定）
        # 公式の購入送料（一次情報で確認したものだけ。src/market/official_shipping.py）
        costs += _official_shipping.known_fee(deal.product_id, getattr(deal, 'official_url', '') or '', official)
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
        # 在庫ありが明示されているときだけ（空・不明・入荷待ちは在庫ありにしない）
        stock_ok = _stock.is_explicit_in_stock(stock_status)
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


    # ----- Caution / CTA / Footer -----


    # 取得失敗が一定件数以上のとき表示する上部バー
    _COLLECTOR_WARN_THRESHOLD: int = 5  # failed >= この件数で表示


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
                f"- **{s.product_name}**: {_official_label(s.product_id, s.official_price_jpy)}{fmt_price(s.official_price_jpy)} "
                f"/ 中古{fmt_price(s.domestic_used_price_jpy)} "
                f"/ 差{fmt_profit(s.premium_gap_jpy)} / {getattr(s,'sale_method','')}"
            )
        if not advanced_snaps:
            lines.append("条件を満たす候補なし")

        lines.extend(["", DISCLAIMER_FULL])
        return "\n".join(lines)
