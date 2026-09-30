# -*- coding: utf-8 -*-
"""PokemonProductRegistryCollector — ポケモンカード公式の商品レジストリ。

取得元: https://www.pokemon-card.com/products/resultAPI.php
  公式の商品一覧ページ（/products/index.html）が、ページ内の JavaScript から
  呼び出している JSON API。カテゴリトップ（/products/index.html）の本文は
  商品カテゴリの紹介文だけで個別商品を含まないため、解析対象にしない。

  パラメータは公式 bundle.js の実装（setRequestParams）に合わせる:
    productType / dateLowerY,M,D / dateUpperY,M,D / page

取得方針:
  - 周辺グッズ（productType=peripheral）は TCG の販売監視対象外のため取得しない。
  - 商品詳細ページは発見（URL を記録）するが、取得は現在イベントに関係する
    ものだけ・1回の実行あたり MAX_DETAIL_FETCH 件まで（RateLimiter が同一
    ドメイン60秒間隔を強制するため、取得数そのものを絞る）。
  - 記載の無い項目は None。パック価格から BOX 価格を作らない。
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional
from urllib.parse import urlencode, urljoin, urlparse

from src.tcg.funnel import (
    PAGE_LISTING, PAGE_PRODUCT, REJECT_ACCESSORY, REJECT_NO_RELEASE_DATE,
    REJECT_PAST_RELEASE, REJECT_DUPLICATE,
)
from src.tcg.models import (
    BASIS_RELEASE_DATE_ONLY, CHANNEL_UNKNOWN, EVENT_GENERAL_SALE, TCG_POKEMON,
    TcgEvent, now_jst, parse_dt,
)
from src.tcg.product_types import (
    PT_ACCESSORY, classify_pokemon_product_type, is_box_opportunity_eligible,
    parse_contents, parse_release_date, split_prices,
)

from .base import BaseTcgCollector
from .keyword_page import slugify

logger = logging.getLogger(__name__)

SITE_ROOT = "https://www.pokemon-card.com"
API_URL = SITE_ROOT + "/products/resultAPI.php"
LISTING_URL = SITE_ROOT + "/products/index.html"

# 取得する商品種別（API の productType 値）
API_TYPES: tuple[str, ...] = ("expansion", "construction", "others")
# 1種別あたりの最大ページ数（公式 API の maxPage を超えては取りに行かない）
MAX_PAGES_PER_TYPE = 3
# 取得期間: 過去 LOOKBACK_DAYS 〜 未来 LOOKAHEAD_DAYS
LOOKBACK_DAYS = 120
LOOKAHEAD_DAYS = 400
# 発売日からこの日数以内なら「現在のイベント」として扱う
# （freshness の48時間カットオフと合わせる。これより古い発売は registry のみ）
CURRENT_RELEASE_WINDOW = timedelta(days=2)
# 1回の実行で取得する商品詳細ページの上限
MAX_DETAIL_FETCH = 4
# 商品詳細として扱ってよいドメイン（公式のみ）
DETAIL_DOMAINS: tuple[str, ...] = ("www.pokemon-card.com", "www.30th.pokemon-card.com")


def build_api_url(api_type: str, page: int = 1, now=None) -> str:
    """公式 API の URL を組み立てる。"""
    now = now or now_jst()
    lo = now - timedelta(days=LOOKBACK_DAYS)
    hi = now + timedelta(days=LOOKAHEAD_DAYS)
    params = {
        "productType": api_type,
        "dateLowerY": lo.year, "dateLowerM": lo.month, "dateLowerD": lo.day,
        "dateUpperY": hi.year, "dateUpperM": hi.month, "dateUpperD": hi.day,
    }
    if page > 1:
        params["page"] = page
    return API_URL + "?" + urlencode(params)


def normalize_detail_url(link: str) -> Optional[str]:
    """商品詳細リンクを絶対 URL にし、公式ドメイン以外・アンカーを除外する。"""
    if not link:
        return None
    url = urljoin(SITE_ROOT + "/", link.strip())
    url = url.split("#", 1)[0]
    host = (urlparse(url).hostname or "").lower()
    if host not in DETAIL_DOMAINS:
        return None
    return url


def product_from_api(item: dict, discovered_at: str, source_url: str) -> Optional[dict]:
    """API の1商品を registry レコードに変換する。商品名が無ければ None。"""
    title = (item.get("productTitle") or "").strip()
    if not title:
        return None
    api_type = (item.get("productType") or "").strip()
    ptype = classify_pokemon_product_type(api_type, title)
    prices = split_prices(ptype, item.get("priceTxt") or "", api_type=api_type)
    contents = parse_contents(item.get("description") or "")
    detail = normalize_detail_url(item.get("link_detailPage") or "")
    image = item.get("tumbsImg") or ""
    return {
        "product_id": "pokemon-" + slugify(title),
        "name": title,
        "tcg": TCG_POKEMON,
        "api_product_type": api_type,
        "product_type": ptype,
        "box_opportunity_eligible": is_box_opportunity_eligible(ptype),
        "release_date": parse_release_date(item.get("releaseDate") or ""),
        "release_date_text": item.get("releaseDate") or None,
        "price_text": prices["price_text"],
        "pack_price": prices["pack_price"],
        "retail_price": prices["retail_price"],
        "retail_price_basis": prices["retail_price_basis"],
        # 公式が「○パック入り」と明示した場合のみ。無ければ None
        "packs_per_box": contents["packs_per_box"],
        "cards_per_pack": contents["cards_per_pack"],
        "box_configuration": (item.get("description") or "").strip() or None,
        "stores_available": (item.get("storesAvailable") or "").strip() or None,
        "official_url": detail,
        "canonical_url": None,          # 詳細ページを取得した場合のみ設定
        "official_image_url": urljoin(SITE_ROOT + "/", image) if image else None,
        "pokemon_center_url": (item.get("link_pokemonCenter") or "").strip() or None,
        "series_name": None,
        "product_code": None,
        "source_url": source_url,
        "discovered_at": discovered_at,
        "verified": True,               # 公式 API から直接取得した値のみ
        "last_verified_at": discovered_at,
        "detail_fetched": False,
    }


def secondary_mapping(record: dict) -> Optional[dict]:
    """Task20: 二次流通価格を投入するための product mapping。

    BOX Opportunity 対象の種別だけ。シュリンク付き / なしを別 variant にする。
    """
    if not record.get("box_opportunity_eligible"):
        return None
    pid = record["product_id"]
    return {
        "product_id": pid,
        "name": record["name"],
        "sealed_variant": f"{pid}:SEALED_SHRINK",
        "unsealed_variant": f"{pid}:SHRINK_REMOVED",
    }


class PokemonProductRegistryCollector(BaseTcgCollector):
    """公式商品 API から registry を作り、発売予定・発売直後の商品をイベント化する。"""

    source_key = "POKEMON_CARD_OFFICIAL"
    source_name = "ポケモンカードゲーム公式（商品API）"
    tcg = TCG_POKEMON
    channel = CHANNEL_UNKNOWN          # 公式は販売チャネルを限定していない
    urls = (API_URL,)
    requires_product_pages = True      # 商品ページを発見できなければ DEGRADED

    def __init__(self) -> None:
        super().__init__()
        self.registry: list[dict] = []

    # ── 取得 ────────────────────────────────────────────────────────────
    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        now = now_jst()
        discovered_at = now.isoformat()
        seen_ids: set[tuple] = set()

        for api_type in API_TYPES:
            page, max_page = 1, 1
            while page <= min(max_page, MAX_PAGES_PER_TYPE):
                url = build_api_url(api_type, page, now)
                self.funnel.pages_discovered += 1
                data = self._fetch_json(url, page_type=PAGE_LISTING,
                                        referer=LISTING_URL)
                if not isinstance(data, dict) or data.get("result") != 1:
                    break
                try:
                    max_page = int(data.get("maxPage") or 1)
                except (TypeError, ValueError):
                    max_page = 1
                diag = self.funnel.pages[-1]
                items = data.get("products")
                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, dict):
                        continue
                    rec = product_from_api(item, discovered_at, url)
                    if rec is None:
                        continue
                    # 同名でも発売日が違えば別の販売（再販等）として残す
                    key = (rec["product_id"], rec["release_date"])
                    if key in seen_ids:
                        continue
                    seen_ids.add(key)
                    self.registry.append(rec)
                    if rec["official_url"]:
                        diag.product_links_discovered += 1
                        self.funnel.product_links_discovered += 1
                page += 1

        detail_urls = {r["official_url"] for r in self.registry if r["official_url"]}
        self.funnel.product_pages_discovered = len(detail_urls)
        if self.funnel.pages_loaded:
            self.health["last_success"] = now_jst().isoformat()

        # 詳細ページで補った canonical / 取扱条件をイベントにも反映するため先に取得
        self._fetch_details(now)
        events = self._build_events(now)
        return self._finish([e.to_dict() for e in events])

    # ── イベント化 ──────────────────────────────────────────────────────
    def _is_current(self, rec: dict, now) -> bool:
        rd = parse_dt(rec.get("release_date"))
        return bool(rd and rd >= now - CURRENT_RELEASE_WINDOW)

    def _build_events(self, now) -> list[TcgEvent]:
        """発売予定・発売直後の商品だけを販売イベントにする。"""
        events: list[TcgEvent] = []
        seen: set[tuple] = set()
        for rec in self.registry:
            self.funnel.candidate_events += 1
            if rec["product_type"] == PT_ACCESSORY:
                self.funnel.reject(REJECT_ACCESSORY)
                continue
            if not rec["release_date"]:
                self.funnel.reject(REJECT_NO_RELEASE_DATE)
                continue
            if not self._is_current(rec, now):
                self.funnel.reject(REJECT_PAST_RELEASE)
                continue
            key = (rec["product_id"], rec["release_date"])
            if key in seen:
                self.funnel.reject(REJECT_DUPLICATE)
                continue
            seen.add(key)

            notes: list[str] = []
            if rec["stores_available"]:
                notes.append(f"公式記載の取扱店: {rec['stores_available']}")
            if rec["pack_price"] and not rec["retail_price"]:
                notes.append("掲載価格は1パックの希望小売価格です（BOX 価格ではありません）")
            notes.append("公式の発売日情報です。店頭・通販の在庫は確認していません")
            events.append(TcgEvent(
                tcg=TCG_POKEMON,
                product_id=rec["product_id"],
                product_name=rec["name"],
                event_type=EVENT_GENERAL_SALE,
                store=self.source_key,
                channel=self.channel,
                sale_start=rec["release_date"],
                release_date=rec["release_date_text"],
                price=rec["retail_price"] or rec["pack_price"],
                pack_price=rec["pack_price"],
                retail_price_basis=rec["retail_price_basis"],
                product_type=rec["product_type"],
                box_configuration=rec["box_configuration"],
                packs_per_box=rec["packs_per_box"],
                official_image_url=rec["official_image_url"],
                canonical_url=rec["canonical_url"],
                stores_available=rec["stores_available"],
                source_url=rec["official_url"] or LISTING_URL,
                source_type="OFFICIAL",
                confidence="high",
                official_confirmation=True,
                # 公式の発売日だけが根拠。在庫・販売中は確認していない
                availability_basis=BASIS_RELEASE_DATE_ONLY,
                notes=notes,
                observed_at=now.isoformat(),
            ))
            self.funnel.accept()
        return events

    # ── 商品詳細 ────────────────────────────────────────────────────────
    def _fetch_details(self, now) -> None:
        """現在イベントに関係する商品詳細ページだけを取得して registry を補う。"""
        targets: list[str] = []
        for rec in self.registry:
            url = rec["official_url"]
            if (url and url not in targets and rec["product_type"] != PT_ACCESSORY
                    and self._is_current(rec, now)):
                targets.append(url)
        for url in targets[:MAX_DETAIL_FETCH]:
            self.funnel.pages_discovered += 1
            html = self._fetch(url, page_type=PAGE_PRODUCT, referer=LISTING_URL)
            if not html:
                continue
            self.funnel.product_pages_loaded += 1
            text = self.to_text(html)
            canonical = self._canonical(html) or self.funnel.pages[-1].final_url or url
            store_note = self._store_note(text)
            for rec in self.registry:
                if rec["official_url"] != url:
                    continue
                rec["detail_fetched"] = True
                rec["canonical_url"] = canonical
                if store_note and not rec["stores_available"]:
                    rec["stores_available"] = store_note
        if len(targets) > MAX_DETAIL_FETCH:
            self.funnel.notes.append(
                f"商品詳細は {MAX_DETAIL_FETCH}/{len(targets)} 件のみ取得"
                "（同一ドメイン60秒間隔のため取得数を制限）")

    @staticmethod
    def _canonical(html: str) -> Optional[str]:
        import re
        m = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
                      html or "", re.I)
        return m.group(1) if m else None

    @staticmethod
    def _store_note(text: str) -> Optional[str]:
        """「○○のみでのお取り扱い」等、公式に明記された取扱条件だけを抜き出す。"""
        import re
        m = re.search(r"[^。\n]{0,40}のみでのお取り扱い[^。\n]{0,20}", text or "")
        return m.group(0).strip() if m else None
