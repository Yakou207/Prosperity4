from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict, Any
import json
import math


class Trader:
    """
    Round2 优化版（基于 round2test.py baseline + baseline_output 回测问题修复）

    关键改动：
    1) 修复下单超限：使用“同侧预算”而不是用成交后仓位去放大反向额度。
    2) ASH 使用自适应 EMA 公允价，避免固定 FV=10000 在 Day1 结构性偏空。
    3) ASH 做市与吃单都做库存约束与分级限量，降低单次冲击。
    4) PEPPER 保持 buy-and-hold 主逻辑，但加 theo 约束与被动补单。
    """

    POSITION_LIMITS = {
        "INTARIAN_PEPPER_ROOT": 80,
        "ASH_COATED_OSMIUM": 80,
    }

    MARKET_ACCESS_FEE = 2000

    # ---------- ASH ----------
    ASH_BASE_FV = 10000.0
    ASH_EMA_ALPHA = 0.05
    ASH_BASE_HALF_SPREAD = 4
    ASH_TAKE_EDGE = 0.0
    ASH_SKEW = 0.28
    ASH_MAX_TAKE_PER_LEVEL = 20
    ASH_MAKE_SIZE = 14

    # ---------- PEPPER ----------
    PEPPER_TREND_PER_STEP = 0.10  # 每 100 timestamp 漂移
    PEPPER_AGG_EDGE = 8.0
    PEPPER_TAKE_SIZE = 30
    PEPPER_MAKE_SIZE = 25
    PEPPER_EARLY_RUSH_POS = 50  # 前期优先快速建仓

    # ---------- state keys ----------
    K_ASH_EMA = "ash_ema"
    K_PEPPER_ANCHOR_FV = "pepper_anchor_fv"
    K_PEPPER_ANCHOR_TS = "pepper_anchor_ts"

    def bid(self, state: TradingState) -> int:
        """Round2 MAF 竞价接口（有些引擎会调用 bid()）。"""
        return self.MARKET_ACCESS_FEE

    def run(self, state: TradingState):
        data = self._load_state(state.traderData)
        result: Dict[str, List[Order]] = {}

        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)
            lim = self.POSITION_LIMITS.get(product, 0)

            if product == "ASH_COATED_OSMIUM":
                orders = self._trade_ash(od, pos, lim, data)
            elif product == "INTARIAN_PEPPER_ROOT":
                orders = self._trade_pepper(od, pos, lim, state.timestamp, data)
            else:
                orders = []

            result[product] = orders

        return result, self.MARKET_ACCESS_FEE, json.dumps(data, separators=(",", ":"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _load_state(self, trader_data: str) -> Dict[str, Any]:
        data = {
            self.K_ASH_EMA: None,
            self.K_PEPPER_ANCHOR_FV: None,
            self.K_PEPPER_ANCHOR_TS: None,
        }
        if not trader_data:
            return data
        try:
            raw = json.loads(trader_data)
            if isinstance(raw, dict):
                data.update(raw)
        except Exception:
            pass
        return data

    @staticmethod
    def _best_bid_ask(od: OrderDepth):
        best_bid = max(od.buy_orders) if od.buy_orders else None
        best_ask = min(od.sell_orders) if od.sell_orders else None
        return best_bid, best_ask

    @staticmethod
    def _book_mid(best_bid, best_ask):
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        if best_bid is not None:
            return float(best_bid)
        if best_ask is not None:
            return float(best_ask)
        return None

    # ------------------------------------------------------------------
    # ASH_COATED_OSMIUM
    # ------------------------------------------------------------------
    def _trade_ash(self, od: OrderDepth, pos: int, lim: int, data: Dict[str, Any]) -> List[Order]:
        orders: List[Order] = []
        symbol = "ASH_COATED_OSMIUM"

        best_bid, best_ask = self._best_bid_ask(od)
        mid = self._book_mid(best_bid, best_ask)

        # 自适应 FV（EMA）
        ema = data.get(self.K_ASH_EMA)
        if mid is not None:
            if ema is None:
                ema = mid
            else:
                ema = (1 - self.ASH_EMA_ALPHA) * float(ema) + self.ASH_EMA_ALPHA * mid
            data[self.K_ASH_EMA] = ema

        fv = float(ema) if ema is not None else self.ASH_BASE_FV

        # 关键修复：预算基于“起始仓位”，不在同一tick内因假设成交而扩容反向额度
        buy_budget = max(0, lim - pos)
        sell_budget = max(0, lim + pos)

        est_pos = pos  # 仅用于报价 skew，不用于预算扩容

        # ---- TAKE: 吃偏离公允价盘口 ----
        if od.sell_orders:
            for ask in sorted(od.sell_orders.keys()):
                if buy_budget <= 0:
                    break
                if ask > fv - self.ASH_TAKE_EDGE:
                    break
                avail = abs(od.sell_orders[ask])
                qty = min(avail, buy_budget, self.ASH_MAX_TAKE_PER_LEVEL)
                if qty <= 0:
                    continue
                orders.append(Order(symbol, ask, qty))
                buy_budget -= qty
                est_pos += qty

        if od.buy_orders:
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                if sell_budget <= 0:
                    break
                if bid < fv + self.ASH_TAKE_EDGE:
                    break
                avail = od.buy_orders[bid]
                qty = min(avail, sell_budget, self.ASH_MAX_TAKE_PER_LEVEL)
                if qty <= 0:
                    continue
                orders.append(Order(symbol, bid, -qty))
                sell_budget -= qty
                est_pos -= qty

        # ---- MAKE: 库存 skew 做市 ----
        inv_penalty = self.ASH_SKEW * est_pos
        adj_fv = fv - inv_penalty

        half_spread = self.ASH_BASE_HALF_SPREAD + min(3, abs(est_pos) // 25)
        our_bid = math.floor(adj_fv - half_spread)
        our_ask = math.ceil(adj_fv + half_spread)

        if best_bid is not None:
            our_bid = max(our_bid, best_bid + 1)
        if best_ask is not None:
            # 维持靠近卖一，避免远离市场吃不到单
            our_ask = max(our_ask, best_ask - 1)

        # 相对 FV 的软护栏（不是固定 10000）
        our_bid = min(our_bid, math.floor(fv + 1))
        our_ask = max(our_ask, math.ceil(fv - 1))

        # 防穿价
        if best_ask is not None and our_bid >= best_ask:
            our_bid = best_ask - 1
        if best_bid is not None and our_ask <= best_bid:
            our_ask = best_bid + 1
        if our_ask <= our_bid:
            our_ask = our_bid + 1

        make_size = self.ASH_MAKE_SIZE
        if abs(est_pos) >= 60:
            make_size = 10
        elif abs(est_pos) >= 40:
            make_size = 14

        if buy_budget > 0:
            q = min(make_size, buy_budget)
            if q > 0:
                orders.append(Order(symbol, int(our_bid), int(q)))
                buy_budget -= q

        if sell_budget > 0:
            q = min(make_size, sell_budget)
            if q > 0:
                orders.append(Order(symbol, int(our_ask), -int(q)))
                sell_budget -= q

        return orders

    # ------------------------------------------------------------------
    # INTARIAN_PEPPER_ROOT
    # ------------------------------------------------------------------
    def _trade_pepper(
        self,
        od: OrderDepth,
        pos: int,
        lim: int,
        timestamp: int,
        data: Dict[str, Any],
    ) -> List[Order]:
        orders: List[Order] = []
        symbol = "INTARIAN_PEPPER_ROOT"

        best_bid, best_ask = self._best_bid_ask(od)
        mid = self._book_mid(best_bid, best_ask)

        anchor_fv = data.get(self.K_PEPPER_ANCHOR_FV)
        anchor_ts = data.get(self.K_PEPPER_ANCHOR_TS)
        if anchor_fv is None and mid is not None:
            anchor_fv = mid
            anchor_ts = timestamp
            data[self.K_PEPPER_ANCHOR_FV] = anchor_fv
            data[self.K_PEPPER_ANCHOR_TS] = anchor_ts

        if anchor_fv is None or anchor_ts is None:
            # 无法估值时：仅保守被动挂单
            if best_bid is not None and best_ask is not None and pos < lim:
                bid_px = min(best_bid + 1, best_ask - 1)
                qty = min(self.PEPPER_MAKE_SIZE, lim - pos)
                if qty > 0 and bid_px < best_ask:
                    orders.append(Order(symbol, int(bid_px), int(qty)))
            return orders

        steps = max(0.0, (timestamp - anchor_ts) / 100.0)
        theo = float(anchor_fv) + self.PEPPER_TREND_PER_STEP * steps

        buy_budget = max(0, lim - pos)

        # TAKE：优先快速建仓；后续只吃“相对 theo 不贵”的卖盘
        if od.sell_orders and buy_budget > 0:
            for ask in sorted(od.sell_orders.keys()):
                if buy_budget <= 0:
                    break
                must_rush = pos < self.PEPPER_EARLY_RUSH_POS
                affordable = ask <= theo + self.PEPPER_AGG_EDGE
                if not must_rush and not affordable:
                    break

                avail = abs(od.sell_orders[ask])
                qty = min(avail, buy_budget, self.PEPPER_TAKE_SIZE)
                if qty <= 0:
                    continue
                orders.append(Order(symbol, ask, int(qty)))
                buy_budget -= qty
                pos += qty

        # MAKE：补剩余仓位
        if buy_budget > 0 and best_bid is not None and best_ask is not None:
            bid_px = min(best_bid + 1, best_ask - 1, math.floor(theo))
            if bid_px < best_ask:
                qty = min(self.PEPPER_MAKE_SIZE, buy_budget)
                if qty > 0:
                    orders.append(Order(symbol, int(bid_px), int(qty)))

        return orders