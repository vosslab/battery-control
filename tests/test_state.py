"""Tests for state.py - command buffer state and persistence."""

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
		assert cs.last_action == ""
		assert cs.token_expired is False
		assert cs.last_epcube_mode == ""
		assert cs.last_epcube_reserve_soc is None
		assert cs.last_epcube_command_at is None

	#============================================
	def test_save_and_load(self, tmp_path):
		"""Save state and load it back correctly."""
		state_file = str(tmp_path / "state.json")
		# save state
		cs = state_mod.ControlState(state_file)
		cs.last_action = "discharge_enabled"
		cs.last_epcube_mode = "self_consumption"
		cs.last_epcube_reserve_soc = 60
		cs.last_epcube_command_at = "2025-06-15T17:00:00"
		cs.save()
		# verify file exists
		assert os.path.isfile(state_file)
		# load into new instance
		cs2 = state_mod.ControlState(state_file)
		cs2.load()
		assert cs2.last_action == "discharge_enabled"
		assert cs2.last_epcube_mode == "self_consumption"
		assert cs2.last_epcube_reserve_soc == 60
		assert cs2.last_epcube_command_at == "2025-06-15T17:00:00"

	#============================================
	def test_atomic_save(self, tmp_path):
		"""Save is atomic (uses tmp + rename)."""
		state_file = str(tmp_path / "state.json")
		cs = state_mod.ControlState(state_file)
		cs.last_epcube_mode = "backup"
		cs.save()
		# tmp file should not exist after save
		assert not os.path.isfile(state_file + ".tmp")
		# state file should be valid JSON
		with open(state_file, "r") as f:
			data = json.load(f)
		assert data["last_epcube_mode"] == "backup"

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
		cs.last_action = "discharge_enabled"
		cs.last_epcube_mode = "self_consumption"
		d = cs.to_dict()
		assert d["last_action"] == "discharge_enabled"
		assert d["last_epcube_mode"] == "self_consumption"
		assert "token_expired" in d
		assert "last_epcube_reserve_soc" in d
		assert "last_epcube_command_at" in d

	#============================================
	def test_round_trip_preserves_all_fields(self, tmp_path):
		"""Save then load preserves all state fields."""
		state_file = str(tmp_path / "state.json")
		cs = state_mod.ControlState(state_file)
		cs.last_action = "discharge_enabled"
		cs.last_epcube_mode = "self_consumption"
		cs.last_epcube_reserve_soc = 55
		cs.last_epcube_command_at = "2025-07-15T16:00:00"
		cs.token_expired = True
		cs.save()
		# load into a fresh instance
		cs2 = state_mod.ControlState(state_file)
		cs2.load()
		assert cs2.last_action == "discharge_enabled"
		assert cs2.last_epcube_mode == "self_consumption"
		assert cs2.last_epcube_reserve_soc == 55
		assert cs2.token_expired is True

	#============================================
	def test_load_ignores_unknown_fields(self, tmp_path):
		"""Load gracefully ignores fields not in _DEFAULT_STATE."""
		state_file = str(tmp_path / "state.json")
		# write JSON with old hysteresis fields
		old_data = {
			"price_segment_counter": 5,
			"current_price_segment": 2,
			"action_stable_count": 3,
			"peak_mode_active": True,
			"last_action": "discharge_enabled",
			"last_epcube_mode": "backup",
		}
		with open(state_file, "w") as f:
			json.dump(old_data, f)
		# load should work without errors
		cs = state_mod.ControlState(state_file)
		cs.load()
		# known fields restored
		assert cs.last_action == "discharge_enabled"
		assert cs.last_epcube_mode == "backup"
		# unknown fields do not become attributes
		assert not hasattr(cs, "price_segment_counter")
		assert not hasattr(cs, "peak_mode_active")

	#============================================
	def test_buffer_state_defaults(self):
		"""New ControlState has correct buffer field defaults."""
		cs = state_mod.ControlState()
		assert cs.last_epcube_mode == ""
		assert cs.last_epcube_reserve_soc is None
		assert cs.last_epcube_command_at is None
		assert cs.last_commanded_floor is None
