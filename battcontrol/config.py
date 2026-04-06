"""YAML configuration loader and validator for battery control system."""

# Standard Library
import os
import copy
import tempfile
import datetime

# PIP3 modules
import yaml
import numpy


# valid season keys used across seasonal config dicts
SEASON_KEYS = ("summer", "shoulder", "winter")

# configuration schema: one canonical source of truth for all config keys
# "type": expected Python type (int rejects bool; int accepted for float)
# "default": stable default, auto-filled if missing from YAML
# "required": True means must be in user YAML if no default (default: False)
# "min"/"max": range bounds for numeric values
# keys with no "default" and required=False are experimental (absent unless set)
CONFIG_SCHEMA = {
	# battery
	"battery_capacity_kwh": {"type": float, "default": 20.0, "min": 0.1},
	# hard reserve: seasonal dict, validated separately
	"hard_reserve_pct": {
		"type": dict,
		"default": {"summer": 10, "shoulder": 15, "winter": 20},
	},
	# price floor anchors: seasonal dict of anchor lists, validated separately
	"price_floor_anchors": {
		"type": dict,
		"default": {
			"summer": [
				{"price_cents": 8, "soc_floor_pct": 50},
				{"price_cents": 10, "soc_floor_pct": 30},
				{"price_cents": 20, "soc_floor_pct": 20},
				{"price_cents": 30, "soc_floor_pct": 10},
			],
			"shoulder": [
				{"price_cents": 8, "soc_floor_pct": 55},
				{"price_cents": 10, "soc_floor_pct": 38},
				{"price_cents": 20, "soc_floor_pct": 25},
				{"price_cents": 30, "soc_floor_pct": 15},
			],
			"winter": [
				{"price_cents": 8, "soc_floor_pct": 60},
				{"price_cents": 10, "soc_floor_pct": 45},
				{"price_cents": 20, "soc_floor_pct": 30},
				{"price_cents": 30, "soc_floor_pct": 20},
			],
		},
	},
	# headroom band for near-full battery during solar surplus
	"headroom_band_low": {"type": int, "default": 85, "min": 0, "max": 100},
	"headroom_band_high": {"type": int, "default": 95, "min": 0, "max": 100},
	# cutoff buffer: deadband half-width in cents
	"cutoff_buffer_cents": {"type": float, "default": 0.5, "min": 0.0},
	# command buffer: minimum SoC change to trigger EP Cube update
	"reserve_soc_buffer_pct": {"type": int, "default": 2, "min": 0, "max": 50},
	# command buffer: optional periodic resend (0 = disabled)
	"epcube_resend_interval_minutes": {"type": int, "default": 0, "min": 0},
	# time-period reserve adjustment on top of price floor (above cutoff only)
	"time_adjust_soc_pct": {"type": int, "default": 5, "min": 0, "max": 100},
	"evening_adjust_start_hour": {"type": int, "default": 13, "min": 0, "max": 23},
	"evening_adjust_end_hour": {"type": int, "default": 23, "min": 0, "max": 23},
	"morning_adjust_start_hour": {"type": int, "default": 2, "min": 0, "max": 23},
	"morning_adjust_end_hour": {"type": int, "default": 10, "min": 0, "max": 23},
	# cutoff scale: multiplier on comedlib cutoff (1.0 = no change, 0.5 = half)
	"cutoff_scale": {"type": float, "default": 1.0, "min": 0.0, "max": 5.0},
	# cutoff adjustment: SoC-based wrapper around comedlib cutoff
	"cutoff_adjust_soc_high_threshold": {"type": int, "default": 85, "min": 0, "max": 100},
	"cutoff_adjust_soc_low_threshold": {"type": int, "default": 25, "min": 0, "max": 100},
	"cutoff_adjust_soc_high_cents": {"type": float, "default": 1.0, "min": 0.0},
	"cutoff_adjust_soc_low_cents": {"type": float, "default": 1.0, "min": 0.0},
	"cutoff_adjust_min_cents": {"type": float, "default": 2.0, "min": 0.0},
	"cutoff_adjust_max_cents": {"type": float, "default": 12.0, "min": 0.0},
	# season auto-detection or manual override
	"season": {"type": str, "default": "auto"},
	# EP Cube connection settings
	"epcube_token": {"type": str, "default": ""},
	"epcube_token_file": {"type": str, "default": ""},
	"epcube_auth_file": {"type": str, "default": ""},
	"epcube_region": {"type": str, "default": "US"},
	"epcube_device_sn": {"type": str, "default": ""},
	# EP Cube credentials (injected from auth file, not in user YAML)
	"epcube_username": {"type": str, "default": ""},
	"epcube_password": {"type": str, "default": ""},
	# WeMo smart plug device names
	"wemo_charge_plug_name": {"type": str, "default": ""},
	"wemo_discharge_plug_name": {"type": str, "default": ""},
	# state persistence
	"state_file_path": {
		"type": str,
		"default": os.path.join(tempfile.gettempdir(), "battery_control_state.json"),
	},
	"hourly_csv_path": {"type": str, "default": "data/hourly_history.csv"},
	# safety default: dry run
	"dry_run": {"type": bool, "default": True},
	# token age warning threshold in hours
	"token_warning_age_hours": {"type": int, "default": 168, "min": 1},
	# --- EXPERIMENTAL (optional, absent by default) ---
	# EP Cube reserve only controls discharge, not PV charging.
	# These rules may not create headroom. Needs live testing.
	"negative_price_floor": {"type": int, "min": 0, "max": 100},
	"pre_solar_soc_threshold": {"type": int, "min": 0, "max": 100},
	"pre_solar_target_floor": {"type": int, "min": 0, "max": 100},
	"pre_solar_start_hour": {"type": int, "min": 0, "max": 23},
	"pre_solar_end_hour": {"type": int, "min": 0, "max": 23},
}


