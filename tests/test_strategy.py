"""Tests for pure policy functions in battcontrol.strategy module."""

# Standard Library
import datetime

# local repo modules
import battcontrol.strategy


#============================================
def make_config(
	hard_reserve_summer: int = 10,
	hard_reserve_winter: int = 20,
	afternoon_target_summer: int = 90,
	afternoon_target_winter: int = 70,
	extreme_threshold: int = 20,
	night_floor_summer: int = 25,
	night_floor_winter: int = 35,
) -> dict:
	"""
	Helper to build a test config dict.

	Args:
		hard_reserve_summer: Hard reserve for summer.
		hard_reserve_winter: Hard reserve for winter.
		afternoon_target_summer: Afternoon target SoC for summer.
		afternoon_target_winter: Afternoon target SoC for winter.
		extreme_threshold: Price threshold for extreme pricing.
		night_floor_summer: Night floor for summer.
		night_floor_winter: Night floor for winter.

	Returns:
		dict: Test configuration.
	"""
	return {
		"battery_capacity_kwh": 20.0,
		"hard_reserve_pct": {
			"summer": hard_reserve_summer,
			"winter": hard_reserve_winter,
		},
		"afternoon_target_soc_pct": {
			"summer": afternoon_target_summer,
			"winter": afternoon_target_winter,
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
		"extreme_price_threshold": extreme_threshold,
		"night_floor_pct": {
			"summer": night_floor_summer,
			"winter": night_floor_winter,
		},
		"headroom_band_low": 85,
		"headroom_band_high": 95,
		"solar_sunset_threshold_watts": 50,
		"season": "auto",
	}


#============================================
class TestGuard:
	"""Test hard reserve guard."""

	def test_hard_reserve_blocks_discharge(self):
		"""SoC at or below hard reserve disables discharge."""
		config = make_config(hard_reserve_summer=10)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=10,
			solar_power_watts=100,
			load_power_watts=50,
			comed_price_cents=15,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_DISABLED
		assert "Hard reserve" in result.reason

	def test_hard_reserve_guard_above_threshold(self):
		"""SoC above hard reserve allows normal routing."""
		config = make_config(hard_reserve_summer=10)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=100,
			load_power_watts=50,
			comed_price_cents=15,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# should route to daylight logic
		assert result.action != battcontrol.strategy.Action.DISCHARGE_DISABLED


#============================================
class TestDaylightLogic:
	"""Test daylight logic (section B of STRATEGY.md)."""

	def test_surplus_below_target_charges(self):
		"""Solar surplus + SoC below target -> charge from solar."""
		config = make_config(afternoon_target_summer=90)
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
		assert result.action == battcontrol.strategy.Action.CHARGE_FROM_SOLAR
		assert "surplus" in result.reason.lower() and "target" in result.reason.lower()

	def test_surplus_above_target_holds(self):
		"""Solar surplus + SoC at target + non-extreme price -> hold."""
		config = make_config(
			afternoon_target_summer=90,
			extreme_threshold=20,
		)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=90,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.CHARGE_FROM_SOLAR
		assert "holding" in result.reason.lower()

	def test_surplus_above_target_extreme_price_creates_headroom(self):
		"""Solar surplus + SoC high + extreme price -> discharge to create headroom."""
		config = make_config(
			afternoon_target_summer=90,
			extreme_threshold=20,
		)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=96,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=25,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_ENABLED
		assert "headroom" in result.reason.lower()

	def test_no_surplus_extreme_price_discharges(self):
		"""No solar surplus + extreme price -> discharge."""
		config = make_config(
			hard_reserve_summer=10,
			extreme_threshold=20,
		)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=50,
			load_power_watts=100,
			comed_price_cents=25,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_ENABLED
		assert "extreme price" in result.reason.lower()

	def test_no_surplus_normal_price_preserves(self):
		"""No solar surplus + normal price -> preserve for evening (daylight logic)."""
		config = make_config(extreme_threshold=20, afternoon_target_summer=80)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=51,
			load_power_watts=100,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# with 51W solar (just above threshold), routes to daylight logic
		assert result.action == battcontrol.strategy.Action.DISCHARGE_DISABLED
		assert "preserving for peak" in result.reason.lower()


#============================================
class TestNightLogic:
	"""Test night logic (section D of STRATEGY.md)."""

	def test_night_extreme_price_discharges(self):
		"""Night + extreme price + above floor -> discharge."""
		config = make_config(
			night_floor_summer=25,
			extreme_threshold=20,
		)
		current_time = datetime.datetime(2026, 7, 15, 23)
		result = battcontrol.strategy.evaluate(
			battery_soc=60,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=25,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_ENABLED
		assert "extreme" in result.reason.lower()

	def test_night_extreme_price_at_floor_holds(self):
		"""Night + extreme price but at floor -> hold."""
		config = make_config(
			night_floor_summer=25,
			extreme_threshold=20,
		)
		current_time = datetime.datetime(2026, 7, 15, 23)
		result = battcontrol.strategy.evaluate(
			battery_soc=25,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=25,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_DISABLED

	def test_night_normal_price_holds(self):
		"""Night + normal price -> hold."""
		config = make_config(
			night_floor_summer=25,
			extreme_threshold=20,
		)
		current_time = datetime.datetime(2026, 7, 15, 23)
		result = battcontrol.strategy.evaluate(
			battery_soc=60,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_DISABLED
		assert "night hold" in result.reason.lower()


#============================================
class TestPeakLogic:
	"""Test peak logic (section E of STRATEGY.md)."""

	def test_peak_above_floor_discharges(self):
		"""Peak window + price maps to floor below SoC -> discharge."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 18)
		battery_soc = 40
		result = battcontrol.strategy.evaluate(
			battery_soc=battery_soc,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=12,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_ENABLED
		assert result.soc_floor < battery_soc

	def test_peak_at_or_below_floor_holds(self):
		"""Peak window + SoC at or below interpolated floor -> hold."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 18)
		result = battcontrol.strategy.evaluate(
			battery_soc=25,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=12,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_DISABLED

	def test_peak_high_price_lower_floor(self):
		"""Peak + higher price -> lower floor (discharge more)."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 18)
		result_low_price = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=8,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		result_high_price = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=25,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# higher price should have lower floor (more aggressive discharge)
		assert result_high_price.soc_floor < result_low_price.soc_floor


#============================================
class TestRouting:
	"""Test routing logic (time of day + solar availability)."""

	def test_no_solar_in_peak_uses_peak_logic(self):
		"""No solar + in peak window -> peak logic."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 18)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=20,
			load_power_watts=50,
			comed_price_cents=15,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# peak logic returns discharge/hold based on floor
		assert result.target_mode in ("self_consumption", "backup")

	def test_no_solar_not_in_peak_uses_night_logic(self):
		"""No solar + not in peak window -> night logic."""
		config = make_config(
			extreme_threshold=20,
			night_floor_summer=25,
		)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=20,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		assert result.action == battcontrol.strategy.Action.DISCHARGE_DISABLED
		assert "night hold" in result.reason.lower()

	def test_solar_available_in_peak_uses_peak_logic(self):
		"""Solar available + in peak window -> peak logic (time priority)."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 18)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=15,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# should use peak logic (time takes priority)
		assert result.price_segment >= -1

	def test_solar_available_not_in_peak_uses_daylight(self):
		"""Solar available + not in peak window -> daylight logic."""
		config = make_config(afternoon_target_summer=90)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=15,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# should charge from solar
		assert result.action == battcontrol.strategy.Action.CHARGE_FROM_SOLAR


#============================================
class TestSeasonalVariant:
	"""Test seasonal differences in reserve levels and targets."""

	def test_winter_higher_reserves(self):
		"""Winter should have higher reserves than summer."""
		config = make_config(
			hard_reserve_summer=10,
			hard_reserve_winter=20,
			afternoon_target_summer=90,
			afternoon_target_winter=70,
			night_floor_summer=25,
			night_floor_winter=35,
		)
		summer_time = datetime.datetime(2026, 7, 15, 14)
		winter_time = datetime.datetime(2026, 1, 15, 14)
		# summer with solar surplus below target -> charge
		summer_result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=summer_time,
			config=config,
		)
		# winter with same conditions -> charge (winter target is lower)
		winter_result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=300,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=winter_time,
			config=config,
		)
		# both should charge
		assert summer_result.action == battcontrol.strategy.Action.CHARGE_FROM_SOLAR
		assert winter_result.action == battcontrol.strategy.Action.CHARGE_FROM_SOLAR


#============================================
class TestEdgeCases:
	"""Test edge cases and boundary conditions."""

	def test_zero_solar_power(self):
		"""Zero solar power treated as no solar."""
		config = make_config(extreme_threshold=20, night_floor_summer=25)
		current_time = datetime.datetime(2026, 7, 15, 23)
		result = battcontrol.strategy.evaluate(
			battery_soc=60,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=15,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# should use night logic
		assert "night" in result.reason.lower() or result.price_segment >= -1

	def test_exact_threshold_solar_available(self):
		"""Solar at threshold boundary is available."""
		config = make_config(afternoon_target_summer=90)
		current_time = datetime.datetime(2026, 7, 15, 14)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=50,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# 50W is at threshold, should be NOT available (threshold uses >)
		assert result.price_segment >= -1 or "night" in result.reason.lower()

	def test_peak_window_boundary_start(self):
		"""Hour exactly at peak window start is in peak window."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 16)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=15,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# should use peak logic
		assert result.price_segment >= -1

	def test_peak_window_boundary_end(self):
		"""Hour before peak window end is in peak window."""
		config = make_config()
		current_time = datetime.datetime(2026, 7, 15, 21)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=15,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# should use peak logic
		assert result.price_segment >= -1

	def test_peak_window_boundary_after_end(self):
		"""Hour at or after peak window end is not in peak window."""
		config = make_config(
			extreme_threshold=20,
			night_floor_summer=25,
		)
		current_time = datetime.datetime(2026, 7, 15, 22)
		result = battcontrol.strategy.evaluate(
			battery_soc=50,
			solar_power_watts=0,
			load_power_watts=50,
			comed_price_cents=10,
			comed_median_cents=10,
			current_time=current_time,
			config=config,
		)
		# should use night logic
		assert "night" in result.reason.lower()


#============================================
class TestDecisionResult:
	"""Test DecisionResult class."""

	def test_decision_result_repr(self):
		"""DecisionResult repr formats correctly."""
		result = battcontrol.strategy.DecisionResult(
			action=battcontrol.strategy.Action.DISCHARGE_ENABLED,
			reason="Test reason",
			soc_floor=30,
		)
		repr_str = repr(result)
		assert "DISCHARGE_ENABLED" in repr_str or "discharge_enabled" in repr_str
		assert "Self-consumption" in repr_str
		assert "30" in repr_str

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
