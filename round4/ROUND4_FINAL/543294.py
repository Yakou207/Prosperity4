from datamodel import OrderDepth, TradingState, Order
from typing import Dict, List, Tuple, Optional
from math import ceil, erf, floor, log, sqrt, tanh
import json

# Variant: FINAL balanced adaptive allocator cap230
# Strategy: Hidden-oriented adaptive VEV allocator with max short cap 230, normalized edge, learned prior, hedge capacity, and strike feedback.
# Framework: dynamic prior learning + normalized edge + portfolio delta hedge capacity + strike-level performance feedback; conservative max cap 230.
# Dynamic cap interval is capped at 230, not fixed 5200/5300 hard caps. Runtime: no file I/O, no conversions.

POSITION_LIMITS: Dict[str, int] = {
    "HYDROGEL_PACK": 200,
    "VELVETFRUIT_EXTRACT": 200,
    "VEV_4000": 300,
    "VEV_4500": 300,
    "VEV_5000": 300,
    "VEV_5100": 300,
    "VEV_5200": 300,
    "VEV_5300": 300,
    "VEV_5400": 300,
    "VEV_5500": 300,
    "VEV_6000": 300,
    "VEV_6500": 300,
}

TRADE_UNDERLYING = True
TRADE_OPTIONS = True
TRADE_HYDROGEL = True

UNDERLYING = "VELVETFRUIT_EXTRACT"

ACTIVE_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]


# ── HYDROGEL_PACK ─────────────────────────────────────────────

HG_FAIR = 9991
HG_TAKE_EDGE = 26
HG_TAKE_SIZE = 18
HG_POST_EDGE = 9
HG_POST_SIZE = 18
HG_SKEW_DIV = 25

# ── HYDROGEL momentum overlay ─────────────────────────────
HG_MOM_ALPHA = 0.12
HG_MOM_K = 0.45
HG_MOM_CAP = 5
HG_MOM_TAKE_BOOST = 1.3
HG_MOM_KEY = "HYDROGEL_PACK_ema"


# ── VELVETFRUIT_EXTRACT (base) ───────────────────────────────

VE_ANCHOR = 5262.0
VE_ANCHOR_WEIGHT = 0.6
VE_EMA_ALPHA = 0.08
VE_IMBALANCE_K = 2.0
VE_IMBALANCE_CAP = 2.0
VE_SKEW_DIV = 72

VE_EDGE = 6
VE_SIZE = 26
VE_POST_EDGE = 1
VE_POST_SIZE = 26

# ── Counterparty flow overlay (Round4) ───────────────────────
# Positive score => likely informed; negative => likely anti-informed.
# From analysis: Mark 67 strong positive, Mark 49 strong negative.
TRADER_PRIOR_SCORE: Dict[str, float] = {
    "Mark 67": 2.0,
    "Mark 49": -1.8,
    "Mark 22": -0.2,
    "Mark 14": -0.1,
}

# v2: anti signal weight is 50% of informed signal
INFORMED_SIGNAL_WEIGHT = 1.0
ANTI_SIGNAL_WEIGHT = 0.5

FLOW_EMA_ALPHA = 0.38
FLOW_CLIP = 1.7
VE_FLOW_SHIFT_K = 2.6
OPT_FLOW_SHIFT_K = 0.50


def weighted_trader_prior(name: Optional[str]) -> float:
    base = TRADER_PRIOR_SCORE.get(name, 0.0)
    if base > 0:
        return INFORMED_SIGNAL_WEIGHT * base
    if base < 0:
        return ANTI_SIGNAL_WEIGHT * base
    return 0.0


# ── Options ───────────────────────────────────────────────

OPTION_TAKE_SIZE = 16        # extreme option-only crossing size
OPTION_POST_SIZE = 16        # extreme option-only passive quote size
OPTION_MAX_POSITION = 140    # extreme option-only per-strike soft cap

# Additional side-specific soft caps to avoid sticky long exposure in far OTM wings.
OPTION_LONG_CAP_5300 = 18
OPTION_LONG_CAP_5400 = 6
OPTION_LONG_CAP_5500 = 3

# Strike-specific coupon focus. Historical submitted logs suggest the useful
# coupon edge is concentrated around VEV_5200/5300, while high-strike wings
# need tighter long exposure control.
OPTION_CORE_STRIKES = {5200, 5300}
OPTION_CORE_TAKE_SIZE = 26
OPTION_CORE_POST_SIZE = 26
OPTION_CORE_SHORT_CAP = 230
OPTION_WING_TAKE_SIZE = 6
OPTION_WING_POST_SIZE = 6
OPTION_WING_SHORT_CAP = 90

# Asymmetric edges — bias toward fading vol (sell options).
OPTION_BUY_EDGE = 1.45
OPTION_SELL_EDGE = 0.04
OPTION_POST_BUY_EDGE = 1.55
OPTION_POST_SELL_EDGE = 0.04

OPTION_SKEW_DIV = 42

SMILE_SYMMETRIC = True