#============================================
def get_defaults() -> dict:
	"""
	Build a complete default config dict from CONFIG_SCHEMA.

	Returns:
		dict: Config dict with all stable defaults applied.
	"""
	defaults = {}
	for key, entry in CONFIG_SCHEMA.items():
		if "default" in entry:
			default_val = entry["default"]
			if isinstance(default_val, (dict, list)):
				defaults[key] = copy.deepcopy(default_val)
			else:
				defaults[key] = default_val
	return defaults


#============================================
def apply_defaults(config: dict) -> None:
	"""
	Fill missing stable keys from CONFIG_SCHEMA defaults.

	Deep-copies dict/list defaults to avoid sharing mutable objects.
	Modifies config in place.

	Args:
		config: Configuration dictionary to fill.
	"""
	for key, schema_entry in CONFIG_SCHEMA.items():
		if "default" in schema_entry and key not in config:
			default_val = schema_entry["default"]
			# deep-copy mutable defaults
			if isinstance(default_val, (dict, list)):
				config[key] = copy.deepcopy(default_val)
			else:
				config[key] = default_val


#============================================
def _check_type(key: str, value, expected_type: type) -> None:
	"""
	Check that value matches expected type.

	Special rules:
	- int rejects bool (bool is subclass of int in Python)
	- int is accepted where float is expected

	Args:
		key: Config key name (for error messages).
		value: The value to check.
		expected_type: Expected Python type.

	Raises:
		ValueError: If type does not match.
	"""
	# reject bool for int fields
	if expected_type == int and isinstance(value, bool):
		raise ValueError(
			f"Config '{key}': expected int, got bool ({value})"
		)
	# accept int for float fields
	if expected_type == float and isinstance(value, int) and not isinstance(value, bool):
		return
	if not isinstance(value, expected_type):
		raise ValueError(
			f"Config '{key}': expected {expected_type.__name__}, "
			f"got {type(value).__name__} ({value!r})"
		)


#============================================
def _validate_seasonal_dict(key: str, value: dict) -> None:
	"""
	Validate a seasonal dict has all required season keys with int 0-100 values.

	Args:
		key: Config key name (for error messages).
		value: The seasonal dict to validate.

	Raises:
		ValueError: If seasons are missing or values are out of range.
	"""
	for season in SEASON_KEYS:
		if season not in value:
			raise ValueError(
				f"Config '{key}': missing season '{season}'"
			)
		season_val = value[season]
		if not isinstance(season_val, int) or isinstance(season_val, bool):
			raise ValueError(
				f"Config '{key}[{season}]': expected int, "
				f"got {type(season_val).__name__}"
			)
		if not (0 <= season_val <= 100):
			raise ValueError(
				f"Config '{key}[{season}]': {season_val} not in 0..100"
			)


