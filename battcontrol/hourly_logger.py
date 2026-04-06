"""Hourly data logger for persistent CSV history."""

# Standard Library
import os
import csv
import logging
import datetime

# local repo modules
import battcontrol.config

logger = logging.getLogger(__name__)

# CSV output columns in order
CSV_COLUMNS = [
	"hour_start", "season", "comed_price", "comed_price_median", "comed_cutoff",
	"start_soc", "end_soc", "grid_kwh", "solar_kwh", "load_kwh",
	"battery_charge_kwh", "battery_discharge_kwh",
	"policy_action", "epcube_mode", "reserve_soc",
	"sample_count", "used_fallback_power_integration",
]


#============================================
class HourlyLogger:
	"""
	Accumulates per-cycle data and writes one CSV row per completed hour.

	This logger is not persisted to state.json. It tracks the current hour's
	electricity counters, power accumulation, and policy decisions. When an
	hour boundary is crossed, it flushes the prior hour's data to CSV.
	"""

	#============================================
	def __init__(self, csv_path: str = "data/hourly_history.csv"):
		"""
		Initialize the hourly logger.

		Args:
			csv_path: Path to the output CSV file.
		"""
		self.csv_path = csv_path
		# current hour state
		self.current_hour = None
		self.hour_start_time = None
		self.start_soc = None
		self.latest_soc = None
		self.latest_price = None
		self.latest_median = None
		self.latest_cutoff = None
		self.latest_action = None
		self.latest_mode = None
		self.latest_reserve = None
		self.sample_count = 0
		# counter snapshots for kWh computation
		self.hour_start_counters = None
		self.latest_counters = None
		# fallback power integration
		self.power_accumulator = {
			"grid": 0.0,
			"solar": 0.0,
			"load": 0.0,
		}
		self.used_fallback = False
		# previous cycle time for interval estimation
		self.last_cycle_time = None
		# startup tracking
		self.startup_written = False
		self.latest_epcube_data = None

	#============================================
	def record_cycle(
		self,
		now: datetime.datetime,
		epcube_data: dict,
		comed_price: float,
		comed_median: float,
		comed_cutoff: float,
		result,
		config: dict,
	) -> None:
		"""
		Record a cycle's data and flush if hour boundary crossed.

		Args:
			now: Current datetime.
			epcube_data: Dict from epcube_client.get_device_data() with
				battery_soc, solar_power_watts, grid_power_watts,
				smart_home_power_watts, and *_electricity_kwh fields.
			comed_price: Predicted price in cents.
			comed_median: Median price in cents.
			result: DecisionResult from strategy.evaluate().
			config: Configuration dictionary.
		"""
		# Check hour boundary
		if self.current_hour is not None and now.hour != self.current_hour:
			self._flush_hour(config)

		# Start new hour if needed
		if self.current_hour is None:
			self.current_hour = now.hour
			self.hour_start_time = now.replace(minute=0, second=0, microsecond=0)
			self.start_soc = epcube_data.get("battery_soc", 0)
			self.hour_start_counters = self._extract_counters(epcube_data)
			self.sample_count = 0
			self.power_accumulator = {"grid": 0.0, "solar": 0.0, "load": 0.0}
			self.used_fallback = False
			self.last_cycle_time = None

		# Accumulate cycle data
		self.sample_count += 1
		self.latest_soc = epcube_data.get("battery_soc", 0)
		self.latest_price = comed_price
		self.latest_median = comed_median
		self.latest_cutoff = comed_cutoff
		self.latest_action = result.state.value if hasattr(result.state, 'value') else str(result.state)
		self.latest_mode = result.target_mode
		self.latest_reserve = result.soc_floor
		self.latest_counters = self._extract_counters(epcube_data)

		# Accumulate power for fallback
		interval_seconds = self._estimate_interval(now)
		self._accumulate_power(epcube_data, interval_seconds)

		self.last_cycle_time = now
		self.latest_epcube_data = epcube_data

	#============================================
	def write_startup_entry(self, config: dict) -> None:
		"""
		Write a STARTUP row to CSV using snapshot power projected over one hour.

		Called once after the first record_cycle() so real device data is available.

		Args:
			config: Configuration dictionary.
		"""
		if self.startup_written:
			return
		# estimate kWh by projecting snapshot watts over one hour
		epcube = self.latest_epcube_data or {}
		grid_kwh = (epcube.get("grid_power_watts") or 0) / 1000.0
		solar_kwh = (epcube.get("solar_power_watts") or 0) / 1000.0
		load_kwh = (epcube.get("smart_home_power_watts") or 0) / 1000.0
		# season from config
		now = self.hour_start_time or datetime.datetime.now()
		season = battcontrol.config.get_season(config, now)
		# build row with real prices/SoC and snapshot-estimated energy
		row_dict = {
			"hour_start": now.strftime("%Y-%m-%d %H:%M"),
			"season": season,
			"comed_price": f"{self.latest_price:.1f}" if self.latest_price is not None else "",
			"comed_price_median": f"{self.latest_median:.1f}" if self.latest_median is not None else "",
			"comed_cutoff": f"{self.latest_cutoff:.1f}" if self.latest_cutoff is not None else "",
			"start_soc": self.latest_soc if self.latest_soc is not None else "",
			"end_soc": self.latest_soc if self.latest_soc is not None else "",
			"grid_kwh": f"{grid_kwh:.3f}",
			"solar_kwh": f"{solar_kwh:.3f}",
			"load_kwh": f"{load_kwh:.3f}",
			"battery_charge_kwh": "0.000",
			"battery_discharge_kwh": "0.000",
			"policy_action": "STARTUP",
			"epcube_mode": self.latest_mode or "",
			"reserve_soc": self.latest_reserve or "",
			"sample_count": 0,
			"used_fallback_power_integration": "False",
		}
		self._write_csv_row(row_dict)
		self.startup_written = True
		logger.info("Startup entry written to %s", self.csv_path)

	#============================================
	def _extract_counters(self, epcube_data: dict) -> dict:
		"""
		Extract electricity counters from epcube data.

		Returns dict with keys: grid_electricity_kwh, solar_electricity_kwh,
		smart_home_electricity_kwh (or None if not available).

		Args:
			epcube_data: Device data dict from epcube_client.

		Returns:
			dict: Counter values or None for missing fields.
		"""
		return {
			"grid": epcube_data.get("grid_electricity_kwh"),
			"solar": epcube_data.get("solar_electricity_kwh"),
			"load": epcube_data.get("smart_home_electricity_kwh"),
		}

	#============================================
	def _estimate_interval(self, now: datetime.datetime) -> float:
		"""
		Estimate interval since last cycle in seconds.

		Args:
			now: Current datetime.

		Returns:
			float: Interval in seconds (default 180 if first cycle).
		"""
		if self.last_cycle_time is None:
			return 180.0  # default 3 minutes
		delta = (now - self.last_cycle_time).total_seconds()
		return max(delta, 1.0)  # at least 1 second

	#============================================
	def _accumulate_power(self, epcube_data: dict, interval_seconds: float) -> None:
		"""
		Accumulate power readings over time for fallback kWh computation.

		Set used_fallback=True if counters are missing (will need fallback).

		Args:
			epcube_data: Device data dict.
			interval_seconds: Time since last cycle in seconds.
		"""
		grid_watts = epcube_data.get("grid_power_watts")
		solar_watts = epcube_data.get("solar_power_watts")
		load_watts = epcube_data.get("smart_home_power_watts")
		grid_kwh = epcube_data.get("grid_electricity_kwh")
		solar_kwh = epcube_data.get("solar_electricity_kwh")
		load_kwh = epcube_data.get("smart_home_electricity_kwh")

		# If any counter is None, we'll need to use power fallback
		if grid_kwh is None or solar_kwh is None or load_kwh is None:
			self.used_fallback = True

		# Accumulate power and convert to kWh
		# watts * seconds / 3600 = Wh, then / 1000 = kWh
		if grid_watts is not None:
			self.power_accumulator["grid"] += grid_watts * interval_seconds / 3600000.0

		if solar_watts is not None:
			self.power_accumulator["solar"] += solar_watts * interval_seconds / 3600000.0

		if load_watts is not None:
			self.power_accumulator["load"] += load_watts * interval_seconds / 3600000.0

	#============================================
	def _flush_hour(self, config: dict) -> None:
		"""
		Compute and write the previous hour's CSV row.

		Args:
			config: Configuration dictionary.
		"""
		if self.current_hour is None or self.hour_start_time is None:
			return

		# Compute kWh values
		grid_kwh = self._compute_kwh("grid")
		solar_kwh = self._compute_kwh("solar")
		load_kwh = self._compute_kwh("load")

		# Battery charge/discharge from SoC delta
		battery_capacity = config["battery_capacity_kwh"]
		soc_delta = self.latest_soc - self.start_soc
		battery_charge_kwh = 0.0
		battery_discharge_kwh = 0.0
		if soc_delta > 0:
			battery_charge_kwh = soc_delta * battery_capacity / 100.0
		elif soc_delta < 0:
			battery_discharge_kwh = abs(soc_delta) * battery_capacity / 100.0

		# Season
		season = battcontrol.config.get_season(config, self.hour_start_time)

		# Build row
		row_dict = {
			"hour_start": self.hour_start_time.strftime("%Y-%m-%d %H:%M"),
			"season": season,
			"comed_price": f"{self.latest_price:.1f}" if self.latest_price is not None else "",
			"comed_price_median": f"{self.latest_median:.1f}" if self.latest_median is not None else "",
		"comed_cutoff": f"{self.latest_cutoff:.1f}" if self.latest_cutoff is not None else "",
			"start_soc": self.start_soc,
			"end_soc": self.latest_soc,
			"grid_kwh": f"{grid_kwh:.3f}" if grid_kwh is not None else "",
			"solar_kwh": f"{solar_kwh:.3f}" if solar_kwh is not None else "",
			"load_kwh": f"{load_kwh:.3f}" if load_kwh is not None else "",
			"battery_charge_kwh": f"{battery_charge_kwh:.3f}",
			"battery_discharge_kwh": f"{battery_discharge_kwh:.3f}",
			"policy_action": self.latest_action or "",
			"epcube_mode": self.latest_mode or "",
			"reserve_soc": self.latest_reserve or "",
			"sample_count": self.sample_count,
			"used_fallback_power_integration": "True" if self.used_fallback else "False",
		}

		# Write CSV row
		self._write_csv_row(row_dict)

		# Log summary
		logger.info(
			"Hourly flush: %s | grid %.3f kWh | solar %.3f kWh | load %.3f kWh | "
			"battery charge %.3f discharge %.3f | %d samples",
			self.hour_start_time.strftime("%Y-%m-%d %H:%M"),
			grid_kwh if grid_kwh is not None else 0.0,
			solar_kwh if solar_kwh is not None else 0.0,
			load_kwh if load_kwh is not None else 0.0,
			battery_charge_kwh,
			battery_discharge_kwh,
			self.sample_count,
		)

		# Reset for next hour
		self.current_hour = None
		self.hour_start_time = None
		self.start_soc = None
		self.latest_soc = None
		self.latest_price = None
		self.latest_median = None
		self.latest_cutoff = None
		self.latest_action = None
		self.latest_mode = None
		self.latest_reserve = None
		self.sample_count = 0
		self.hour_start_counters = None
		self.latest_counters = None
		self.power_accumulator = {"grid": 0.0, "solar": 0.0, "load": 0.0}
		self.used_fallback = False
		self.last_cycle_time = None

	#============================================
	def _compute_kwh(self, key: str) -> float:
		"""
		Compute kWh for a given counter (grid, solar, load).

		Uses counter deltas if both snapshots are non-None, otherwise falls
		back to power accumulation.

		Args:
			key: Counter key ("grid", "solar", or "load").

		Returns:
			float: kWh value, or None if unavailable.
		"""
		if (self.hour_start_counters is not None and
			self.latest_counters is not None and
			self.hour_start_counters.get(key) is not None and
			self.latest_counters.get(key) is not None):
			# Use counter delta (primary method)
			kwh = self.latest_counters[key] - self.hour_start_counters[key]
			return kwh
		# Fall back to power accumulation
		return self.power_accumulator.get(key, 0.0)

	#============================================
	def _write_csv_row(self, row_dict: dict) -> None:
		"""
		Write a single row to the CSV file.

		Creates the file and header if it doesn't exist.

		Args:
			row_dict: Row data as dict with CSV_COLUMNS keys.
		"""
		# Ensure directory exists
		csv_dir = os.path.dirname(self.csv_path)
		if csv_dir and not os.path.exists(csv_dir):
			os.makedirs(csv_dir, exist_ok=True)

		# Check if file exists (need to write header)
		file_exists = os.path.exists(self.csv_path)

		with open(self.csv_path, 'a', newline='') as f:
			writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
			if not file_exists:
				writer.writeheader()
			writer.writerow(row_dict)
