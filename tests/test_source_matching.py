#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Source Matching 回帰テスト（Task19）。

商品同一性・容量・型番・状態・アクセサリー・下取・検索結果降格・stale main 拒否 を検証。
利益/AI ロジックは対象外（マッチング品質のみ）。

実行: pytest tests/test_source_matching.py  または  python tests/test_source_matching.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.market.price_quality import (
    extract_capacity_gb, _model_key, model_compatible, condition_class,
    is_main_promotable, detect_duplicate_price_pattern,
)
from src.market.official_price_validator import sanity_check_price
from src.market.product_identity_resolver import ProductIdentityResolver


# ── 容量正規化（Task6）──
def test_capacity_normalization():
    assert extract_capacity_gb("256GB") == 256
    assert extract_capacity_gb("256 GB") == 256
    assert extract_capacity_gb("512GB") == 512
    assert extract_capacity_gb("1TB") == 1024
    assert extract_capacity_gb("1 TB") == 1024
    assert extract_capacity_gb("1024GB") == 1024
    assert extract_capacity_gb("2TB") == 2048


def test_capacity_256_ne_512():
    assert extract_capacity_gb("iPhone 17 Pro 256GB") != extract_capacity_gb("iPhone 17 Pro 512GB")


def test_1tb_eq_1024gb():
    assert extract_capacity_gb("1TB") == extract_capacity_gb("1024GB") == 1024


# ── 機種判別（Task7）──
def test_iphone_pro_ne_pro_max():
    assert model_compatible("iPhone 17 Pro 256GB", "iPhone 17 Pro Max 256GB") is False


def test_iphone_generation_16_ne_17():
    assert model_compatible("iPhone 16 Pro", "iPhone 17 Pro") is False


def test_iphone_pro_same_capacity_differs_ok_model():
    # 同機種・容量違いは機種としては互換（容量で別SKU判定する）
    assert model_compatible("iPhone 17 Pro 256GB", "iPhone 17 Pro 512GB") is True


def test_gr4_ne_gr4hdf():
    assert model_compatible("RICOH GR IV", "RICOH GR IV HDF") is False


def test_gr4hdf_ne_gr4monochrome():
    assert model_compatible("RICOH GR IV HDF", "RICOH GR IV Monochrome") is False


def test_leica_m11_ne_m11p():
    assert model_compatible("Leica M11-P", "Leica M11") is False


# ── Sony 型番エイリアス（Task7）──
def _resolver():
    products = {
        "prod_a1ii": {"name": "SONY α1 II", "model_number": "ILCE-1M2", "brand": "SONY"},
        "prod_a7rv": {"name": "SONY α7R V", "model_number": "ILCE-7RM5", "brand": "SONY"},
        "prod_fx3": {"name": "SONY FX3", "model_number": "ILME-FX3", "brand": "SONY"},
        "prod_iphone17pro_256": {"name": "iPhone 17 Pro 256GB SIMフリー", "model_number": ""},
        "prod_iphone17pm_512": {"name": "iPhone 17 Pro Max 512GB SIMフリー", "model_number": ""},
    }
    return ProductIdentityResolver(products)


def test_sony_model_alias_mapping():
    R = _resolver()
    r = R.resolve(source_title="SONY α1 II ILCE-1M2 ボディ", link_type="item")
    assert r.matched_product_id == "prod_a1ii"
    assert r.identity_confidence == "high"
    assert r.matched_tier == "model_number"
    # 別型番は α1 II に誤マッチしない
    r2 = R.resolve(source_title="SONY α7R V ILCE-7RM5 ボディ", link_type="item")
    assert r2.matched_product_id == "prod_a7rv"


# ── アクセサリー拒否（Task9）──
def test_accessory_rejection():
    R = _resolver()
    r = R.resolve(source_title="iPhone 17 Pro ケース 手帳型 レザー", link_type="item")
    assert r.accessory_flag is True
    assert r.identity_confidence == "low"
    # main 昇格ゲートでも拒否
    obs = {"price": 6800, "is_fresh": True, "is_exact_product_match": True,
           "product_match_confidence": "high", "link_type": "item", "is_body_only": True,
           "accessory_flag": True, "product_name": "iPhone 17 Pro ケース", "rejection_reason": None}
    assert is_main_promotable(obs) is False


# ── 下取拒否（Task11）: sanity で非本体文脈を弾く ──
def test_tradein_rejection():
    assert sanity_check_price(180000, 200000, "下取価格 トレードイン") is not None
    assert sanity_check_price(8000, 200000, "月々のお支払い 分割") is not None


# ── 検索結果は low confidence（Task12）──
def test_search_result_low_confidence():
    R = _resolver()
    r = R.resolve(source_title="iPhone 17 Pro 256GB", link_type="search",
                  expected_product_id="prod_iphone17pro_256")
    assert r.identity_confidence in ("low", "medium")
    assert r.identity_confidence != "high"
    # search は main 昇格しない
    obs = {"price": 194800, "is_fresh": True, "is_exact_product_match": False,
           "product_match_confidence": "medium", "link_type": "search", "is_body_only": True,
           "product_name": "iPhone 17 Pro 256GB", "rejection_reason": None}
    assert is_main_promotable(obs) is False


# ── stale は main 拒否（Task13）──
def test_stale_main_rejection():
    obs = {"price": 194800, "is_fresh": False, "is_exact_product_match": True,
           "product_match_confidence": "high", "link_type": "item", "is_body_only": True,
           "product_name": "iPhone 17 Pro 256GB", "rejection_reason": "stale_over_14d"}
    assert is_main_promotable(obs) is False


# ── main 昇格は高信頼+fresh+exact のみ（Task13）──
def test_main_promotion_requires_all():
    good = {"price": 194800, "is_fresh": True, "is_exact_product_match": True,
            "product_match_confidence": "high", "link_type": "item", "is_body_only": True,
            "product_name": "iPhone 17 Pro 256GB", "rejection_reason": None}
    assert is_main_promotable(good) is True


# ── duplicate risk（Task14/15）──
def test_duplicate_high_risk_different_capacity():
    obs = [
        {"source_name": "X", "price_role": "sell", "price_type": "buyback_price",
         "price": 193500, "product_id": "a", "product_name": "iPhone 17 Pro Max 256GB", "condition": "new"},
        {"source_name": "X", "price_role": "sell", "price_type": "buyback_price",
         "price": 193500, "product_id": "b", "product_name": "iPhone 17 Pro Max 512GB", "condition": "new"},
    ]
    d = detect_duplicate_price_pattern(obs)
    assert len(d) == 1
    assert d[0]["risk_level"] == "high"          # 異容量同額 = high


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
            print(f"  PASS {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL {fn.__name__}: {e}")
            raise
    print(f"\n{passed}/{len(fns)} passed")
    return passed == len(fns)


if __name__ == "__main__":
    raise SystemExit(0 if _run_all() else 1)
