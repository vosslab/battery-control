"""Tests for deadband previous_state derived from device reserve."""

# Standard Library
import sys
import datetime

# PIP3 modules
import pytest

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()
sys.path.insert(0, REPO_ROOT)

import battcontrol.config as config_mod
import battcontrol.decision_engine as decision_engine_mod
import battcontrol.strategy as strategy_mod
import battcontrol.state as state_mod


NOW = datetime.datetime(2026, 4, 22, 12, 0, 0)


#============================================
@pytest.fixture
def control_state(tmp_path) -> state_mod.ControlState:
	"""Fresh in-memory ControlState backed by a tmp_path file."""
	state_file = tmp_path / "state.json"
	return state_mod.ControlState(file_path=str(state_file))


#============================================
def _run_decide(device_reserve_soc, control_state):
	"""Call decide with deadband-edge price so previous_state drives outcome."""
	config = config_mod.get_defaults()
	# pin the deadband width so the test does not depend on default tuning
	config["cutoff_buffer_cents"] = 0.5
	result = decision_engine_mod.decide(
		battery_soc=60,
		solar_power_watts=0,
		load_power_watts=500,
		# price exactly at cutoff -> inside deadband, previous_state decides
		comed_price_cents=10.0,
		comed_median_cents=10.0,
		comed_cutoff_cents=10.0,
		config=config,
		control_state=control_state,
		current_time=NOW,
		device_reserve_soc=device_reserve_soc,
	)
	return result


#============================================
def test_device_reserve_100_maps_to_below_cutoff(control_state):
	"""Device at full reserve means last effective decision was BELOW_CUTOFF."""
	result = _run_decide(device_reserve_soc=100, control_state=control_state)
	assert result.state == strategy_mod.StrategyState.BELOW_CUTOFF


#============================================
def test_device_reserve_below_100_maps_to_above_cutoff(control_state):
	"""Any reserve < 100 means last effective decision was ABOVE_CUTOFF."""
	result = _run_decide(device_reserve_soc=40, control_state=control_state)
	assert result.state == strategy_mod.StrategyState.ABOVE_CUTOFF


#============================================
def test_no_device_reserve_uses_local_state(control_state):
	"""
	device_reserve_soc=None -> fall back to control_state.last_strategy_state.

	Seed the local state as ABOVE_CUTOFF and confirm it survives the
	deadband when the device hint is absent.
	"""
	control_state.last_strategy_state = strategy_mod.StrategyState.ABOVE_CUTOFF.value
	result = _run_decide(device_reserve_soc=None, control_state=control_state)
	assert result.state == strategy_mod.StrategyState.ABOVE_CUTOFF
