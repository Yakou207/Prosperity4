# Trader_Analysis 说明

本目录是对 ROUND4 三个 trade CSV 的复核分析（重点验证 anti-informed 是否真实信号）。

## 核心结论文件
- [trader_signal_recheck_report.md](trader_signal_recheck_report.md)

## 关键数据表
- [trader_edge_horizon_summary.csv](trader_edge_horizon_summary.csv): 每个交易员在多 horizon 下的 edge、命中率、显著性
- [trader_edge_day_summary.csv](trader_edge_day_summary.csv): 每个交易员按 day 的 edge 明细
- [trader_edge_robustness.csv](trader_edge_robustness.csv): 稳健性总览（显著正/负 horizon 数）
- [trader_day_sign_consistency.csv](trader_day_sign_consistency.csv): 日级符号一致性（是否长期同向）

## 脚本
- [reanalyze_trader_signal.py](reanalyze_trader_signal.py)
