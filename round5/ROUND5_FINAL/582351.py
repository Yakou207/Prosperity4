from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Optional
import json


POSITION_LIMIT = 10
PROFIT_SWITCH_THRESHOLD = 160000.0
DRAWDOWN_DEFENSE_THRESHOLD = 35000.0
EDGE_EMA_ALPHA = 0.30
REL_EMA_ALPHA = 0.30
FAIR_EMA_ALPHA = 0.12
VOL_EMA_ALPHA = 0.20
SPREAD_EMA_ALPHA = 0.20
MM_MAX_SIZE_BALANCED = 2
MM_MAX_SIZE_DEFENSE = 1
MM_EDGE_THRESHOLD = 0.25
MM_REL_HEALTH_FLOOR = -12.0

# Final v8:
# 1. Before first estimated profit reaches 160k, run the aggressive v4+lottery book.
# 2. After the first 160k trigger, keep the profitable priors as default.
#    Only reduce size when market-relative monitors say the old relationship
#    has stopped working. This avoids overreacting to noise while still
#    protecting the long final test.
# 3. If the post-switch estimate draws down 35k from its own peak, move to a
#    relative-aware core-defense book instead of fully stopping.
# 4. After 160k only, add passive two-sided quotes around a monitored fair.
#    The market-making layer is inventory-aware and capped; it helps harvest
#    spread without fighting the main directional book.
#
# The trigger uses mark-to-market PnL estimated from first seen mids because
# the Trader does not receive the official UI PnL directly.

AGGRESSIVE_CONFIG = {
    "PEBBLES_XL": {"direction": 1, "target": 10, "clip": 4},
    "MICROCHIP_OVAL": {"direction": -1, "target": 10, "clip": 4},
    "OXYGEN_SHAKE_GARLIC": {"direction": 1, "target": 10, "clip": 4},
    "SLEEP_POD_COTTON": {"direction": 1, "target": 10, "clip": 4},
    "ROBOT_LAUNDRY": {"direction": -1, "target": 10, "clip": 4},
    "TRANSLATOR_SPACE_GRAY": {"direction": -1, "target": 10, "clip": 4},
    "UV_VISOR_AMBER": {"direction": -1, "target": 10, "clip": 4},
    "UV_VISOR_RED": {"direction": 1, "target": 10, "clip": 4},
    "UV_VISOR_ORANGE": {"direction": 1, "target": 10, "clip": 4},
    "PEBBLES_S": {"direction": -1, "target": 10, "clip": 4},
    "PEBBLES_XS": {"direction": -1, "target": 10, "clip": 4},
    "MICROCHIP_RECTANGLE": {"direction": -1, "target": 10, "clip": 4},
    "OXYGEN_SHAKE_MINT": {"direction": -1, "target": 10, "clip": 4},
    "OXYGEN_SHAKE_MORNING_BREATH": {"direction": -1, "target": 10, "clip": 4},
    "TRANSLATOR_VOID_BLUE": {"direction": 1, "target": 10, "clip": 4},
    "SLEEP_POD_NYLON": {"direction": 1, "target": 10, "clip": 4},
    "SLEEP_POD_SUEDE": {"direction": 1, "target": 10, "clip": 4},
    "MICROCHIP_CIRCLE": {"direction": -1, "target": 10, "clip": 4},
    "PANEL_4X4": {"direction": 1, "target": 10, "clip": 5},
    "SLEEP_POD_LAMB_WOOL": {"direction": -1, "target": 10, "clip": 5},
    "TRANSLATOR_GRAPHITE_MIST": {"direction": 1, "target": 10, "clip": 5},
    "PANEL_1X4": {"direction": -1, "target": 10, "clip": 5},
    "PANEL_2X2": {"direction": -1, "target": 10, "clip": 5},
    "TRANSLATOR_ECLIPSE_CHARCOAL": {"direction": 1, "target": 10, "clip": 5},
    "GALAXY_SOUNDS_PLANETARY_RINGS": {"direction": -1, "target": 10, "clip": 4},
    "ROBOT_IRONING": {"direction": 1, "target": 10, "clip": 4},
    "MICROCHIP_SQUARE": {"direction": -1, "target": 10, "clip": 4},
    "GALAXY_SOUNDS_DARK_MATTER": {"direction": -1, "target": 10, "clip": 4},
    "UV_VISOR_MAGENTA": {"direction": -1, "target": 10, "clip": 4},
    "PANEL_1X2": {"direction": -1, "target": 10, "clip": 4},
}

