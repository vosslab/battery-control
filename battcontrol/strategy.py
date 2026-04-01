"""Pure policy functions for battery control strategy.

This module implements the STRATEGY.md flowchart without state management or I/O.
It takes a snapshot of current conditions and returns a policy decision.
"""

# Standard Library
import enum
import datetime
import logging

# local repo modules
import battcontrol.config

logger = logging.getLogger(__name__)


#============================================
class Action(enum.Enum):
	"""Controller policy actions.

	These represent controller intent, not hardware commands.
	Each action maps to an EP Cube mode and a SoC reserve rule:
	  CHARGE_FROM_SOLAR -> Self-consumption with high reserve (target SoC)
	  DISCHARGE_ENABLED -> Self-consumption with floor from price band
	  DISCHARGE_DISABLED -> Backup with max(current SoC, configured hold floor)
	"""
	CHARGE_FROM_SOLAR = "charge_from_solar"
	DISCHARGE_ENABLED = "discharge_enabled"
	DISCHARGE_DISABLED = "discharge_disabled"

# maps target_mode strings to human-readable EP Cube mode names for logging
TARGET_MODE_DISPLAY = {
	"self_consumption": "Self-consumption",
	"backup": "Backup",
}


#============================================
class DecisionResult:
	"""
	Result from the decision engine.

	Attributes:
		action: Controller policy action.
		reason: Human-readable explanation.
		soc_floor: Reserve SoC percentage for this decision.
		price_segment: Segment index from interpolation anchors (-1 = sentinel).
		target_mode: EP Cube mode ('self_consumption' or 'backup').
	"""

	#============================================
	def __init__(
		self,
		action: Action,
		reason: str,
		soc_floor: int = 0,
		price_segment: int = -1,
		target_mode: str = "",
	):
		"""
		Initialize a decision result.

		Args:
			action: Controller policy action.
			reason: Human-readable explanation.
			soc_floor: Reserve SoC percentage.
			price_segment: Segment index from get_price_segment_index().
			target_mode: EP Cube mode name.
		"""
		self.action = action
		self.reason = reason
		self.soc_floor = soc_floor
		self.price_segment = price_segment
		self.target_mode = target_mode

	#============================================
	def __repr__(self) -> str:
		mode_name = TARGET_MODE_DISPLAY.get(self.target_mode, self.target_mode)
		return (
			f"DecisionResult({self.action.value} | "
			f"Mode: {mode_name} | reserve {self.soc_floor}% | "
			f"{self.reason})"
		)


#============================================
def _is_solar_available(solar_power_watts: float, threshold: float = 50.0) -> bool:
	"""
	Check if meaningful solar power is available.

	Args:
		solar_power_watts: Current solar generation in watts.
		threshold: Minimum watts to consider solar available.

	Returns:
		bool: True if solar is available.
	"""
	return solar_power_watts > threshold


#============================================
def _compute_solar_surplus(solar_power_watts: float, load_power_watts: float) -> float:
	"""
	Estimate solar surplus (solar minus house load).

	Args:
		solar_power_watts: Current solar generation.
		load_power_watts: Current house load (from smartHomePower or backUpPower).

	Returns:
		float: Surplus in watts (positive means excess solar).
	"""
	return solar_power_watts - load_power_watts


#============================================
def _is_in_peak_window(current_time: datetime.datetime, config: dict) -> bool:
	"""
	Check if current time is within the peak arbitrage window.

	Args:
		current_time: Current datetime.
		config: Configuration dictionary.

	Returns:
		bool: True if in peak window.
	"""
	hour = current_time.hour
	start = config.get("peak_window_start", 16)
	end = config.get("peak_window_end", 22)
	return start <= hour < end


