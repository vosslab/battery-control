"""SoC-aware cutoff adjustment wrapper for comedlib.

comedlib's getReasonableCutOff() uses time-of-day heuristics (weekend bonus,
late-night bonus, solar-peak Gaussian) but has no knowledge of actual battery
state. This module wraps that cutoff with an additive SoC-based adjustment,
following the same pattern used in wemoPlug-comed-multi.py (bounds + bias)
and thermostat-comed.py (domain-specific bonus).

The wrapper only reads current SoC to shift the cutoff. Reserve-floor
selection and all other battery behavior remain in strategy.py.
"""

# Standard Library
import logging

logger = logging.getLogger(__name__)


#============================================
def _soc_adjustment(battery_soc: int, config: dict) -> float:
	"""Compute cutoff adjustment in cents based on battery SoC.

	Monotonic linear interpolation from positive (conserve) at low SoC
	to negative (discharge) at high SoC. Zero at the midpoint between
	the two thresholds.

	Args:
		battery_soc: Current battery state of charge percentage (0-100).
		config: Configuration dictionary.

	Returns:
		float: Adjustment in cents. Positive = raise cutoff (conserve),
			negative = lower cutoff (more discharge).
	"""
	high_threshold = config.get("cutoff_adjust_soc_high_threshold", 85)
	low_threshold = config.get("cutoff_adjust_soc_low_threshold", 25)
	high_cents = config.get("cutoff_adjust_soc_high_cents", 1.0)
	low_cents = config.get("cutoff_adjust_soc_low_cents", 1.0)
	# clamp SoC to threshold range
	if battery_soc >= high_threshold:
		# full negative adjustment: lower cutoff to allow more discharge
		return -high_cents
	if battery_soc <= low_threshold:
		# full positive adjustment: raise cutoff to conserve
		return low_cents
	# linear interpolation between thresholds
	# at low_threshold: +low_cents, at high_threshold: -high_cents
	threshold_range = high_threshold - low_threshold
	fraction = (battery_soc - low_threshold) / threshold_range
	# interpolate from +low_cents (fraction=0) to -high_cents (fraction=1)
	adjustment = low_cents - fraction * (low_cents + high_cents)
	return adjustment


#============================================
def _validate_config(config: dict) -> None:
	"""Validate cutoff adjustment configuration.

	Args:
		config: Configuration dictionary.

	Raises:
		ValueError: If config values are invalid.
	"""
	high_threshold = config.get("cutoff_adjust_soc_high_threshold", 85)
	low_threshold = config.get("cutoff_adjust_soc_low_threshold", 25)
	if low_threshold >= high_threshold:
		raise ValueError(
			f"cutoff_adjust_soc_low_threshold ({low_threshold}) must be "
			f"less than cutoff_adjust_soc_high_threshold ({high_threshold})"
		)
	min_cents = config.get("cutoff_adjust_min_cents", 2.0)
	max_cents = config.get("cutoff_adjust_max_cents", 12.0)
	if min_cents > max_cents:
		raise ValueError(
			f"cutoff_adjust_min_cents ({min_cents}) must be "
			f"<= cutoff_adjust_max_cents ({max_cents})"
		)
	# cent adjustments must be non-negative
	high_cents = config.get("cutoff_adjust_soc_high_cents", 1.0)
	low_cents = config.get("cutoff_adjust_soc_low_cents", 1.0)
	if high_cents < 0:
		raise ValueError(
			f"cutoff_adjust_soc_high_cents must be >= 0, got {high_cents}"
		)
	if low_cents < 0:
		raise ValueError(
			f"cutoff_adjust_soc_low_cents must be >= 0, got {low_cents}"
		)


#============================================
def adjust_cutoff(
	raw_cutoff_cents: float,
	battery_soc: int,
	config: dict,
) -> float:
	"""Adjust comedlib cutoff based on battery SoC.

	Takes the raw cutoff from comedlib.getReasonableCutOff() and applies
	a small additive SoC-based adjustment. High SoC lowers the cutoff
	(more willing to discharge), low SoC raises it (conserve battery).
	The result is clamped to configurable bounds.

	Args:
		raw_cutoff_cents: Raw cutoff price from comedlib in cents.
		battery_soc: Current battery state of charge percentage (0-100).
		config: Configuration dictionary.

	Returns:
		float: Adjusted cutoff price in cents, clamped to bounds.

	Raises:
		ValueError: If config values are invalid.
	"""
	_validate_config(config)
	# compute SoC-based adjustment
	soc_adjust = _soc_adjustment(battery_soc, config)
	# apply adjustment
	adjusted = raw_cutoff_cents + soc_adjust
	# clamp to bounds
	min_cents = config.get("cutoff_adjust_min_cents", 2.0)
	max_cents = config.get("cutoff_adjust_max_cents", 12.0)
	clamped = max(min_cents, min(max_cents, adjusted))
	# log one compact line
	was_clamped = (clamped != adjusted)
	if was_clamped:
		logger.info(
			"Cutoff adjust: raw %.1fc, soc %d%% -> %+.1fc, final %.1fc (clamped)",
			raw_cutoff_cents, battery_soc, soc_adjust, clamped,
		)
	else:
		logger.info(
			"Cutoff adjust: raw %.1fc, soc %d%% -> %+.1fc, final %.1fc",
			raw_cutoff_cents, battery_soc, soc_adjust, clamped,
		)
	return clamped
