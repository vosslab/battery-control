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
			decision_engine.Action.DISCHARGE_DISABLED, config, dry_run=True
		)
		assert result is False

	#============================================
	def test_discharge_enabled_dry_run(self):
		"""DISCHARGE_ENABLED in dry run enables discharge plug."""
		config = {
			"wemo_charge_plug_name": "Charger",
			"wemo_discharge_plug_name": "Discharger",
		}
		result = wemo_actuator.execute_wemo(
			decision_engine.Action.DISCHARGE_ENABLED, config, dry_run=True
		)
		assert result is True

	#============================================
	def test_discharge_disabled_dry_run(self):
		"""DISCHARGE_DISABLED in dry run turns off both plugs."""
		config = {
			"wemo_charge_plug_name": "Charger",
			"wemo_discharge_plug_name": "Discharger",
		}
		result = wemo_actuator.execute_wemo(
			decision_engine.Action.DISCHARGE_DISABLED, config, dry_run=True
		)
		assert result is True

	#============================================
	def test_charge_from_solar_dry_run(self):
		"""CHARGE_FROM_SOLAR in dry run turns off both plugs."""
		config = {
			"wemo_charge_plug_name": "Charger",
			"wemo_discharge_plug_name": "Discharger",
		}
		result = wemo_actuator.execute_wemo(
			decision_engine.Action.CHARGE_FROM_SOLAR, config, dry_run=True
		)
		assert result is True