FALLBACK_SMILE_A = 1.90
FALLBACK_SMILE_C = 0.017
FALLBACK_SIGMA = 0.017

DAY_LENGTH = 1_000_000.0
STARTING_TTE = 4.0
OPTION_ENTRY_CUTOFF = 850_000


def option_long_short_caps(strike: int) -> Tuple[int, int]:
    """Per-strike soft caps: emphasize core coupons and limit long wing exposure."""
    long_cap = OPTION_MAX_POSITION
    short_cap = OPTION_MAX_POSITION

    if strike in OPTION_CORE_STRIKES:
        short_cap = OPTION_CORE_SHORT_CAP

    if strike >= 5500:
        long_cap = OPTION_LONG_CAP_5500
        short_cap = min(short_cap, OPTION_WING_SHORT_CAP)
    elif strike >= 5400:
        long_cap = OPTION_LONG_CAP_5400
        short_cap = min(short_cap, OPTION_WING_SHORT_CAP)
    elif strike >= 5300:
        long_cap = min(long_cap, OPTION_LONG_CAP_5300)

    return long_cap, short_cap


def option_sizes(strike: int) -> Tuple[int, int]:
    """Return take/post sizes for each coupon strike."""
    if strike in OPTION_CORE_STRIKES:
        return OPTION_CORE_TAKE_SIZE, OPTION_CORE_POST_SIZE
    if strike >= 5400:
        return OPTION_WING_TAKE_SIZE, OPTION_WING_POST_SIZE
    return OPTION_TAKE_SIZE, OPTION_POST_SIZE


def option_edges(strike: int, eff_flow: float) -> Tuple[float, float, float, float]:
    """Strike-aware buy/sell and post edges.

    This variant is more willing to sell 5200/5300 coupons, but more cautious
    about buying high-strike wings.
    """
    buy_base = OPTION_BUY_EDGE
    sell_base = OPTION_SELL_EDGE
    post_buy = OPTION_POST_BUY_EDGE
    post_sell = OPTION_POST_SELL_EDGE

    if strike in OPTION_CORE_STRIKES:
        buy_base = max(buy_base, 1.45)
        sell_base = 0.02
        post_buy = max(post_buy, 1.65)
        post_sell = 0.02
    elif strike >= 5400:
        buy_base = max(buy_base, 1.95)
        sell_base = max(sell_base, 0.28)
        post_buy = max(post_buy, 2.05)
        post_sell = max(post_sell, 0.28)
    elif strike <= 4500:
        buy_base = max(buy_base, 1.15)
        sell_base = max(sell_base, 0.30)

    buy_edge = buy_base - max(0.0, eff_flow) * 0.20
    sell_edge = sell_base + min(0.0, eff_flow) * 0.20
    return max(0.4, buy_edge), max(0.05, sell_edge), post_buy, post_sell


# ── Black-Scholes helpers ─────────────────────────────────

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def bs_call_price(spot: float, strike: float, tte: float, sigma: float) -> float:
    if spot <= 0:
        return 0.0
    intrinsic = max(0.0, spot - strike)
    if tte <= 0 or sigma <= 0:
        return intrinsic
    try:
        sig_t = sigma * sqrt(tte)
        d1 = (log(spot / strike) + 0.5 * sigma * sigma * tte) / sig_t
        d2 = d1 - sig_t
        return spot * norm_cdf(d1) - strike * norm_cdf(d2)
    except Exception:
        return intrinsic


def bs_delta(spot: float, strike: float, tte: float, sigma: float) -> float:
    if spot <= 0:
        return 0.0
    if tte <= 0 or sigma <= 0:
        return 1.0 if spot > strike else 0.0
    try:
        sig_t = sigma * sqrt(tte)
        d1 = (log(spot / strike) + 0.5 * sigma * sigma * tte) / sig_t
        return norm_cdf(d1)
    except Exception:
        return 1.0 if spot > strike else 0.0


