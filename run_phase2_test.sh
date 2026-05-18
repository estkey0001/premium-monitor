#!/bin/bash
# ===========================================
# Phase 2.6 実サイト取得テストスクリプト
# ===========================================
set -e

cd "$(dirname "$0")"
echo "========================================"
echo " Phase 2.6 - 実サイト取得テスト"
echo " $(date)"
echo "========================================"
echo ""

# --- 依存ライブラリ ---
echo "[1/4] Installing dependencies..."
pip install -r requirements.txt -q 2>&1 | tail -3
pip install playwright -q 2>&1 | tail -1
playwright install chromium 2>&1 | tail -3
echo "  Done."
echo ""

# --- DB初期化 ---
echo "[2/4] Initializing database..."
python -m src.cli init-db
python -m src.cli seed
echo ""

# --- Collector テスト (6パターン) ---
echo "[3/4] Running collectors..."
echo ""

echo "--- [1/6] kakaku × gr3x ---"
python -m src.cli test-collector --source kakaku --product gr3x --skip-rate-limit 2>&1
echo ""

echo "--- [2/6] yodobashi × gr3x ---"
python -m src.cli test-collector --source yodobashi --product gr3x --skip-rate-limit 2>&1
echo ""

echo "--- [3/6] map_camera × gr3x ---"
python -m src.cli test-collector --source map_camera --product gr3x --skip-rate-limit 2>&1
echo ""

echo "--- [4/6] kakaku × x100vi ---"
python -m src.cli test-collector --source kakaku --product x100vi --skip-rate-limit 2>&1
echo ""

echo "--- [5/6] yodobashi × x100vi ---"
python -m src.cli test-collector --source yodobashi --product x100vi --skip-rate-limit 2>&1
echo ""

echo "--- [6/6] map_camera × x100vi ---"
python -m src.cli test-collector --source map_camera --product x100vi --skip-rate-limit 2>&1
echo ""

# --- 結果確認 ---
echo "[4/4] Results..."
echo ""
python -m src.cli latest-observations
python -m src.cli price-history --product gr3x
python -m src.cli price-history --product x100vi

echo "========================================"
echo " テスト完了: $(date)"
echo "========================================"
