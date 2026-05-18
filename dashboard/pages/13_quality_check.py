"""Phase 8: 品質チェックダッシュボード"""

import streamlit as st
from dashboard.components.db_helper import check_db, get_db_path

st.set_page_config(page_title="品質チェック", page_icon="🔍", layout="wide")
check_db()
st.title("🔍 品質チェック")


def _get_checker():
    """QualityCheckerインスタンスを取得する。"""
    import sys
    from pathlib import Path
    # premium-monitor/src をパスに追加
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from src.db.database import Database
    from src.db.repository import Repository
    from src.pipeline.quality_checker import QualityChecker

    db_path = get_db_path()
    db = Database.__new__(Database)
    db.db_path = Path(db_path)
    db._connection = None
    db.init_schema()
    return QualityChecker(repository=Repository(db)), db


try:
    checker, db = _get_checker()
except Exception as e:
    st.error(f"品質チェッカーの初期化に失敗: {e}")
    st.stop()

# ============================
# 全チェック実行
# ============================
try:
    summary = checker.run_all_checks()
except Exception as e:
    st.error(f"チェック実行エラー: {e}")
    st.stop()

# ============================
# サマリ表示
# ============================
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("合計チェック項目", summary["total"])
with col2:
    st.metric("❌ Errors", summary["errors"])
with col3:
    st.metric("⚠️ Warnings", summary["warnings"])
with col4:
    st.metric("✅ OK", summary["ok"])

st.markdown("---")

# ============================
# 1. データ整合性
# ============================
st.subheader("1. データ整合性チェック")

data_results = summary["data_results"]
d_errors = [r for r in data_results if r["level"] == "error"]
d_warnings = [r for r in data_results if r["level"] == "warning"]

if not d_errors and not d_warnings:
    st.success("データ整合性に問題なし")
else:
    if d_errors:
        st.error(f"❌ {len(d_errors)} 件のエラー")
        for r in d_errors:
            st.markdown(f"- **[{r['category']}]** {r['message']}")
    if d_warnings:
        st.warning(f"⚠️ {len(d_warnings)} 件の警告")
        for r in d_warnings:
            st.markdown(f"- **[{r['category']}]** {r['message']}")

st.markdown("---")

# ============================
# 2. 初心者向け品質チェック
# ============================
st.subheader("2. 初心者向け (beginner_easy) 品質チェック")

beginner_results = summary["beginner_results"]
b_ok = [r for r in beginner_results if r["level"] == "ok"]
b_issues = [r for r in beginner_results if r["level"] != "ok"]

if not beginner_results:
    st.info("beginner_easy の商品なし")
elif not b_issues:
    st.success(f"✅ 全 {len(b_ok)} 件の初心者向け商品が品質OK")
else:
    st.warning(f"⚠️ {len(b_issues)} 件に品質問題あり")
    for r in b_issues:
        icon = "🔻" if r.get("should_downgrade") else "⚠️"
        with st.expander(f"{icon} {r.get('product_name', '?')}"):
            for issue in r.get("issues", []):
                st.markdown(f"- {issue}")
            if r.get("should_downgrade"):
                st.error("→ **beginner_watch への降格推奨**")
                st.caption("CLI: `python -m src.cli recalc-market-scores --fix-downgrade`")

    if b_ok:
        st.success(f"✅ {len(b_ok)} 件は品質OK")

st.markdown("---")

# ============================
# 3. 上級者向け品質チェック
# ============================
st.subheader("3. 上級者向け (advanced) 品質チェック")

advanced_results = summary["advanced_results"]
a_ok = [r for r in advanced_results if r["level"] == "ok"]
a_issues = [r for r in advanced_results if r["level"] != "ok"]

if not advanced_results:
    st.info("advanced_high_profit / expert_only の商品なし")
elif not a_issues:
    st.success(f"✅ 全 {len(a_ok)} 件の上級者向け商品が品質OK")
else:
    st.warning(f"⚠️ {len(a_issues)} 件に品質問題あり")
    for r in a_issues:
        with st.expander(f"⚠️ {r.get('product_name', '?')}"):
            for issue in r.get("issues", []):
                st.markdown(f"- {issue}")

    if a_ok:
        st.success(f"✅ {len(a_ok)} 件は品質OK")

st.markdown("---")

# ============================
# 4. 投稿テンプレート安全チェック
# ============================
st.subheader("4. 投稿テンプレート安全チェック")

publish_results = summary["publish_results"]
p_errors = [r for r in publish_results if r["level"] == "error"]
p_oks = [r for r in publish_results if r["level"] == "ok"]

if p_errors:
    st.error(f"❌ 禁止表現検出: {len(p_errors)} 件")
    for r in p_errors:
        with st.expander(f"❌ [{r['channel']}] {r['forbidden_phrase']}"):
            st.markdown(f"- **item_id**: `{r['item_id']}`")
            st.markdown(f"- **channel**: {r['channel']}")
            st.markdown(f"- **禁止表現**: `{r['forbidden_phrase']}`")
            st.markdown(f"- **抜粋**: ...{r['excerpt']}...")
else:
    for r in p_oks:
        st.success(f"✅ {r['message']}")

st.markdown("---")

# ============================
# 5. 修正推奨まとめ
# ============================
st.subheader("5. 修正推奨項目")

all_issues = [r for r in summary["results"] if r["level"] in ("error", "warning")]
if not all_issues:
    st.success("修正推奨項目なし。データ品質は良好です。")
else:
    st.markdown(f"**合計 {len(all_issues)} 件の修正推奨項目**")
    st.markdown("**推奨アクション:**")

    # カテゴリ別にグルーピング
    cats = {}
    for r in all_issues:
        cat = r["category"]
        cats.setdefault(cat, []).append(r)

    for cat, items in sorted(cats.items()):
        level_icon = "❌" if any(i["level"] == "error" for i in items) else "⚠️"
        st.markdown(f"- {level_icon} **{cat}**: {len(items)} 件")

    st.markdown("")
    st.markdown("**CLI コマンド:**")
    st.code(
        "# データ整合性チェック\n"
        "python -m src.cli validate-data\n\n"
        "# スコア再計算\n"
        "python -m src.cli recalc-market-scores\n\n"
        "# beginner降格付き再計算\n"
        "python -m src.cli recalc-market-scores --fix-downgrade\n\n"
        "# 投稿テンプレートチェック\n"
        "python -m src.cli validate-publish-text",
        language="bash",
    )

# クリーンアップ
try:
    db.close()
except Exception:
    pass
