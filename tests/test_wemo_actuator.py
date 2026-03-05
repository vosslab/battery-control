"""Tests for wemo_actuator.py - WeMo smart plug control."""

# Standard Library

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.decision_engine as decision_engine
import battcontrol.wemo_actuator as wemo_actuator


#============================================
class TestExecuteWemo:
	"""Tests for execute_wemo function."""

	#============================================
	def test_no_plugs_configured(self):
		"""No WeMo plugs configured returns False."""
		config = {"wemo_charge_plug_name": "", "wemo_discharge_plug_name": ""}
		result = wemo_actuator.execute_wemo(
			decision_engine.Action.HOLD, config, dry_run=True
		)
		assert result is False

	#============================================
	def test_charge_from_grid_dry_run(self):
		"""CHARGE_FROM_GRID in dry run logs correctly."""
		config = {
			"wemo_charge_plug_name": "Charger",
			"wemo_discharge_plug_name": "Discharger",
		}
		result = wemo_actuator.execute_wemo(
			decision_engine.Action.CHARGE_FROM_GRID, config, dry_run=True
		)
		assert result is True

	#============================================
	def test_discharge_dry_run(self):
		"""ALLOW_DISCHARGE in dry run logs correctly."""
		config = {
			"wemo_charge_plug_name": "Charger",
			"wemo_discharge_plug_name": "Discharger",
		}
		result = wemo_actuator.execute_wemo(
			decision_engine.Action.ALLOW_DISCHARGE, config, dry_run=True
		)
		assert result is True

	#============================================
	def test_hold_dry_run(self):
		"""HOLD in dry run turns off both plugs."""
		config = {
			"wemo_charge_plug_name": "Charger",
			"wemo_discharge_plug_name": "Discharger",
		}
		result = wemo_actuator.execute_wemo(
			decision_engine.Action.HOLD, config, dry_run=True
		)
		assert result is True

	#============================================
	def test_force_no_discharge_dry_run(self):
		"""FORCE_NO_DISCHARGE in dry run turns off both plugs."""
		config = {
			"wemo_charge_plug_name": "Charger",
			"wemo_discharge_plug_name": "Discharger",
		}
		result = wemo_actuator.execute_wemo(
			decision_engine.Action.FORCE_NO_DISCHARGE, config, dry_run=True
		)
		assert result is True
