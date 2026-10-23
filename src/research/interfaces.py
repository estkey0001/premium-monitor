"""リサーチエンジンの共通の窓口（設計のみ。Market Research Foundation F・G）。

実装は Apple（src/discovery/apple.py）だけ。ここは「Apple で作った発見の形を、ほかの公式販売元・売却先に広げるとき
に守る形」を決める。新しい取得元をここに足す前に、取得の作法（src/collectors/polite.py: robots.txt・同じドメインの
間隔・取得元の打ち切り・正直な User-Agent）と利用規約の確認を済ませる。遮断された取得元は回避しない。

「コードがある」ことは網羅に数えない。実データ（観測した行）が出ているものだけを網羅に数える。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from src.market import price_types as pt


@dataclass(frozen=True)
class RetailListing:
    """公式の販売元の一覧から読んだ1商品（小売起点の発見の入力）。

    価格は公式のページが明示した値だけ。名前だけで正本にしない（identity は JAN・型番・部品番号で確かめる）。
    """
    maker: str
    name: str
    price: Optional[int]                 # 税込の公式価格（読めなければ None。推測しない）
    url: str                             # 商品の公式ページ（検索結果・トップは不可）
    observed_at: str                     # 実際に取得した時刻
    jan: str = ""
    model_number: str = ""
    part_numbers: tuple[str, ...] = ()
    available: Optional[bool] = None     # 公式が在庫・販売中を明示したときだけ。読めなければ None


@runtime_checkable
class RetailDiscoveryAdapter(Protocol):
    """小売起点の発見（公式の一覧 → 買取・中古を照合 → 調査候補）の窓口。

    対象の候補: Apple（実装済み）・Nintendo・Sony・Ricoh・Fujifilm・Canon・Nikon。
    実装の条件: 公式の公開ページ（ログイン不要）に商品の一覧があり、robots.txt が許し、規約が自動取得を禁じていない。
    """
    source_id: str
    maker: str

    def list_products(self) -> list[RetailListing]:
        """公式の一覧にある商品。取得は src/collectors/polite.py を通す。失敗したら例外でなく空を返さず、理由を持つ。"""
        ...


@dataclass(frozen=True)
class SoldRecord:
    """成約（実際に売れた価格）の1件。出品中の価格・希望価格は成約にしない。"""
    marketplace: str                     # mercari / yahoo_auctions / rakuma / ebay など
    title: str
    price: int
    sold_at: str                         # 成約の日時（無いものは成約として使わない）
    item_url: str                        # 商品（取引）の個別ページ（検索結果は不可）
    condition: str = ""
    currency: str = "JPY"
    source_kind: str = ""                # official_api / licensed_data / public_page


# 成約の証拠の要件（これを満たさない行は成約の中央値にも利益の売値にも使わない）
SOLD_EVIDENCE_REQUIREMENTS = (
    "item_url: 個別の取引ページ（検索結果・店トップは不可）",
    "sold_at: 成約の日時",
    "price > 0（円。外貨は換算の根拠が要る）",
    "title が正本の商品と照合できる（JAN・型番・部品番号。付属品・別の型番を除く）",
    "取得が公式 API・許諾されたデータ・規約が許す公開ページのいずれか（規約・アクセス制限に反する取得は禁止）",
    "中央値に使うときは、期間（開始・終了）と件数（既定 3 件以上）が揃う",
)


@runtime_checkable
class MarketplaceSoldAdapter(Protocol):
    """成約の取得の窓口（メルカリ・ヤフオク・ラクマ・eBay）。

    現状の実データ: すべて 0 件（メルカリ・ヤフオクは規約上ライブ取得をしない・ラクマは 0 行・eBay は API が未設定）。
    実装の前に: 公式 API・許諾の有無と規約を確認する。無いものは「未対応」として残し、網羅に数えない。
    """
    marketplace: str
    terms_allow_automation: bool         # 規約が自動取得を許しているか（False なら実装しない）

    def fetch_sold(self, product_id: str) -> list[SoldRecord]:
        ...


def valid_sold_record(r: SoldRecord) -> list[str]:
    """成約の証拠として使えない理由（空なら使える）。"""
    out = []
    out.extend(pt.sold_evidence_reasons(r.item_url, r.sold_at))      # dummy_url / no_item_url / no_sold_at / sold_at_in_future
    if not isinstance(r.price, int) or r.price <= 0:
        out.append("invalid_price")
    if r.currency != "JPY":
        out.append("foreign_currency_without_conversion")
    if not r.source_kind:
        out.append("source_kind_unknown")
    return out