#============================================
def _daylight_logic(
	battery_soc: int,
	solar_power_watts: float,
	load_power_watts: float,
	comed_price_cents: float,
	season: str,
	config: dict,
) -> DecisionResult:
	"""
	Implement section B of STRATEGY.md: daylight logic.

	Args:
		battery_soc: Current SoC percentage.
		solar_power_watts: Current solar power in watts.
		load_power_watts: Current house load in watts.
		comed_price_cents: Current ComEd price in cents.
		season: 'summer', 'shoulder', or 'winter'.
		config: Configuration dictionary.

	Returns:
		DecisionResult: The daylight decision.
	"""
	surplus = _compute_solar_surplus(solar_power_watts, load_power_watts)
	afternoon_target = battcontrol.config.get_seasonal_value(
		config, "afternoon_target_soc_pct", season
	)
	extreme_threshold = config.get("extreme_price_threshold", 20)
	logger.info(
		"Daylight: surplus %.0fW (solar %.0fW - load %.0fW)",
		surplus, solar_power_watts, load_power_watts,
	)
	if surplus > 0:
		# section B.2: solar is excess
		if battery_soc < afternoon_target:
			# B.2a: below afternoon target, let solar charge
			logger.info(
				"Charging from solar: SoC %d%% below afternoon target %d%%",
				battery_soc, afternoon_target,
			)
			return DecisionResult(
				action=Action.CHARGE_FROM_SOLAR,
				reason=f"Solar surplus, SoC {battery_soc}% < target {afternoon_target}%",
				soc_floor=afternoon_target,
				target_mode="self_consumption",
			)
		# B.2b: at or above target, check headroom
		band_high = config.get("headroom_band_high", 95)
		band_low = config.get("headroom_band_low", 85)
		if battery_soc >= band_high and comed_price_cents >= extreme_threshold:
			# allow limited discharge to create headroom for more solar
			logger.info(
				"Creating headroom: SoC %d%% >= %d%%, price %.1fc extreme",
				battery_soc, band_high, comed_price_cents,
			)
			return DecisionResult(
				action=Action.DISCHARGE_ENABLED,
				reason=f"Creating headroom: SoC {battery_soc}% >= {band_high}%, extreme price",
				soc_floor=band_low,
				target_mode="self_consumption",
			)
		if battery_soc >= band_high and comed_price_cents < 0:
			# negative price: absorb solar into battery instead of exporting at a loss
			logger.info(
				"Negative price headroom: SoC %d%% >= %d%%, price %.1fc negative",
				battery_soc, band_high, comed_price_cents,
			)
			return DecisionResult(
				action=Action.DISCHARGE_ENABLED,
				reason=f"Negative price headroom: SoC {battery_soc}% >= {band_high}%, price {comed_price_cents:.1f}c",
				soc_floor=band_low,
				target_mode="self_consumption",
			)
		# not exporting or price is cheap, hold at target
		logger.info(
			"At target: SoC %d%% >= target %d%%, price %.1fc not extreme",
			battery_soc, afternoon_target, comed_price_cents,
		)
		return DecisionResult(
			action=Action.CHARGE_FROM_SOLAR,
			reason=f"Solar surplus, SoC {battery_soc}% >= target, holding",
			soc_floor=afternoon_target,
			target_mode="self_consumption",
		)
	# section B.3: no solar surplus
	if comed_price_cents >= extreme_threshold:
		# B.3a: extreme price override
		extreme_floor = battcontrol.config.get_seasonal_value(
			config, "hard_reserve_pct", season
		)
		logger.info(
			"Extreme price override: %.1fc >= %dc, discharging to floor %d%%",
			comed_price_cents, extreme_threshold, extreme_floor,
		)
		return DecisionResult(
			action=Action.DISCHARGE_ENABLED,
			reason=(f"No surplus, extreme price {comed_price_cents:.1f}c >= "
				f"{extreme_threshold}c"),
			soc_floor=extreme_floor,
			price_segment=-1,
			target_mode="self_consumption",
		)
	# B.3b: self-consumption at current SoC -- no grid charging, captures solar when surplus appears
	logger.info(
		"Self-consumption hold: no surplus, price %.1fc below extreme %dc, reserve %d%%",
		comed_price_cents, extreme_threshold, battery_soc,
	)
	return DecisionResult(
		action=Action.DISCHARGE_DISABLED,
		reason=(f"No surplus, price {comed_price_cents:.1f}c not extreme, "
			f"self-consumption hold at {battery_soc}%"),
		soc_floor=battery_soc,
		target_mode="self_consumption",
	)