#============================================
def _validate_price_floor_anchors(anchors_dict: dict) -> None:
	"""
	Validate price_floor_anchors structure.

	Checks that all season keys exist, each has a non-empty list of anchors
	with price_cents and soc_floor_pct, prices are sorted ascending, and
	floors are 0-100.

	Args:
		anchors_dict: The price_floor_anchors dict.

	Raises:
		ValueError: If structure is invalid.
	"""
	for season in SEASON_KEYS:
		if season not in anchors_dict:
			raise ValueError(
				f"Config 'price_floor_anchors': missing season '{season}'"
			)
		anchors = anchors_dict[season]
		if not isinstance(anchors, list) or len(anchors) < 2:
			raise ValueError(
				f"Config 'price_floor_anchors[{season}]': "
				f"need at least 2 anchors, got {len(anchors) if isinstance(anchors, list) else type(anchors).__name__}"
			)
		for i, anchor in enumerate(anchors):
			if "price_cents" not in anchor:
				raise ValueError(
					f"Config 'price_floor_anchors[{season}][{i}]': "
					f"missing 'price_cents'"
				)
			if "soc_floor_pct" not in anchor:
				raise ValueError(
					f"Config 'price_floor_anchors[{season}][{i}]': "
					f"missing 'soc_floor_pct'"
				)
			floor_val = anchor["soc_floor_pct"]
			if not (0 <= floor_val <= 100):
				raise ValueError(
					f"Config 'price_floor_anchors[{season}][{i}]': "
					f"soc_floor_pct {floor_val} not in 0..100"
				)
		# validate sorted ascending prices
		validate_anchors(anchors)


#============================================
def validate_config(config: dict) -> None:
	"""
	Validate configuration against CONFIG_SCHEMA.

	Checks for unknown keys, type mismatches, range violations,
	missing required keys, and nested structure validity.

	Args:
		config: Configuration dictionary (after apply_defaults).

	Raises:
		ValueError: If any validation check fails.
	"""
	# check for unknown keys
	for key in config:
		if key not in CONFIG_SCHEMA:
			raise ValueError(
				f"Unknown config key: '{key}' (typo?)"
			)
	# check required keys without defaults
	for key, schema_entry in CONFIG_SCHEMA.items():
		is_required = schema_entry.get("required", False)
		has_default = "default" in schema_entry
		if is_required and not has_default and key not in config:
			raise ValueError(
				f"Required config key '{key}' is missing"
			)
	# type and range checks for all present keys
	for key in config:
		schema_entry = CONFIG_SCHEMA[key]
		value = config[key]
		# type check
		expected_type = schema_entry["type"]
		_check_type(key, value, expected_type)
		# range check for numeric types
		if "min" in schema_entry and isinstance(value, (int, float)):
			if value < schema_entry["min"]:
				raise ValueError(
					f"Config '{key}': {value} < min {schema_entry['min']}"
				)
		if "max" in schema_entry and isinstance(value, (int, float)):
			if value > schema_entry["max"]:
				raise ValueError(
					f"Config '{key}': {value} > max {schema_entry['max']}"
				)
	# nested structure validation
	if "hard_reserve_pct" in config:
		_validate_seasonal_dict("hard_reserve_pct", config["hard_reserve_pct"])
	if "price_floor_anchors" in config:
		_validate_price_floor_anchors(config["price_floor_anchors"])
	# experimental key group: pre-solar keys must all be set or all absent
	pre_solar_keys = [
		"pre_solar_soc_threshold", "pre_solar_target_floor",
		"pre_solar_start_hour", "pre_solar_end_hour",
	]
	present = [k for k in pre_solar_keys if k in config]
	if present and len(present) != len(pre_solar_keys):
		missing = [k for k in pre_solar_keys if k not in config]
		raise ValueError(
			f"Pre-solar keys must all be set or all absent. "
			f"Missing: {missing}"
		)
	# time-period overlap validation
	validate_time_adjust(config)


