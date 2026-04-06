"""Tests for config schema validation."""

# PIP3 modules
import pytest

# local repo modules
import battcontrol.config


#============================================
def _make_valid_config() -> dict:
	"""Build a minimal valid config dict from schema defaults."""
	return battcontrol.config.get_defaults()


#============================================
class TestApplyDefaults:
	"""Tests for apply_defaults()."""

	#============================================
	def test_empty_config_gets_all_defaults(self):
		"""An empty config should have all stable keys after apply_defaults."""
		config = {}
		battcontrol.config.apply_defaults(config)
		# check a few key stable defaults
		assert config["battery_capacity_kwh"] == 20.0
		assert config["headroom_band_high"] == 95
		assert config["dry_run"] is True

	#============================================
	def test_user_value_not_overwritten(self):
		"""User-provided values should not be replaced by defaults."""
		config = {"battery_capacity_kwh": 15.0}
		battcontrol.config.apply_defaults(config)
		assert config["battery_capacity_kwh"] == 15.0

	#============================================
	def test_mutable_defaults_not_shared(self):
		"""Dict/list defaults should be deep-copied, not shared."""
		config_a = {}
		config_b = {}
		battcontrol.config.apply_defaults(config_a)
		battcontrol.config.apply_defaults(config_b)
		# mutating one should not affect the other
		config_a["hard_reserve_pct"]["summer"] = 99
		assert config_b["hard_reserve_pct"]["summer"] != 99


#============================================
class TestValidateConfig:
	"""Tests for validate_config()."""

	#============================================
	def test_valid_defaults_pass(self):
		"""Default config should pass validation."""
		config = _make_valid_config()
		# should not raise
		battcontrol.config.validate_config(config)

	#============================================
	def test_unknown_key_raises(self):
		"""A typo or unknown key should raise ValueError."""
		config = _make_valid_config()
		config["time_adjust_soc_prt"] = 5
		with pytest.raises(ValueError, match="Unknown config key.*time_adjust_soc_prt"):
			battcontrol.config.validate_config(config)

	#============================================
	def test_wrong_type_raises(self):
		"""Wrong type for a config value should raise ValueError."""
		config = _make_valid_config()
		config["headroom_band_high"] = "ninety"
		with pytest.raises(ValueError, match="expected int.*got str"):
			battcontrol.config.validate_config(config)

	#============================================
	def test_bool_rejected_for_int(self):
		"""Bool should not pass as int."""
		config = _make_valid_config()
		config["headroom_band_high"] = True
		with pytest.raises(ValueError, match="expected int.*got bool"):
			battcontrol.config.validate_config(config)

	#============================================
	def test_int_accepted_for_float(self):
		"""Int should be accepted where float is expected."""
		config = _make_valid_config()
		config["battery_capacity_kwh"] = 20
		# should not raise
		battcontrol.config.validate_config(config)

	#============================================
	def test_range_violation_raises(self):
		"""Value outside min/max range should raise ValueError."""
		config = _make_valid_config()
		config["headroom_band_high"] = 150
		with pytest.raises(ValueError, match="150 > max 100"):
			battcontrol.config.validate_config(config)

	#============================================
	def test_experimental_key_absent_by_default(self):
		"""Experimental keys should not be in default config."""
		config = _make_valid_config()
		assert "negative_price_floor" not in config
		assert "pre_solar_soc_threshold" not in config

	#============================================
	def test_experimental_key_valid_when_set(self):
		"""Experimental keys should validate when present."""
		config = _make_valid_config()
		config["negative_price_floor"] = 70
		# should not raise
		battcontrol.config.validate_config(config)

	#============================================
	def test_experimental_key_range_check(self):
		"""Experimental keys should still have range checks."""
		config = _make_valid_config()
		config["negative_price_floor"] = 200
		with pytest.raises(ValueError, match="200 > max 100"):
			battcontrol.config.validate_config(config)


#============================================
class TestNestedValidation:
	"""Tests for nested structure validation."""

	#============================================
	def test_hard_reserve_missing_season_raises(self):
		"""Missing season key in hard_reserve_pct should raise."""
		config = _make_valid_config()
		del config["hard_reserve_pct"]["shoulder"]
		with pytest.raises(ValueError, match="missing season.*shoulder"):
			battcontrol.config.validate_config(config)

	#============================================
	def test_price_floor_anchors_missing_season_raises(self):
		"""Missing season in price_floor_anchors should raise."""
		config = _make_valid_config()
		del config["price_floor_anchors"]["winter"]
		with pytest.raises(ValueError, match="missing season.*winter"):
			battcontrol.config.validate_config(config)

	#============================================
	def test_price_floor_anchors_unsorted_raises(self):
		"""Unsorted anchor prices should raise."""
		config = _make_valid_config()
		config["price_floor_anchors"]["summer"] = [
			{"price_cents": 20, "soc_floor_pct": 30},
			{"price_cents": 10, "soc_floor_pct": 50},
		]
		with pytest.raises(ValueError, match="strictly increasing"):
			battcontrol.config.validate_config(config)

	#============================================
	def test_price_floor_anchors_floor_out_of_range_raises(self):
		"""Anchor floor outside 0-100 should raise."""
		config = _make_valid_config()
		config["price_floor_anchors"]["summer"][0]["soc_floor_pct"] = 150
		with pytest.raises(ValueError, match="150 not in 0..100"):
			battcontrol.config.validate_config(config)


#============================================
class TestLoadConfig:
	"""Tests for load_config() end-to-end."""

	#============================================
	def test_load_config_yml(self):
		"""config.yml should load and validate."""
		config = battcontrol.config.load_config("config.yml")
		# stable keys present
		assert "battery_capacity_kwh" in config
		assert "hard_reserve_pct" in config
		# experimental keys absent (not in config.yml)
		assert "negative_price_floor" not in config
