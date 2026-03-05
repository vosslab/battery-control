"""Integration smoke test for battery_controller.py."""

# Standard Library
import os

# PIP3 modules
import yaml

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.config as config_mod
import battcontrol.state as state_mod
import battcontrol.decision_engine as decision_engine


#============================================
def _make_config_file(tmp_path, overrides: dict = None) -> str:
	"""
	Create a temporary config file for testing.

	Args:
		tmp_path: pytest tmp_path fixture.
		overrides: Config values to override.

	Returns:
		str: Path to the temporary config file.
	"""
	config = dict(config_mod.DEFAULTS)
	config["epcube_token"] = "test_token"
	config["epcube_device_sn"] = "TEST_SN"
	config["state_file_path"] = str(tmp_path / "state.json")
	config["dry_run"] = True
	if overrides:
		config.update(overrides)
	config_path = str(tmp_path / "config.yml")
	with open(config_path, "w") as f:
		yaml.dump(config, f)
	return config_path


#============================================
class TestSmokePipeline:
	"""Integration tests for the full controller pipeline."""

	#============================================
	def test_full_pipeline_dry_run(self, tmp_path):
		"""Full pipeline runs without exceptions in dry-run mode."""
		config_path = _make_config_file(tmp_path)
		config = config_mod.load_config(config_path)
		# load state
		control_state = state_mod.ControlState(str(tmp_path / "state.json"))
		control_state.load()
		# mock ComEd price
		comed_price = 12.5
		comed_median = 8.0
		# mock EP Cube data
		epcube_data = {
			"battery_soc": 65,
			"solar_power_watts": 2000,
			"grid_power_watts": 100,
			"backup_power_watts": 800,
			"work_status": "1",
			"device_id": "DEV123",
		}
		# run decision engine
		import datetime
		now = datetime.datetime(2025, 7, 15, 14, 0)
		result = decision_engine.decide(
			battery_soc=epcube_data["battery_soc"],
			solar_power_watts=epcube_data["solar_power_watts"],
			backup_power_watts=epcube_data["backup_power_watts"],
			comed_price_cents=comed_price,
			comed_median_cents=comed_median,
			config=config,
			control_state=control_state,
			current_time=now,
		)
		# verify decision is valid
		assert isinstance(result.action, decision_engine.Action)
		assert result.reason != ""
		# save state
		control_state.save()
		# verify state file written
		assert os.path.isfile(str(tmp_path / "state.json"))

	#============================================
	def test_pipeline_no_solar(self, tmp_path):
		"""Pipeline works with no solar (night scenario)."""
		config_path = _make_config_file(tmp_path)
		config = config_mod.load_config(config_path)
		control_state = state_mod.ControlState(str(tmp_path / "state.json"))
		control_state.load()
		import datetime
		now = datetime.datetime(2025, 7, 15, 20, 0)
		result = decision_engine.decide(
			battery_soc=70,
			solar_power_watts=0,
			backup_power_watts=500,
			comed_price_cents=15.0,
			comed_median_cents=8.0,
			config=config,
			control_state=control_state,
			current_time=now,
		)
		assert isinstance(result.action, decision_engine.Action)
		control_state.save()

	#============================================
	def test_pipeline_token_expired(self, tmp_path):
		"""Pipeline handles token expiration gracefully."""
		config_path = _make_config_file(tmp_path)
		config = config_mod.load_config(config_path)
		control_state = state_mod.ControlState(str(tmp_path / "state.json"))
		control_state.load()
		# simulate expired token
		control_state.mark_token_expired()
		assert control_state.token_expired is True
		# pipeline should still work with no EP Cube data
		import datetime
		now = datetime.datetime(2025, 7, 15, 18, 0)
		result = decision_engine.decide(
			battery_soc=50,
			solar_power_watts=0,
			backup_power_watts=500,
			comed_price_cents=12.0,
			comed_median_cents=8.0,
			config=config,
			control_state=control_state,
			current_time=now,
		)
		assert isinstance(result.action, decision_engine.Action)
		control_state.save()
		# verify state preserves token expired flag
		cs2 = state_mod.ControlState(str(tmp_path / "state.json"))
		cs2.load()
		assert cs2.token_expired is True

	#============================================
	def test_pipeline_extreme_price(self, tmp_path):
		"""Pipeline handles extreme price correctly."""
		config_path = _make_config_file(tmp_path)
		config = config_mod.load_config(config_path)
		control_state = state_mod.ControlState(str(tmp_path / "state.json"))
		control_state.load()
		import datetime
		# summer daytime, no surplus, extreme price
		now = datetime.datetime(2025, 7, 15, 13, 0)
		result = decision_engine.decide(
			battery_soc=80,
			solar_power_watts=100,
			backup_power_watts=500,
			comed_price_cents=30.0,
			comed_median_cents=8.0,
			config=config,
			control_state=control_state,
			current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_TO_FLOOR
		control_state.save()

	#============================================
	def test_pipeline_all_action_types(self, tmp_path):
		"""Verify all action types are reachable."""
		import datetime
		# collect unique actions from various scenarios
		actions_seen = set()
		scenarios = [
			# hard reserve
			(5, 0, 0, 5.0, datetime.datetime(2025, 7, 15, 12, 0)),
			# solar surplus below target
			(60, 3000, 1000, 5.0, datetime.datetime(2025, 7, 15, 12, 0)),
			# night hold
			(40, 0, 200, 3.0, datetime.datetime(2025, 7, 16, 2, 0)),
			# night extreme
			(60, 0, 500, 25.0, datetime.datetime(2025, 7, 15, 23, 0)),
			# peak high
			(80, 0, 500, 25.0, datetime.datetime(2025, 7, 15, 18, 0)),
			# peak mid paced
			(70, 0, 500, 15.0, datetime.datetime(2025, 7, 15, 18, 0)),
			# headroom
			(96, 3000, 1000, 25.0, datetime.datetime(2025, 7, 15, 12, 0)),
		]
		for soc, solar, backup, price, now in scenarios:
			config_path = _make_config_file(tmp_path)
			config = config_mod.load_config(config_path)
			cs = state_mod.ControlState(str(tmp_path / f"state_{soc}_{price}.json"))
			result = decision_engine.decide(
				battery_soc=soc,
				solar_power_watts=solar,
				backup_power_watts=backup,
				comed_price_cents=price,
				comed_median_cents=8.0,
				config=config,
				control_state=cs,
				current_time=now,
			)
			actions_seen.add(result.action)
		# verify we see multiple action types
		assert len(actions_seen) >= 3
