"""Tests for command_buffer.py - deadband logic and mode-change detection."""

# Standard Library
import datetime

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.command_buffer as cb_mod


#============================================
class MockControlState:
	"""Mock ControlState for testing."""

	#============================================
	def __init__(self, mode="", reserve_soc=None, command_at=None):
		"""
		Initialize mock control state.

		Args:
			mode: last_epcube_mode (default "").
			reserve_soc: last_epcube_reserve_soc (default None).
			command_at: last_epcube_command_at ISO timestamp (default None).
		"""
		self.last_epcube_mode = mode
		self.last_epcube_reserve_soc = reserve_soc
		self.last_epcube_command_at = command_at


#============================================
class TestCommandBuffer:
	"""Tests for command buffer deadband logic."""

	#============================================
	def test_same_mode_same_reserve_no_update(self):
		"""Same mode + same reserve -> no update."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 60, state, config, now
		)
		assert should_send is False
		assert "unchanged" in reason
		assert "buffer" in reason

	#============================================
	def test_same_mode_reserve_below_buffer_no_update(self):
		"""Same mode + reserve change below buffer -> no update."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# desire 61%, change is 1%, buffer is 2%, no update
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 61, state, config, now
		)
		assert should_send is False
		assert "unchanged" in reason

	#============================================
	def test_same_mode_reserve_at_buffer_threshold_sends_update(self):
		"""Same mode + reserve change at buffer threshold -> send update."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# desire 62%, change is 2%, equals buffer, should send
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 62, state, config, now
		)
		assert should_send is True
		assert "reserve SoC changed" in reason
		assert "delta 2%" in reason

	#============================================
	def test_same_mode_reserve_above_buffer_sends_update(self):
		"""Same mode + reserve change above buffer -> send update."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# desire 65%, change is 5%, exceeds buffer, should send
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 65, state, config, now
		)
		assert should_send is True
		assert "reserve SoC changed" in reason
		assert "delta 5%" in reason

	#============================================
	def test_mode_changed_sends_update(self):
		"""Mode changed -> send update regardless of reserve."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# change mode but keep same reserve
		should_send, reason = cb_mod.should_send_epcube_update(
			"backup", 60, state, config, now
		)
		assert should_send is True
		assert "mode changed" in reason
		assert "self_consumption" in reason
		assert "backup" in reason

	#============================================
	def test_mode_changed_and_reserve_changed_sends_update(self):
		"""Mode changed + reserve changed -> send update."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"backup", 55, state, config, now
		)
		assert should_send is True
		assert "mode changed" in reason

	#============================================
	def test_resend_interval_disabled_stays_unchanged(self):
		"""Resend interval disabled (0) + unchanged -> stays unchanged."""
		# Make command_at old (shouldn't matter if interval is 0)
		old_time = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
		state = MockControlState(
			mode="self_consumption", reserve_soc=60, command_at=old_time
		)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 60, state, config, now
		)
		assert should_send is False
		assert "unchanged" in reason

	#============================================
	def test_resend_interval_enabled_not_expired_no_update(self):
		"""Resend interval enabled (30 min) and not expired -> no update."""
		# Recent timestamp (5 minutes ago)
		recent_time = (datetime.datetime.now() - datetime.timedelta(minutes=5)).isoformat()
		state = MockControlState(
			mode="self_consumption", reserve_soc=60, command_at=recent_time
		)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 30}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 60, state, config, now
		)
		assert should_send is False
		assert "unchanged" in reason

	#============================================
	def test_resend_interval_enabled_expired_sends_update(self):
		"""Resend interval enabled (30 min) and expired -> send update."""
		# Old timestamp (40 minutes ago)
		old_time = (datetime.datetime.now() - datetime.timedelta(minutes=40)).isoformat()
		state = MockControlState(
			mode="self_consumption", reserve_soc=60, command_at=old_time
		)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 30}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 60, state, config, now
		)
		assert should_send is True
		assert "resend interval expired" in reason

	#============================================
	def test_first_command_empty_mode_sends_update(self):
		"""First-ever command (last_epcube_mode is "") -> send update."""
		state = MockControlState(mode="", reserve_soc=None)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 60, state, config, now
		)
		assert should_send is True
		assert "first command" in reason

	#============================================
	def test_first_command_none_reserve_sends_update(self):
		"""First-ever command (last_epcube_reserve_soc is None) -> send update."""
		state = MockControlState(mode="self_consumption", reserve_soc=None)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 60, state, config, now
		)
		assert should_send is True
		assert "first command" in reason

	#============================================
	def test_custom_buffer_pct_config(self):
		"""Custom buffer percentage is respected."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 5, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# reserve change is 3%, buffer is 5%, no update
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 63, state, config, now
		)
		assert should_send is False
		assert "5% buffer" in reason

	#============================================
	def test_custom_buffer_pct_exceeds_threshold(self):
		"""Custom buffer pct: change above custom threshold sends update."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 5, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# reserve change is 6%, buffer is 5%, should send
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 66, state, config, now
		)
		assert should_send is True
		assert "reserve SoC changed" in reason

	#============================================
	def test_negative_reserve_change_uses_absolute_value(self):
		"""Negative reserve change (decreasing SoC) uses absolute value."""
		state = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# reserve drops from 60 to 57 (delta 3), exceeds buffer
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 57, state, config, now
		)
		assert should_send is True
		assert "reserve SoC changed" in reason

	#============================================
	def test_resend_interval_with_none_command_at_expired(self):
		"""Resend interval enabled but last_command_at is None -> send update."""
		state = MockControlState(
			mode="self_consumption", reserve_soc=60, command_at=None
		)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 30}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 60, state, config, now
		)
		assert should_send is True
		assert "resend interval expired" in reason

	#============================================
	def test_large_time_gap_exceeds_resend_interval(self):
		"""Large time gap (days ago) exceeds resend interval -> send update."""
		old_time = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat()
		state = MockControlState(
			mode="self_consumption", reserve_soc=60, command_at=old_time
		)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 30}
		now = datetime.datetime.now()
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 60, state, config, now
		)
		assert should_send is True
		assert "resend interval expired" in reason

	#============================================
	def test_multiple_modes_changes_over_calls(self):
		"""Multiple sequential mode changes are detected."""
		# First transition
		state1 = MockControlState(mode="self_consumption", reserve_soc=60)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		should_send1, _ = cb_mod.should_send_epcube_update(
			"backup", 60, state1, config, now
		)
		assert should_send1 is True
		# Second transition (mode changed again)
		state2 = MockControlState(mode="backup", reserve_soc=60)
		should_send2, _ = cb_mod.should_send_epcube_update(
			"charge_limit", 60, state2, config, now
		)
		assert should_send2 is True
		# Same mode (no change) - update state to reflect sent command
		state3 = MockControlState(mode="charge_limit", reserve_soc=60)
		should_send3, reason = cb_mod.should_send_epcube_update(
			"charge_limit", 60, state3, config, now
		)
		assert should_send3 is False
		assert "unchanged" in reason

	#============================================
	def test_zero_reserve_soc_values(self):
		"""Handle zero reserve SoC correctly."""
		state = MockControlState(mode="self_consumption", reserve_soc=0)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# change from 0 to 3, delta is 3, exceeds buffer
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 3, state, config, now
		)
		assert should_send is True
		assert "reserve SoC changed" in reason

	#============================================
	def test_max_reserve_soc_values(self):
		"""Handle max reserve SoC (100%) correctly."""
		state = MockControlState(mode="self_consumption", reserve_soc=100)
		config = {"reserve_soc_buffer_pct": 2, "epcube_resend_interval_minutes": 0}
		now = datetime.datetime.now()
		# change from 100 to 98, delta is 2, equals buffer
		should_send, reason = cb_mod.should_send_epcube_update(
			"self_consumption", 98, state, config, now
		)
		assert should_send is True
		assert "reserve SoC changed" in reason
