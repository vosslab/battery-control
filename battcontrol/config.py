"""YAML configuration loader for battery control system."""

# Standard Library
import os
import tempfile
import datetime

# PIP3 modules
import yaml
import numpy


# default configuration values from STRATEGY.md
DEFAULTS = {
	"battery_capacity_kwh": 20.0,
	# hard reserve: do not discharge below this SoC
	"hard_reserve_pct": {"summer": 10, "shoulder": 15, "winter": 20},
	# price floor anchors for piecewise linear interpolation when price > cutoff
	"price_floor_anchors": {
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
	# headroom band for near-full battery during solar surplus
	"headroom_band_low": 85,
	"headroom_band_high": 95,
	# command buffer: minimum SoC change to trigger EP Cube update
	"reserve_soc_buffer_pct": 2,
	# command buffer: optional periodic resend (0 = disabled)
	"epcube_resend_interval_minutes": 0,
	# time-period reserve adjustment on top of price floor (above cutoff only)
	"time_adjust_soc_pct": 5,
	"evening_adjust_start_hour": 13,
	"evening_adjust_end_hour": 23,
	"morning_adjust_start_hour": 2,
	"morning_adjust_end_hour": 10,
	# cutoff adjustment: SoC-based wrapper around comedlib cutoff
	"cutoff_adjust_soc_high_threshold": 85,
	"cutoff_adjust_soc_low_threshold": 25,
	"cutoff_adjust_soc_high_cents": 1.0,
	"cutoff_adjust_soc_low_cents": 1.0,
	"cutoff_adjust_min_cents": 2.0,
	"cutoff_adjust_max_cents": 12.0,
	# season auto-detection or manual override
	"season": "auto",
	# EP Cube connection settings
	"epcube_token": "",
	"epcube_token_file": "",
	"epcube_auth_file": "",
	"epcube_region": "US",
	"epcube_device_sn": "",
	# WeMo smart plug device names
	"wemo_charge_plug_name": "",
	"wemo_discharge_plug_name": "",
	# state persistence file path
	"state_file_path": os.path.join(tempfile.gettempdir(), "battery_control_state.json"),
	# safety default: dry run
	"dry_run": True,
	# token age warning threshold in hours
	"token_warning_age_hours": 168,
}


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
	season_setting = config.get("season", "auto")
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
	Load configuration from a YAML file and apply defaults.

	Args:
		config_path: Path to YAML configuration file.

	Returns:
		dict: Complete configuration with defaults applied.

	Raises:
		FileNotFoundError: If config file does not exist.
		ValueError: If required fields are missing.
	"""
	if not os.path.isfile(config_path):
		raise FileNotFoundError(f"Config file not found: {config_path}")
	with open(config_path, "r") as f:
		user_config = yaml.safe_load(f)
	if user_config is None:
		user_config = {}
	# merge user config over defaults
	config = _deep_merge(DEFAULTS, user_config)
	# load EP Cube credentials from auth file if configured
	auth_file = config.get("epcube_auth_file", "")
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
	token_file = config.get("epcube_token_file", "")
	if token_file:
		token_path = os.path.expanduser(token_file)
		if os.path.isfile(token_path):
			with open(token_path, "r") as tf:
				file_token = tf.read().strip()
			if file_token:
				config["epcube_token"] = file_token
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
	value = config.get(key, {})
	if isinstance(value, dict):
		return value.get(season, value.get("summer", 0))
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
	time_adjust = config.get("time_adjust_soc_pct", 5)
	if time_adjust < 0:
		raise ValueError(f"time_adjust_soc_pct must be >= 0, got {time_adjust}")
	evening_start = config.get("evening_adjust_start_hour", 13)
	evening_end = config.get("evening_adjust_end_hour", 23)
	morning_start = config.get("morning_adjust_start_hour", 2)
	morning_end = config.get("morning_adjust_end_hour", 10)
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
	anchors = config.get("price_floor_anchors", {}).get(season, [])
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
