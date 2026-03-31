"""YAML configuration loader for battery control system."""

# Standard Library
import os
import tempfile
import datetime

# PIP3 modules
import yaml


# default configuration values from STRATEGY.md
DEFAULTS = {
	"battery_capacity_kwh": 20.0,
	# hard reserve: do not discharge below this SoC
	"hard_reserve_pct": {"summer": 10, "winter": 20},
	# afternoon target SoC before peak window
	"afternoon_target_soc_pct": {"summer": 90, "winter": 70},
	# peak arbitrage window hours (24h format)
	"peak_window_start": 16,
	"peak_window_end": 22,
	# seasonal price band SoC floors during peak window
	"price_band_floors": {
		"summer": {
			"low": {"max_price_cents": 8, "soc_floor_pct": 50},
			"mid_low": {"max_price_cents": 10, "soc_floor_pct": 30},
			"mid_high": {"max_price_cents": 20, "soc_floor_pct": 20},
			"high": {"max_price_cents": 9999, "soc_floor_pct": 10},
		},
		"winter": {
			"low": {"max_price_cents": 8, "soc_floor_pct": 60},
			"mid_low": {"max_price_cents": 10, "soc_floor_pct": 45},
			"mid_high": {"max_price_cents": 20, "soc_floor_pct": 30},
			"high": {"max_price_cents": 9999, "soc_floor_pct": 20},
		},
	},
	# extreme price threshold for daytime discharge override
	"extreme_price_threshold": 20,
	# conservative night floor when not in peak window
	"night_floor_pct": {"summer": 25, "winter": 35},
	# headroom band for near-full battery during solar surplus
	"headroom_band_low": 85,
	"headroom_band_high": 95,
	# consecutive checks before switching price bands
	"hysteresis_count": 2,
	# stable cycles before sending EP Cube command
	"token_friction_count": 2,
	# solar fade detection thresholds
	"solar_sunset_threshold_watts": 50,
	"solar_sunset_duration_minutes": 20,
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
		str: 'summer' or 'winter'.
	"""
	if now is None:
		now = datetime.datetime.now()
	season_setting = config.get("season", "auto")
	if season_setting in ("summer", "winter"):
		return season_setting
	# auto-detect: May through September is summer
	month = now.month
	if 5 <= month <= 9:
		return "summer"
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
		key: Config key that has summer/winter sub-keys.
		season: 'summer' or 'winter'.

	Returns:
		int: The seasonal value.
	"""
	value = config.get(key, {})
	if isinstance(value, dict):
		return value.get(season, value.get("summer", 0))
	return value


#============================================
def get_price_band_floor(config: dict, season: str, price_cents: float) -> int:
	"""
	Determine the SoC floor for the current price band.

	Args:
		config: Configuration dictionary.
		season: 'summer' or 'winter'.
		price_cents: Current price in cents.

	Returns:
		int: SoC floor percentage for the matching price band.
	"""
	bands = config.get("price_band_floors", {}).get(season, {})
	# iterate bands in order: low, mid_low, mid_high, high
	band_order = ["low", "mid_low", "mid_high", "high"]
	for band_name in band_order:
		band = bands.get(band_name, {})
		max_price = band.get("max_price_cents", 9999)
		if price_cents < max_price:
			return band.get("soc_floor_pct", 50)
	# fallback: return the highest band floor
	last_band = bands.get("high", {})
	return last_band.get("soc_floor_pct", 10)


#============================================
def get_price_band_name(config: dict, season: str, price_cents: float) -> str:
	"""
	Determine the price band name for the current price.

	Args:
		config: Configuration dictionary.
		season: 'summer' or 'winter'.
		price_cents: Current price in cents.

	Returns:
		str: Band name ('low', 'mid_low', 'mid_high', or 'high').
	"""
	bands = config.get("price_band_floors", {}).get(season, {})
	band_order = ["low", "mid_low", "mid_high", "high"]
	for band_name in band_order:
		band = bands.get(band_name, {})
		max_price = band.get("max_price_cents", 9999)
		if price_cents < max_price:
			return band_name
	return "high"
