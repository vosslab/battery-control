"""Tests for hourly_logger.py - hourly CSV data accumulation and logging."""

# Standard Library
import os
import csv
import datetime

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.strategy as strategy_mod
import battcontrol.hourly_logger as logger_mod


#============================================
def make_epcube_data(
	battery_soc: int = 50,
	solar_power_watts: float = 100.0,
	grid_power_watts: float = 200.0,
	smart_home_power_watts: float = 150.0,
	grid_electricity_kwh: float = 1000.0,
	solar_electricity_kwh: float = 500.0,
	smart_home_electricity_kwh: float = 800.0,
) -> dict:
	"""
	Create a mock epcube_data dict.

	Args:
		battery_soc: Battery state of charge percentage.
		solar_power_watts: Solar generation in watts.
		grid_power_watts: Grid power in watts (positive = import).
		smart_home_power_watts: House load in watts.
		grid_electricity_kwh: Grid electricity counter in kWh.
		solar_electricity_kwh: Solar electricity counter in kWh.
		smart_home_electricity_kwh: Smart home electricity counter in kWh.

	Returns:
		dict: Mock epcube data.
	"""
	return {
		"battery_soc": battery_soc,
		"solar_power_watts": solar_power_watts,
		"grid_power_watts": grid_power_watts,
		"smart_home_power_watts": smart_home_power_watts,
		"grid_electricity_kwh": grid_electricity_kwh,
		"solar_electricity_kwh": solar_electricity_kwh,
		"smart_home_electricity_kwh": smart_home_electricity_kwh,
	}


#============================================
def make_decision_result(
	action: str = "charge_from_solar",
	target_mode: str = "self_consumption",
	soc_floor: int = 50,
) -> strategy_mod.DecisionResult:
	"""
	Create a mock DecisionResult.

	Args:
		action: Action value (as string, e.g., "charge_from_solar").
		target_mode: EP Cube mode name.
		soc_floor: Reserve SoC percentage.

	Returns:
		strategy_mod.DecisionResult: Mock result.
	"""
	# Convert string action to enum
	action_enum = strategy_mod.Action.CHARGE_FROM_SOLAR
	if action == "discharge_enabled":
		action_enum = strategy_mod.Action.DISCHARGE_ENABLED
	elif action == "discharge_disabled":
		action_enum = strategy_mod.Action.DISCHARGE_DISABLED

	return strategy_mod.DecisionResult(
		action=action_enum,
		reason="Test decision",
		soc_floor=soc_floor,
		target_mode=target_mode,
	)


