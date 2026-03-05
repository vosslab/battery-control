"""Tests for state.py - hysteresis and state persistence."""

# Standard Library
import os
import json

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.state as state_mod


#============================================
class TestControlState:
	"""Tests for ControlState class."""

	#============================================
	def test_load_missing_file(self):
		"""Load from missing file returns defaults."""
		cs = state_mod.ControlState("/nonexistent/state.json")
		cs.load()
		assert cs.price_band_counter == 0
		assert cs.current_price_band == ""
		assert cs.last_action == ""
		assert cs.peak_mode_active is False
		assert cs.token_expired is False

	#============================================
	def test_save_and_load(self, tmp_path):
		"""Save state and load it back correctly."""
		state_file = str(tmp_path / "state.json")
		# save state
		cs = state_mod.ControlState(state_file)
		cs.price_band_counter = 3
		cs.current_price_band = "mid_high"
		cs.last_action = "allow_discharge"
		cs.action_stable_count = 2
		cs.peak_mode_active = True
		cs.peak_mode_entered_at = "2025-06-15T17:00:00"
		cs.save()
		# verify file exists
		assert os.path.isfile(state_file)
		# load into new instance
		cs2 = state_mod.ControlState(state_file)
		cs2.load()
		assert cs2.price_band_counter == 3
		assert cs2.current_price_band == "mid_high"
		assert cs2.last_action == "allow_discharge"
		assert cs2.action_stable_count == 2
		assert cs2.peak_mode_active is True
		assert cs2.peak_mode_entered_at == "2025-06-15T17:00:00"

	#============================================
	def test_atomic_save(self, tmp_path):
		"""Save is atomic (uses tmp + rename)."""
		state_file = str(tmp_path / "state.json")
		cs = state_mod.ControlState(state_file)
		cs.price_band_counter = 1
		cs.save()
		# tmp file should not exist after save
		assert not os.path.isfile(state_file + ".tmp")
		# state file should be valid JSON
		with open(state_file, "r") as f:
			data = json.load(f)
		assert data["price_band_counter"] == 1

	#============================================
	def test_reset_daily(self):
		"""reset_daily clears peak mode state."""
		cs = state_mod.ControlState()
		cs.peak_mode_active = True
		cs.peak_mode_entered_at = "2025-06-15T17:00:00"
		cs.reset_daily()
		assert cs.peak_mode_active is False
		assert cs.peak_mode_entered_at is None

	#============================================
	def test_update_price_band_same(self):
		"""Same band increments counter, returns False."""
		cs = state_mod.ControlState()
		cs.current_price_band = "low"
		cs.price_band_counter = 1
		changed = cs.update_price_band("low")
		assert changed is False
		assert cs.price_band_counter == 2

	#============================================
	def test_update_price_band_change(self):
		"""Different band resets counter, returns True."""
		cs = state_mod.ControlState()
		cs.current_price_band = "low"
		cs.price_band_counter = 3
		changed = cs.update_price_band("mid_high")
		assert changed is True
		assert cs.price_band_counter == 1
		assert cs.current_price_band == "mid_high"

	#============================================
	def test_update_action_same(self):
		"""Same action increments stable count."""
		cs = state_mod.ControlState()
		cs.last_action = "hold"
		cs.action_stable_count = 1
		cs.update_action("hold")
		assert cs.action_stable_count == 2

	#============================================
	def test_update_action_change(self):
		"""Different action resets stable count."""
		cs = state_mod.ControlState()
		cs.last_action = "hold"
		cs.action_stable_count = 5
		cs.update_action("allow_discharge")
		assert cs.action_stable_count == 1
		assert cs.last_action == "allow_discharge"

	#============================================
	def test_mark_token_expired(self):
		"""mark_token_expired sets flag and timestamp."""
		cs = state_mod.ControlState()
		cs.mark_token_expired()
		assert cs.token_expired is True
		assert cs.token_expired_at is not None

	#============================================
	def test_mark_token_success(self):
		"""mark_token_success clears expired flag."""
		cs = state_mod.ControlState()
		cs.token_expired = True
		cs.token_expired_at = "2025-06-15T10:00:00"
		cs.mark_token_success()
		assert cs.token_expired is False
		assert cs.token_expired_at is None
		assert cs.token_last_success_at is not None

	#============================================
	def test_to_dict(self):
		"""to_dict returns all state fields."""
		cs = state_mod.ControlState()
		cs.price_band_counter = 2
		cs.current_price_band = "high"
		d = cs.to_dict()
		assert d["price_band_counter"] == 2
		assert d["current_price_band"] == "high"
		assert "token_expired" in d
