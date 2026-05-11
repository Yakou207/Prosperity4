# IMC Prosperity 4 — Yakou207

**Overall Rank: #526**

## Overview

IMC Prosperity 4 is a multi-round algorithmic trading competition. Each round introduces new market mechanics, products, and strategic challenges. This repository contains my final submissions, data analysis, and market data for all five rounds.

## Round-by-Round Strategy

| Round | Products | Core Strategy | Key Techniques |
|-------|----------|---------------|----------------|
| 1 | Ash-Coated Osmium, Intarian Pepper Root | Market making + trend following | Wall mid estimation, mean reversion detection, informed trader signal tracking |
| 2 | Ash-Coated Osmium, Intarian Pepper Root | Adaptive FV market making + MAF bidding | EMA fair value (α=0.05), inventory skew, linear trend following, MAF bid at 2,000 XIRECs |
| 3 | 12 products (VEV basket, HYDROGEL, VELVETFRUIT) | Delta-1 basket arbitrage + options market making | Black-Scholes pricing, volatility smile fitting, ETF delta-neutral hedging |
| 4 | 12 products, 67+ traders | Multi-layer counterparty alpha | Informed trader following, anti-informed reversal, microstructure OBI, B-S delta hedging with dynamic IV |
| 5 | 50 products across 10 categories | Pure trend following + adaptive risk | Directional EMA crossover on all products, aggressive→conservative profit switching at 160K, drawdown defense at 35K |

## Manual Challenge

Portfolio allocation optimization based on news-driven analysis of the Prosperity universe. Strategic weight adjustment across categories based on market conditions.

## Repository Structure

```
├── README.md                        # This file
├── .gitignore
├── datamodel.py                     # IMC API data model
├── backtester.py                    # Local backtesting engine
├── Writing algorithm in Python.md   # Official IMC guide
├── round1/
│   ├── 273860.py                    # Final submission
│   ├── DATA_ANALYSIS.md             # Market data analysis
│   └── data/                        # Price & trade CSVs
├── round2/
│   ├── 363464.py
│   ├── DATA_ANALYSIS.md
│   └── data/
├── round3/
│   ├── 485759.py
│   ├── DATA_ANALYSIS.md
│   └── data/
├── round4/
│   ├── 543294.py
│   ├── DATA_ANALYSIS.md
│   ├── trader analysis files
│   └── data/
└── round5/
    ├── 582351.py
    ├── DATA_ANALYSIS.md
    ├── Manual Challenge/
    └── data/
```