#============================================
def _night_logic(
	battery_soc: int,
	comed_price_cents: float,
	season: str,
	current_time: datetime.datetime,
	config: dict,
) -> DecisionResult:
	"""
	Implement section D of STRATEGY.md: night logic.

	Args:
		battery_soc: Current SoC percentage.
		comed_price_cents: Current ComEd price in cents.
		season: 'summer', 'shoulder', or 'winter'.
		current_time: Current datetime.
		config: Configuration dictionary.

	Returns:
		DecisionResult: The night decision.
	"""
	extreme_threshold = config.get("extreme_price_threshold", 20)
	night_floor = battcontrol.config.get_seasonal_value(
		config, "night_floor_pct", season
	)
	# D.2: discharge only if extreme price and above night floor
	if comed_price_cents >= extreme_threshold and battery_soc > night_floor:
		logger.info(
			"Night extreme: price %.1fc >= %dc, SoC %d%% > floor %d%%, discharging",
			comed_price_cents, extreme_threshold, battery_soc, night_floor,
		)
		return DecisionResult(
			action=Action.DISCHARGE_ENABLED,
			reason=(f"Night extreme price {comed_price_cents:.1f}c, discharging to "
				f"floor {night_floor}%"),
			soc_floor=night_floor,
			price_segment=-1,
			target_mode="self_consumption",
		)
	# otherwise hold
	logger.info(
		"Night hold: price %.1fc vs extreme %dc, SoC %d%% vs floor %d%%",
		comed_price_cents, extreme_threshold, battery_soc, night_floor,
	)
	return DecisionResult(
		action=Action.DISCHARGE_DISABLED,
		reason=f"Night hold: price {comed_price_cents:.1f}c, SoC {battery_soc}%",
		soc_floor=night_floor,
		target_mode="backup",
	)


#============================================
def _peak_logic(
	battery_soc: int,
	comed_price_cents: float,
	season: str,
	current_time: datetime.datetime,
	config: dict,
) -> DecisionResult:
	"""
	Implement section E of STRATEGY.md: peak logic (evening arbitrage).

	Args:
		battery_soc: Current SoC percentage.
		comed_price_cents: Current ComEd price in cents.
		season: 'summer', 'shoulder', or 'winter'.
		current_time: Current datetime.
		config: Configuration dictionary.

	Returns:
		DecisionResult: The peak decision.
	"""
	# E.2: interpolate SoC floor from price anchors
	soc_floor = battcontrol.config.get_price_floor(config, season, comed_price_cents)
	segment_idx = battcontrol.config.get_price_segment_index(
		config, season, comed_price_cents
	)
	bounds = battcontrol.config.get_price_segment_bounds(
		config, season, comed_price_cents
	)
	# format segment bounds for logging
	lo_str = f"{bounds[0]:.1f}" if bounds[0] is not None else "<min"
	hi_str = f"{bounds[1]:.1f}" if bounds[1] is not None else ">max"
	logger.info(
		"Peak: price %.1fc in [%s, %s]c -> floor %d%%",
		comed_price_cents, lo_str, hi_str, soc_floor,
	)
	# E.4: discharge decision
	if battery_soc <= soc_floor:
		# at or below floor, hold
		logger.info(
			"At floor: SoC %d%% <= %d%%, holding",
			battery_soc, soc_floor,
		)
		return DecisionResult(
			action=Action.DISCHARGE_DISABLED,
			reason=(f"Peak: SoC {battery_soc}% <= floor {soc_floor}% "
				f"(price {comed_price_cents:.1f}c)"),
			soc_floor=soc_floor,
			price_segment=segment_idx,
			target_mode="backup",
		)
	# above floor: discharge enabled
	peak_end = config.get("peak_window_end", 22)
	remaining_hours = max(peak_end - current_time.hour, 1)
	usable_pct = max(battery_soc - soc_floor, 0)
	capacity = config.get("battery_capacity_kwh", 20.0)
	usable_kwh = capacity * usable_pct / 100.0
	logger.info(
		"Discharge enabled: price %.1fc, "
		"SoC %d%% above %d%% floor, %.1f kWh usable over %d hrs",
		comed_price_cents,
		battery_soc, soc_floor, usable_kwh, remaining_hours,
	)
	return DecisionResult(
		action=Action.DISCHARGE_ENABLED,
		reason=(f"Peak: SoC {battery_soc}% above "
			f"{soc_floor}% floor, discharge enabled (price {comed_price_cents:.1f}c)"),
		soc_floor=soc_floor,
		price_segment=segment_idx,
		target_mode="self_consumption",
	)


