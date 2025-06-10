import pandas as pd

# 读取原始数据
input_file = 'btc_trading.csv'
output_file = 'btc_trading_with_backtest.csv'
df = pd.read_csv(input_file)

# 新增明细列
extra_cols = [
    '当前仓位类型',
    '持有BTC数量',
    '当前总资产USD',
    '当前持有信号',
    '备注'
]
for col in extra_cols:
    df[col] = ''

# 策略参数
initial_usd = 1000
current_usd = initial_usd
current_btc = 0
current_position = '空仓'  # 空仓/现货/一倍合约/两倍合约
active_signals = set()
last_price = None

# 信号顺序
signal_order = ['tempeture_index', '120_ma', 'ADX']

def normalize_signal(sig: str) -> str:
    """将各种形式的信号字段统一映射为核心关键词"""
    sig = str(sig)
    if 'tempeture_index' in sig:
        return 'tempeture_index'
    if '120_ma' in sig:
        return '120_ma'
    if 'ADX' in sig:
        return 'ADX'
    return sig.strip()

# 记录每一行的明细
for idx, row in df.iterrows():
    date = row['日期/时间']
    price = float(str(row['价格 USD']).replace(',', ''))
    type_ = row['类型']
    raw_signal = row['信号']
    signal = normalize_signal(raw_signal)
    remark = ''

    # === 先根据最新价结算当前持有的合约仓位盈亏 ===
    if current_position == '一倍合约' and last_price is not None:
        current_btc += (price - last_price) / last_price * current_btc  # 1x 合约 PnL
    elif current_position == '两倍合约' and last_price is not None:
        current_btc += 2 * (price - last_price) / last_price * current_btc  # 2x 合约 PnL
    # 现货和空仓不需要动态结算 BTC 数量

    # 更新 last_price (用于下一行结算)。对现货也记录价格，方便之后从现货切换到合约时计算收益
    if current_position != '空仓':
        last_price = price

    # === 处理信号变化 ===
    if type_ == '进场':
        active_signals.add(signal)
    elif type_ == '出场':
        active_signals.discard(signal)

    n_signal = len(active_signals)

    # === 根据信号数量决定目标仓位 ===
    target_position = (
        '空仓' if n_signal == 0 else
        '现货' if n_signal == 1 else
        '一倍合约' if n_signal == 2 else
        '两倍合约'
    )

    # === 如果需要切换仓位 ===
    if target_position != current_position:
        # 先把现有仓位全部转换成 USD
        if current_position == '现货':
            current_usd = current_btc * price
            current_btc = 0
        elif current_position in ['一倍合约', '两倍合约']:
            # 合约已在上方结算 PnL，直接按现价换算 USD
            current_usd = current_btc * price
            current_btc = 0
        # 空仓则本身就是 USD

        # 再根据目标仓位重新建仓
        if target_position == '现货':
            current_btc = current_usd / price
            current_usd = 0
            remark = f'切换为现货({n_signal} signal)'
        elif target_position == '一倍合约':
            current_btc = current_usd / price
            current_usd = 0
            remark = '切换为一倍合约'
        elif target_position == '两倍合约':
            current_btc = current_usd / price
            current_usd = 0
            remark = '切换为两倍合约'
        elif target_position == '空仓':
            remark = '全部平仓为空仓'

        current_position = target_position
        last_price = price if current_position in ['一倍合约', '两倍合约'] else None

    # === 记录明细 ===
    df.at[idx, '当前仓位类型'] = current_position
    df.at[idx, '持有BTC数量'] = current_btc
    df.at[idx, '当前总资产USD'] = current_usd if current_usd > 0 else current_btc * price
    df.at[idx, '当前持有信号'] = ','.join(sorted(active_signals))
    df.at[idx, '备注'] = remark

# 保存新csv
cols = list(df.columns)
df.to_csv(output_file, index=False, encoding='utf-8-sig')
print(f'回测明细已保存到 {output_file}') 