"""Decision engine implementing the STRATEGY.md flowchart for battery control."""

# Standard Library
import enum
import datetime
import logging

# local repo modules
import battcontrol.config as config_mod
import battcontrol.state as state_mod

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

# maps each action to its EP Cube mode name for logging
ACTION_MODE_MAP = {
	Action.CHARGE_FROM_SOLAR: "Self-consumption",
	Action.DISCHARGE_ENABLED: "Self-consumption",
	Action.DISCHARGE_DISABLED: "Backup",
}


#============================================
class DecisionResult:
	"""
	Result from the decision engine.

	Attributes:
		action: Controller policy action.
		reason: Human-readable explanation.
		soc_floor: Reserve SoC percentage for this decision.
		price_band: Current price band name (if applicable).
		target_mode: EP Cube mode ('self_consumption' or 'backup').
	"""

	#============================================
	def __init__(
		self,
		action: Action,
		reason: str,
		soc_floor: int = 0,
		price_band: str = "",
		target_mode: str = "",
	):
		"""
		Initialize a decision result.

		Args:
			action: Controller policy action.
			reason: Human-readable explanation.
			soc_floor: Reserve SoC percentage.
			price_band: Current price band name.
			target_mode: EP Cube mode name.
		"""
		self.action = action
		self.reason = reason
		self.soc_floor = soc_floor
		self.price_band = price_band
		self.target_mode = target_mode

	#============================================
	def __repr__(self) -> str:
		mode_name = ACTION_MODE_MAP.get(self.action, "?")
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
def _should_transition_to_peak(
	current_time: datetime.datetime,
	solar_power_watts: float,
	control_state: state_mod.ControlState,
	config: dict,
) -> bool:
	"""
	Determine if we should transition from daylight to peak logic.

	Transition triggers (section C of STRATEGY.md):
	- Local time >= peak_window_start
	- Solar power below threshold for solar_sunset_duration_minutes

	Args:
		current_time: Current datetime.
		solar_power_watts: Current solar power.
		control_state: Current control state.
		config: Configuration dictionary.

	Returns:
		bool: True if should transition to peak logic.
	"""
	# time-based trigger
	if current_time.hour >= config.get("peak_window_start", 16):
		return True
	# solar fade trigger
	threshold = config.get("solar_sunset_threshold_watts", 50)
	duration_minutes = config.get("solar_sunset_duration_minutes", 20)
	if solar_power_watts > threshold:
		# solar is still strong, update timestamp
		control_state.last_solar_above_threshold_at = current_time.isoformat()
		return False
	# solar is below threshold, check how long
	last_above = control_state.last_solar_above_threshold_at
	if last_above is None:
		# never recorded solar above threshold, treat as night
		return True
	last_above_dt = datetime.datetime.fromisoformat(last_above)
	elapsed_minutes = (current_time - last_above_dt).total_seconds() / 60.0
	if elapsed_minutes >= duration_minutes:
		return True
	return False