BALANCED_CONFIG = {
    # Default after 160k is still assertive; relative monitors do the trimming.
    "PEBBLES_XL": {"direction": 1, "target": 10, "clip": 4},
    "MICROCHIP_OVAL": {"direction": -1, "target": 10, "clip": 4},
    "OXYGEN_SHAKE_GARLIC": {"direction": 1, "target": 10, "clip": 4},
    "SLEEP_POD_COTTON": {"direction": 1, "target": 10, "clip": 4},
    "ROBOT_LAUNDRY": {"direction": -1, "target": 10, "clip": 4},
    "TRANSLATOR_SPACE_GRAY": {"direction": -1, "target": 10, "clip": 4},
    "UV_VISOR_AMBER": {"direction": -1, "target": 10, "clip": 4},
    "UV_VISOR_RED": {"direction": 1, "target": 10, "clip": 4},
    "UV_VISOR_ORANGE": {"direction": 1, "target": 10, "clip": 4},
    "PEBBLES_S": {"direction": -1, "target": 10, "clip": 4},

    "PEBBLES_XS": {"direction": -1, "target": 9, "clip": 4},
    "MICROCHIP_RECTANGLE": {"direction": -1, "target": 9, "clip": 4},
    "PANEL_4X4": {"direction": 1, "target": 9, "clip": 4},
    "SLEEP_POD_LAMB_WOOL": {"direction": -1, "target": 9, "clip": 4},
    "TRANSLATOR_GRAPHITE_MIST": {"direction": 1, "target": 9, "clip": 4},
    "PANEL_1X4": {"direction": -1, "target": 9, "clip": 4},
    "PANEL_2X2": {"direction": -1, "target": 9, "clip": 4},
    "TRANSLATOR_ECLIPSE_CHARCOAL": {"direction": 1, "target": 9, "clip": 4},
    "OXYGEN_SHAKE_MINT": {"direction": -1, "target": 7, "clip": 3},
    "OXYGEN_SHAKE_MORNING_BREATH": {"direction": -1, "target": 7, "clip": 3},
    "TRANSLATOR_VOID_BLUE": {"direction": 1, "target": 7, "clip": 3},
    "SLEEP_POD_NYLON": {"direction": 1, "target": 7, "clip": 3},
    "SLEEP_POD_SUEDE": {"direction": 1, "target": 7, "clip": 3},
    "MICROCHIP_CIRCLE": {"direction": -1, "target": 7, "clip": 3},
    "GALAXY_SOUNDS_PLANETARY_RINGS": {"direction": -1, "target": 8, "clip": 3},
    "ROBOT_IRONING": {"direction": 1, "target": 8, "clip": 3},
    "MICROCHIP_SQUARE": {"direction": -1, "target": 8, "clip": 3},
    "GALAXY_SOUNDS_DARK_MATTER": {"direction": -1, "target": 8, "clip": 3},
    "UV_VISOR_MAGENTA": {"direction": -1, "target": 8, "clip": 3},
    "PANEL_1X2": {"direction": -1, "target": 8, "clip": 3},
}

