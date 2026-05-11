# Trader 信号复核报告（重点：anti-informed 是否真实）

## 方法
- 使用 3 天 trade + price 数据，对每笔成交构建 edge：`sign(side) * future_mid_change`。
- 多 horizon 稳健性：100/300/500/1000。
- 显著性检验：对单交易员 edge 做 sign-flip permutation p-value。
- 日内一致性：按 day 检查 edge 符号是否稳定。

## 主要结论
- **存在稳健 informed 候选**：
  - Mark 67: mean_edge_avg=2.0333, sig_pos_horizons=4/4
  - Mark 01: mean_edge_avg=0.0414, sig_pos_horizons=2/4
- **anti-informed 方面存在统计上可复现的负向候选**：
  - Mark 49: mean_edge_avg=-1.8996, sig_neg_horizons=4/4
  - Mark 22: mean_edge_avg=-0.1255, sig_neg_horizons=4/4

## 针对 Mark 49 的专项结论
- 多 horizon 显著负向次数: 4/4
  - h=100: mean_edge=-1.8115, p=0.0003, n=122
  - h=300: mean_edge=-1.8484, p=0.0003, n=122
  - h=500: mean_edge=-1.8197, p=0.0003, n=122
  - h=1000: mean_edge=-2.1189, p=0.0003, n=122
- 日级负向主导（neg_ratio>=2/3）的 horizon 数: 4/4
  - h=100: neg_days=3/3, mean_day_edge=-1.8160
  - h=300: neg_days=3/3, mean_day_edge=-1.8466
  - h=500: neg_days=3/3, mean_day_edge=-1.8266
  - h=1000: neg_days=3/3, mean_day_edge=-2.1328
- 结论：Mark 49 更接近“有规律的反向流”而非纯噪音。
- 交易建议：可作为 anti-informed 信号，但仓位权重低于 informed（例如 30%~50%）。

## 输出文件
- trader_edge_horizon_summary.csv
- trader_edge_day_summary.csv
- trader_edge_robustness.csv
- trader_day_sign_consistency.csv
- trader_signal_recheck_report.md