#============================================
def _compute_pacing(
	battery_soc: int,
	soc_floor: int,
	current_time: datetime.datetime,
	config: dict,
) -> float:
	"""
	Compute pacing guideline for floor selection (internal heuristic only).

	This value is used to inform floor choice, not to control discharge rate.
	The EP Cube does not support rate limiting.

	Args:
		battery_soc: Current battery state of charge percentage.
		soc_floor: Target SoC floor percentage.
		current_time: Current datetime.
		config: Configuration dictionary.

	Returns:
		float: Estimated kWh available per remaining hour.
	"""
	capacity = config.get("battery_capacity_kwh", 20.0)
	peak_end = config.get("peak_window_end", 22)
	# compute usable energy above floor
	usable_pct = max(battery_soc - soc_floor, 0)
	usable_kwh = capacity * usable_pct / 100.0
	# compute remaining peak hours
	remaining_hours = peak_end - current_time.hour
	if remaining_hours <= 0:
		remaining_hours = 1
	# spread remaining energy over remaining hours
	max_kwh = usable_kwh / remaining_hours
	return max_kwh


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
		season: 'summer' or 'winter'.
		config: Configuration dictionary.

	Returns:
		DecisionResult: The daylight decision.
	"""
	surplus = _compute_solar_surplus(solar_power_watts, load_power_watts)
	afternoon_target = config_mod.get_seasonal_value(config, "afternoon_target_soc_pct", season)
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
		extreme_floor = config_mod.get_seasonal_value(config, "hard_reserve_pct", season)
		logger.info(
			"Extreme price override: %.1fc >= %dc, discharging to floor %d%%",
			comed_price_cents, extreme_threshold, extreme_floor,
		)
		return DecisionResult(
			action=Action.DISCHARGE_ENABLED,
			reason=f"No surplus, extreme price {comed_price_cents:.1f}c >= {extreme_threshold}c",
			soc_floor=extreme_floor,
			price_band="extreme",
			target_mode="self_consumption",
		)
	# B.3b: preserve for evening
	logger.info(
		"Preserving for peak: no surplus, price %.1fc below extreme %dc",
		comed_price_cents, extreme_threshold,
	)
	return DecisionResult(
		action=Action.DISCHARGE_DISABLED,
		reason=f"No surplus, price {comed_price_cents:.1f}c not extreme, preserving for peak",
		soc_floor=battery_soc,
		target_mode="backup",
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
		season: 'summer' or 'winter'.
		current_time: Current datetime.
		config: Configuration dictionary.

	Returns:
		DecisionResult: The night decision.
	"""
	extreme_threshold = config.get("extreme_price_threshold", 20)
	night_floor = config_mod.get_seasonal_value(config, "night_floor_pct", season)
	# D.2: discharge only if extreme price and above night floor
	if comed_price_cents >= extreme_threshold and battery_soc > night_floor:
		logger.info(
			"Night extreme: price %.1fc >= %dc, SoC %d%% > floor %d%%, discharging",
			comed_price_cents, extreme_threshold, battery_soc, night_floor,
		)
		return DecisionResult(
			action=Action.DISCHARGE_ENABLED,
			reason=f"Night extreme price {comed_price_cents:.1f}c, discharging to floor {night_floor}%",
			soc_floor=night_floor,
			price_band="extreme",
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
	control_state: state_mod.ControlState,
) -> DecisionResult:
	"""
	Implement section E of STRATEGY.md: peak logic (evening arbitrage).

	Args:
		battery_soc: Current SoC percentage.
		comed_price_cents: Current ComEd price in cents.
		season: 'summer' or 'winter'.
		current_time: Current datetime.
		config: Configuration dictionary.
		control_state: Current control state.

	Returns:
		DecisionResult: The peak decision.
	"""
	# mark peak mode as active
	if not control_state.peak_mode_active:
		control_state.peak_mode_active = True
		control_state.peak_mode_entered_at = current_time.isoformat()
	# E.2: select SoC floor from price band
	soc_floor = config_mod.get_price_band_floor(config, season, comed_price_cents)
	price_band = config_mod.get_price_band_name(config, season, comed_price_cents)
	logger.info(
		"Peak: price %.1fc -> band '%s', floor %d%%",
		comed_price_cents, price_band, soc_floor,
	)
	# E.3: compute pacing guideline (used for logging, not rate control)
	_compute_pacing(battery_soc, soc_floor, current_time, config)
	# E.4: discharge decision
	if battery_soc <= soc_floor:
		# at or below floor, hold
		logger.info(
			"At floor: SoC %d%% <= %d%%, holding",
			battery_soc, soc_floor,
		)
		return DecisionResult(
			action=Action.DISCHARGE_DISABLED,
			reason=f"Peak: SoC {battery_soc}% <= floor {soc_floor}% ({price_band})",
			soc_floor=soc_floor,
			price_band=price_band,
			target_mode="backup",
		)
	# above floor: discharge enabled
	peak_end = config.get("peak_window_end", 22)
	remaining_hours = max(peak_end - current_time.hour, 1)
	usable_pct = max(battery_soc - soc_floor, 0)
	capacity = config.get("battery_capacity_kwh", 20.0)
	usable_kwh = capacity * usable_pct / 100.0
	logger.info(
		"Discharge enabled: price %.1fc in '%s' band, "
		"SoC %d%% above %d%% floor, %.1f kWh usable over %d hrs",
		comed_price_cents, price_band,
		battery_soc, soc_floor, usable_kwh, remaining_hours,
	)
	return DecisionResult(
		action=Action.DISCHARGE_ENABLED,
		reason=(f"Peak {price_band}: SoC {battery_soc}% above "
			f"{soc_floor}% floor, discharge enabled"),
		soc_floor=soc_floor,
		price_band=price_band,
		target_mode="self_consumption",
	)


