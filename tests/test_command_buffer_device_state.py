"""Tests for device-state-aware command buffer suppression."""

# Standard Library
import sys
import datetime

# PIP3 modules
import pytest

# local repo modules
import file_utils

REPO_ROOT = file_utils.get_repo_root()
sys.path.insert(0, REPO_ROOT)

import battcontrol.command_buffer as command_buffer_mod
import battcontrol.state as state_mod


# minimal config shared across tests
CONFIG = {
	"reserve_soc_buffer_pct": 5,
	"epcube_resend_interval_minutes": 60,
}

NOW = datetime.datetime(2026, 4, 22, 12, 0, 0)


#============================================
@pytest.fixture
def control_state(tmp_path) -> state_mod.ControlState:
	"""Fresh in-memory ControlState backed by a tmp_path file."""
	state_file = tmp_path / "state.json"
	return state_mod.ControlState(file_path=str(state_file))


#============================================
def test_device_matches_desired_suppresses(control_state):
	"""Device already at desired mode and reserve -> suppress."""
	should_send, reason = command_buffer_mod.should_send_epcube_update(
		desired_mode="self_consumption",
		desired_reserve_soc=45,
		control_state=control_state,
		config=CONFIG,
		now=NOW,
		device_mode="self_consumption",
		device_reserve_soc=45,
	)
	assert should_send is False
	assert "unchanged" in reason


#============================================
def test_device_reserve_within_buffer_suppresses(control_state):
	"""Delta below buffer_pct -> suppress even though values differ."""
	should_send, _ = command_buffer_mod.should_send_epcube_update(
		desired_mode="self_consumption",
		desired_reserve_soc=47,
		control_state=control_state,
		config=CONFIG,
		now=NOW,
		device_mode="self_consumption",
		device_reserve_soc=45,
	)
	assert should_send is False


#============================================
def test_device_reserve_beyond_buffer_sends(control_state):
	"""Delta >= buffer_pct -> send."""
	should_send, reason = command_buffer_mod.should_send_epcube_update(
		desired_mode="self_consumption",
		desired_reserve_soc=50,
		control_state=control_state,
		config=CONFIG,
		now=NOW,
		device_mode="self_consumption",
		device_reserve_soc=45,
	)
	assert should_send is True
	assert "reserve SoC change" in reason


#============================================
def test_device_mode_mismatch_sends(control_state):
	"""Mode disagreement -> send regardless of reserve."""
	should_send, reason = command_buffer_mod.should_send_epcube_update(
		desired_mode="self_consumption",
		desired_reserve_soc=50,
		control_state=control_state,
		config=CONFIG,
		now=NOW,
		device_mode="backup",
		device_reserve_soc=50,
	)
	assert should_send is True
	assert "mode mismatch" in reason


#============================================
def test_no_device_state_falls_back_to_local_memory(control_state):
	"""
	device_mode=None -> old local-memory path.

	With a fresh control_state (no previous state), the legacy path
	returns True via rule 4 ('first command: no previous state').
	"""
	should_send, reason = command_buffer_mod.should_send_epcube_update(
		desired_mode="self_consumption",
		desired_reserve_soc=50,
		control_state=control_state,
		config=CONFIG,
		now=NOW,
		device_mode=None,
		device_reserve_soc=None,
	)
	assert should_send is True
	assert "first command" in reason


#============================================
def test_flap_scenario_two_hosts_converge(control_state):
	"""
	Simulate two hosts alternating against a shared device state.

	If host A writes reserve 100 and host B later writes reserve 40,
	A's next cycle (computing desired=100) should see device=40 and
	send once; after that the device reports 100 again and A's
	subsequent same-intent cycle should suppress. No infinite flap.
	"""

	device_reserve = 40
	# host A cycle 1: desired 100, device at 40 -> sends
	should_send, _ = command_buffer_mod.should_send_epcube_update(
		desired_mode="self_consumption",
		desired_reserve_soc=100,
		control_state=control_state,
		config=CONFIG,
		now=NOW,
		device_mode="self_consumption",
		device_reserve_soc=device_reserve,
	)
	assert should_send is True
	# device is now 100 (after A's write); A cycle 2 with same intent -> suppress
	device_reserve = 100
	should_send, _ = command_buffer_mod.should_send_epcube_update(
		desired_mode="self_consumption",
		desired_reserve_soc=100,
		control_state=control_state,
		config=CONFIG,
		now=NOW + datetime.timedelta(minutes=5),
		device_mode="self_consumption",
		device_reserve_soc=device_reserve,
	)
	assert should_send is False
