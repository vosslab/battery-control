"""Pure policy functions for battery control strategy.

This module implements a price-first policy: the primary decision axis is
whether the current price is above or below the comedlib cutoff. Solar and
load determine physical outcomes under that policy but do not change the
policy itself.
"""

# Standard Library
import enum
import datetime
import logging

# local repo modules
import battcontrol.config

logger = logging.getLogger(__name__)


#============================================
class StrategyState(enum.Enum):
	"""Economic regime for the control interval.

	The controller sets a stable battery policy based on price vs cutoff.
	The inverter handles solar/load transitions within that policy.
	"""
	BELOW_CUTOFF = "below_cutoff"
	ABOVE_CUTOFF = "above_cutoff"


#============================================
class DecisionResult:
	"""
	Result from the decision engine.

	Attributes:
		state: Economic regime (below or above cutoff).
		reason: Human-readable explanation.
		soc_floor: Reserve SoC percentage for this decision.
		target_mode: EP Cube mode (always 'self_consumption' for now).
	"""

	#============================================
	def __init__(
		self,
		state: StrategyState,
		reason: str,
		soc_floor: int = 0,
		target_mode: str = "self_consumption",
	):
		"""
		Initialize a decision result.

		Args:
			state: Economic regime.
			reason: Human-readable explanation.
			soc_floor: Reserve SoC percentage.
			target_mode: EP Cube mode name.
		"""
		self.state = state
		self.reason = reason
		self.soc_floor = soc_floor
		self.target_mode = target_mode

	#============================================
	def __repr__(self) -> str:
		return (
			f"DecisionResult({self.state.value} | "
			f"reserve {self.soc_floor}% | "
			f"{self.reason})"
		)


#============================================
def _determine_state(
	comed_price_cents: float,
	comed_cutoff_cents: float,
	cutoff_buffer: float,
	previous_state: StrategyState,
) -> StrategyState:
	"""
	Determine economic state with deadband around the cutoff.

	Prevents chattering when price oscillates near the cutoff boundary.
	The command buffer protects the output; this protects the decision
	boundary itself.

	Args:
		comed_price_cents: Current ComEd price in cents.
		comed_cutoff_cents: Cutoff price from comedlib.
		cutoff_buffer: Half-width of the deadband in cents.
		previous_state: Last strategy state (None on startup).

	Returns:
		StrategyState: The economic regime for this interval.
	"""
	if comed_price_cents <= comed_cutoff_cents - cutoff_buffer:
		return StrategyState.BELOW_CUTOFF
	if comed_price_cents >= comed_cutoff_cents + cutoff_buffer:
		return StrategyState.ABOVE_CUTOFF
	# in the deadband: keep previous state, or fall through to raw comparison
	if previous_state is not None:
		logger.info(
			"Deadband: price %.1fc within %.1fc of cutoff %.1fc, keeping %s",
			comed_price_cents, cutoff_buffer, comed_cutoff_cents,
			previous_state.value,
		)
		return previous_state
	# no previous state (startup): raw comparison
	if comed_price_cents <= comed_cutoff_cents:
		return StrategyState.BELOW_CUTOFF
	return StrategyState.ABOVE_CUTOFF


