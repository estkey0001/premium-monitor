"""Phase 14: 新商品・転売機会スキャン管理画面"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import streamlit as st

from dashboard.components.db_helper import check_db, get_db_path

st.set_page_config(page_title="新商品機会", page_icon="🆕", layout="wide")
check_db()
st.title("🆕 新商品・転売機会スキャン")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JST = timezone(timedelta(hours=9))


def _get_repo():
    """DB と Repository を生成して返す。"""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from src.db.database import Database
    from src.db.repository import Repository
    db = Database.__new__(Database)
    db.db_path = get_db_path()
    db._connection = None
    db.init_schema()
    return Repository(db), db


# ===== スキャンボタン =====
st.subheader("🔍 スキャン実行")
col_btn, col_info = st.columns([2, 3])
with col_btn:
    if st.button("▶ 今すぐスキャン（新商品候補検出）", type="primary", use_container_width=True):
        try:
            repo, db = _get_repo()
            from src.market.new_product_scanner import NewProductScanner
            scanner = NewProductScanner(repository=repo)
            result = scanner.scan()
            db.close()
            st.success(f"✅ スキャン完了: 新規={result['new']}件 スキップ={result['skipped']}件")
            if result["errors"]:
                for e in result["errors"][:3]:
                    st.warning(f"⚠️ {e}")
            st.rerun()
        except Exception as e:
            st.error(f"スキャンエラー: {e}")
with col_info:
    st.caption("スキャンは config/new_product_watchlist.yaml の候補リストを使用します。")
    st.caption("自動購入・自動応募は一切行いません。監視・記録のみです。")

st.markdown("---")

# ===== 候補一覧 =====
st.subheader("📋 新商品候補一覧")

# フィルタ
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    filter_status = st.selectbox("ステータス", ["全て", "pending", "watching", "approved", "rejected"])
with col_f2:
    filter_category = st.selectbox(
        "カテゴリ", ["全て", "iphone", "camera", "game_console", "mac", "ipad", "apple_watch"]
    )
with col_f3:
    sort_by = st.selectbox("ソート", ["転売期待スコア↓", "信頼度↓", "難易度↓", "登録日↓"])

try:
    repo, db = _get_repo()
    status_param = None if filter_status == "全て" else filter_status
    candidates = repo.list_product_candidates(status=status_param, limit=100)
    db.close()

    # カテゴリフィルタ
    if filter_category != "全て":
        candidates = [c for c in candidates if getattr(c, "category", c.genre) == filter_category]

    # ソート
    if sort_by == "転売期待スコア↓":
        candidates.sort(key=lambda c: getattr(c, "resale_potential_score", 0), reverse=True)
    elif sort_by == "信頼度↓":
        candidates.sort(key=lambda c: c.confidence, reverse=True)
    elif sort_by == "難易度↓":
        candidates.sort(key=lambda c: c.difficulty_score, reverse=True)
    else:
        candidates.sort(key=lambda c: c.detected_at, reverse=True)

    st.caption(f"候補数: {len(candidates)}件")

    if not candidates:
        st.info("該当する候補がありません。「今すぐスキャン」を実行してください。")
    else:
        for c in candidates:
            status_icon = {
                "pending": "⏳", "watching": "👁️", "approved": "✅", "rejected": "❌"
            }.get(c.status, "❓")
            level_label = {
                "beginner_easy": "🟢 初級者",
                "beginner_watch": "🟡 初級者(要確認)",
                "advanced_high_profit": "🔵 上級者",
                "expert_only": "🔴 上級者専用",
            }.get(c.user_level, c.user_level or "未分類")

            resale_score = getattr(c, "resale_potential_score", 0)
            with st.expander(
                f"{status_icon} {c.product_name} — {level_label} | 転売期待: {resale_score:.0%}"
            ):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("初心者向けスコア", f"{c.beginner_score:.0%}")
                with col2:
                    st.metric("転売期待スコア", f"{resale_score:.0%}")
                with col3:
                    st.metric("入手難易度", f"{c.difficulty_score:.0%}")

                col_i1, col_i2 = st.columns(2)
                with col_i1:
                    st.markdown(f"**カテゴリ:** `{getattr(c, 'category', c.genre)}`")
                    st.markdown(f"**ブランド:** {c.brand}")
                    official_price = getattr(c, "official_price", None) or c.estimated_price
                    if official_price:
                        st.markdown(f"**想定価格:** ¥{official_price:,}")
                    st.markdown(f"**販売方法:** {getattr(c, 'sale_method', '-')}")
                with col_i2:
                    if getattr(c, "release_date", ""):
                        st.markdown(f"**発売予定:** {c.release_date}")
                    st.markdown(f"**検出ソース:** {getattr(c, 'detected_source', '-')}")
                    if c.detected_url:
                        st.markdown(f"**参考URL:** [{c.detected_url[:40]}...]({c.detected_url})")

                if c.reason_for_beginner:
                    st.caption(f"📌 判定理由: {c.reason_for_beginner}")
                if c.caution_note:
                    st.caption(f"⚠️ 注意: {c.caution_note}")

                # アクションボタン
                if c.status not in ("approved", "rejected"):
                    btn_col1, btn_col2, btn_col3 = st.columns(3)
                    with btn_col1:
                        if st.button("✅ Approve", key=f"approve_{c.id}", use_container_width=True):
                            try:
                                repo2, db2 = _get_repo()
                                repo2.update_product_candidate_status(c.id, "approved")
                                db2.close()
                                st.success(f"✅ {c.product_name} を approved に変更しました")
                                st.rerun()
                            except Exception as e:
                                st.error(f"エラー: {e}")
                    with btn_col2:
                        if st.button("👁️ Watch", key=f"watch_{c.id}", use_container_width=True):
                            try:
                                repo2, db2 = _get_repo()
                                repo2.update_product_candidate_status(c.id, "watching")
                                db2.close()
                                st.success(f"👁️ {c.product_name} を watching に変更しました")
                                st.rerun()
                            except Exception as e:
                                st.error(f"エラー: {e}")
                    with btn_col3:
                        if st.button("❌ Reject", key=f"reject_{c.id}", use_container_width=True):
                            try:
                                repo2, db2 = _get_repo()
                                repo2.update_product_candidate_status(c.id, "rejected")
                                db2.close()
                                st.info(f"❌ {c.product_name} を rejected に変更しました")
                                st.rerun()
                            except Exception as e:
                                st.error(f"エラー: {e}")
                elif c.status == "approved":
                    st.success("✅ 承認済み — productsへの追加は手動で行ってください")

except Exception as e:
    st.error(f"候補一覧取得エラー: {e}")
    import traceback
    st.code(traceback.format_exc())
