"""Tests for decision_engine.py - strategy flowchart logic."""

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
class TestGuards:
	"""Tests for section A: guard checks."""

	#============================================
	def test_hard_reserve_summer(self):
		"""SoC at hard reserve blocks discharge (summer)."""
		config = _make_config()
		cs = _make_state()
		# summer hard reserve is 10%
		now = datetime.datetime(2025, 7, 15, 14, 0)
		result = decision_engine.decide(
			battery_soc=10, solar_power_watts=0, load_power_watts=0,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_DISABLED
		assert "Hard reserve" in result.reason

	#============================================
	def test_hard_reserve_winter(self):
		"""SoC at hard reserve blocks discharge (winter)."""
		config = _make_config()
		cs = _make_state()
		# winter hard reserve is 20%
		now = datetime.datetime(2025, 1, 15, 14, 0)
		result = decision_engine.decide(
			battery_soc=20, solar_power_watts=0, load_power_watts=0,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_DISABLED

	#============================================
	def test_above_hard_reserve_proceeds(self):
		"""SoC above hard reserve does not trigger guard."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 14, 0)
		result = decision_engine.decide(
			battery_soc=50, solar_power_watts=500, load_power_watts=200,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action != decision_engine.Action.DISCHARGE_DISABLED or "Hard reserve" not in result.reason


#============================================
class TestDaylightLogic:
	"""Tests for section B: daylight logic."""

	#============================================
	def test_solar_surplus_below_target(self):
		"""Solar surplus with SoC below afternoon target: charge from solar."""
		config = _make_config()
		cs = _make_state()
		# summer afternoon target is 90%
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.CHARGE_FROM_SOLAR
		assert "target" in result.reason

	#============================================
	def test_solar_surplus_above_target_hold(self):
		"""Solar surplus with SoC above target and normal price: charge from solar."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=92, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.CHARGE_FROM_SOLAR

	#============================================
	def test_solar_surplus_headroom_extreme_price(self):
		"""Near-full battery with extreme price creates headroom."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=96, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=25.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_ENABLED
		assert "headroom" in result.reason.lower()

	#============================================
	def test_no_surplus_extreme_price(self):
		"""No solar surplus with extreme price: discharge to floor."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=80, solar_power_watts=100, load_power_watts=500,
			comed_price_cents=25.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_ENABLED
		assert "extreme" in result.reason.lower()

	#============================================
	def test_no_surplus_normal_price(self):
		"""No solar surplus with normal price: preserve."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 12, 0)
		result = decision_engine.decide(
			battery_soc=80, solar_power_watts=100, load_power_watts=500,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_DISABLED
		assert "preserving" in result.reason.lower()


#============================================
class TestNightLogic:
	"""Tests for section D: night logic."""

	#============================================
	def test_night_extreme_price(self):
		"""Night with extreme price: discharge to floor."""
		config = _make_config()
		cs = _make_state()
		# 11pm, no solar, outside peak window
		now = datetime.datetime(2025, 7, 15, 23, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=25.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_ENABLED

	#============================================
	def test_night_normal_price(self):
		"""Night with normal price: hold."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 16, 2, 0)
		result = decision_engine.decide(
			battery_soc=40, solar_power_watts=0, load_power_watts=200,
			comed_price_cents=3.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_DISABLED


#============================================
class TestPeakLogic:
	"""Tests for section E: peak logic."""

	#============================================
	def test_peak_high_price_discharge(self):
		"""Peak window with high price: discharge to floor."""
		config = _make_config()
		cs = _make_state()
		# 6pm summer, no solar
		now = datetime.datetime(2025, 7, 15, 18, 0)
		result = decision_engine.decide(
			battery_soc=80, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=25.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_ENABLED
		assert result.price_band == "high"
		assert result.soc_floor == 10  # summer high band floor

	#============================================
	def test_peak_low_price_hold(self):
		"""Peak window with low price and SoC at floor: hold."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 18, 0)
		result = decision_engine.decide(
			battery_soc=50, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=3.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		# SoC 50% == low band floor 50%, should hold
		assert result.action == decision_engine.Action.DISCHARGE_DISABLED

	#============================================
	def test_peak_mid_price_discharge(self):
		"""Peak window with mid price: discharge enabled."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 18, 0)
		result = decision_engine.decide(
			battery_soc=70, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.DISCHARGE_ENABLED
		assert result.price_band == "mid_high"

	#============================================
	def test_peak_winter_higher_floors(self):
		"""Winter peak has higher SoC floors."""
		config = _make_config()
		cs = _make_state()
		# January, 6pm
		now = datetime.datetime(2025, 1, 15, 18, 0)
		result = decision_engine.decide(
			battery_soc=80, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.soc_floor == 30  # winter mid_high floor

	#============================================
	def test_peak_mode_activation(self):
		"""Peak logic activates peak_mode_active in state."""
		config = _make_config()
		cs = _make_state()
		assert cs.peak_mode_active is False
		now = datetime.datetime(2025, 7, 15, 18, 0)
		decision_engine.decide(
			battery_soc=80, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert cs.peak_mode_active is True


#============================================
class TestHysteresis:
	"""Tests for section F: hysteresis and token friction."""

	#============================================
	def test_price_band_counter_increments(self):
		"""Consecutive same-band checks increment counter."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 18, 0)
		# first check
		decision_engine.decide(
			battery_soc=80, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		first_count = cs.price_band_counter
		# second check, same price
		decision_engine.decide(
			battery_soc=80, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert cs.price_band_counter == first_count + 1

	#============================================
	def test_action_stability_tracking(self):
		"""Action stable count tracks consecutive identical decisions."""
		config = _make_config()
		cs = _make_state()
		now = datetime.datetime(2025, 7, 15, 18, 0)
		# two identical decisions
		decision_engine.decide(
			battery_soc=80, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		decision_engine.decide(
			battery_soc=80, solar_power_watts=0, load_power_watts=500,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert cs.action_stable_count >= 2


#============================================
class TestTransitionTrigger:
	"""Tests for section C: transition from daylight to peak."""

	#============================================
	def test_time_trigger(self):
		"""At peak_window_start, transition to peak logic."""
		config = _make_config()
		cs = _make_state()
		# 4pm with solar
		now = datetime.datetime(2025, 7, 15, 16, 0)
		decision_engine.decide(
			battery_soc=80, solar_power_watts=500, load_power_watts=200,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		# should use peak logic since it's 4pm
		assert cs.peak_mode_active is True

	#============================================
	def test_before_peak_daylight(self):
		"""Before peak window with solar: daylight logic."""
		config = _make_config()
		cs = _make_state()
		cs.last_solar_above_threshold_at = datetime.datetime(2025, 7, 15, 14, 0).isoformat()
		now = datetime.datetime(2025, 7, 15, 14, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=3000, load_power_watts=1000,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		assert result.action == decision_engine.Action.CHARGE_FROM_SOLAR
		assert cs.peak_mode_active is False
