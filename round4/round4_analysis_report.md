# ROUND4 数据分析结果

## 1) Round3 vs Round4 Algo 差异结论
详见 `round3_vs_round4_algo_diff.md`。核心是 Round4 开放 `buyer/seller`，可以做对手行为建模。

## 2) Price 数据分析（概览）
- 价格样本总行数: **360,000**
- 产品数: **12**

### 按 mean |Δmid| 排名前五产品
- HYDROGEL_PACK: mean|Δmid|=1.6660, spread_mean=15.7279
- VEV_4000: mean|Δmid|=0.9362, spread_mean=20.7535
- VEV_4500: mean|Δmid|=0.8834, spread_mean=15.7938
- VELVETFRUIT_EXTRACT: mean|Δmid|=0.8619, spread_mean=4.9824
- VEV_5000: mean|Δmid|=0.7505, spread_mean=5.9642

已输出：
- `price_summary_by_product.csv`
- `price_liquidity_depth_summary.csv`
- `core_products_midprice.png`
- `voucher_abs_move_mean.png`

## 3) Trade 数据分析：高频交易员
- 成交样本总行数: **4,281**
- 交易员数量（buyer/seller 合并去重）: **7**

### Top 10 HFT 候选（按 hft_score）
- Mark 14: trades=2172, active_ts=2000, trades/ts=1.086, products=7, score=0.857
- Mark 22: trades=1584, active_ts=454, trades/ts=3.489, products=12, score=0.857
- Mark 01: trades=1843, active_ts=795, trades/ts=2.318, products=7, score=0.836
- Mark 38: trades=1478, active_ts=1392, trades/ts=1.062, products=7, score=0.593
- Mark 55: trades=1198, active_ts=1155, trades/ts=1.037, products=1, score=0.357
- Mark 49: trades=122, active_ts=117, trades/ts=1.043, products=1, score=0.264
- Mark 67: trades=165, active_ts=165, trades/ts=1.000, products=1, score=0.236

已输出：
- `trader_activity_hft_rank.csv`
- `trader_informed_signal_rank.csv`

## 4) Trade 数据分析：是否存在 informed trader
- 存在可疑 informed trader 信号，以下为 `mean_edge` 最高的前 10 名：
  - Mark 67: n=165, mean_edge=1.945455, hit_rate=0.830, z=1.92
  - Mark 55: n=1198, mean_edge=0.073456, hit_rate=0.442, z=0.06
  - Mark 01: n=1843, mean_edge=0.024417, hit_rate=0.187, z=0.01
  - Mark 38: n=1478, mean_edge=0.006766, hit_rate=0.465, z=-0.01
  - Mark 14: n=2172, mean_edge=-0.030847, hit_rate=0.415, z=-0.04
  - Mark 22: n=1584, mean_edge=-0.110480, hit_rate=0.134, z=-0.12
  - Mark 49: n=122, mean_edge=-1.819672, hit_rate=0.139, z=-1.82

已输出：
- `trader_informed_signal_rank.csv`
- `informed_signal_by_symbol_trader.csv`

## 5) 方法说明（简要）
- HFT 识别：综合 `trades`、`trades_per_timestamp`、`products` 构造 `hft_score`。
- Informed 识别：以 `sign(signed_qty) * future_mid_change(h=500)` 定义单笔 edge，聚合到交易员。