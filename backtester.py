"""
Prosperity 回测框架
用于在本地测试交易算法
"""

import json
import csv
from datetime import datetime
from datamodel import (
    OrderDepth, TradingState, Trade, Order, Listing,
    Observation, ConversionObservation
)
from typing import Dict, List, Tuple
import pandas as pd


class BacktestEngine:
    """
    简单的回测引擎，用于测试交易算法
    """
    
    def __init__(self, trader_class, initial_balance: float = 1000000):
        """
        初始化回测引擎
        
        Args:
            trader_class: Trader类
            initial_balance: 初始资金（XIRECS）
        """
        self.trader = trader_class()
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.positions: Dict[str, int] = {}  # 产品 -> 仓位
        self.trade_history: List[Dict] = []  # 交易历史记录
        self.pnl_history: List[Dict] = []  # PnL历史
        
    def load_market_data_from_csv(self, filepath: str) -> List[Dict]:
        """
        从CSV文件加载市场数据
        预期格式: timestamp, product, bid_price, bid_volume, ask_price, ask_volume
        
        Args:
            filepath: CSV文件路径
            
        Returns:
            市场快照列表
        """
        snapshots = []
        try:
            df = pd.read_csv(filepath)
            # 按时间戳分组
            for timestamp, group in df.groupby('timestamp'):
                snapshot = {
                    'timestamp': timestamp,
                    'order_depths': {}
                }
                for _, row in group.iterrows():
                    product = row['product']
                    if product not in snapshot['order_depths']:
                        snapshot['order_depths'][product] = {
                            'buy_orders': {},
                            'sell_orders': {}
                        }
                    
                    # 添加买单
                    if pd.notna(row.get('bid_price', None)):
                        bid_price = int(row['bid_price'])
                        bid_volume = int(row['bid_volume'])
                        snapshot['order_depths'][product]['buy_orders'][bid_price] = bid_volume
                    
                    # 添加卖单
                    if pd.notna(row.get('ask_price', None)):
                        ask_price = int(row['ask_price'])
                        ask_volume = int(row['ask_volume'])
                        snapshot['order_depths'][product]['sell_orders'][ask_price] = -ask_volume
                
                snapshots.append(snapshot)
        except FileNotFoundError:
            print(f"文件未找到: {filepath}")
        except Exception as e:
            print(f"加载CSV失败: {e}")
        
        return snapshots
    
    def create_trading_state(
        self,
        timestamp: int,
        order_depths: Dict[str, OrderDepth],
        own_trades: Dict[str, List[Trade]] = None,
        market_trades: Dict[str, List[Trade]] = None,
        trader_data: str = ""
    ) -> TradingState:
        """
        创建TradingState对象
        
        Args:
            timestamp: 时间戳
            order_depths: 订单簿深度
            own_trades: 自己的交易
            market_trades: 市场交易
            trader_data: 交易者数据
            
        Returns:
            TradingState对象
        """
        if own_trades is None:
            own_trades = {}
        if market_trades is None:
            market_trades = {}
        
        # 创建产品列表
        listings = {}
        for product in order_depths.keys():
            listings[product] = Listing(
                symbol=product,
                product=product,
                denomination="XIRECS"
            )
        
        # 创建observations (可选)
        observations = Observation(
            plainValueObservations={},
            conversionObservations={}
        )
        
        return TradingState(
            traderData=trader_data,
            timestamp=timestamp,
            listings=listings,
            order_depths=order_depths,
            own_trades=own_trades,
            market_trades=market_trades,
            position=self.positions.copy(),
            observations=observations
        )
    
    def convert_to_order_depth(self, buy_orders: Dict[int, int], sell_orders: Dict[int, int]) -> OrderDepth:
        """
        将字典转换为OrderDepth对象
        
        Args:
            buy_orders: 买单字典 {价格: 数量}
            sell_orders: 卖单字典 {价格: 数量}
            
        Returns:
            OrderDepth对象
        """
        od = OrderDepth()
        od.buy_orders = buy_orders
        od.sell_orders = sell_orders
        return od
    
    def run_backtest(self, market_snapshots: List[Dict]) -> Dict:
        """
        运行回测
        
        Args:
            market_snapshots: 市场快照列表
            
        Returns:
            回测结果字典
        """
        print(f"\n{'='*60}")
        print(f"开始回测 | 初始资金: {self.initial_balance:,.0f} XIRECS")
        print(f"{'='*60}\n")
        
        for i, snapshot in enumerate(market_snapshots):
            timestamp = snapshot['timestamp']
            
            # 构建OrderDepth对象
            order_depths = {}
            for product, depths in snapshot['order_depths'].items():
                order_depths[product] = self.convert_to_order_depth(
                    depths['buy_orders'],
                    depths['sell_orders']
                )
                # 初始化仓位
                if product not in self.positions:
                    self.positions[product] = 0
            
            # 创建TradingState
            state = self.create_trading_state(
                timestamp=timestamp,
                order_depths=order_depths
            )
            
            # 调用交易算法
            try:
                result, conversions, trader_data = self.trader.run(state)
            except Exception as e:
                print(f"时间戳 {timestamp} 运行算法出错: {e}")
                continue
            
            # 处理订单
            for product, orders in result.items():
                for order in orders:
                    self._process_order(order, order_depths[product], timestamp)
            
            # 定期输出进度
            if (i + 1) % max(1, len(market_snapshots) // 10) == 0:
                print(f"进度: {i+1}/{len(market_snapshots)} 步骤完成")
        
        # 生成回测报告
        report = self._generate_report()
        return report
    
    def _process_order(self, order: Order, order_depth: OrderDepth, timestamp: int):
        """
        处理单个订单
        
        Args:
            order: Order对象
            order_depth: 该产品的OrderDepth
            timestamp: 时间戳
        """
        product = order.symbol
        price = order.price
        quantity = order.quantity
        
        # 买单 (quantity > 0)
        if quantity > 0:
            # 尝试与卖单成交
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price <= price and quantity > 0:
                    ask_volume = -order_depth.sell_orders[ask_price]
                    trade_volume = min(quantity, ask_volume)
                    
                    # 记录交易
                    self._record_trade(
                        product, ask_price, trade_volume,
                        "BUY", timestamp
                    )
                    
                    quantity -= trade_volume
                    self.positions[product] = self.positions.get(product, 0) + trade_volume
        
        # 卖单 (quantity < 0)
        elif quantity < 0:
            # 尝试与买单成交
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price >= price and quantity < 0:
                    bid_volume = order_depth.buy_orders[bid_price]
                    trade_volume = min(-quantity, bid_volume)
                    
                    # 记录交易
                    self._record_trade(
                        product, bid_price, trade_volume,
                        "SELL", timestamp
                    )
                    
                    quantity += trade_volume
                    self.positions[product] = self.positions.get(product, 0) - trade_volume
    
    def _record_trade(self, product: str, price: float, quantity: int, side: str, timestamp: int):
        """
        记录交易
        
        Args:
            product: 产品名称
            price: 成交价格
            quantity: 成交数量
            side: 买卖方向 ('BUY'/'SELL')
            timestamp: 时间戳
        """
        trade_value = price * quantity
        self.trade_history.append({
            'timestamp': timestamp,
            'product': product,
            'side': side,
            'price': price,
            'quantity': quantity,
            'value': trade_value
        })
        
        # 更新余额
        if side == "BUY":
            self.current_balance -= trade_value
        else:
            self.current_balance += trade_value
    
    def _generate_report(self) -> Dict:
        """
        生成回测报告
        
        Returns:
            报告字典
        """
        total_trades = len(self.trade_history)
        total_buy_volume = sum(t['quantity'] for t in self.trade_history if t['side'] == 'BUY')
        total_sell_volume = sum(t['quantity'] for t in self.trade_history if t['side'] == 'SELL')
        
        # 计算盈亏
        realized_pnl = sum(t['value'] for t in self.trade_history if t['side'] == 'SELL') - \
                       sum(t['value'] for t in self.trade_history if t['side'] == 'BUY')
        
        report = {
            'total_trades': total_trades,
            'total_buy_volume': total_buy_volume,
            'total_sell_volume': total_sell_volume,
            'final_positions': self.positions,
            'final_balance': self.current_balance,
            'realized_pnl': realized_pnl,
            'roi': (realized_pnl / self.initial_balance) * 100 if self.initial_balance > 0 else 0,
        }
        
        print(f"\n{'='*60}")
        print(f"回测完成 | 最终报告")
        print(f"{'='*60}")
        print(f"总交易数: {report['total_trades']}")
        print(f"总买入量: {report['total_buy_volume']:,}")
        print(f"总卖出量: {report['total_sell_volume']:,}")
        print(f"\n最终仓位: {report['final_positions']}")
        print(f"最终余额: {report['final_balance']:,.2f} XIRECS")
        print(f"已实现盈亏: {report['realized_pnl']:,.2f} XIRECS")
        print(f"收益率: {report['roi']:.2f}%")
        print(f"{'='*60}\n")
        
        return report


def run_simple_backtest():
    """
    运行简单的回测示例（无CSV数据）
    """
    # 延迟导入，避免循环依赖
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    
    from Prosperity.Round1code import Trader
    
    # 创建回测引擎
    engine = BacktestEngine(Trader)
    
    # 创建示例市场快照（模拟5个时间步骤）
    market_snapshots = [
        {
            'timestamp': 1000,
            'order_depths': {
                'ASH_COATED_OSMIUM': {
                    'buy_orders': {9999: 5, 9998: 10},
                    'sell_orders': {10001: -5, 10002: -10}
                },
                'INTARIAN_PEPPER_ROOT': {
                    'buy_orders': {100: 20, 99: 15},
                    'sell_orders': {102: -20, 103: -15}
                }
            }
        },
        {
            'timestamp': 1100,
            'order_depths': {
                'ASH_COATED_OSMIUM': {
                    'buy_orders': {10000: 8, 9999: 12},
                    'sell_orders': {10002: -8, 10003: -12}
                },
                'INTARIAN_PEPPER_ROOT': {
                    'buy_orders': {101: 18, 100: 22},
                    'sell_orders': {103: -18, 104: -22}
                }
            }
        },
        {
            'timestamp': 1200,
            'order_depths': {
                'ASH_COATED_OSMIUM': {
                    'buy_orders': {10001: 10, 10000: 15},
                    'sell_orders': {10003: -10, 10004: -15}
                },
                'INTARIAN_PEPPER_ROOT': {
                    'buy_orders': {102: 16, 101: 20},
                    'sell_orders': {104: -16, 105: -20}
                }
            }
        },
    ]
    
    # 运行回测
    report = engine.run_backtest(market_snapshots)
    return report


if __name__ == "__main__":
    # 运行示例回测
    report = run_simple_backtest()