BALANCED_BOUNDS = {
    "PEBBLES_XL": (8, 10),
    "MICROCHIP_OVAL": (8, 10),
    "OXYGEN_SHAKE_GARLIC": (6, 10),
    "SLEEP_POD_COTTON": (8, 10),
    "ROBOT_LAUNDRY": (8, 10),
    "TRANSLATOR_SPACE_GRAY": (8, 10),
    "UV_VISOR_AMBER": (6, 10),
    "UV_VISOR_RED": (8, 10),
    "UV_VISOR_ORANGE": (6, 10),
    "PEBBLES_S": (8, 10),
    "PEBBLES_XS": (4, 10),
    "MICROCHIP_RECTANGLE": (4, 10),
    "PANEL_4X4": (5, 10),
    "SLEEP_POD_LAMB_WOOL": (5, 10),
    "TRANSLATOR_GRAPHITE_MIST": (5, 10),
    "PANEL_1X4": (5, 10),
    "PANEL_2X2": (5, 10),
    "TRANSLATOR_ECLIPSE_CHARCOAL": (5, 10),
    "OXYGEN_SHAKE_MINT": (2, 9),
    "OXYGEN_SHAKE_MORNING_BREATH": (2, 9),
    "TRANSLATOR_VOID_BLUE": (2, 9),
    "SLEEP_POD_NYLON": (2, 9),
    "SLEEP_POD_SUEDE": (2, 9),
    "MICROCHIP_CIRCLE": (2, 9),
    "GALAXY_SOUNDS_PLANETARY_RINGS": (2, 10),
    "ROBOT_IRONING": (2, 10),
    "MICROCHIP_SQUARE": (2, 10),
    "GALAXY_SOUNDS_DARK_MATTER": (2, 10),
    "UV_VISOR_MAGENTA": (2, 10),
    "PANEL_1X2": (2, 10),
}

RELATIVE_GROUPS = {
    "PEBBLES_REL": {
        "longs": ["PEBBLES_XL"],
        "shorts": ["PEBBLES_S", "PEBBLES_XS"],
        "products": ["PEBBLES_XL", "PEBBLES_S", "PEBBLES_XS"],
    },
    "UV_VISOR_REL": {
        "longs": ["UV_VISOR_RED", "UV_VISOR_ORANGE"],
        "shorts": ["UV_VISOR_AMBER", "UV_VISOR_MAGENTA"],
        "products": ["UV_VISOR_RED", "UV_VISOR_ORANGE", "UV_VISOR_AMBER", "UV_VISOR_MAGENTA"],
    },
    "PANEL_REL": {
        "longs": ["PANEL_4X4"],
        "shorts": ["PANEL_1X4", "PANEL_2X2", "PANEL_1X2"],
        "products": ["PANEL_4X4", "PANEL_1X4", "PANEL_2X2", "PANEL_1X2"],
    },
    "ROBOT_REL": {
        "longs": ["ROBOT_IRONING"],
        "shorts": ["ROBOT_LAUNDRY"],
        "products": ["ROBOT_IRONING", "ROBOT_LAUNDRY"],
    },
    "SLEEP_POD_REL": {
        "longs": ["SLEEP_POD_COTTON", "SLEEP_POD_NYLON", "SLEEP_POD_SUEDE"],
        "shorts": ["SLEEP_POD_LAMB_WOOL"],
        "products": ["SLEEP_POD_COTTON", "SLEEP_POD_NYLON", "SLEEP_POD_SUEDE", "SLEEP_POD_LAMB_WOOL"],
    },
    "OXYGEN_REL": {
        "longs": ["OXYGEN_SHAKE_GARLIC"],
        "shorts": ["OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_MORNING_BREATH"],
        "products": ["OXYGEN_SHAKE_GARLIC", "OXYGEN_SHAKE_MINT", "OXYGEN_SHAKE_MORNING_BREATH"],
    },
    "TRANSLATOR_REL": {
        "longs": ["TRANSLATOR_GRAPHITE_MIST", "TRANSLATOR_ECLIPSE_CHARCOAL", "TRANSLATOR_VOID_BLUE"],
        "shorts": ["TRANSLATOR_SPACE_GRAY"],
        "products": [
            "TRANSLATOR_GRAPHITE_MIST",
            "TRANSLATOR_ECLIPSE_CHARCOAL",
            "TRANSLATOR_VOID_BLUE",
            "TRANSLATOR_SPACE_GRAY",
        ],
    },
}