#============================================
def get_season(config: dict, now: datetime.datetime = None) -> str:
	"""
	Determine the current season based on config or month.

	Args:
		config: Configuration dictionary.
		now: Current datetime (defaults to now).

	Returns:
		str: 'summer', 'shoulder', or 'winter'.
	"""
	if now is None:
		now = datetime.datetime.now()
	season_setting = config["season"]
	if season_setting in ("summer", "shoulder", "winter"):
		return season_setting
	# auto-detect based on month
	# summer: May-Sep, shoulder: Mar-Apr + Oct-Nov, winter: Dec-Feb
	month = now.month
	if 5 <= month <= 9:
		return "summer"
	if month in (3, 4, 10, 11):
		return "shoulder"
	return "winter"


#============================================
def _deep_merge(base: dict, override: dict) -> dict:
	"""
	Recursively merge override dict into base dict.

	Args:
		base: Base dictionary with defaults.
		override: Override dictionary from user config.

	Returns:
		dict: Merged dictionary.
	"""
	merged = dict(base)
	for key, value in override.items():
		if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
			merged[key] = _deep_merge(merged[key], value)
		else:
			merged[key] = value
	return merged


#============================================
def load_config(config_path: str) -> dict:
	"""
	Load configuration from a YAML file, apply defaults, and validate.

	Load order:
	1. Load YAML
	2. Load auth/token files (EP Cube credentials)
	3. Apply stable defaults from CONFIG_SCHEMA
	4. Validate against schema

	Args:
		config_path: Path to YAML configuration file.

	Returns:
		dict: Complete, validated configuration.

	Raises:
		FileNotFoundError: If config file does not exist.
		ValueError: If validation fails.
	"""
	if not os.path.isfile(config_path):
		raise FileNotFoundError(f"Config file not found: {config_path}")
	with open(config_path, "r") as f:
		user_config = yaml.safe_load(f)
	if user_config is None:
		user_config = {}
	# build base from schema defaults, then merge user config on top
	base_defaults = {}
	for key, entry in CONFIG_SCHEMA.items():
		if "default" in entry:
			default_val = entry["default"]
			if isinstance(default_val, (dict, list)):
				base_defaults[key] = copy.deepcopy(default_val)
			else:
				base_defaults[key] = default_val
	config = _deep_merge(base_defaults, user_config)
	# load EP Cube credentials from auth file if configured
	auth_file = config["epcube_auth_file"]
	if auth_file:
		auth_path = os.path.expanduser(auth_file)
		if os.path.isfile(auth_path):
			with open(auth_path, "r") as af:
				auth_data = yaml.safe_load(af)
			if auth_data and isinstance(auth_data, dict):
				# copy auth fields into config (only if present in auth file)
				auth_keys = [
					"epcube_region", "epcube_device_sn",
					"epcube_username", "epcube_password",
				]
				for key in auth_keys:
					if key in auth_data:
						config[key] = auth_data[key]
	# load EP Cube token from external file if configured
	token_file = config["epcube_token_file"]
	if token_file:
		token_path = os.path.expanduser(token_file)
		if os.path.isfile(token_path):
			with open(token_path, "r") as tf:
				file_token = tf.read().strip()
			if file_token:
				config["epcube_token"] = file_token
	# apply stable defaults, then validate
	apply_defaults(config)
	validate_config(config)
	return config


#============================================
def get_seasonal_value(config: dict, key: str, season: str) -> int:
	"""
	Get a seasonal value from config.

	Args:
		config: Configuration dictionary.
		key: Config key that has summer/shoulder/winter sub-keys.
		season: 'summer', 'shoulder', or 'winter'.

	Returns:
		int: The seasonal value.
	"""
	value = config[key]
	if isinstance(value, dict):
		return value[season]
	return value


#============================================
def validate_anchors(anchors: list) -> None:
	"""
	Validate price floor anchor list.

	Args:
		anchors: List of anchor dicts with price_cents and soc_floor_pct.

	Raises:
		ValueError: If anchors are invalid.
	"""
	if len(anchors) < 2:
		raise ValueError(f"Need at least 2 anchors, got {len(anchors)}")
	prices = [a["price_cents"] for a in anchors]
	for i in range(len(prices) - 1):
		if prices[i] >= prices[i + 1]:
			raise ValueError(
				f"Anchor prices must be strictly increasing: "
				f"{prices[i]} >= {prices[i + 1]} at index {i}"
			)


