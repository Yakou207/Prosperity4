import json
import math
from typing import List, Dict, Any
from datamodel import OrderDepth, TradingState, Order

# ==========================================
# 1. 基础配置 (General Settings)
# ==========================================
STATIC_SYMBOL = 'ASH_COATED_OSMIUM'
DYNAMIC_SYMBOL = 'INTARIAN_PEPPER_ROOT'

POS_LIMITS = {
    STATIC_SYMBOL: 20,
    DYNAMIC_SYMBOL: 20
}

LONG, NEUTRAL, SHORT = 1, 0, -1

# ==========================================
# 2. 基础交易员基类 (Base Trader Class)
# ==========================================
class BaseTrader:
    def __init__(self, name, state, prints, new_trader_data, product_group=None):

        self.orders = []

        self.name = name
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data
        self.product_group = name if product_group is None else product_group

        self.last_traderData = self.get_last_traderData()

        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0)

        self.expected_position = self.initial_position


        self.mkt_buy_orders, self.mkt_sell_orders = self.get_order_depth()
        self.bid_wall, self.wall_mid, self.ask_wall = self.get_walls()
        self.best_bid, self.best_ask = self.get_best_bid_ask()

        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self.get_max_allowed_volume()
        self.total_mkt_buy_volume, self.total_mkt_sell_volume = self.get_total_market_buy_sell_volume()

    def get_last_traderData(self):
                        
        last_traderData = {}
        try:
            if self.state.traderData != '':
                last_traderData = json.loads(self.state.traderData)
        except: self.log("ERROR", 'td')

        return last_traderData


    def get_best_bid_ask(self):

        best_bid = best_ask = None

        try:
            if len(self.mkt_buy_orders) > 0:
                best_bid = max(self.mkt_buy_orders.keys())
            if len(self.mkt_sell_orders) > 0:
                best_ask = min(self.mkt_sell_orders.keys())
        except: pass

        return best_bid, best_ask


    def get_walls(self):

        bid_wall = wall_mid = ask_wall = None

        try: bid_wall = min([x for x,_ in self.mkt_buy_orders.items()])
        except: pass
        
        try: ask_wall = max([x for x,_ in self.mkt_sell_orders.items()])
        except: pass

        try: wall_mid = (bid_wall + ask_wall) / 2
        except: pass

        return bid_wall, wall_mid, ask_wall
    
    def get_total_market_buy_sell_volume(self):

        market_bid_volume = market_ask_volume = 0

        try:
            market_bid_volume = sum([v for p, v in self.mkt_buy_orders.items()])
            market_ask_volume = sum([v for p, v in self.mkt_sell_orders.items()])
        except: pass

        return market_bid_volume, market_ask_volume
    

    def get_max_allowed_volume(self):
        max_allowed_buy_volume = self.position_limit - self.initial_position
        max_allowed_sell_volume = self.position_limit + self.initial_position
        return max_allowed_buy_volume, max_allowed_sell_volume

    def get_order_depth(self):

        order_depth, buy_orders, sell_orders = {}, {}, {}

        try: order_depth: OrderDepth = self.state.order_depths[self.name]
        except: pass
        try: buy_orders = {bp: abs(bv) for bp, bv in sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)}
        except: pass
        try: sell_orders = {sp: abs(sv) for sp, sv in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])}
        except: pass

        return buy_orders, sell_orders
    

    def bid(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_buy_volume)
        order = Order(self.name, int(price), abs_volume)
        if logging: self.log("BUYO", {"p":price, "s":self.name, "v":int(volume)}, product_group='ORDERS')
        self.max_allowed_buy_volume -= abs_volume
        self.orders.append(order)

    def ask(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_sell_volume)
        order = Order(self.name, int(price), -abs_volume)
        if logging: self.log("SELLO", {"p":price, "s":self.name, "v":int(volume)}, product_group='ORDERS')
        self.max_allowed_sell_volume -= abs_volume
        self.orders.append(order)

    def log(self, kind, message, product_group=None):
        if product_group is None: product_group = self.product_group

        if product_group == 'ORDERS':
            group = self.prints.get(product_group, [])
            group.append({kind: message})
        else:
            group = self.prints.get(product_group, {})
            group[kind] = message

        self.prints[product_group] = group
        
    def get_orders(self):
        # overwrite this in each trader
        return {}

