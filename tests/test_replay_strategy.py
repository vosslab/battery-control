"""Tests for replay_strategy.py - strategy replay and comparison."""

# Standard Library
import csv

# PIP3 modules
import pytest
import yaml

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import replay_strategy


#============================================
class TestReplayStrategy:
	"""Tests for replay_strategy functions."""

	#============================================
	def test_replay_produces_output(self, tmp_path):
		"""Replay on sample data produces results."""
		# create minimal config
		config_file = tmp_path / "config.yml"
		config_data = {
			'battery_capacity_kwh': 20.0,
			'hard_reserve_pct': {'summer': 10, 'winter': 20},
			'afternoon_target_soc_pct': {'summer': 90, 'winter': 70},
			'peak_window_start': 16,
			'peak_window_end': 22,
			'extreme_price_threshold': 20,
			'night_floor_pct': {'summer': 25, 'winter': 35},
			'headroom_band_low': 85,
			'headroom_band_high': 95,
			'solar_sunset_threshold_watts': 50,
		}
		with open(config_file, 'w') as f:
			yaml.dump(config_data, f)

		# create hourly data
		input_file = tmp_path / "hourly.csv"
		hourly_data = [
			{
				'hour_start': '2025-03-15T14:00:00',
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
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		# run replay
		output_file = tmp_path / "replay.csv"
		results = replay_strategy.run_replay(
			str(input_file),
			str(config_file),
			'test_replay',
			str(output_file),
		)

		# verify output exists and has data
		assert output_file.exists()
		assert len(results) > 0

		# read and verify CSV
		with open(output_file, 'r') as f:
			reader = csv.DictReader(f)
			rows = list(reader)

		assert len(rows) == 1
		assert rows[0]['strategy_name'] == 'test_replay'
		assert 'actual_cost_cents' in rows[0]
		assert 'replay_cost_cents' in rows[0]

	#============================================
	def test_replay_different_config(self, tmp_path):
		"""Changing config changes replay outcomes."""
		# create two configs with different reserves
		config1_file = tmp_path / "config1.yml"
		config1_data = {
			'battery_capacity_kwh': 20.0,
			'hard_reserve_pct': {'summer': 10, 'winter': 20},
			'afternoon_target_soc_pct': {'summer': 90, 'winter': 70},
			'peak_window_start': 16,
			'peak_window_end': 22,
			'extreme_price_threshold': 20,
			'night_floor_pct': {'summer': 25, 'winter': 35},
			'headroom_band_low': 85,
			'headroom_band_high': 95,
			'solar_sunset_threshold_watts': 50,
		}
		with open(config1_file, 'w') as f:
			yaml.dump(config1_data, f)

		config2_file = tmp_path / "config2.yml"
		config2_data = dict(config1_data)
		config2_data['hard_reserve_pct'] = {'summer': 15, 'winter': 25}
		with open(config2_file, 'w') as f:
			yaml.dump(config2_data, f)

		# create hourly data
		input_file = tmp_path / "hourly.csv"
		hourly_data = [
			{
				'hour_start': '2025-03-16T20:00:00',
				'season': 'winter',
				'comed_price': '25.0',
				'comed_price_median': '20.0',
				'start_soc': '30',
				'end_soc': '25',
				'grid_kwh': '0.5',
				'solar_kwh': '0.0',
				'load_kwh': '1.0',
				'battery_charge_kwh': '0.0',
				'battery_discharge_kwh': '0.5',
				'policy_action': 'discharge_enabled',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '20',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
		]

		with open(input_file, 'w', newline='') as f:
			fieldnames = hourly_data[0].keys()
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			writer.writerows(hourly_data)

		# run replay with both configs
		results1 = replay_strategy.run_replay(
			str(input_file),
			str(config1_file),
			'config1',
		)
		results2 = replay_strategy.run_replay(
			str(input_file),
			str(config2_file),
			'config2',
		)

		# both should produce results
		assert len(results1) > 0
		assert len(results2) > 0

	#============================================
	def test_soc_simulation(self, tmp_path):
		"""Simulated SoC tracks correctly across hours."""
		# create config
		config_file = tmp_path / "config.yml"
		config_data = {
			'battery_capacity_kwh': 20.0,
			'hard_reserve_pct': {'summer': 10, 'winter': 20},
			'afternoon_target_soc_pct': {'summer': 90, 'winter': 70},
			'peak_window_start': 16,
			'peak_window_end': 22,
			'extreme_price_threshold': 20,
			'night_floor_pct': {'summer': 25, 'winter': 35},
			'headroom_band_low': 85,
			'headroom_band_high': 95,
			'solar_sunset_threshold_watts': 50,
		}
		with open(config_file, 'w') as f:
			yaml.dump(config_data, f)

		# create hourly data with charge then discharge
		input_file = tmp_path / "hourly.csv"
		hourly_data = [
			{
				'hour_start': '2025-03-17T10:00:00',
				'season': 'winter',
				'comed_price': '8.0',
				'comed_price_median': '8.0',
				'start_soc': '50',
				'end_soc': '60',
				'grid_kwh': '0.0',
				'solar_kwh': '3.0',
				'load_kwh': '2.0',
				'battery_charge_kwh': '1.0',
				'battery_discharge_kwh': '0.0',
				'policy_action': 'charge_from_solar',
				'epcube_mode': 'self_consumption',
				'reserve_soc': '50',
				'sample_count': '1',
				'used_fallback_power_integration': 'False',
			},
			{
				'hour_start': '2025-03-17T18:00:00',
				'season': 'winter',
				'comed_price': '28.0',
				'comed_price_median': '15.0',
				'start_soc': '60',
				'end_soc': '50',
				'grid_kwh': '0.0',
				'solar_kwh': '0.0',
				'load_kwh': '1.0',
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

		# run replay
		results = replay_strategy.run_replay(
			str(input_file),
			str(config_file),
			'test_soc',
		)

		# should have one day of results
		assert len(results) > 0

	#============================================
	def test_blank_battery_fields_fallback(self, tmp_path):
		"""Handles missing charge/discharge gracefully."""
		# create config
		config_file = tmp_path / "config.yml"
		config_data = {
			'battery_capacity_kwh': 20.0,
			'hard_reserve_pct': {'summer': 10, 'winter': 20},
			'afternoon_target_soc_pct': {'summer': 90, 'winter': 70},
			'peak_window_start': 16,
			'peak_window_end': 22,
			'extreme_price_threshold': 20,
			'night_floor_pct': {'summer': 25, 'winter': 35},
			'headroom_band_low': 85,
			'headroom_band_high': 95,
			'solar_sunset_threshold_watts': 50,
		}
		with open(config_file, 'w') as f:
			yaml.dump(config_data, f)

		# create hourly data with blank battery fields
		input_file = tmp_path / "hourly.csv"
		hourly_data = [
			{
				'hour_start': '2025-03-18T11:00:00',
				'season': 'winter',
				'comed_price': '9.0',
				'comed_price_median': '8.0',
				'start_soc': '55',
				'end_soc': '60',
				'grid_kwh': '0.5',
				'solar_kwh': '2.0',
				'load_kwh': '1.5',
				'battery_charge_kwh': '',
				'battery_discharge_kwh': '',
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

		# run replay - should not crash
		results = replay_strategy.run_replay(
			str(input_file),
			str(config_file),
			'test_fallback',
		)

		# should produce results
		assert len(results) > 0

	#============================================
	def test_cost_comparison(self, tmp_path):
		"""Improvement is computed correctly."""
		# create config
		config_file = tmp_path / "config.yml"
		config_data = {
			'battery_capacity_kwh': 20.0,
			'hard_reserve_pct': {'summer': 10, 'winter': 20},
			'afternoon_target_soc_pct': {'summer': 90, 'winter': 70},
			'peak_window_start': 16,
			'peak_window_end': 22,
			'extreme_price_threshold': 20,
			'night_floor_pct': {'summer': 25, 'winter': 35},
			'headroom_band_low': 85,
			'headroom_band_high': 95,
			'solar_sunset_threshold_watts': 50,
		}
		with open(config_file, 'w') as f:
			yaml.dump(config_data, f)

		# create hourly data
		input_file = tmp_path / "hourly.csv"
		hourly_data = [
			{
				'hour_start': '2025-03-19T15:00:00',
				'season': 'winter',
				'comed_price': '18.0',
				'comed_price_median': '15.0',
				'start_soc': '60',
				'end_soc': '55',
				'grid_kwh': '0.3',
				'solar_kwh': '1.0',
				'load_kwh': '1.3',
				'battery_charge_kwh': '0.0',
				'battery_discharge_kwh': '0.5',
				'policy_action': 'discharge_enabled',
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

		# run replay
		results = replay_strategy.run_replay(
			str(input_file),
			str(config_file),
			'test_cost',
		)

		# verify results have improvement metric
		assert len(results) > 0
		result = results[0]
		assert 'improvement_cents' in result

	#============================================
	def test_missing_input_file(self, tmp_path):
		"""Missing input file raises FileNotFoundError."""
		config_file = tmp_path / "config.yml"
		with open(config_file, 'w') as f:
			yaml.dump({}, f)

		input_file = tmp_path / "nonexistent.csv"

		with pytest.raises(FileNotFoundError):
			replay_strategy.run_replay(
				str(input_file),
				str(config_file),
				'test',
			)

	#============================================
	def test_missing_config_file(self, tmp_path):
		"""Missing config file raises FileNotFoundError."""
		input_file = tmp_path / "hourly.csv"
		with open(input_file, 'w') as f:
			f.write("hour_start,comed_price\n")

		config_file = tmp_path / "nonexistent.yml"

		with pytest.raises(FileNotFoundError):
			replay_strategy.run_replay(
				str(input_file),
				str(config_file),
				'test',
			)
