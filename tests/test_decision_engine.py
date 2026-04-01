"""Tests for decision_engine.py - thin orchestrator calling strategy.

Only tests orchestrator mechanics (returns DecisionResult, updates state).
Strategy decisions are tested in test_strategy.py.
"""

# Standard Library
import datetime

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.config as config_mod
import battcontrol.state as state_mod
import battcontrol.decision_engine as decision_engine


#============================================
def _make_state() -> state_mod.ControlState:
	"""Create a fresh ControlState for testing."""
	cs = state_mod.ControlState()
	return cs


#============================================
def _make_config() -> dict:
	"""Create a default config for testing."""
	return dict(config_mod.DEFAULTS)


#============================================
class TestDecideReturnsResult:
	"""Tests that decide() returns a well-formed DecisionResult."""

	#============================================
	def test_returns_decision_result(self):
		"""decide() returns a DecisionResult with required fields."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		# result has the expected attributes
		assert hasattr(result, "action")
		assert hasattr(result, "reason")
		assert hasattr(result, "soc_floor")
		assert hasattr(result, "target_mode")

	#============================================
	def test_action_is_valid_enum(self):
		"""decide() returns an action from the Action enum."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert isinstance(result.action, decision_engine.Action)

	#============================================
	def test_soc_floor_is_int(self):
		"""decide() returns an integer soc_floor."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert isinstance(result.soc_floor, int)

	#============================================
	def test_reason_is_nonempty_string(self):
		"""decide() returns a non-empty reason string."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert isinstance(result.reason, str)
		assert len(result.reason) > 0


#============================================
class TestDecideTracksAction:
	"""Tests that decide() updates last_action in state."""

	#============================================
	def test_last_action_updated(self):
		"""decide() updates control_state.last_action."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert cs.last_action == result.action.value

	#============================================
	def test_last_action_changes_on_second_call(self):
		"""Calling decide() twice updates last_action each time."""
		config = _make_config()
		cs = _make_state()
		# first call
		now1 = datetime.datetime(2025, 7, 15, 12, 0)
		result1 = decision_engine.decide(
			battery_soc=60, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now1,
		)
		assert cs.last_action == result1.action.value
		# second call with different inputs
		now2 = datetime.datetime(2025, 7, 15, 14, 0)
		result2 = decision_engine.decide(
			battery_soc=60, solar_power_watts=0, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now2,
		)
		assert cs.last_action == result2.action.value