#============================================
def evaluate(
	battery_soc: int,
	solar_power_watts: float,
	load_power_watts: float,
	comed_price_cents: float,
	comed_median_cents: float,
	current_time: datetime.datetime,
	config: dict,
) -> DecisionResult:
	"""
	Pure policy evaluation function. No state mutation, no I/O, no side effects.

	This is the core routing function implementing the STRATEGY.md flowchart.
	It takes a snapshot and returns the policy decision without caring about
	historical state or cadence.

	Args:
		battery_soc: Current battery state of charge percentage.
		solar_power_watts: Current solar generation in watts.
		load_power_watts: Current house load in watts (from smartHomePower).
		comed_price_cents: Current ComEd price in cents.
		comed_median_cents: 24-hour median ComEd price in cents (unused but kept
			for replay compatibility).
		current_time: Current datetime.
		config: Configuration dictionary.

	Returns:
		DecisionResult: The battery control decision.
	"""
	# determine season
	season = battcontrol.config.get_season(config, current_time)
	# section A: guards
	hard_reserve = battcontrol.config.get_seasonal_value(
		config, "hard_reserve_pct", season
	)
	# log key inputs for reasoning trace
	logger.info(
		"Inputs: SoC %d%% | Price %.1fc | Solar %.0fW | Load %.0fW | Hour %d | "
		"Season %s",
		battery_soc, comed_price_cents, solar_power_watts, load_power_watts,
		current_time.hour, season,
	)
	# A.1: hard reserve check
	if battery_soc <= hard_reserve:
		reason = f"Hard reserve: SoC {battery_soc}% <= {hard_reserve}%"
		logger.info("Guard: %s", reason)
		result = DecisionResult(
			action=Action.DISCHARGE_DISABLED,
			reason=reason,
			soc_floor=hard_reserve,
			target_mode="backup",
		)
		logger.info("Decision: %s", result)
		return result
	logger.info("Guard: SoC %d%% above hard reserve %d%%", battery_soc, hard_reserve)
	# A.2/A.3: solar availability check
	solar_threshold = config.get("solar_sunset_threshold_watts", 50)
	solar_available = _is_solar_available(solar_power_watts, solar_threshold)
	solar_tag = "yes" if solar_available else "no"
	logger.info(
		"Solar available: %s (%.0fW, threshold %dW)",
		solar_tag, solar_power_watts, solar_threshold,
	)
	if not solar_available:
		# no solar: night logic or peak logic
		# check if in peak window
		if _is_in_peak_window(current_time, config):
			logger.info("Entering peak logic")
			result = _peak_logic(
				battery_soc, comed_price_cents, season, current_time, config
			)
		else:
			logger.info("Entering night logic")
			result = _night_logic(
				battery_soc, comed_price_cents, season, current_time, config
			)
		logger.info("Decision: %s", result)
		return result
	# solar is available
	# Section C: solar available routing. Time of day takes priority over solar
	# fading, so check peak window first.
	if _is_in_peak_window(current_time, config):
		logger.info("Solar available but in peak window, using peak logic")
		result = _peak_logic(
			battery_soc, comed_price_cents, season, current_time, config
		)
		logger.info("Decision: %s", result)
		return result
	# section B: daylight logic
	logger.info("Entering daylight logic")
	result = _daylight_logic(
		battery_soc, solar_power_watts, load_power_watts,
		comed_price_cents, season, config
	)
	logger.info("Decision: %s", result)
	return result