#============================================
def decide(
	battery_soc: int,
	solar_power_watts: float,
	load_power_watts: float,
	comed_price_cents: float,
	comed_median_cents: float,
	config: dict,
	control_state: state_mod.ControlState,
	current_time: datetime.datetime = None,
) -> DecisionResult:
	"""
	Main decision function implementing the full STRATEGY.md flowchart.

	Args:
		battery_soc: Current battery state of charge percentage.
		solar_power_watts: Current solar generation in watts.
		load_power_watts: Current house load in watts (from smartHomePower).
		comed_price_cents: Current ComEd price in cents.
		comed_median_cents: 24-hour median ComEd price in cents.
		config: Configuration dictionary.
		control_state: ControlState instance for hysteresis tracking.
		current_time: Current datetime (defaults to now).

	Returns:
		DecisionResult: The battery control decision.
	"""
	if current_time is None:
		current_time = datetime.datetime.now()
	# determine season
	season = config_mod.get_season(config, current_time)
	# section A: guards
	hard_reserve = config_mod.get_seasonal_value(config, "hard_reserve_pct", season)
	# log key inputs for reasoning trace
	logger.info(
		"Inputs: SoC %d%% | Price %.1fc | Solar %.0fW | Load %.0fW | Hour %d | Season %s",
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
		_apply_hysteresis(result, config, control_state)
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
				battery_soc, comed_price_cents, season, current_time, config, control_state
			)
		else:
			logger.info("Entering night logic")
			result = _night_logic(
				battery_soc, comed_price_cents, season, current_time, config
			)
		_apply_hysteresis(result, config, control_state)
		logger.info("Decision: %s", result)
		return result
	# solar is available
	# section C: check transition trigger
	if _should_transition_to_peak(current_time, solar_power_watts, control_state, config):
		# peak mode holds once entered (section F.2)
		if control_state.peak_mode_active or _is_in_peak_window(current_time, config):
			logger.info(
				"Transition to peak: hour %d, peak mode active",
				current_time.hour,
			)
			result = _peak_logic(
				battery_soc, comed_price_cents, season, current_time, config, control_state
			)
			_apply_hysteresis(result, config, control_state)
			logger.info("Decision: %s", result)
			return result
	# section B: daylight logic
	logger.info("Entering daylight logic")
	result = _daylight_logic(
		battery_soc, solar_power_watts, load_power_watts,
		comed_price_cents, season, config
	)
	_apply_hysteresis(result, config, control_state)
	logger.info("Decision: %s", result)
	return result


#============================================
def _apply_hysteresis(
	result: DecisionResult,
	config: dict,
	control_state: state_mod.ControlState,
) -> None:
	"""
	Apply hysteresis and token friction to a decision result.

	Modifies the result in-place if hysteresis conditions are not met.

	Args:
		result: Decision result to potentially modify.
		config: Configuration dictionary.
		control_state: Control state for tracking.
	"""
	hysteresis_count = config.get("hysteresis_count", 2)
	friction_count = config.get("token_friction_count", 2)
	# track price band changes
	if result.price_band:
		band_changed = control_state.update_price_band(result.price_band)
		if band_changed:
			logger.info(
				"Band changed to '%s' (%d/%d checks needed)",
				result.price_band, control_state.price_band_counter, hysteresis_count,
			)
		# if band just changed and not enough consecutive checks, hold previous
		elif control_state.price_band_counter < hysteresis_count:
			logger.debug(
				"Hysteresis: band %s has %d/%d consecutive checks",
				result.price_band, control_state.price_band_counter, hysteresis_count
			)
	# track action stability for token friction
	control_state.update_action(result.action.value)
	if control_state.action_stable_count < friction_count:
		logger.debug(
			"Token friction: action %s stable for %d/%d cycles",
			result.action.value, control_state.action_stable_count, friction_count
		)
