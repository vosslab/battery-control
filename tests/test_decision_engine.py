"""Tests for decision_engine.py - thin orchestrator calling strategy."""

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
	"""Tests for section A: guard checks via decide()."""

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
		assert result.action != decision_engine.Action.DISCHARGE_DISABLED


#============================================
class TestDaylightLogic:
	"""Tests for section B: daylight logic via decide()."""

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
		"""Solar surplus with SoC above target and normal price: hold."""
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
	"""Tests for section D: night logic via decide()."""

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
	"""Tests for section E: peak logic via decide()."""

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
		# summer 25c interpolated between 20c(20%) and 30c(10%) = 15%
		assert result.soc_floor == 15

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
		# 15c summer: interpolated between 10c(30%) and 20c(20%) = 25%
		assert result.soc_floor == 25

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
		# winter 15c interpolated between 10c(45%) and 20c(30%) = 38%
		assert result.soc_floor == 38


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
class TestRouting:
	"""Tests for routing by time of day and solar availability."""

	#============================================
	def test_solar_in_peak_uses_peak(self):
		"""Solar available during peak window uses peak logic."""
		config = _make_config()
		cs = _make_state()
		# 5pm with solar
		now = datetime.datetime(2025, 7, 15, 17, 0)
		result = decision_engine.decide(
			battery_soc=80, solar_power_watts=500, load_power_watts=200,
			comed_price_cents=15.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		# peak logic: above floor -> discharge enabled
		assert result.action == decision_engine.Action.DISCHARGE_ENABLED

	#============================================
	def test_no_solar_before_peak_uses_night(self):
		"""No solar before peak window uses night logic."""
		config = _make_config()
		cs = _make_state()
		# 3pm, no solar, before peak window
		now = datetime.datetime(2025, 7, 15, 15, 0)
		result = decision_engine.decide(
			battery_soc=60, solar_power_watts=10, load_power_watts=200,
			comed_price_cents=5.0, comed_median_cents=8.0,
			config=config, control_state=cs, current_time=now,
		)
		# night logic: normal price -> hold
		assert result.action == decision_engine.Action.DISCHARGE_DISABLED
