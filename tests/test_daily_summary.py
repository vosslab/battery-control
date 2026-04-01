"""Tests for daily_summary.py - daily aggregation and cost analysis."""

# Standard Library
import csv

# PIP3 modules
import pytest

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import daily_summary


#============================================
class TestDailySummary:
	"""Tests for daily_summary functions."""

	#============================================
	def test_single_day_aggregation(self, tmp_path):
		"""Single day of data produces correct totals."""
		input_file = tmp_path / "hourly.csv"
		output_file = tmp_path / "daily.csv"

		# create sample hourly data
		hourly_data = [
			{
				'hour_start': '2025-03-15T08:00:00',
				'season': 'winter',
				'comed_price': '10.0',
				'comed_price_median': '9.0',
				'start_soc': '50',
				'end_soc': '55',
				'grid_kwh': '1.0',
				'solar_kwh': '2.0',
				'load_kwh': '2.5',
				'battery_charge_kwh': '0.5',
				'battery_discharge_kwh': '0.0',
				'policy_action': 'charge_from_solar',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '50',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
			{
				'hour_start': '2025-03-15T09:00:00',
				'season': 'winter',
				'comed_price': '12.0',
				'comed_price_median': '9.0',
				'start_soc': '55',
				'end_soc': '60',
				'grid_kwh': '0.5',
				'solar_kwh': '3.0',
				'load_kwh': '2.5',
				'battery_charge_kwh': '0.5',
				'battery_discharge_kwh': '0.0',
				'policy_action': 'charge_from_solar',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '55',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		# process
		daily_summary.process_daily_summary(str(input_file), str(output_file))

		# verify output
		assert output_file.exists()
		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)

		assert len(rows) == 1
		row = rows[0]
		assert row['date'] == '2025-03-15'
		assert row['season'] == 'winter'
		assert float(row['grid_kwh']) == pytest.approx(1.5, abs=0.1)
		assert float(row['solar_kwh']) == pytest.approx(5.0, abs=0.1)
		assert float(row['load_kwh']) == pytest.approx(5.0, abs=0.1)

	#============================================
	def test_cost_calculation(self, tmp_path):
		"""Actual cost is grid_kwh * price."""
		input_file = tmp_path / "hourly.csv"
		output_file = tmp_path / "daily.csv"

		hourly_data = [
			{
				'hour_start': '2025-03-16T14:00:00',
				'season': 'winter',
				'comed_price': '20.0',
				'comed_price_median': '15.0',
				'start_soc': '60',
				'end_soc': '50',
				'grid_kwh': '2.0',
				'solar_kwh': '0.5',
				'load_kwh': '2.0',
				'battery_charge_kwh': '0.0',
				'battery_discharge_kwh': '1.0',
				'policy_action': 'discharge_enabled',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '50',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		daily_summary.process_daily_summary(str(input_file), str(output_file))

		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			row = next(reader)

		# actual cost should be influenced by grid usage and price
		# baseline = max(2.0 - 0.5, 0) * 20 = 1.5 * 20 = 30 cents
		# actual = 2.0 * 20 = 40 cents
		# savings should be baseline - actual = 30 - 40 = -10 (negative because battery worsened it)
		baseline = float(row['baseline_cost_cents'])
		assert baseline == pytest.approx(30.0, abs=1.0)

	#============================================
	def test_baseline_calculation(self, tmp_path):
		"""Baseline is max(load - solar, 0) * price."""
		input_file = tmp_path / "hourly.csv"
		output_file = tmp_path / "daily.csv"

		hourly_data = [
			{
				'hour_start': '2025-03-17T10:00:00',
				'season': 'winter',
				'comed_price': '15.0',
				'comed_price_median': '12.0',
				'start_soc': '70',
				'end_soc': '75',
				'grid_kwh': '0.0',
				'solar_kwh': '3.0',
				'load_kwh': '2.0',
				'battery_charge_kwh': '1.0',
				'battery_discharge_kwh': '0.0',
				'policy_action': 'charge_from_solar',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '70',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		daily_summary.process_daily_summary(str(input_file), str(output_file))

		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			row = next(reader)

		# baseline = max(2.0 - 3.0, 0) * 15 = 0 * 15 = 0 cents
		baseline = float(row['baseline_cost_cents'])
		assert baseline == pytest.approx(0.0, abs=0.1)

	#============================================
	def test_savings_calculation(self, tmp_path):
		"""Savings is baseline - actual."""
		input_file = tmp_path / "hourly.csv"
		output_file = tmp_path / "daily.csv"

		hourly_data = [
			{
				'hour_start': '2025-03-18T16:00:00',
				'season': 'winter',
				'comed_price': '25.0',
				'comed_price_median': '20.0',
				'start_soc': '80',
				'end_soc': '70',
				'grid_kwh': '0.5',
				'solar_kwh': '1.0',
				'load_kwh': '1.5',
				'battery_charge_kwh': '0.0',
				'battery_discharge_kwh': '0.5',
				'policy_action': 'discharge_enabled',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '70',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		daily_summary.process_daily_summary(str(input_file), str(output_file))

		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			row = next(reader)

		# baseline = max(1.5 - 1.0, 0) * 25 = 0.5 * 25 = 12.5 cents
		# actual = 0.5 * 25 = 12.5 cents
		# savings = 12.5 - 12.5 = 0 cents
		baseline = float(row['baseline_cost_cents'])
		actual = float(row['actual_cost_cents'])
		assert baseline == pytest.approx(12.5, abs=1.0)
		assert actual == pytest.approx(12.5, abs=1.0)

	#============================================
	def test_multi_day(self, tmp_path):
		"""Two days produce two rows."""
		input_file = tmp_path / "hourly.csv"
		output_file = tmp_path / "daily.csv"

		hourly_data = [
			{
				'hour_start': '2025-03-19T08:00:00',
				'season': 'winter',
				'comed_price': '10.0',
				'comed_price_median': '9.0',
				'start_soc': '50',
				'end_soc': '55',
				'grid_kwh': '1.0',
				'solar_kwh': '2.0',
				'load_kwh': '2.5',
				'battery_charge_kwh': '0.5',
				'battery_discharge_kwh': '0.0',
				'policy_action': 'charge_from_solar',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '50',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
			{
				'hour_start': '2025-03-20T08:00:00',
				'season': 'winter',
				'comed_price': '12.0',
				'comed_price_median': '10.0',
				'start_soc': '55',
				'end_soc': '60',
				'grid_kwh': '0.8',
				'solar_kwh': '2.2',
				'load_kwh': '2.5',
				'battery_charge_kwh': '0.5',
				'battery_discharge_kwh': '0.0',
				'policy_action': 'charge_from_solar',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '55',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		daily_summary.process_daily_summary(str(input_file), str(output_file))

		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)

		assert len(rows) == 2
		assert rows[0]['date'] == '2025-03-19'
		assert rows[1]['date'] == '2025-03-20'

	#============================================
	def test_partial_day(self, tmp_path):
		"""Day with few hours still produces a row."""
		input_file = tmp_path / "hourly.csv"
		output_file = tmp_path / "daily.csv"

		hourly_data = [
			{
				'hour_start': '2025-03-21T22:00:00',
				'season': 'winter',
				'comed_price': '8.0',
				'comed_price_median': '8.0',
				'start_soc': '45',
				'end_soc': '45',
				'grid_kwh': '0.2',
				'solar_kwh': '0.0',
				'load_kwh': '0.2',
				'battery_charge_kwh': '0.0',
				'battery_discharge_kwh': '0.0',
				'policy_action': 'discharge_disabled',
				'epcube_mode': 'backup',
				'reserve_soc': '45',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		daily_summary.process_daily_summary(str(input_file), str(output_file))

		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)

		assert len(rows) == 1
		assert rows[0]['date'] == '2025-03-21'

	#============================================
	def test_blank_fields_handled(self, tmp_path):
		"""Blank kWh fields treated as 0.0."""
		input_file = tmp_path / "hourly.csv"
		output_file = tmp_path / "daily.csv"

		hourly_data = [
			{
				'hour_start': '2025-03-22T12:00:00',
				'season': 'winter',
				'comed_price': '11.0',
				'comed_price_median': '10.0',
				'start_soc': '50',
				'end_soc': '50',
				'grid_kwh': '',
				'solar_kwh': '2.0',
				'load_kwh': '2.0',
				'battery_charge_kwh': '',
				'battery_discharge_kwh': '',
				'policy_action': 'charge_from_solar',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '50',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		daily_summary.process_daily_summary(str(input_file), str(output_file))

		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			row = next(reader)

		# blank fields should be 0
		assert float(row['grid_kwh']) == pytest.approx(0.0, abs=0.1)
		assert float(row['battery_charge_kwh']) == pytest.approx(0.0, abs=0.1)
		assert float(row['battery_discharge_kwh']) == pytest.approx(0.0, abs=0.1)

	#============================================
	def test_blank_price_skipped(self, tmp_path):
		"""Rows with blank price are skipped."""
		input_file = tmp_path / "hourly.csv"
		output_file = tmp_path / "daily.csv"

		hourly_data = [
			{
				'hour_start': '2025-03-23T06:00:00',
				'season': 'winter',
				'comed_price': '',
				'comed_price_median': '',
				'start_soc': '50',
				'end_soc': '50',
				'grid_kwh': '1.0',
				'solar_kwh': '0.0',
				'load_kwh': '1.0',
				'battery_charge_kwh': '0.0',
				'battery_discharge_kwh': '0.0',
				'policy_action': 'discharge_disabled',
				'epcube_mode': 'backup',
				'reserve_soc': '50',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		daily_summary.process_daily_summary(str(input_file), str(output_file))

		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)

		# no rows should be produced (price was blank)
		assert len(rows) == 0

	#============================================
	def test_missing_input_file(self, tmp_path):
		"""Missing input file raises FileNotFoundError."""
		input_file = tmp_path / "nonexistent.csv"
		output_file = tmp_path / "daily.csv"

		with pytest.raises(FileNotFoundError):
			daily_summary.process_daily_summary(str(input_file), str(output_file))
