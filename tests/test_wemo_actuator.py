"""Tests for wemo_actuator.py - WeMo smart plug control."""

# Standard Library

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.decision_engine
import battcontrol.wemo_actuator


#============================================
class TestExecuteWemo:
	"""Tests for execute_wemo function."""

	#============================================
	def test_no_plugs_configured(self):
		"""No WeMo plugs configured returns False."""
		config = {"wemo_charge_plug_name": "", "wemo_discharge_plug_name": ""}
		result = battcontrol.wemo_actuator.execute_wemo(
			battcontrol.decision_engine.Action.DISCHARGE_DISABLED, config, dry_run=True
		)
		assert result is False
