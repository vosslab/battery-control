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
def _daylight_logic(
	battery_soc: int,
	solar_power_watts: float,
	load_power_watts: float,
	comed_price_cents: float,
	comed_cutoff_cents: float,
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
		comed_cutoff_cents: Reasonable cutoff price from comedlib.
		season: 'summer', 'shoulder', or 'winter'.
		config: Configuration dictionary.

	Returns:
		DecisionResult: The daylight decision.
	"""
	surplus = _compute_solar_surplus(solar_power_watts, load_power_watts)
	logger.info(
		"Daylight: surplus %.0fW (solar %.0fW - load %.0fW)",
		surplus, solar_power_watts, load_power_watts,
	)
	if surplus > 0:
		# section B.2: solar is excess
		# B.2x: if price is above the comedlib cutoff, export surplus to grid
		# rather than charging battery. Use price-to-SoC anchors for the
		# discharge floor so the battery is ready if load spikes past solar.
		if comed_price_cents > comed_cutoff_cents:
			price_floor = battcontrol.config.get_price_floor(
				config, season, comed_price_cents
			)
			segment_idx = battcontrol.config.get_price_segment_index(
				config, season, comed_price_cents
			)
			logger.info(
				"Price %.1fc above cutoff %.1fc during surplus, "
				"exporting to grid, floor %d%%",
				comed_price_cents, comed_cutoff_cents, price_floor,
			)
			return DecisionResult(
				action=Action.DISCHARGE_ENABLED,
				reason=(f"Price {comed_price_cents:.1f}c > cutoff "
					f"{comed_cutoff_cents:.1f}c, exporting surplus, "
					f"floor {price_floor}%"),
				soc_floor=price_floor,
				price_segment=segment_idx,
				target_mode="self_consumption",
			)
		if battery_soc < 100:
			# B.2a: not full, let solar charge to 100%
			logger.info(
				"Charging from solar: SoC %d%% below 100%%",
				battery_soc,
			)
			return DecisionResult(
				action=Action.CHARGE_FROM_SOLAR,
				reason=f"Solar surplus, SoC {battery_soc}% < 100%, charging",
				soc_floor=100,
				target_mode="self_consumption",
			)
		# B.2b: at or above target, check headroom
		band_high = config.get("headroom_band_high", 95)
		band_low = config.get("headroom_band_low", 85)
		if battery_soc >= band_high and comed_price_cents > comed_cutoff_cents:
			# allow limited discharge to create headroom for more solar
			headroom_floor = battcontrol.config.get_price_floor(
				config, season, comed_price_cents
			)
			logger.info(
				"Creating headroom: SoC %d%% >= %d%%, price %.1fc > cutoff %.1fc, floor %d%%",
				battery_soc, band_high, comed_price_cents, comed_cutoff_cents, headroom_floor,
			)
			return DecisionResult(
				action=Action.DISCHARGE_ENABLED,
				reason=(f"Creating headroom: SoC {battery_soc}% >= {band_high}%, "
					f"price {comed_price_cents:.1f}c > cutoff {comed_cutoff_cents:.1f}c"),
				soc_floor=headroom_floor,
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
		# not exporting or price is cheap, hold at 100%
		logger.info(
			"Full: SoC %d%%, price %.1fc <= cutoff %.1fc, holding",
			battery_soc, comed_price_cents, comed_cutoff_cents,
		)
		return DecisionResult(
			action=Action.CHARGE_FROM_SOLAR,
			reason=f"Solar surplus, SoC {battery_soc}% full, holding",
			soc_floor=100,
			target_mode="self_consumption",
		)
	# section B.3: no solar surplus
	if comed_price_cents > comed_cutoff_cents:
		# B.3a: price above cutoff, discharge with interpolated floor
		price_floor = battcontrol.config.get_price_floor(
			config, season, comed_price_cents
		)
		segment_idx = battcontrol.config.get_price_segment_index(
			config, season, comed_price_cents
		)
		logger.info(
			"No surplus, price %.1fc > cutoff %.1fc, discharging to floor %d%%",
			comed_price_cents, comed_cutoff_cents, price_floor,
		)
		return DecisionResult(
			action=Action.DISCHARGE_ENABLED,
			reason=(f"No surplus, price {comed_price_cents:.1f}c > "
				f"cutoff {comed_cutoff_cents:.1f}c"),
			soc_floor=price_floor,
			price_segment=segment_idx,
			target_mode="self_consumption",
		)
	# B.3b: self-consumption at current SoC -- no grid charging, captures solar when surplus appears
	logger.info(
		"Self-consumption hold: no surplus, price %.1fc <= cutoff %.1fc, reserve %d%%",
		comed_price_cents, comed_cutoff_cents, battery_soc,
	)
	return DecisionResult(
		action=Action.DISCHARGE_DISABLED,
		reason=(f"No surplus, price {comed_price_cents:.1f}c <= "
			f"cutoff {comed_cutoff_cents:.1f}c, hold at {battery_soc}%"),
		soc_floor=battery_soc,
		target_mode="self_consumption",
	)


#============================================
def _night_logic(
	battery_soc: int,
	comed_price_cents: float,
	comed_cutoff_cents: float,
	season: str,
	current_time: datetime.datetime,
	config: dict,
) -> DecisionResult:
	"""
	Implement section D of STRATEGY.md: night logic.

	Args:
		battery_soc: Current SoC percentage.
		comed_price_cents: Current ComEd price in cents.
		comed_cutoff_cents: Reasonable cutoff price from comedlib.
		season: 'summer', 'shoulder', or 'winter'.
		current_time: Current datetime.
		config: Configuration dictionary.

	Returns:
		DecisionResult: The night decision.
	"""
	night_floor = battcontrol.config.get_seasonal_value(
		config, "night_floor_pct", season
	)
	# D.2: discharge only if price above cutoff and above night floor
	if comed_price_cents > comed_cutoff_cents and battery_soc > night_floor:
		# use price anchors but never go below night floor
		price_floor = max(
			battcontrol.config.get_price_floor(config, season, comed_price_cents),
			night_floor,
		)
		segment_idx = battcontrol.config.get_price_segment_index(
			config, season, comed_price_cents
		)
		logger.info(
			"Night discharge: price %.1fc > cutoff %.1fc, SoC %d%% > floor %d%%",
			comed_price_cents, comed_cutoff_cents, battery_soc, price_floor,
		)
		return DecisionResult(
			action=Action.DISCHARGE_ENABLED,
			reason=(f"Night price {comed_price_cents:.1f}c > "
				f"cutoff {comed_cutoff_cents:.1f}c, floor {price_floor}%"),
			soc_floor=price_floor,
			price_segment=segment_idx,
			target_mode="self_consumption",
		)
	# otherwise hold
	logger.info(
		"Night hold: price %.1fc vs cutoff %.1fc, SoC %d%% vs floor %d%%",
		comed_price_cents, comed_cutoff_cents, battery_soc, night_floor,
	)
	return DecisionResult(
		action=Action.DISCHARGE_DISABLED,
		reason=f"Night hold: price {comed_price_cents:.1f}c, SoC {battery_soc}%",
		soc_floor=night_floor,
		target_mode="backup",
	)



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
		comed_cutoff_cents: Reasonable cutoff price from comedlib. Prices above
			this indicate conserve mode (export surplus); below means consume
			(charge battery).
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
		"Inputs: SoC %d%% | Price %.1fc | Cutoff %.1fc | Solar %.0fW | Load %.0fW "
		"| Hour %d | Season %s",
		battery_soc, comed_price_cents, comed_cutoff_cents, solar_power_watts,
		load_power_watts, current_time.hour, season,
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
		# no solar: night logic (price vs cutoff gates discharge)
		logger.info("Entering night logic")
		result = _night_logic(
			battery_soc, comed_price_cents, comed_cutoff_cents,
			season, current_time, config
		)
		logger.info("Decision: %s", result)
		return result
	# solar is available: daylight logic (price vs cutoff gates discharge)
	logger.info("Entering daylight logic")
	result = _daylight_logic(
		battery_soc, solar_power_watts, load_power_watts,
		comed_price_cents, comed_cutoff_cents, season, config
	)
	logger.info("Decision: %s", result)
	return result