CORE_DEFENSE_CONFIG = {
    "PEBBLES_XL": {"direction": 1, "target": 10, "clip": 4},
    "MICROCHIP_OVAL": {"direction": -1, "target": 10, "clip": 4},
    "OXYGEN_SHAKE_GARLIC": {"direction": 1, "target": 8, "clip": 4},
    "SLEEP_POD_COTTON": {"direction": 1, "target": 10, "clip": 4},
    "ROBOT_LAUNDRY": {"direction": -1, "target": 10, "clip": 4},
    "TRANSLATOR_SPACE_GRAY": {"direction": -1, "target": 10, "clip": 4},
    "UV_VISOR_AMBER": {"direction": -1, "target": 8, "clip": 4},
    "UV_VISOR_RED": {"direction": 1, "target": 10, "clip": 4},
    "UV_VISOR_ORANGE": {"direction": 1, "target": 8, "clip": 4},
    "PEBBLES_S": {"direction": -1, "target": 10, "clip": 4},
}

CORE_DEFENSE_BOUNDS = {
    "PEBBLES_XL": (7, 10),
    "MICROCHIP_OVAL": (7, 10),
    "OXYGEN_SHAKE_GARLIC": (4, 8),
    "SLEEP_POD_COTTON": (7, 10),
    "ROBOT_LAUNDRY": (7, 10),
    "TRANSLATOR_SPACE_GRAY": (7, 10),
    "UV_VISOR_AMBER": (4, 8),
    "UV_VISOR_RED": (7, 10),
    "UV_VISOR_ORANGE": (4, 8),
    "PEBBLES_S": (7, 10),
}

ALL_PRODUCTS = sorted(set(AGGRESSIVE_CONFIG) | set(BALANCED_CONFIG) | set(CORE_DEFENSE_CONFIG))