#============================================
class TestHourlyLogger:
	"""Tests for HourlyLogger."""

	#============================================
	def test_first_cycle_starts_accumulation(self, tmp_path):
		"""First record_cycle initializes hour state."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		now = datetime.datetime(2026, 3, 31, 13, 30, 0)
		epcube_data = make_epcube_data(battery_soc=50)
		result = make_decision_result()
		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		logger.record_cycle(now, epcube_data, 12.0, 10.0, result, config)

		assert logger.current_hour == 13
		assert logger.hour_start_time == datetime.datetime(2026, 3, 31, 13, 0, 0)
		assert logger.start_soc == 50
		assert logger.sample_count == 1

	#============================================
	def test_same_hour_accumulates(self, tmp_path):
		"""Multiple cycles in same hour increment sample_count."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Three cycles in the same hour
		for i in range(3):
			now = datetime.datetime(2026, 3, 31, 13, 0 + i*5, 0)
			epcube_data = make_epcube_data(battery_soc=50 + i)
			result = make_decision_result()
			logger.record_cycle(now, epcube_data, 12.0, 10.0, result, config)

		assert logger.sample_count == 3
		assert logger.latest_soc == 52

	#============================================
	def test_hour_boundary_flushes(self, tmp_path):
		"""Cycle in new hour triggers flush of previous hour."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Cycle in hour 13
		now1 = datetime.datetime(2026, 3, 31, 13, 30, 0)
		epcube_data1 = make_epcube_data(battery_soc=50)
		result1 = make_decision_result()
		logger.record_cycle(now1, epcube_data1, 12.0, 10.0, result1, config)

		assert logger.current_hour == 13

		# Cycle in hour 14 triggers flush
		now2 = datetime.datetime(2026, 3, 31, 14, 5, 0)
		epcube_data2 = make_epcube_data(battery_soc=55)
		result2 = make_decision_result()
		logger.record_cycle(now2, epcube_data2, 13.0, 10.5, result2, config)

		# CSV should have been written
		assert os.path.exists(csv_path)
		# Logger should now be in hour 14
		assert logger.current_hour == 14

	#============================================
	def test_csv_created_with_header(self, tmp_path):
		"""First flush creates file with header row."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Cycle in hour 13
		now1 = datetime.datetime(2026, 3, 31, 13, 30, 0)
		epcube_data1 = make_epcube_data(battery_soc=50)
		result1 = make_decision_result()
		logger.record_cycle(now1, epcube_data1, 12.0, 10.0, result1, config)

		# Cycle in hour 14 to trigger flush
		now2 = datetime.datetime(2026, 3, 31, 14, 5, 0)
		epcube_data2 = make_epcube_data(battery_soc=55)
		result2 = make_decision_result()
		logger.record_cycle(now2, epcube_data2, 13.0, 10.5, result2, config)

		# Check file exists and has header
		assert os.path.exists(csv_path)
		with open(csv_path, 'r') as f:
			reader = csv.reader(f)
			header = next(reader)
			assert header == logger_mod.CSV_COLUMNS

	#============================================
	def test_csv_appends_rows(self, tmp_path):
		"""Subsequent flushes append (don't overwrite)."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# First hour: 13:30
		now1 = datetime.datetime(2026, 3, 31, 13, 30, 0)
		epcube_data1 = make_epcube_data(battery_soc=50)
		result1 = make_decision_result()
		logger.record_cycle(now1, epcube_data1, 12.0, 10.0, result1, config)

		# Second hour: 14:30 (triggers flush of hour 13)
		now2 = datetime.datetime(2026, 3, 31, 14, 30, 0)
		epcube_data2 = make_epcube_data(battery_soc=55)
		result2 = make_decision_result()
		logger.record_cycle(now2, epcube_data2, 13.0, 10.5, result2, config)

		# Third hour: 15:30 (triggers flush of hour 14)
		now3 = datetime.datetime(2026, 3, 31, 15, 30, 0)
		epcube_data3 = make_epcube_data(battery_soc=60)
		result3 = make_decision_result()
		logger.record_cycle(now3, epcube_data3, 14.0, 11.0, result3, config)

		# Check file has header + 2 data rows
		with open(csv_path, 'r') as f:
			reader = csv.reader(f)
			rows = list(reader)
		assert len(rows) == 3  # header + 2 data rows

	#============================================
	def test_counter_based_kwh(self, tmp_path):
		"""kWh computed from electricity counter deltas."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Hour 13: First cycle - counters at initial values
		now1 = datetime.datetime(2026, 3, 31, 13, 5, 0)
		epcube_data1 = make_epcube_data(
			battery_soc=50,
			grid_electricity_kwh=1000.0,
			solar_electricity_kwh=500.0,
			smart_home_electricity_kwh=800.0,
		)
		result1 = make_decision_result()
		logger.record_cycle(now1, epcube_data1, 12.0, 10.0, result1, config)

		# Hour 13: Second cycle - counters advanced further
		now1b = datetime.datetime(2026, 3, 31, 13, 10, 0)
		epcube_data1b = make_epcube_data(
			battery_soc=51,
			grid_electricity_kwh=1010.0,  # +10 from start of hour
			solar_electricity_kwh=520.0,  # +20 from start of hour
			smart_home_electricity_kwh=830.0,  # +30 from start of hour
		)
		result1b = make_decision_result()
		logger.record_cycle(now1b, epcube_data1b, 12.0, 10.0, result1b, config)

		# Hour 14: Triggers flush of hour 13
		now2 = datetime.datetime(2026, 3, 31, 14, 5, 0)
		epcube_data2 = make_epcube_data(battery_soc=60)
		result2 = make_decision_result()
		logger.record_cycle(now2, epcube_data2, 13.0, 10.5, result2, config)

		# Read CSV to verify deltas from hour 13
		# The deltas are: latest_counters - hour_start_counters
		# = (1010, 520, 830) - (1000, 500, 800) = (10, 20, 30)
		with open(csv_path, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)
		assert len(rows) == 1  # first hour's flush
		row = rows[0]
		assert float(row["grid_kwh"]) == 10.0
		assert float(row["solar_kwh"]) == 20.0
		assert float(row["load_kwh"]) == 30.0

	#============================================
	def test_fallback_power_integration(self, tmp_path):
		"""When counters are None, uses power accumulator."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Hour 13: First cycle - counters missing
		now1 = datetime.datetime(2026, 3, 31, 13, 5, 0)
		epcube_data1 = make_epcube_data(
			battery_soc=50,
			grid_electricity_kwh=None,  # Missing!
			solar_electricity_kwh=None,
			smart_home_electricity_kwh=None,
		)
		result1 = make_decision_result()
		logger.record_cycle(now1, epcube_data1, 12.0, 10.0, result1, config)

		# Hour 13: Second cycle - counters still missing
		now1b = datetime.datetime(2026, 3, 31, 13, 10, 0)
		epcube_data1b = make_epcube_data(
			battery_soc=51,
			grid_electricity_kwh=None,
			solar_electricity_kwh=None,
			smart_home_electricity_kwh=None,
		)
		result1b = make_decision_result()
		logger.record_cycle(now1b, epcube_data1b, 12.0, 10.0, result1b, config)

		# Hour 14: flush hour 13
		now2 = datetime.datetime(2026, 3, 31, 14, 5, 0)
		epcube_data2 = make_epcube_data(battery_soc=55)
		result2 = make_decision_result()
		logger.record_cycle(now2, epcube_data2, 13.0, 10.5, result2, config)

		# Read CSV
		with open(csv_path, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)
		assert len(rows) == 1
		row = rows[0]
		# should use power fallback because counters were None
		assert row["used_fallback_power_integration"] == "True"

	#============================================
	def test_battery_charge_discharge_from_soc(self, tmp_path):
		"""Charge/discharge derived from SoC delta."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Hour 13: Cycle 1 - SoC at 50%
		now1 = datetime.datetime(2026, 3, 31, 13, 5, 0)
		epcube_data1 = make_epcube_data(battery_soc=50)
		result1 = make_decision_result()
		logger.record_cycle(now1, epcube_data1, 12.0, 10.0, result1, config)

		# Hour 13: Cycle 2 - SoC charged to 70%
		now1b = datetime.datetime(2026, 3, 31, 13, 30, 0)
		epcube_data1b = make_epcube_data(battery_soc=70)
		result1b = make_decision_result()
		logger.record_cycle(now1b, epcube_data1b, 12.0, 10.0, result1b, config)

		# Hour 14: Cycle 1 - triggers flush of hour 13
		now2 = datetime.datetime(2026, 3, 31, 14, 5, 0)
		epcube_data2 = make_epcube_data(battery_soc=70)
		result2 = make_decision_result()
		logger.record_cycle(now2, epcube_data2, 13.0, 10.5, result2, config)

		# Read CSV - hour 13 should be flushed
		with open(csv_path, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)
		assert len(rows) == 1
		row = rows[0]
		# Hour 13: SoC went from 50% to 70% = +20%
		# 20% of 20 kWh = 4 kWh charged
		assert float(row["battery_charge_kwh"]) == 4.0
		assert float(row["battery_discharge_kwh"]) == 0.0

		# Hour 14: Cycle 2 - SoC discharges to 40%
		now2b = datetime.datetime(2026, 3, 31, 14, 30, 0)
		epcube_data2b = make_epcube_data(battery_soc=40)
		result2b = make_decision_result()
		logger.record_cycle(now2b, epcube_data2b, 13.0, 10.5, result2b, config)

		# Hour 15: Cycle 1 - triggers flush of hour 14
		now3 = datetime.datetime(2026, 3, 31, 15, 5, 0)
		epcube_data3 = make_epcube_data(battery_soc=40)
		result3 = make_decision_result()
		logger.record_cycle(now3, epcube_data3, 14.0, 11.0, result3, config)

		# Read CSV again
		with open(csv_path, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)
		assert len(rows) == 2
		row2 = rows[1]
		# Hour 14: SoC went from 70% to 40% = -30%
		# 30% of 20 kWh = 6 kWh discharged
		assert float(row2["battery_discharge_kwh"]) == 6.0
		assert float(row2["battery_charge_kwh"]) == 0.0

	#============================================
	def test_partial_hour_no_flush(self, tmp_path):
		"""Session ending mid-hour does not write partial row."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Single cycle in hour 13
		now = datetime.datetime(2026, 3, 31, 13, 30, 0)
		epcube_data = make_epcube_data(battery_soc=50)
		result = make_decision_result()
		logger.record_cycle(now, epcube_data, 12.0, 10.0, result, config)

		# No flush called, session ends
		assert not os.path.exists(csv_path)

	#============================================
	def test_csv_column_count(self, tmp_path):
		"""Written row has exactly 16 columns."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Hour 13
		now1 = datetime.datetime(2026, 3, 31, 13, 30, 0)
		epcube_data1 = make_epcube_data(battery_soc=50)
		result1 = make_decision_result()
		logger.record_cycle(now1, epcube_data1, 12.0, 10.0, result1, config)

		# Hour 14 triggers flush
		now2 = datetime.datetime(2026, 3, 31, 14, 5, 0)
		epcube_data2 = make_epcube_data(battery_soc=55)
		result2 = make_decision_result()
		logger.record_cycle(now2, epcube_data2, 13.0, 10.5, result2, config)

		# Read CSV
		with open(csv_path, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)
		assert len(rows) == 1
		row = rows[0]
		assert len(row) == len(logger_mod.CSV_COLUMNS)
		assert len(logger_mod.CSV_COLUMNS) == 16

	#============================================
	def test_action_and_mode_logged(self, tmp_path):
		"""Latest action and mode are recorded."""
		csv_path = str(tmp_path / "hourly.csv")
		logger = logger_mod.HourlyLogger(csv_path=csv_path)

		config = {"battery_capacity_kwh": 20.0, "season": "auto"}

		# Hour 13 with DISCHARGE_ENABLED action
		now1 = datetime.datetime(2026, 3, 31, 13, 30, 0)
		epcube_data1 = make_epcube_data(battery_soc=50)
		result1 = make_decision_result(
			action="discharge_enabled",
			target_mode="self_consumption",
			soc_floor=30,
		)
		logger.record_cycle(now1, epcube_data1, 12.0, 10.0, result1, config)

		# Hour 14 triggers flush
		now2 = datetime.datetime(2026, 3, 31, 14, 5, 0)
		epcube_data2 = make_epcube_data(battery_soc=55)
		result2 = make_decision_result()
		logger.record_cycle(now2, epcube_data2, 13.0, 10.5, result2, config)

		# Read CSV
		with open(csv_path, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)
		row = rows[0]
		assert row["policy_action"] == "discharge_enabled"
		assert row["epcube_mode"] == "self_consumption"
		assert int(row["reserve_soc"]) == 30
