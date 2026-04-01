"""Tests for battcontrol.strategy module.

Strategy is actively evolving, so these tests verify structure and
contract (evaluate returns a valid DecisionResult), not specific
decisions for given inputs. Decision correctness is validated by
replay_strategy.py against historical data.
"""

# Standard Library
import datetime

# local repo modules
import battcontrol.strategy


#============================================
def make_config() -> dict:
	"""
	Helper to build a test config dict with default values.

	Returns:
		dict: Test configuration.
	"""
	return {
		"battery_capacity_kwh": 20.0,
		"hard_reserve_pct": {
			"summer": 10,
			"winter": 20,
		},
		"afternoon_target_soc_pct": {
			"summer": 90,
			"winter": 70,
		},
		"peak_window_start": 16,
		"peak_window_end": 22,
		"price_floor_anchors": {
			"summer": [
				{"price_cents": 8, "soc_floor_pct": 50},
				{"price_cents": 10, "soc_floor_pct": 30},
				{"price_cents": 20, "soc_floor_pct": 20},
				{"price_cents": 30, "soc_floor_pct": 10},
			],
			"winter": [
				{"price_cents": 8, "soc_floor_pct": 60},
				{"price_cents": 10, "soc_floor_pct": 45},
				{"price_cents": 20, "soc_floor_pct": 30},
				{"price_cents": 30, "soc_floor_pct": 20},
			],
		},
		"extreme_price_threshold": 20,
		"night_floor_pct": {
			"summer": 25,
			"winter": 35,
		},
		"headroom_band_low": 85,
		"headroom_band_high": 95,
		"solar_sunset_threshold_watts": 50,
		"season": "auto",
	}


#============================================
class TestEvaluateContract:
	"""Test that evaluate() returns a well-formed DecisionResult."""

	#============================================
	def test_returns_decision_result(self):
		"""evaluate() returns a DecisionResult instance."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_action_is_valid_enum(self):
		"""evaluate() returns an Action enum member."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result.action, battcontrol.strategy.Action)

	#============================================
	def test_soc_floor_in_range(self):
		"""evaluate() returns soc_floor between 0 and 100."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert 0 <= result.soc_floor <= 100

	#============================================
	def test_reason_is_nonempty(self):
		"""evaluate() returns a non-empty reason string."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result.reason, str)
		assert len(result.reason) > 0

	#============================================
	def test_target_mode_is_valid(self):
		"""evaluate() returns a recognized target_mode."""
		config = make_config()
		valid_modes = ("self_consumption", "backup")
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.target_mode in valid_modes


#============================================
class TestEvaluateDoesNotCrash:
	"""Test that evaluate() handles a range of inputs without errors."""

	#============================================
	def test_zero_solar(self):
		"""evaluate() handles zero solar power."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=0,
			load_power_watts=200,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_zero_load(self):
		"""evaluate() handles zero load."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=0,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_low_soc(self):
		"""evaluate() handles SoC at minimum."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=5,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_full_soc(self):
		"""evaluate() handles SoC at 100."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=100,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_extreme_high_price(self):
		"""evaluate() handles extreme high price (200c/kWh)."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=200.0,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_extreme_negative_price(self):
		"""evaluate() handles extreme negative price (-20c/kWh)."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=-20.0,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_night_hours(self):
		"""evaluate() handles night time."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 2)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=0,
			load_power_watts=200,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_peak_hours(self):
		"""evaluate() handles peak window time."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 18)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=0,
			load_power_watts=200,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)

	#============================================
	def test_winter_season(self):
		"""evaluate() handles winter dates."""
		config = make_config()
		current_time = datetime.datetime(2026, 1, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert isinstance(result, battcontrol.strategy.DecisionResult)


#============================================
class TestDecisionResult:
	"""Test DecisionResult class."""

	#============================================
	def test_decision_result_repr(self):
		"""DecisionResult repr formats correctly."""
		result = battcontrol.strategy.DecisionResult(
			action=battcontrol.strategy.Action.DISCHARGE_ENABLED,
			reason="Test reason",
			soc_floor=30,
		)
		repr_str = repr(result)
		assert "discharge_enabled" in repr_str
		assert "30" in repr_str

	#============================================
	def test_decision_result_attributes(self):
		"""DecisionResult stores all attributes correctly."""
		result = battcontrol.strategy.DecisionResult(
			action=battcontrol.strategy.Action.CHARGE_FROM_SOLAR,
			reason="Test reason",
			soc_floor=75,
			price_segment=2,
			target_mode="self_consumption",
		)
		assert result.action == battcontrol.strategy.Action.CHARGE_FROM_SOLAR
		assert result.reason == "Test reason"
		assert result.soc_floor == 75
		assert result.price_segment == 2
		assert result.target_mode == "self_consumption"
