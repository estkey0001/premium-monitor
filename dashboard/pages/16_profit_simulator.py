"""Phase 10: 利益シミュレーター"""

import streamlit as st
from pathlib import Path
from dashboard.components.db_helper import check_db, get_db_path, query_df, fmt_price

st.set_page_config(page_title="利益シミュレーター", page_icon="🧮", layout="wide")
check_db()
st.title("🧮 利益シミュレーター")

def _get_repo():
    import sys
    project_root = Path(__file__).resolve().parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from src.db.database import Database
    from src.db.repository import Repository
    db = Database.__new__(Database)
    db.db_path = get_db_path()
    db._connection = None
    db.init_schema()
    return Repository(db), db

try:
    repo, db = _get_repo()
except Exception as e:
    st.error(f"初期化エラー: {e}")
    st.stop()

# 商品リスト取得
products = repo.list_products()
product_options = {f"{p.name} (¥{p.retail_price:,})" if p.retail_price else p.name: p.id for p in products}

if not product_options:
    st.info("商品がありません。seedを実行してください。")
    st.stop()

# ===== 入力 =====
col1, col2 = st.columns(2)

with col1:
    st.subheader("商品選択")
    selected_name = st.selectbox("商品", list(product_options.keys()))
    selected_pid = product_options[selected_name]
    selected_product = repo.get_product(selected_pid)

    if selected_product:
        st.markdown(f"**ブランド:** {selected_product.brand}")
        st.markdown(f"**定価:** ¥{selected_product.retail_price:,}" if selected_product.retail_price else "定価: 未設定")

with col2:
    st.subheader("コスト設定")
    shipping = st.number_input("送料 (¥)", value=1000, min_value=0, step=100)
    transfer_fee = st.number_input("振込手数料 (¥)", value=300, min_value=0, step=100)
    transport = st.number_input("移動コスト (¥)", value=500, min_value=0, step=100)
    cc_fee_rate = st.number_input("クレカ手数料率 (%)", value=0.0, min_value=0.0, max_value=5.0, step=0.1) / 100
    other_costs = st.number_input("その他コスト (¥)", value=0, min_value=0, step=100)

st.markdown("---")

# ===== シミュレーション実行 =====
if st.button("シミュレーション実行", type="primary"):
    from src.market.profit_simulator import ProfitSimulator
    sim = ProfitSimulator(repository=repo)
    result = sim.simulate(
        product_id=selected_pid,
        shipping=shipping, transfer_fee=transfer_fee,
        transport=transport, cc_fee_rate=cc_fee_rate,
        other_costs=other_costs,
    )

    if not result:
        st.error("商品が見つかりません。")
    elif "error" in result:
        st.warning(result["error"])
        st.info("買取データをインポートしてください: `python -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv`")
    else:
        # サマリ
        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("公式価格", f"¥{result['official_price']:,}")
        col_b.metric("合計コスト", f"¥{result['cost_breakdown']['total']:,}")
        col_c.metric("最大実質利益", f"+¥{result['best_net_profit']:,}" if result['best_net_profit'] > 0 else "---")
        col_d.metric("最大利益率", f"{result['best_rate']:.1%}" if result['best_rate'] > 0 else "---")

        st.markdown("---")

        # 買取店別テーブル
        st.subheader("買取店別シミュレーション")
        if result["shops"]:
            import pandas as pd
            rows = []
            for s in result["shops"]:
                rows.append({
                    "買取店": s["shop_name"],
                    "買取価格": f"¥{s['buyback_price']:,}",
                    "条件": s["condition"],
                    "粗利": f"+¥{s['gross_profit']:,}" if s["gross_profit"] > 0 else f"¥{s['gross_profit']:,}",
                    "コスト": f"-¥{result['cost_breakdown']['total']:,}",
                    "実質利益": f"+¥{s['net_profit']:,}" if s["net_profit"] > 0 else f"¥{s['net_profit']:,}",
                    "利益率": f"{s['net_profit_rate']:.1%}",
                    "判定": "✅ 利益あり" if s["profitable"] else "❌ 赤字",
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

        # コスト内訳
        with st.expander("コスト内訳"):
            cb = result["cost_breakdown"]
            st.markdown(f"- 送料: ¥{cb['shipping']:,}")
            st.markdown(f"- 振込手数料: ¥{cb['transfer_fee']:,}")
            st.markdown(f"- 移動コスト: ¥{cb['transport']:,}")
            st.markdown(f"- クレカ手数料: ¥{cb['cc_fee']:,}")
            st.markdown(f"- その他: ¥{cb['other']:,}")
            st.markdown(f"- **合計: ¥{cb['total']:,}**")

        # beginner判定
        if result["best_net_profit"] >= 5000:
            st.success("🟢 この案件は beginner_easy の条件を満たす可能性があります（実質利益 ≥ ¥5,000）")
        elif result["best_net_profit"] >= 3000:
            st.info("🟡 beginner_watch: 利益はあるが条件確認が必要です")
        elif result["best_net_profit"] > 0:
            st.warning("利益は出ますが、コスト変動で赤字になるリスクがあります")
        else:
            st.error("❌ 現在の条件では赤字です")

try:
    db.close()
except Exception:
    pass
