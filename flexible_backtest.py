"""
flexible_backtest.py
-------------------
可复用的 BTC 回测脚本，支持**任意**信号组合 → 仓位/杠杆映射。

用法（命令行示例::Windows PowerShell）：
    python flexible_backtest.py --input btc_trading.csv --output result.csv

参数说明：
    --input   输入 csv (默认 btc_trading.csv)
    --output  输出 csv (默认 flexible_result.csv)
    --initial 初始资金 USD (默认 1000)

如需自定义策略，请修改 `DEFAULT_POLICY` 或在代码外部构造同结构的字典后
调用 `run_backtest(config, input_path, output_path)`。

策略配置 `policy` 的格式::
    {
        frozenset():                {"position": "空仓"},
        frozenset({"tempeture_index"}): {"position": "现货"},
        frozenset({"tempeture_index", "120_ma"}): {"position": "一倍合约"},
        ...
    }
其中 `position` 只能取 "空仓" / "现货" / "一倍合约" / "两倍合约"。
若字典缺少某组合，回测时默认沿用上一次仓位；如无上一次，则空仓。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, FrozenSet, List

import pandas as pd

SIGNALS = {"tempeture_index", "120_ma", "ADX"}
POSITIONS = {"空仓", "现货", "一倍合约", "两倍合约"}

# ------------------------- 默认策略映射 -------------------------
DEFAULT_POLICY: Dict[FrozenSet[str], dict] = {
    frozenset(): {"position": "空仓"},
    frozenset({"tempeture_index"}): {"position": "现货"},
    frozenset({"120_ma"}): {"position": "现货"},
    frozenset({"ADX"}): {"position": "现货"},
    frozenset({"tempeture_index", "120_ma"}): {"position": "一倍合约"},
    frozenset({"tempeture_index", "ADX"}): {"position": "一倍合约"},
    frozenset({"120_ma", "ADX"}): {"position": "一倍合约"},
    frozenset({"tempeture_index", "120_ma", "ADX"}): {"position": "两倍合约"},
}

# ------------------------- 工具函数 -------------------------

def normalize_signal(sig: str) -> str:
    """将 csv 中各种描述归并到核心信号关键字。"""
    sig = str(sig)
    if "tempeture_index" in sig:
        return "tempeture_index"
    if "120_ma" in sig:
        return "120_ma"
    if "ADX" in sig:
        return "ADX"
    return sig.strip()

# ------------------------- 核心回测函数 -------------------------

def run_backtest(policy: Dict[FrozenSet[str], dict],
                 input_csv: str | Path = "btc_trading.csv",
                 output_csv: str | Path = "flexible_result.csv",
                 initial_usd: float = 1000.0) -> pd.DataFrame:
    """执行回测，返回带明细的 DataFrame，同时另存为 `output_csv`."""

    df = pd.read_csv(input_csv)

    # 追加输出列
    cols_to_add = ["当前仓位类型", "持有BTC数量", "当前总资产USD", "当前持有信号", "备注"]
    for col in cols_to_add:
        df[col] = ""

    # 状态变量
    usd: float = initial_usd
    btc: float = 0.0
    position: str = "空仓"
    active_signals: set[str] = set()
    last_price: float | None = None  # 合约持仓的上一价

    for idx, row in df.iterrows():
        price = float(str(row["价格 USD"]).replace(",", ""))
        action_type = row["类型"]  # 进场 or 出场
        sig_raw = row["信号"]
        sig = normalize_signal(sig_raw)
        remark: str = ""

        # -------- step1: 结算已有合约的浮盈浮亏 --------
        if position == "一倍合约" and last_price is not None:
            btc += (price - last_price) / last_price * btc
        elif position == "两倍合约" and last_price is not None:
            btc += 2 * (price - last_price) / last_price * btc

        # 更新 last_price（主要给下一行用）
        if position in {"一倍合约", "两倍合约"}:
            last_price = price
        else:
            last_price = None

        # -------- step2: 更新信号集合 --------
        if action_type == "进场":
            active_signals.add(sig)
        elif action_type == "出场":
            active_signals.discard(sig)

        signal_key = frozenset(active_signals)
        target_cfg = policy.get(signal_key, None)
        target_position: str = target_cfg["position"] if target_cfg else position  # 缺省沿用
        if target_position not in POSITIONS:
            raise ValueError(f"未知仓位类型: {target_position}")

        # -------- step3: 若需要换仓，先全部平为 USD，再开新仓 --------
        if target_position != position:
            # 平掉旧仓 → 变 USD
            if position == "现货":
                usd = btc * price
                btc = 0.0
            elif position in {"一倍合约", "两倍合约"}:
                usd = btc * price  # 步骤1 已结算 PnL
                btc = 0.0
            # 空仓则 usd 保持不变

            # 开新仓
            if target_position == "现货":
                btc = usd / price
                usd = 0.0
            elif target_position in {"一倍合约", "两倍合约"}:
                btc = usd / price
                usd = 0.0
                last_price = price  # 开仓价
            # 若目标为空仓就什么都不做
            remark = f"换仓→{target_position}"
            position = target_position

        # -------- step4: 写回明细 --------
        total_assets = usd if usd > 0 else btc * price
        df.at[idx, "当前仓位类型"] = position
        df.at[idx, "持有BTC数量"] = btc
        df.at[idx, "当前总资产USD"] = total_assets
        df.at[idx, "当前持有信号"] = ",".join(sorted(active_signals))
        df.at[idx, "备注"] = remark

    # 保存结果
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"回测完成，结果已保存到 {output_csv}")
    return df

# ------------------------- CLI -------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="灵活多信号组合 BTC 回测脚本")
    p.add_argument("--input", default="btc_trading.csv", help="输入 csv 文件路径")
    p.add_argument("--output", default="flexible_result.csv", help="输出 csv 文件路径")
    p.add_argument("--initial", type=float, default=1000.0, help="初始资金 (USD)")
    # 支持传入自定义 policy 的 json 字符串或文件路径
    p.add_argument("--policy", help="自定义策略映射 (json 字符串或文件路径)，不填则用默认")
    return p.parse_args()


def _load_policy(policy_arg: str | None) -> Dict[FrozenSet[str], dict]:
    if not policy_arg:
        return DEFAULT_POLICY
    # 判断是文件还是直接的 json 字符串
    policy_path = Path(policy_arg)
    if policy_path.exists():
        text = policy_path.read_text(encoding="utf-8")
    else:
        text = policy_arg
    raw = json.loads(text)
    policy: Dict[FrozenSet[str], dict] = {}
    for k, v in raw.items():
        if isinstance(k, str):
            k_set = frozenset(k.split("|")) if k else frozenset()
        else:
            k_set = frozenset(k)
        policy[k_set] = v
    return policy


def main():
    args = _parse_args()
    policy = _load_policy(args.policy)
    run_backtest(policy, args.input, args.output, args.initial)


if __name__ == "__main__":
    main() 