#============================================
def evaluate(
	battery_soc: int,
	solar_power_watts: float,
	load_power_watts: float,
	comed_price_cents: float,
	comed_median_cents: float,
	comed_cutoff_cents: float,
	current_time: datetime.datetime,
	config: dict,
	previous_state: StrategyState = None,
) -> DecisionResult:
	"""
	Pure policy evaluation function. No state mutation, no I/O.

	Primary decision axis: price vs cutoff (economic regime).
	Solar and load determine physical outcomes but do not change the policy.

	Args:
		battery_soc: Current battery state of charge percentage.
		solar_power_watts: Current solar generation in watts.
		load_power_watts: Current house load in watts.
		comed_price_cents: Current ComEd price in cents.
		comed_median_cents: 24-hour median ComEd price (unused, kept for
			replay compatibility).
		comed_cutoff_cents: Reasonable cutoff price from comedlib.
		current_time: Current datetime.
		config: Configuration dictionary.
		previous_state: Last strategy state for deadband (None on startup).

	Returns:
		DecisionResult: The battery control decision.
	"""
	# determine season
	season = battcontrol.config.get_season(config, current_time)
	hard_reserve = battcontrol.config.get_seasonal_value(
		config, "hard_reserve_pct", season
	)
	# log key inputs for reasoning trace
	logger.info(
		"Inputs: SoC %d%% | Price %.1fc | Cutoff %.1fc | Solar %.0fW | Load %.0fW "
		"| Hour %d | Season %s",
		battery_soc, comed_price_cents, comed_cutoff_cents, solar_power_watts,
		load_power_watts, current_time.hour, season,
	)
	# guard: hard reserve check
	if battery_soc <= hard_reserve:
		reason = f"Hard reserve: SoC {battery_soc}% <= {hard_reserve}%"
		logger.info("Guard: %s", reason)
		result = DecisionResult(
			state=StrategyState.BELOW_CUTOFF,
			reason=reason,
			soc_floor=hard_reserve,
		)
		logger.info("Decision: %s", result)
		return result
	logger.info("Guard: SoC %d%% above hard reserve %d%%", battery_soc, hard_reserve)
	# determine economic state with deadband
	cutoff_buffer = config.get("cutoff_buffer_cents", 0.5)
	state = _determine_state(
		comed_price_cents, comed_cutoff_cents, cutoff_buffer, previous_state,
	)
	logger.info("State: %s (price %.1fc, cutoff %.1fc)", state.value, comed_price_cents, comed_cutoff_cents)
	# below cutoff: cheap grid, do not spend battery
	if state == StrategyState.BELOW_CUTOFF:
		# headroom exception: near-full battery with negative price
		# discharge a bit to absorb solar instead of exporting at a loss
		band_high = config.get("headroom_band_high", 95)
		band_low = config.get("headroom_band_low", 85)
		if battery_soc >= band_high and comed_price_cents < 0:
			logger.info(
				"Negative price headroom: SoC %d%% >= %d%%, price %.1fc negative",
				battery_soc, band_high, comed_price_cents,
			)
			result = DecisionResult(
				state=StrategyState.BELOW_CUTOFF,
				reason=(f"Negative price headroom: SoC {battery_soc}% >= "
					f"{band_high}%, price {comed_price_cents:.1f}c"),
				soc_floor=band_low,
			)
			logger.info("Decision: %s", result)
			return result
		# normal below-cutoff: reserve 100%, battery holds
		reason = (f"Below cutoff: price {comed_price_cents:.1f}c <= "
			f"cutoff {comed_cutoff_cents:.1f}c, reserve 100%")
		logger.info(reason)
		result = DecisionResult(
			state=StrategyState.BELOW_CUTOFF,
			reason=reason,
			soc_floor=100,
		)
		logger.info("Decision: %s", result)
		return result
	# above cutoff: expensive grid, allow battery use
	base_price_floor = battcontrol.config.get_price_floor(
		config, season, comed_price_cents
	)
	# time-period reserve adjustment
	hour = current_time.hour
	time_adjust = config.get("time_adjust_soc_pct", 5)
	evening_start = config.get("evening_adjust_start_hour", 13)
	evening_end = config.get("evening_adjust_end_hour", 23)
	morning_start = config.get("morning_adjust_start_hour", 2)
	morning_end = config.get("morning_adjust_end_hour", 10)
	adjust = 0
	period_label = ""
	if evening_start <= hour <= evening_end:
		# preserve more battery for later expensive load
		adjust = time_adjust
		period_label = f", evening +{time_adjust}%"
	elif morning_start <= hour <= morning_end:
		# allow more battery use now because solar is likely coming
		adjust = -time_adjust
		period_label = f", morning -{time_adjust}%"
	final_floor = max(0, min(100, base_price_floor + adjust))
	reason = (f"Above cutoff: price {comed_price_cents:.1f}c >= "
		f"cutoff {comed_cutoff_cents:.1f}c, base floor {base_price_floor}%"
		f"{period_label}, reserve {final_floor}%")
	logger.info(reason)
	result = DecisionResult(
		state=StrategyState.ABOVE_CUTOFF,
		reason=reason,
		soc_floor=final_floor,
	)
	logger.info("Decision: %s", result)
	return result