def implied_vol(target: float, spot: float, strike: float, tte: float) -> Optional[float]:
    intrinsic = max(0.0, spot - strike)
    if target <= intrinsic + 1e-6 or target >= spot:
        return None
    lo, hi = 1e-4, 2.0
    if bs_call_price(spot, strike, tte, hi) < target:
        return None
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if bs_call_price(spot, strike, tte, mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def fit_smile(
    xs: List[float], ys: List[float], symmetric: bool = False
) -> Optional[Tuple[float, float, float]]:
    n = len(xs)

    if symmetric:
        if n < 2:
            return None
        s2 = sum(x * x for x in xs)
        s4 = sum(x ** 4 for x in xs)
        t0 = sum(ys)
        t2 = sum(x * x * y for x, y in zip(xs, ys))
        det = s4 * float(n) - s2 * s2
        if abs(det) < 1e-12:
            return None
        a = (t2 * float(n) - t0 * s2) / det
        c = (s4 * t0 - s2 * t2) / det
        return a, 0.0, c

    if n < 3:
        return None
    s1 = sum(xs)
    s2 = sum(x * x for x in xs)
    s3 = sum(x ** 3 for x in xs)
    s4 = sum(x ** 4 for x in xs)
    t0 = sum(ys)
    t1 = sum(x * y for x, y in zip(xs, ys))
    t2 = sum(x * x * y for x, y in zip(xs, ys))
    M = [[s4, s3, s2], [s3, s2, s1], [s2, s1, float(n)]]
    rhs = [t2, t1, t0]

    def det3(A: List[List[float]]) -> float:
        return (
            A[0][0] * (A[1][1] * A[2][2] - A[1][2] * A[2][1])
            - A[0][1] * (A[1][0] * A[2][2] - A[1][2] * A[2][0])
            + A[0][2] * (A[1][0] * A[2][1] - A[1][1] * A[2][0])
        )

    D = det3(M)
    if abs(D) < 1e-12:
        return None
    out = []
    for j in range(3):
        Mj = [row[:] for row in M]
        for i in range(3):
            Mj[i][j] = rhs[i]
        out.append(det3(Mj) / D)
    return out[0], out[1], out[2]


class Trader:
    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}
        trader_data = self.load_trader_data(state.traderData)

        # ── HYDROGEL_PACK ─────────────────────────────────
        if TRADE_HYDROGEL:
            od = state.order_depths.get("HYDROGEL_PACK")
            if od is not None:
                pos = state.position.get("HYDROGEL_PACK", 0)
                result["HYDROGEL_PACK"] = self.trade_hydrogel(od, pos, trader_data)
        elif "HYDROGEL_PACK" in state.order_depths:
            result["HYDROGEL_PACK"] = []

        # Counterparty signal for underlying
        underlying_flow = self.counterparty_signal(state, UNDERLYING, trader_data)

        # ── VELVETFRUIT_EXTRACT (delta hedge from options) ──
        if TRADE_UNDERLYING:
            od = state.order_depths.get(UNDERLYING)
            if od is not None:
                pos = state.position.get(UNDERLYING, 0)

                hedge_offset = 0
                spot_for_delta = self.get_mid_price(od)
                if spot_for_delta is not None and spot_for_delta > 0:
                    tte_h = max(0.01, STARTING_TTE - state.timestamp / DAY_LENGTH)
                    net_d = 0.0
                    for strike in ACTIVE_STRIKES:
                        opos = state.position.get(f"VEV_{strike}", 0)
                        if opos != 0:
                            net_d += opos * bs_delta(
                                spot_for_delta, strike, tte_h, FALLBACK_SIGMA
                            )
                    hedge_offset = int(round(net_d))

                result[UNDERLYING] = self.trade_delta_one(
                    UNDERLYING,
                    od,
                    pos,
                    POSITION_LIMITS[UNDERLYING],
                    trader_data,
                    hedge_offset=hedge_offset,
                    flow_signal=underlying_flow,
                )
        elif UNDERLYING in state.order_depths:
            result[UNDERLYING] = []

        # ── Options with smile fit + counterparty flow overlay ────────────────────────
        if TRADE_OPTIONS:
            spot = self.get_mid_price(state.order_depths.get(UNDERLYING))
            if spot is not None and spot > 0:
                tte = max(0.01, STARTING_TTE - state.timestamp / DAY_LENGTH)
                sqrt_t = sqrt(tte)

                # Pass 1: invert IV from each strike's mid.
                xs: List[float] = []
                ys: List[float] = []
                for strike in ACTIVE_STRIKES:
                    od = state.order_depths.get(f"VEV_{strike}")
                    mid = self.get_mid_price(od)
                    if mid is None:
                        continue
                    iv = implied_vol(mid, spot, strike, tte)
                    if iv is None:
                        continue
                    xs.append(log(strike / spot) / sqrt_t)
                    ys.append(iv)

                fit = fit_smile(xs, ys, symmetric=SMILE_SYMMETRIC)
                opportunity_map = self.build_opportunity_map(state, spot, tte, fit, trader_data)

                # Pass 2: trade each strike against fitted IV.
                for strike in ACTIVE_STRIKES:
                    product = f"VEV_{strike}"
                    od = state.order_depths.get(product)
                    if od is None:
                        result[product] = []
                        continue

                    m = log(strike / spot) / sqrt_t
                    if fit is not None:
                        a, b, c = fit
                        sigma_use = a * m * m + b * m + c
                    else:
                        sigma_use = FALLBACK_SMILE_A * m * m + FALLBACK_SMILE_C
                    sigma_use = max(0.001, min(0.5, sigma_use))

                    pos = state.position.get(product, 0)
                    option_flow = self.counterparty_signal(state, product, trader_data)
                    result[product] = self.trade_option(
                        product,
                        strike,
                        od,
                        pos,
                        spot,
                        tte,
                        sigma_use,
                        state.timestamp,
                        option_flow,
                        opportunity_map.get(strike),
                    )

        for strike in ACTIVE_STRIKES:
            product = f"VEV_{strike}"
            if product in state.order_depths and product not in result:
                result[product] = []

        return result, 0, json.dumps(trader_data, separators=(",", ":"))

    # ─────────────────────────────────────────────────────
    def counterparty_signal(self, state: TradingState, product: str, trader_data: Dict) -> float:
        """
        Signal > 0 => follow-up bullish pressure from informed side.
        Signal < 0 => bearish pressure / anti-informed buy pressure.
        Uses priors + EMA smoothing in traderData.
        """
        market_trades = getattr(state, "market_trades", {}) or {}
        trades = market_trades.get(product, [])

        score_raw = 0.0
        qty_sum = 0.0
        for tr in trades:
            q = abs(getattr(tr, "quantity", 0) or 0)
            if q <= 0:
                continue
            b = getattr(tr, "buyer", None)
            s = getattr(tr, "seller", None)
            sb = weighted_trader_prior(b)
            ss = weighted_trader_prior(s)
            score_raw += q * (sb - ss)
            qty_sum += q

        instant = tanh(score_raw / max(25.0, qty_sum)) if qty_sum > 0 else 0.0

        flow_map = trader_data.get("flow_ema")
        if not isinstance(flow_map, dict):
            flow_map = {}
            trader_data["flow_ema"] = flow_map

        old = float(flow_map.get(product, 0.0))
        ema = (1.0 - FLOW_EMA_ALPHA) * old + FLOW_EMA_ALPHA * instant
        flow_map[product] = ema

        out = 0.65 * instant + 0.35 * ema
        if out > FLOW_CLIP:
            return FLOW_CLIP
        if out < -FLOW_CLIP:
            return -FLOW_CLIP
        return out

    # ─────────────────────────────────────────────────────
    def trade_hydrogel(self, od: OrderDepth, position: int, trader_data: Dict) -> List[Order]:
        orders: List[Order] = []
        best_bid = self.best_bid(od)
        best_ask = self.best_ask(od)
        if best_bid is None or best_ask is None:
            return orders

        buy_room = POSITION_LIMITS["HYDROGEL_PACK"] - position
        sell_room = POSITION_LIMITS["HYDROGEL_PACK"] + position

        mid = (best_bid + best_ask) / 2.0
        old_ema = trader_data.get(HG_MOM_KEY, mid)
        ema = (1.0 - HG_MOM_ALPHA) * old_ema + HG_MOM_ALPHA * mid
        trader_data[HG_MOM_KEY] = ema

        raw_momentum = mid - ema
        mom_shift = max(-HG_MOM_CAP, min(HG_MOM_CAP, HG_MOM_K * raw_momentum))
        fair = HG_FAIR + mom_shift

        buy_take_edge = HG_TAKE_EDGE - max(0.0, mom_shift) * HG_MOM_TAKE_BOOST
        sell_take_edge = HG_TAKE_EDGE + min(0.0, mom_shift) * HG_MOM_TAKE_BOOST
        buy_take_edge = max(12.0, buy_take_edge)
        sell_take_edge = max(12.0, sell_take_edge)

        if best_ask < fair - buy_take_edge and buy_room > 0:
            qty = min(HG_TAKE_SIZE, buy_room, abs(od.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", best_ask, qty))
                position += qty
                buy_room -= qty

        if best_bid > fair + sell_take_edge and sell_room > 0:
            qty = min(HG_TAKE_SIZE, sell_room, od.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", best_bid, -qty))
                position -= qty
                sell_room -= qty

        skew = self.signed_bucket(position, HG_SKEW_DIV)
        bid_px = floor(fair - HG_POST_EDGE - skew)
        ask_px = ceil(fair + HG_POST_EDGE - skew)

        if buy_room > 0 and bid_px < best_ask:
            qty = min(HG_POST_SIZE, buy_room)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", bid_px, qty))

        if sell_room > 0 and ask_px > best_bid:
            qty = min(HG_POST_SIZE, sell_room)
            if qty > 0:
                orders.append(Order("HYDROGEL_PACK", ask_px, -qty))

        return orders

    # ─────────────────────────────────────────────────────
    def trade_delta_one(
        self,
        product: str,
        od: OrderDepth,
        position: int,
        limit: int,
        trader_data: Dict,
        hedge_offset: int = 0,
        flow_signal: float = 0.0,
    ) -> List[Order]:
        """
        hedge_offset: net delta exposure from option positions.
        flow_signal: Round4 counterparty alpha overlay.
        """
        orders: List[Order] = []
        best_bid = self.best_bid(od)
        best_ask = self.best_ask(od)
        if best_bid is None or best_ask is None:
            return orders

        mid = (best_bid + best_ask) / 2.0
        ema_key = f"{product}_ema"
        old_ema = trader_data.get(ema_key, mid)
        ema = (1.0 - VE_EMA_ALPHA) * old_ema + VE_EMA_ALPHA * mid
        trader_data[ema_key] = ema

        anchor_used = self.effective_velvet_anchor(trader_data, mid)
        blended = VE_ANCHOR_WEIGHT * anchor_used + (1.0 - VE_ANCHOR_WEIGHT) * ema

        bid_vol = float(od.buy_orders[best_bid])
        ask_vol = float(abs(od.sell_orders[best_ask]))
        total = bid_vol + ask_vol

        if total > 0:
            imbalance = (bid_vol - ask_vol) / total
            shift = max(-VE_IMBALANCE_CAP, min(VE_IMBALANCE_CAP, VE_IMBALANCE_K * imbalance))
        else:
            shift = 0.0

        flow_shift = max(-3.0, min(3.0, VE_FLOW_SHIFT_K * flow_signal))
        fair = blended + shift + flow_shift

        buy_room = limit - position
        sell_room = limit + position

        # Slightly loosen crossing thresholds with strong directional flow.
        buy_edge = max(3.0, VE_EDGE - max(0.0, flow_shift))
        sell_edge = max(3.0, VE_EDGE + min(0.0, flow_shift))

        if best_ask < fair - buy_edge and buy_room > 0:
            qty = min(VE_SIZE, buy_room, abs(od.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_room -= qty

        if best_bid > fair + sell_edge and sell_room > 0:
            qty = min(VE_SIZE, sell_room, od.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                position -= qty
                sell_room -= qty

        synthetic_pos = position + hedge_offset
        skew = synthetic_pos // VE_SKEW_DIV
        bid_px = int(fair - VE_POST_EDGE - skew)
        ask_px = int(fair + VE_POST_EDGE - skew)

        if buy_room > 0 and bid_px < best_ask:
            qty = min(VE_POST_SIZE, buy_room)
            if qty > 0:
                orders.append(Order(product, bid_px, qty))

        if sell_room > 0 and ask_px > best_bid:
            qty = min(VE_POST_SIZE, sell_room)
            if qty > 0:
                orders.append(Order(product, ask_px, -qty))

        return orders

    # ─────────────────────────────────────────────────────
    def trade_option(
        self,
        product: str,
        strike: int,
        od: OrderDepth,
        position: int,
        spot: float,
        tte: float,
        sigma: float,
        timestamp: int,
        flow_signal: float,
        opportunity: Optional[Dict] = None,
    ) -> List[Order]:
        """Take + post against smile fair + counterparty overlay."""
        orders: List[Order] = []
        best_bid = self.best_bid(od)
        best_ask = self.best_ask(od)
        if best_bid is None or best_ask is None:
            return orders

        base_fair = bs_call_price(spot, strike, tte, sigma)

        # Dampen counterparty-flow impact on far OTM options (small delta -> weaker directional reliability).
        d = bs_delta(spot, strike, tte, max(0.01, sigma))
        flow_mult = max(0.25, min(1.0, d / 0.40))
        eff_flow = flow_signal * flow_mult
        fair = base_fair + max(-2.0, min(2.0, OPT_FLOW_SHIFT_K * eff_flow))

        long_cap, short_cap = option_long_short_caps(strike)
        if opportunity is not None:
            # Dynamic opportunity allocator can promote non-5200/5300 strikes
            # when relative value, moneyness, liquidity, and risk permit it.
            if opportunity.get("override_short_cap", False):
                short_cap = int(max(0, min(POSITION_LIMITS[product], opportunity.get("short_cap", short_cap))))
            else:
                short_cap = int(max(0, min(POSITION_LIMITS[product], max(short_cap, opportunity.get("short_cap", short_cap)))))
            if opportunity.get("override_long_cap", False):
                long_cap = int(max(0, min(POSITION_LIMITS[product], opportunity.get("long_cap", long_cap))))
            else:
                long_cap = int(max(0, min(POSITION_LIMITS[product], max(long_cap, opportunity.get("long_cap", long_cap)))))

        buy_room = min(
            POSITION_LIMITS[product] - position,
            long_cap - position,
        )
        sell_room = min(
            POSITION_LIMITS[product] + position,
            short_cap + position,
        )

        take_size, post_size = option_sizes(strike)
        if opportunity is not None:
            take_size = int(max(1, opportunity.get("take_size", take_size)))
            post_size = int(max(1, opportunity.get("post_size", post_size)))

        if timestamp >= OPTION_ENTRY_CUTOFF:
            if position > 0:
                qty = min(position, take_size, od.buy_orders[best_bid])
                if qty > 0:
                    orders.append(Order(product, best_bid, -qty))
            elif position < 0:
                qty = min(-position, take_size, abs(od.sell_orders[best_ask]))
                if qty > 0:
                    orders.append(Order(product, best_ask, qty))
            return orders

        buy_edge, sell_edge, post_buy_edge, post_sell_edge = option_edges(strike, eff_flow)
        if opportunity is not None:
            buy_edge = max(0.25, float(opportunity.get("buy_edge", buy_edge)))
            sell_edge = max(0.01, float(opportunity.get("sell_edge", sell_edge)))
            post_buy_edge = max(0.25, float(opportunity.get("post_buy_edge", post_buy_edge)))
            post_sell_edge = max(0.01, float(opportunity.get("post_sell_edge", post_sell_edge)))

        if best_ask < fair - buy_edge and buy_room > 0:
            qty = min(take_size, buy_room, abs(od.sell_orders[best_ask]))
            if qty > 0:
                orders.append(Order(product, best_ask, qty))
                position += qty
                buy_room -= qty

        if best_bid > fair + sell_edge and sell_room > 0:
            qty = min(take_size, sell_room, od.buy_orders[best_bid])
            if qty > 0:
                orders.append(Order(product, best_bid, -qty))
                position -= qty
                sell_room -= qty

        skew = position / OPTION_SKEW_DIV
        adj_fair = fair - skew

        if buy_room > 0:
            target_bid = floor(adj_fair - post_buy_edge)
            improve = best_bid + 1
            if improve < adj_fair - post_buy_edge and improve < best_ask:
                target_bid = improve
            if target_bid >= 0 and target_bid < best_ask:
                qty = min(post_size, buy_room)
                if qty > 0:
                    orders.append(Order(product, target_bid, qty))

        if sell_room > 0:
            target_ask = ceil(adj_fair + post_sell_edge)
            improve = best_ask - 1
            if improve > adj_fair + post_sell_edge and improve > best_bid:
                target_ask = improve
            if target_ask > best_bid:
                qty = min(post_size, sell_room)
                if qty > 0:
                    orders.append(Order(product, target_ask, -qty))

        return orders


    # ─────────────────────────────────────────────────────
    def _smile_sigma(self, strike: int, spot: float, tte: float, fit: Optional[Tuple[float, float, float]]) -> float:
        sqrt_t = sqrt(max(0.01, tte))
        m = log(strike / spot) / sqrt_t
        if fit is not None:
            a, b, c = fit
            sigma = a * m * m + b * m + c
        else:
            sigma = FALLBACK_SMILE_A * m * m + FALLBACK_SMILE_C
        return max(0.001, min(0.5, sigma))

    def _velvet_context(self, trader_data: Dict, mid: float) -> Dict[str, float]:
        """Slow online reference for relative logic.

        It learns, but slowly, so it cannot immediately destroy the proven
        visible-regime edge.
        """
        slow_key = "g7_ve_slow_ref"
        fast_key = "g7_ve_fast_ref"
        dev_key = "g7_ve_abs_dev"
        old_slow = float(trader_data.get(slow_key, mid))
        old_fast = float(trader_data.get(fast_key, mid))
        fast = 0.88 * old_fast + 0.12 * mid
        slow = 0.985 * old_slow + 0.015 * mid
        old_dev = float(trader_data.get(dev_key, 10.0))
        dev = 0.96 * old_dev + 0.04 * abs(mid - slow)
        trader_data[slow_key] = slow
        trader_data[fast_key] = fast
        trader_data[dev_key] = max(3.0, dev)
        z = (fast - slow) / max(3.0, dev)
        return {"fast": fast, "slow": slow, "dev": max(3.0, dev), "z": z}

    def effective_velvet_anchor(self, trader_data: Dict, mid: float) -> float:
        ctx = self._velvet_context(trader_data, mid)
        # Guarded anchor: keep the proven 5262 prior dominant, but slowly learn
        # if the market center persistently moves away from it.
        drift = abs(ctx["slow"] - VE_ANCHOR)
        if drift < 60:
            w = 0.10
        elif drift < 120:
            w = 0.22
        else:
            w = 0.35
        return (1.0 - w) * VE_ANCHOR + w * ctx["slow"]

    def _option_metrics(self, state: TradingState, spot: float, tte: float, fit: Optional[Tuple[float, float, float]]) -> Dict[int, Dict[str, float]]:
        out: Dict[int, Dict[str, float]] = {}
        for strike in ACTIVE_STRIKES:
            product = f"VEV_{strike}"
            od = state.order_depths.get(product)
            if od is None or not od.buy_orders or not od.sell_orders:
                continue
            best_bid = self.best_bid(od)
            best_ask = self.best_ask(od)
            if best_bid is None or best_ask is None:
                continue
            sigma = self._smile_sigma(strike, spot, tte, fit)
            fair = bs_call_price(spot, strike, tte, sigma)
            delta = bs_delta(spot, strike, tte, sigma)
            spread = max(1.0, float(best_ask - best_bid))
            bid_vol = float(od.buy_orders[best_bid])
            ask_vol = float(abs(od.sell_orders[best_ask]))
            liq = min(1.0, (bid_vol + ask_vol) / 60.0)
            log_m = abs(log(strike / max(1.0, spot)))
            near = max(0.0, 1.0 - log_m / 0.055)
            sell_edge = float(best_bid) - fair
            buy_edge = fair - float(best_ask)
            mid = 0.5 * (float(best_bid) + float(best_ask))
            out[strike] = {
                "mid": mid,
                "fair": fair,
                "sigma": sigma,
                "delta": delta,
                "spread": spread,
                "liq": liq,
                "near": near,
                "sell_edge": sell_edge,
                "buy_edge": buy_edge,
                "log_m": log_m,
            }
        return out



    # ─────────────────────────────────────────────────────

    def _update_strike_learning(self, trader_data: Dict, metrics: Dict[int, Dict[str, float]]) -> Dict[int, Dict[str, float]]:
        """Online strike-level learner using only past state and current mid.

        It is intentionally slow: 5200/5300 remain useful priors, but the model
        can promote other strikes if their own recent sell signals were followed
        by favorable mid-price movement.  This is not RL; it is a clipped EMA
        feedback overlay designed to avoid hard-coding absolute strikes.
        """
        store = trader_data.get("g9_strike_stats")
        if not isinstance(store, dict):
            store = {}
            trader_data["g9_strike_stats"] = store

        out: Dict[int, Dict[str, float]] = {}
        for strike, m in metrics.items():
            key = str(strike)
            s = store.get(key)
            if not isinstance(s, dict):
                s = {}
            prev_mid = s.get("prev_mid")
            prev_signal = float(s.get("prev_signal", 0.0))
            perf = 0.0
            if isinstance(prev_mid, (int, float)) and abs(prev_signal) > 0.05:
                # Positive signal means we preferred selling.  A later lower mid
                # is favorable; a higher mid is unfavorable.  Clip heavily.
                move = float(prev_mid) - float(m.get("mid", prev_mid))
                perf = max(-1.0, min(1.0, (move / 8.0) * (1.0 if prev_signal > 0 else -1.0)))
            old_perf = float(s.get("perf", 0.0))
            perf_ema = 0.965 * old_perf + 0.035 * perf

            raw_sell = float(m.get("sell_edge", 0.0))
            norm_scale = max(1.0, float(m.get("spread", 1.0)), 0.018 * max(10.0, float(m.get("fair", 10.0))))
            norm_sell = raw_sell / norm_scale
            signal = max(-1.0, min(1.0, norm_sell))

            base_prior = 0.24 if strike in (5200, 5300) else 0.0
            old_learned = float(s.get("learned_prior", base_prior))
            # Slow adaptive prior: reward confirmed strikes, but decay toward a
            # small visible-data prior for 5200/5300 only.
            target = base_prior + 0.42 * perf_ema + 0.13 * max(0.0, min(1.0, norm_sell))
            learned_prior = 0.985 * old_learned + 0.015 * max(-0.25, min(0.55, target))

            s["prev_mid"] = float(m.get("mid", 0.0))
            s["prev_signal"] = signal
            s["perf"] = perf_ema
            s["learned_prior"] = learned_prior
            store[key] = s
            out[strike] = {
                "perf": perf_ema,
                "prior": learned_prior,
                "norm_sell": norm_sell,
                "norm_scale": norm_scale,
            }
        return out

    def _portfolio_hedge_context(self, state: TradingState, metrics: Dict[int, Dict[str, float]]) -> Dict[str, float]:
        """Estimate option-book delta and remaining VELVET hedge capacity."""
        ve_pos = float(state.position.get(UNDERLYING, 0))
        net_delta = 0.0
        gross_short_delta = 0.0
        for strike, m in metrics.items():
            pos = float(state.position.get(f"VEV_{strike}", 0))
            d = float(m.get("delta", 0.0))
            net_delta += pos * d
            if pos < 0:
                gross_short_delta += -pos * d
        # Short call delta is negative in portfolio terms and needs long VELVET.
        hedge_needed = max(0.0, -net_delta)
        hedge_slack = max(0.0, float(POSITION_LIMITS[UNDERLYING]) - ve_pos)
        stress = hedge_needed / max(1.0, float(POSITION_LIMITS[UNDERLYING]))
        slack_ratio = hedge_slack / max(1.0, float(POSITION_LIMITS[UNDERLYING]))
        return {
            "ve_pos": ve_pos,
            "net_delta": net_delta,
            "gross_short_delta": gross_short_delta,
            "hedge_needed": hedge_needed,
            "hedge_slack": hedge_slack,
            "stress": stress,
            "slack_ratio": slack_ratio,
        }

    def build_opportunity_map(self, state: TradingState, spot: float, tte: float, fit: Optional[Tuple[float, float, float]], trader_data: Dict) -> Dict[int, Dict]:
        """Feedback rotator: more willing to promote non-core strikes when normalized edge and past strike feedback are strong.

        Core framework:
        - dynamic prior learning from strike-level feedback;
        - normalized edge instead of raw absolute edge;
        - portfolio delta hedge capacity;
        - rank-based dynamic cap interval with conservative max cap 230.
        """
        ctx = self._velvet_context(trader_data, spot)
        metrics = self._option_metrics(state, spot, tte, fit)
        learned = self._update_strike_learning(trader_data, metrics)
        hedge = self._portfolio_hedge_context(state, metrics)

        scored: List[Tuple[float, int]] = []
        vol_pen = min(1.25, ctx["dev"] / 42.0)
        uptrend_pen = max(0.0, ctx["z"] - 0.75) * 0.3
        downtrend_bonus = max(0.0, -ctx["z"] - 0.35) * 0.16

        for strike, m in metrics.items():
            l = learned.get(strike, {"prior": 0.0, "perf": 0.0, "norm_sell": 0.0})
            norm_sell = float(l.get("norm_sell", 0.0))
            # Stronger normalization: raw edge must be meaningful relative to
            # spread/fair, otherwise it receives little rank credit.
            normalized_edge_score = 1.35 * max(-0.5, min(1.8, norm_sell))
            perf_score = 0.42 * float(l.get("perf", 0.0))
            prior = float(l.get("prior", 0.0))
            # Optional exploration: if a non-5200/5300 strike is genuinely near
            # current spot and has positive normalized edge, let it compete.
            explore = 0.28 * max(0.0, float(m.get("near", 0.0)) - 0.55) * max(0.0, min(1.0, norm_sell))
            liq_score = 0.22 * float(m.get("liq", 0.0))
            near_score = 0.42 * float(m.get("near", 0.0))
            spread_pen = 0.08 * float(m.get("spread", 1.0))
            # Penalize wings unless they are genuinely near spot and rich.
            wing_pen = 0.0
            if strike >= 5400 and float(m.get("near", 0.0)) < 0.58:
                wing_pen += 0.55
            if strike <= 4500 and float(m.get("near", 0.0)) < 0.50:
                wing_pen += 0.35

            score = normalized_edge_score + near_score + liq_score + prior + perf_score + explore + downtrend_bonus - spread_pen - vol_pen - uptrend_pen - wing_pen
            scored.append((score, strike))

        scored.sort(reverse=True)
        opp: Dict[int, Dict] = {}
        for rank, (score, strike) in enumerate(scored[:4]):
            if score < -0.15:
                continue
            m = metrics[strike]
            l = learned.get(strike, {})
            stable = ctx["dev"] < 34 and abs(ctx["z"]) < 1.55
            very_strong = score > 1.15 and float(l.get("norm_sell", 0.0)) > 0.2
            strong = score > 0.45

            if rank == 0 and very_strong and stable:
                # Final balanced bucket: keep the proven allocator logic, but
                # avoid the 260/270-style concentration that may overfit visible days.
                cap = 230
                size = 22
                sell_edge = 0.018
            elif rank <= 1 and strong:
                cap = 221
                size = 21
                sell_edge = 0.030
            elif rank <= 2:
                cap = 164
                size = 13
                sell_edge = 0.12
            else:
                cap = 94
                size = 8
                sell_edge = 0.24

            # Conservative final upper bound: no dynamic bucket above 230.
            cap = min(230, max(80, cap))

            d = max(0.08, float(m.get("delta", 0.0)))
            current_short = max(0, -int(state.position.get(f"VEV_{strike}", 0)))
            if hedge["stress"] > 1.02 and hedge["hedge_slack"] < 12:
                cap = min(cap, max(current_short, 230))

            # Additional wing safety: wings can still become active, but only
            # with smaller cap unless moneyness and learned performance support it.
            if strike >= 5400 and float(m.get("near", 0.0)) < 0.62:
                cap = min(cap, 130)
                size = min(size, 10)
                sell_edge = max(sell_edge, 0.22)
            elif strike <= 4500 and float(m.get("near", 0.0)) < 0.55:
                cap = min(cap, 120)
                size = min(size, 10)
                sell_edge = max(sell_edge, 0.24)

            # If recent feedback is negative, do not let learned prior blindly
            # expand this strike.  This is the strike-level feedback brake.
            if float(l.get("perf", 0.0)) < -0.22:
                cap = min(cap, max(120, int(cap * 0.82)))
                sell_edge = max(sell_edge, 0.10)

            opp[strike] = {
                "rank": rank,
                "score": score,
                "short_cap": int(cap),
                "take_size": int(size),
                "post_size": int(size),
                "sell_edge": float(sell_edge),
                "post_sell_edge": float(sell_edge),
                "buy_edge": 1.70 if strike < 5400 else 2.15,
                "post_buy_edge": 1.85 if strike < 5400 else 2.30,
                "override_short_cap": True,
            }
        return opp

    # ─────────────────────────────────────────────────────
    def load_trader_data(self, raw: str) -> Dict:
        if not raw:
            return {}
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def best_bid(od: Optional[OrderDepth]) -> Optional[int]:
        if od is None or not od.buy_orders:
            return None
        return max(od.buy_orders)

    @staticmethod
    def best_ask(od: Optional[OrderDepth]) -> Optional[int]:
        if od is None or not od.sell_orders:
            return None
        return min(od.sell_orders)

    @staticmethod
    def get_mid_price(od: Optional[OrderDepth]) -> Optional[float]:
        if od is None:
            return None
        bb = max(od.buy_orders) if od.buy_orders else None
        ba = min(od.sell_orders) if od.sell_orders else None
        if bb is not None and ba is not None:
            return (bb + ba) / 2.0
        if bb is not None:
            return float(bb)
        if ba is not None:
            return float(ba)
        return None

    @staticmethod
    def signed_bucket(position: int, divisor: int) -> int:
        if divisor <= 0:
            return 0
        return int(position / divisor)