# ==========================================
# 3. 静态资产交易员 (Static Asset / Osmium)
# ==========================================
class StaticTrader(BaseTrader):
    # [修复2]：加入 name 参数，避免主循环调用时报 TypeError 导致崩溃中断
    def __init__(self, name, state, prints, new_trader_data):
        super().__init__(name, state, prints, new_trader_data)

    def get_orders(self):

        if self.wall_mid is not None:

            ##########################################################
            ####### 1. TAKING
            ##########################################################
            for sp, sv in self.mkt_sell_orders.items():
                if sp <= self.wall_mid - 1:
                    self.bid(sp, sv, logging=False)
                elif sp <= self.wall_mid and self.initial_position < 0:
                        volume = min(sv,  abs(self.initial_position))
                        self.bid(sp, volume, logging=False)

            for bp, bv in self.mkt_buy_orders.items():
                if bp >= self.wall_mid + 1:
                    self.ask(bp, bv, logging=False)
                elif bp >= self.wall_mid and self.initial_position > 0:
                        volume = min(bv,  self.initial_position)
                        self.ask(bp, volume, logging=False)

            ###########################################################
            ####### 2. MAKING
            ###########################################################
            bid_price = int(self.bid_wall + 1) # base case
            ask_price = int(self.ask_wall - 1) # base case

            # OVERBIDDING: overbid best bid that is still under the mid wall
            for bp, bv in self.mkt_buy_orders.items():
                overbidding_price = bp + 1
                if bv > 1 and overbidding_price < self.wall_mid:
                    bid_price = max(bid_price, overbidding_price)
                    break
                elif bp < self.wall_mid:
                    bid_price = max(bid_price, bp)
                    break

            # UNDERBIDDING: underbid best ask that is still over the mid wall
            for sp, sv in self.mkt_sell_orders.items():
                underbidding_price = sp - 1
                if sv > 1 and underbidding_price > self.wall_mid:
                    ask_price = min(ask_price, underbidding_price)
                    break
                elif sp > self.wall_mid:
                    ask_price = min(ask_price, sp)
                    break

            # POST ORDERS
            self.bid(bid_price, self.max_allowed_buy_volume)
            self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}

# ==========================================
# 4. 动态资产交易员 (Dynamic Asset / Pepper Root)
# ==========================================
class DynamicTrader(BaseTrader):
    # [修复2]：加入 name 参数
    def __init__(self, name, state, prints, new_trader_data):
        super().__init__(name, state, prints, new_trader_data)

        self.informed_direction, self.informed_bought_ts, self.informed_sold_ts = self.check_for_informed()

    # [修复3]：你的原代码缺少这个函数体，如果不定义，这里会报 AttributeError
    # 为了保证你的核心交易逻辑可以顺利运转，提供一个返回默认值的空函数
    def check_for_informed(self):
        # 默认没有检测到内幕交易员的操作，返回中立 (NEUTRAL) 及 None 时间戳
        return NEUTRAL, None, None

    def get_orders(self):

        if self.wall_mid is not None:

            bid_price = self.bid_wall + 1
            bid_volume = self.max_allowed_buy_volume

            if self.informed_bought_ts is not None and self.informed_bought_ts + 5_00 >= self.state.timestamp:
                if self.initial_position < 40:
                    bid_price = self.ask_wall
                    bid_volume = 40 - self.initial_position

            else:
                if self.wall_mid - bid_price < 1 and (self.informed_direction == SHORT and self.initial_position > -40):
                    bid_price = self.bid_wall

            self.bid(bid_price, bid_volume)


            ask_price = self.ask_wall - 1
            ask_volume = self.max_allowed_sell_volume

            if self.informed_sold_ts is not None and self.informed_sold_ts + 5_00 >= self.state.timestamp:
                if self.initial_position > -40:
                    ask_price = self.bid_wall
                    ask_volume = 40 + self.initial_position

            if ask_price - self.wall_mid < 1 and (self.informed_direction == LONG and self.initial_position < 40):
                ask_price = self.ask_wall

            self.ask(ask_price, ask_volume)

        return {self.name: self.orders}
    

# ==========================================
# 5. 主入口 (Trader Class)
# ==========================================
class Trader:
    def run(self, state: TradingState):
        result:dict[str,list[Order]] = {}
        conversions = 0
        new_trader_data = {}
        
        prints = {
            "GENERAL": {
                "TIMESTAMP": state.timestamp,
                "POSITIONS": state.position
            }
        }
        
        product_traders = {
            STATIC_SYMBOL: StaticTrader,
            DYNAMIC_SYMBOL: DynamicTrader,
        }
        
        for symbol, product_trader_class in product_traders.items():
            if symbol in state.order_depths:
                try:
                    # 原本这里传了 symbol, state, prints... 这就是为什么需要 __init__ 也接收 name
                    trader = product_trader_class(symbol, state, prints, new_trader_data)
                    result.update(trader.get_orders())
                except Exception as e:
                    print(f"Error in {symbol} Trader: {e}")

        traderData = json.dumps(new_trader_data)
        
        try:
            print(json.dumps(prints))
        except:
            pass

        return result, conversions, traderData