class Trader:
    def run(self, state: TradingState):
        memory = self._load_memory(state.traderData)
        memory["tick_count"] = int(memory.get("tick_count", 0)) + 1

        anchors = memory.setdefault("anchor_mid", {})
        last_mid = memory.setdefault("last_mid", {})
        edge_ema = memory.setdefault("edge_ema", {})
        fair_ema = memory.setdefault("fair_ema", {})
        vol_ema = memory.setdefault("vol_ema", {})
        spread_ema = memory.setdefault("spread_ema", {})
        rel_anchor = memory.setdefault("rel_anchor", {})
        rel_last = memory.setdefault("rel_last", {})
        rel_ema = memory.setdefault("rel_ema", {})
        last_pos = memory.setdefault("last_pos", {})
        fill_events = int(memory.get("fill_events", 0))

        mids: Dict[str, float] = {}
        for product in ALL_PRODUCTS:
            order_depth = state.order_depths.get(product)
            mid = self._mid(order_depth)
            if mid is not None:
                mids[product] = mid
                anchors.setdefault(product, mid)
                previous_mid = last_mid.get(product)
                if previous_mid is not None:
                    direction = AGGRESSIVE_CONFIG[product]["direction"]
                    raw_move = mid - float(previous_mid)
                    signed_move = direction * raw_move
                    previous_edge = float(edge_ema.get(product, 0.0))
                    edge_ema[product] = (1.0 - EDGE_EMA_ALPHA) * previous_edge + EDGE_EMA_ALPHA * signed_move
                    previous_vol = float(vol_ema.get(product, abs(raw_move)))
                    vol_ema[product] = (1.0 - VOL_EMA_ALPHA) * previous_vol + VOL_EMA_ALPHA * abs(raw_move)
                previous_fair = float(fair_ema.get(product, mid))
                fair_ema[product] = (1.0 - FAIR_EMA_ALPHA) * previous_fair + FAIR_EMA_ALPHA * mid
                last_mid[product] = mid
                self._update_spread_ema(product, order_depth, spread_ema)

            current_position = state.position.get(product, 0)
            previous_position = int(last_pos.get(product, current_position))
            if current_position != previous_position:
                fill_events += abs(current_position - previous_position)
            last_pos[product] = current_position

        relative_health = self._update_relative_health(mids, rel_anchor, rel_last, rel_ema)
        memory["relative_health"] = relative_health
        memory["fill_events"] = fill_events
        estimated_pnl = self._estimate_anchor_pnl(state, mids, anchors)
        max_estimated_pnl = max(float(memory.get("max_estimated_pnl", estimated_pnl)), estimated_pnl)
        memory["estimated_pnl"] = estimated_pnl
        memory["max_estimated_pnl"] = max_estimated_pnl

        mode = memory.get("mode", "aggressive")
        if mode == "aggressive" and estimated_pnl >= PROFIT_SWITCH_THRESHOLD:
            mode = "balanced"
            memory["mode"] = mode
            memory["switch_tick"] = memory["tick_count"]
            memory["switch_fill_events"] = fill_events
            memory["switch_estimated_pnl"] = estimated_pnl
            memory["post_switch_peak"] = estimated_pnl
        elif mode in ("balanced", "core_defense"):
            post_switch_peak = max(float(memory.get("post_switch_peak", estimated_pnl)), estimated_pnl)
            memory["post_switch_peak"] = post_switch_peak
            if mode == "balanced" and post_switch_peak - estimated_pnl >= DRAWDOWN_DEFENSE_THRESHOLD:
                mode = "core_defense"
                memory["mode"] = mode
                memory["defense_tick"] = memory["tick_count"]
                memory["defense_estimated_pnl"] = estimated_pnl

        target_config = self._config_for_mode(mode, edge_ema, relative_health)
        result: Dict[str, List[Order]] = {}
        self._rebalance_to_config(result, state, target_config)
        if mode in ("balanced", "core_defense"):
            projected_position = self._project_positions(state, result)
            self._add_market_making_quotes(
                result,
                state,
                target_config,
                projected_position,
                fair_ema,
                vol_ema,
                spread_ema,
                edge_ema,
                relative_health,
                mode,
            )

        return result, 0, json.dumps(memory, separators=(",", ":"))

    def _config_for_mode(
        self,
        mode: str,
        edge_ema: Dict[str, float],
        relative_health: Dict[str, float],
    ) -> Dict[str, Dict[str, int]]:
        if mode == "core_defense":
            return self._dynamic_config(CORE_DEFENSE_CONFIG, CORE_DEFENSE_BOUNDS, edge_ema, relative_health)
        if mode == "balanced":
            return self._dynamic_config(BALANCED_CONFIG, BALANCED_BOUNDS, edge_ema, relative_health)
        return AGGRESSIVE_CONFIG

    def _dynamic_config(
        self,
        base_config: Dict[str, Dict[str, int]],
        bounds: Dict[str, tuple],
        edge_ema: Dict[str, float],
        relative_health: Dict[str, float],
    ) -> Dict[str, Dict[str, int]]:
        dynamic: Dict[str, Dict[str, int]] = {}
        for product, config in base_config.items():
            base_target = config["target"]
            low, high = bounds.get(product, (max(1, base_target - 2), min(POSITION_LIMIT, base_target + 2)))
            edge = float(edge_ema.get(product, 0.0))
            group_health = self._product_group_health(product, relative_health)

            if group_health <= -25.0:
                target = low
                clip = max(1, config["clip"] - 2)
            elif group_health <= -8.0:
                target = max(low, base_target - 2)
                clip = max(1, config["clip"] - 1)
            elif edge >= 1.5 and group_health >= -3.0:
                target = high
                clip = min(5, config["clip"] + 1)
            elif edge >= 0.35 and group_health >= -5.0:
                target = min(high, base_target + 1)
                clip = config["clip"]
            elif edge <= -1.5:
                target = low
                clip = max(1, config["clip"] - 1)
            elif edge <= -0.35:
                target = max(low, base_target - 1)
                clip = max(1, config["clip"] - 1)
            else:
                target = base_target
                clip = max(1, config["clip"] - 1)

            dynamic[product] = {
                "direction": config["direction"],
                "target": int(max(low, min(high, target))),
                "clip": int(max(1, min(5, clip))),
            }
        return dynamic

    def _update_relative_health(
        self,
        mids: Dict[str, float],
        rel_anchor: Dict[str, float],
        rel_last: Dict[str, float],
        rel_ema: Dict[str, float],
    ) -> Dict[str, float]:
        health: Dict[str, float] = {}
        for name, group in RELATIVE_GROUPS.items():
            spread = self._relative_spread(group, mids)
            if spread is None:
                health[name] = float(rel_ema.get(name, 0.0))
                continue

            rel_anchor.setdefault(name, spread)
            previous_spread = rel_last.get(name)
            if previous_spread is not None:
                delta = spread - float(previous_spread)
                previous_ema = float(rel_ema.get(name, 0.0))
                rel_ema[name] = (1.0 - REL_EMA_ALPHA) * previous_ema + REL_EMA_ALPHA * delta
            rel_last[name] = spread

            anchor_move = spread - float(rel_anchor[name])
            health[name] = anchor_move + 8.0 * float(rel_ema.get(name, 0.0))
        return health

    def _relative_spread(self, group: Dict[str, List[str]], mids: Dict[str, float]) -> Optional[float]:
        longs = [mids[p] for p in group["longs"] if p in mids]
        shorts = [mids[p] for p in group["shorts"] if p in mids]
        if not longs or not shorts:
            return None
        return sum(longs) / len(longs) - sum(shorts) / len(shorts)

    def _product_group_health(self, product: str, relative_health: Dict[str, float]) -> float:
        scores = []
        for name, group in RELATIVE_GROUPS.items():
            if product in group["products"]:
                scores.append(float(relative_health.get(name, 0.0)))
        if not scores:
            return 0.0
        return min(scores)

    def _update_spread_ema(self, product: str, order_depth: OrderDepth, spread_ema: Dict[str, float]) -> None:
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return
        spread = min(order_depth.sell_orders) - max(order_depth.buy_orders)
        previous_spread = float(spread_ema.get(product, spread))
        spread_ema[product] = (1.0 - SPREAD_EMA_ALPHA) * previous_spread + SPREAD_EMA_ALPHA * spread

    def _project_positions(self, state: TradingState, result: Dict[str, List[Order]]) -> Dict[str, int]:
        projected = {product: state.position.get(product, 0) for product in ALL_PRODUCTS}
        for product, orders in result.items():
            projected.setdefault(product, state.position.get(product, 0))
            for order in orders:
                projected[product] += order.quantity
        return projected

    def _add_market_making_quotes(
        self,
        result: Dict[str, List[Order]],
        state: TradingState,
        target_config: Dict[str, Dict[str, int]],
        projected_position: Dict[str, int],
        fair_ema: Dict[str, float],
        vol_ema: Dict[str, float],
        spread_ema: Dict[str, float],
        edge_ema: Dict[str, float],
        relative_health: Dict[str, float],
        mode: str,
    ) -> None:
        max_size = MM_MAX_SIZE_DEFENSE if mode == "core_defense" else MM_MAX_SIZE_BALANCED
        for product, config in target_config.items():
            order_depth = state.order_depths.get(product)
            if order_depth is None or not order_depth.buy_orders or not order_depth.sell_orders:
                continue

            group_health = self._product_group_health(product, relative_health)
            if group_health < MM_REL_HEALTH_FLOOR:
                continue

            fair = float(fair_ema.get(product, self._mid(order_depth) or 0.0))
            if fair <= 0:
                continue

            best_bid = max(order_depth.buy_orders)
            best_ask = min(order_depth.sell_orders)
            observed_spread = best_ask - best_bid
            avg_spread = max(float(spread_ema.get(product, observed_spread)), observed_spread, 1.0)
            vol = float(vol_ema.get(product, 0.0))
            edge = float(edge_ema.get(product, 0.0))

            target_position = config["direction"] * config["target"]
            current_projected = projected_position.get(product, state.position.get(product, 0))
            skew = current_projected - target_position

            half_width = max(1.0, avg_spread / 2.0, 0.35 * vol)
            if abs(edge) > MM_EDGE_THRESHOLD:
                half_width += 0.5

            raw_bid = int(fair - half_width - max(0, skew) * 0.15)
            raw_ask = int(fair + half_width - min(0, skew) * 0.15)
            quote_band = int(max(1.0, min(5.0, avg_spread + 0.5 * vol)))
            bid_price = max(best_bid - quote_band, min(raw_bid, best_bid))
            ask_price = min(best_ask + quote_band, max(raw_ask, best_ask))
            if bid_price >= ask_price:
                bid_price = best_bid
                ask_price = best_ask

            buy_capacity = POSITION_LIMIT - current_projected
            sell_capacity = POSITION_LIMIT + current_projected

            buy_size = min(max_size, buy_capacity)
            sell_size = min(max_size, sell_capacity)

            if current_projected > target_position:
                buy_size = min(buy_size, 1)
                sell_size = min(max_size, sell_size + 1)
            elif current_projected < target_position:
                sell_size = min(sell_size, 1)
                buy_size = min(max_size, buy_size + 1)

            if buy_size > 0 and bid_price < best_ask:
                result.setdefault(product, []).append(Order(product, bid_price, buy_size))
                projected_position[product] = projected_position.get(product, 0) + buy_size
            if sell_size > 0 and ask_price > best_bid:
                result.setdefault(product, []).append(Order(product, ask_price, -sell_size))
                projected_position[product] = projected_position.get(product, 0) - sell_size

    def _rebalance_to_config(
        self,
        result: Dict[str, List[Order]],
        state: TradingState,
        target_config: Dict[str, Dict[str, int]],
    ) -> None:
        for product in ALL_PRODUCTS:
            order_depth = state.order_depths.get(product)
            if order_depth is None:
                continue

            current_position = state.position.get(product, 0)
            config = target_config.get(product)
            if config is None:
                signed_target = 0
                clip = 5
            else:
                signed_target = config["direction"] * config["target"]
                clip = config["clip"]

            if current_position < signed_target:
                self._buy_towards_target(result, product, order_depth, current_position, signed_target, clip)
            elif current_position > signed_target:
                self._sell_towards_target(result, product, order_depth, current_position, signed_target, clip)

    def _estimate_anchor_pnl(self, state: TradingState, mids: Dict[str, float], anchors: Dict[str, float]) -> float:
        total = 0.0
        for product, mid in mids.items():
            current_position = state.position.get(product, 0)
            total += current_position * (mid - float(anchors[product]))
        return total

    def _mid(self, order_depth: Optional[OrderDepth]) -> Optional[float]:
        if order_depth is None or not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        return (max(order_depth.buy_orders) + min(order_depth.sell_orders)) / 2.0

    def _load_memory(self, trader_data: str) -> Dict:
        if not trader_data:
            return {"mode": "aggressive"}
        try:
            data = json.loads(trader_data)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {"mode": "aggressive"}

    def _buy_towards_target(
        self,
        result: Dict[str, List[Order]],
        product: str,
        order_depth: OrderDepth,
        current_position: int,
        signed_target: int,
        clip: int,
    ) -> None:
        remaining = min(signed_target - current_position, POSITION_LIMIT - current_position, clip)
        if remaining <= 0 or not order_depth.sell_orders:
            return

        for ask_price in sorted(order_depth.sell_orders):
            if remaining <= 0:
                break
            quantity = min(remaining, abs(order_depth.sell_orders[ask_price]))
            if quantity > 0:
                result.setdefault(product, []).append(Order(product, ask_price, quantity))
                remaining -= quantity

    def _sell_towards_target(
        self,
        result: Dict[str, List[Order]],
        product: str,
        order_depth: OrderDepth,
        current_position: int,
        signed_target: int,
        clip: int,
    ) -> None:
        remaining = min(current_position - signed_target, POSITION_LIMIT + current_position, clip)
        if remaining <= 0 or not order_depth.buy_orders:
            return

        for bid_price in sorted(order_depth.buy_orders, reverse=True):
            if remaining <= 0:
                break
            quantity = min(remaining, order_depth.buy_orders[bid_price])
            if quantity > 0:
                result.setdefault(product, []).append(Order(product, bid_price, -quantity))
                remaining -= quantity