import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from itertools import combinations

from flexible_backtest import run_backtest, _load_policy, DEFAULT_POLICY

st.set_page_config(page_title="BTC 灵活回测", layout="wide")

st.title("📈 BTC 灵活回测工具")

# ------------------- 输入区域 -------------------

st.sidebar.header("参数设置")

# 上传或使用默认 CSV
default_csv = "btc_trading.csv"

data_file = st.sidebar.file_uploader("上传交易信号 CSV (留空使用默认)", type=["csv"])
if data_file is not None:
    # 保存到临时文件
    tmp_csv_path = Path(tempfile.mkstemp(suffix=".csv")[1])
    tmp_csv_path.write_bytes(data_file.getbuffer())
    input_path = tmp_csv_path
else:
    input_path = default_csv

initial_usd = st.sidebar.number_input("初始资金 (USD)", min_value=100.0, value=1000.0, step=100.0)

st.sidebar.subheader("信号组合 → 仓位设置")

# 枚举全部组合 (0~3 信号)
signal_list = ["tempeture_index", "120_ma", "ADX"]

all_combos = [frozenset()] + [
    frozenset([s]) for s in signal_list
] + [
    frozenset(c) for c in combinations(signal_list, 2)
] + [frozenset(signal_list)]

POSITION_CHOICES = ["空仓", "现货", "一倍合约", "两倍合约"]

policy: dict = {}

def combo_label(fs: frozenset[str]) -> str:
    return " & ".join(sorted(fs)) if fs else "无信号"

for i, fs in enumerate(all_combos):
    default_cfg = DEFAULT_POLICY.get(fs, {"position": "空仓", "ratio": 0.0})
    default_pos = default_cfg["position"]
    default_ratio = float(default_cfg.get("ratio", 1.0))

    c1, c2 = st.sidebar.columns([2, 1])
    with c1:
        sel = st.selectbox(
            combo_label(fs),
            POSITION_CHOICES,
            index=POSITION_CHOICES.index(default_pos),
            key=f"pos_{i}",
        )
    with c2:
        ratio_val = st.number_input(
            label="比例", min_value=0.0, max_value=1.0, step=0.1, value=default_ratio,
            key=f"ratio_{i}",
        )

    policy[fs] = {"position": sel, "ratio": ratio_val}

st.sidebar.markdown("---")
run_clicked = st.sidebar.button("▶ 运行回测")

# ------------------- 回测与输出 -------------------
if run_clicked:
    with st.spinner("正在回测，请稍候…"):
        result_df = run_backtest(policy, input_path, "__tmp_out.csv", initial_usd)

    # 处理日期与日度权益
    result_df["date"] = pd.to_datetime(result_df["日期/时间"])
    daily_equity = (
        result_df.groupby("date")["当前总资产USD"].last().astype(float)
    )
    # 去掉可能为 0 的首尾记录，避免除零导致 -100%
    daily_equity = daily_equity[daily_equity > 0]
    returns = daily_equity.pct_change().dropna()

    # 关键指标
    total_return = daily_equity.iloc[-1] / daily_equity.iloc[0] - 1
    days = (daily_equity.index[-1] - daily_equity.index[0]).days
    annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else np.nan

    rolling_max = daily_equity.cummax()
    drawdown = daily_equity / rolling_max - 1.0
    max_dd = drawdown.min()

    sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() != 0 else np.nan
    downside_std = returns[returns < 0].std()
    sortino = (returns.mean() / downside_std) * np.sqrt(252) if downside_std != 0 else np.nan

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("总收益", f"{total_return*100:,.2f}%")
    col2.metric("年化收益", f"{annual_return*100:,.2f}%")
    col3.metric("最大回撤", f"{max_dd*100:,.2f}%")
    col4.metric("夏普比率", f"{sharpe:.2f}")
    col5.metric("Sortino", f"{sortino:.2f}")

    st.subheader("资产曲线")
    st.line_chart(daily_equity)

    st.subheader("按日期明细 (前 500 行)")
    st.dataframe(result_df.head(500))

    st.success("回测完成！")
else:
    st.info("请在左侧面板设置参数并点击 '运行回测' 按钮") 