#============================================
def validate_time_adjust(config: dict) -> None:
	"""
	Validate time-period adjustment configuration.

	Args:
		config: Configuration dictionary.

	Raises:
		ValueError: If hour ranges are invalid or overlap.
	"""
	time_adjust = config["time_adjust_soc_pct"]
	if time_adjust < 0:
		raise ValueError(f"time_adjust_soc_pct must be >= 0, got {time_adjust}")
	evening_start = config["evening_adjust_start_hour"]
	evening_end = config["evening_adjust_end_hour"]
	morning_start = config["morning_adjust_start_hour"]
	morning_end = config["morning_adjust_end_hour"]
	# validate ranges
	for name, val in [("evening_start", evening_start), ("morning_start", morning_start)]:
		if not (0 <= val < 24):
			raise ValueError(f"{name} must be 0..23, got {val}")
	for name, val in [("evening_end", evening_end), ("morning_end", morning_end)]:
		if not (0 <= val <= 23):
			raise ValueError(f"{name} must be 0..23, got {val}")
	# check overlap: build hour sets and intersect
	evening_hours = set(range(evening_start, evening_end + 1))
	morning_hours = set(range(morning_start, morning_end + 1))
	overlap = evening_hours & morning_hours
	if overlap:
		raise ValueError(
			f"Evening ({evening_start}-{evening_end}) and morning "
			f"({morning_start}-{morning_end}) windows overlap at hours {sorted(overlap)}"
		)


#============================================
def _get_sorted_anchors(config: dict, season: str) -> list:
	"""
	Extract and sort anchors for a season, with validation.

	Args:
		config: Configuration dictionary.
		season: 'summer', 'shoulder', or 'winter'.

	Returns:
		list: Sorted list of anchor dicts.
	"""
	anchors = config["price_floor_anchors"].get(season, [])
	if not anchors:
		return []
	# defensive sort by price
	anchors = sorted(anchors, key=lambda a: a["price_cents"])
	validate_anchors(anchors)
	return anchors


#============================================
def get_price_floor(config: dict, season: str, price_cents: float) -> int:
	"""
	Determine the SoC floor using piecewise linear interpolation.

	Uses numpy.interp to interpolate between anchor points.
	Clamps to first/last anchor floor outside the anchor range.

	Args:
		config: Configuration dictionary.
		season: 'summer', 'shoulder', or 'winter'.
		price_cents: Current price in cents.

	Returns:
		int: Interpolated SoC floor percentage, rounded to nearest 1%.
	"""
	anchors = _get_sorted_anchors(config, season)
	if not anchors:
		return 50
	prices = numpy.array([a["price_cents"] for a in anchors])
	floors = numpy.array([a["soc_floor_pct"] for a in anchors])
	# numpy.interp clamps outside the range by default
	floor_val = numpy.interp(price_cents, prices, floors)
	return round(float(floor_val))


#============================================
def get_price_segment_index(config: dict, season: str, price_cents: float) -> int:
	"""
	Return the segment index for the current price.

	Segments are numbered by which pair of anchors brackets the price:
	  -1 = below first anchor (clamped region)
	  0..N-2 = between anchor pairs
	  N-1 = above last anchor (clamped region)

	Args:
		config: Configuration dictionary.
		season: 'summer', 'shoulder', or 'winter'.
		price_cents: Current price in cents.

	Returns:
		int: Segment index.
	"""
	anchors = _get_sorted_anchors(config, season)
	if not anchors:
		return -1
	prices = numpy.array([a["price_cents"] for a in anchors])
	# searchsorted returns insertion point
	idx = int(numpy.searchsorted(prices, price_cents))
	if idx == 0:
		return -1
	if idx >= len(prices):
		return len(prices) - 1
	# between anchors idx-1 and idx, segment index is idx-1
	return idx - 1


#============================================
def get_price_segment_bounds(
	config: dict, season: str, price_cents: float
) -> tuple:
	"""
	Return the bounding anchor prices for the current segment.

	Args:
		config: Configuration dictionary.
		season: 'summer', 'shoulder', or 'winter'.
		price_cents: Current price in cents.

	Returns:
		tuple: (lower_price, upper_price). None for unbounded ends.
	"""
	anchors = _get_sorted_anchors(config, season)
	if not anchors:
		return (None, None)
	prices = [a["price_cents"] for a in anchors]
	idx = int(numpy.searchsorted(prices, price_cents))
	if idx == 0:
		return (None, prices[0])
	if idx >= len(prices):
		return (prices[-1], None)
	return (prices[idx - 1], prices[idx])
