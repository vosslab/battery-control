"""Tests for config.py - YAML configuration loader."""

# Standard Library
import os
import datetime
import tempfile

# PIP3 modules
import pytest
import yaml

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.config as config_mod


#============================================
class TestLoadConfig:
	"""Tests for load_config function."""

	#============================================
	def test_load_example_config(self):
		"""Load the example config file and verify defaults are applied."""
		config_path = os.path.join(REPO_ROOT, "config_example.yml")
		config = config_mod.load_config(config_path)
		assert config["battery_capacity_kwh"] == 20.0
		assert config["peak_window_start"] == 16
		assert config["peak_window_end"] == 22
		assert config["extreme_price_threshold"] == 20
		assert config["reserve_soc_buffer_pct"] == 2

	#============================================
	def test_load_missing_file(self):
		"""Raise FileNotFoundError for missing config file."""
		with pytest.raises(FileNotFoundError):
			config_mod.load_config("/nonexistent/path/config.yml")

	#============================================
	def test_defaults_applied(self):
		"""Defaults are applied when config file has minimal content."""
		with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
			yaml.dump({"battery_capacity_kwh": 15.0}, f)
			tmp_path = f.name
		try:
			config = config_mod.load_config(tmp_path)
			# overridden value
			assert config["battery_capacity_kwh"] == 15.0
			# default values still present
			assert config["peak_window_start"] == 16
			assert config["hard_reserve_pct"]["summer"] == 10
			assert config["hard_reserve_pct"]["winter"] == 20
		finally:
			os.unlink(tmp_path)

	#============================================
	def test_empty_config_file(self):
		"""Empty YAML file returns all defaults."""
		with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
			f.write("")
			tmp_path = f.name
		try:
			config = config_mod.load_config(tmp_path)
			assert config["battery_capacity_kwh"] == 20.0
			assert config["dry_run"] is True
		finally:
			os.unlink(tmp_path)

	#============================================
	def test_deep_merge_preserves_nested(self):
		"""Deep merge preserves nested defaults not overridden by user."""
		with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
			yaml.dump({"hard_reserve_pct": {"summer": 5}}, f)
			tmp_path = f.name
		try:
			config = config_mod.load_config(tmp_path)
			# overridden
			assert config["hard_reserve_pct"]["summer"] == 5
			# preserved default
			assert config["hard_reserve_pct"]["winter"] == 20
		finally:
			os.unlink(tmp_path)


#============================================
class TestGetSeason:
	"""Tests for get_season function."""

	#============================================
	def test_summer_months(self):
		"""May through September are summer."""
		config = {"season": "auto"}
		for month in (5, 6, 7, 8, 9):
			now = datetime.datetime(2025, month, 15)
			assert config_mod.get_season(config, now) == "summer"

	#============================================
	def test_winter_months(self):
		"""October through April are winter."""
		config = {"season": "auto"}
		for month in (1, 2, 3, 4, 10, 11, 12):
			now = datetime.datetime(2025, month, 15)
			assert config_mod.get_season(config, now) == "winter"

	#============================================
	def test_manual_override(self):
		"""Manual season override ignores month."""
		config_summer = {"season": "summer"}
		config_winter = {"season": "winter"}
		january = datetime.datetime(2025, 1, 15)
		assert config_mod.get_season(config_summer, january) == "summer"
		july = datetime.datetime(2025, 7, 15)
		assert config_mod.get_season(config_winter, july) == "winter"


#============================================
class TestPriceFloor:
	"""Tests for piecewise linear interpolation floor functions."""

	#============================================
	def test_summer_below_first_anchor(self):
		"""Price below first anchor clamps to first floor."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_floor(config, "summer", 5.0)
		assert floor == 50

	#============================================
	def test_summer_at_first_anchor(self):
		"""Price at first anchor returns first floor exactly."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_floor(config, "summer", 8.0)
		assert floor == 50

	#============================================
	def test_summer_floor_decreases_with_price(self):
		"""Higher prices produce lower floors (more discharge allowed)."""
		config = config_mod.DEFAULTS
		floor_low = config_mod.get_price_floor(config, "summer", 8.0)
		floor_mid = config_mod.get_price_floor(config, "summer", 15.0)
		floor_high = config_mod.get_price_floor(config, "summer", 30.0)
		# floor should decrease as price increases
		assert floor_low > floor_mid > floor_high

	#============================================
	def test_summer_interpolation_between_anchors(self):
		"""Interpolated floor falls between neighboring anchor floors."""
		config = config_mod.DEFAULTS
		# 9c is between 8c (50%) and 10c (30%) anchors
		floor_at_8 = config_mod.get_price_floor(config, "summer", 8.0)
		floor_at_9 = config_mod.get_price_floor(config, "summer", 9.0)
		floor_at_10 = config_mod.get_price_floor(config, "summer", 10.0)
		assert floor_at_8 >= floor_at_9 >= floor_at_10

	#============================================
	def test_summer_above_last_anchor(self):
		"""Price above last anchor clamps to last floor."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_floor(config, "summer", 35.0)
		assert floor == 10

	#============================================
	def test_winter_below_first_anchor(self):
		"""Winter price below first anchor clamps to first floor."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_floor(config, "winter", 5.0)
		assert floor == 60

	#============================================
	def test_winter_above_last_anchor(self):
		"""Winter price above last anchor clamps to last floor."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_floor(config, "winter", 35.0)
		assert floor == 20

	#============================================
	def test_segment_index_below(self):
		"""Segment index is -1 for price below first anchor."""
		config = config_mod.DEFAULTS
		idx = config_mod.get_price_segment_index(config, "summer", 5.0)
		assert idx == -1

	#============================================
	def test_segment_index_between(self):
		"""Segment index is 0 for price between first two anchors."""
		config = config_mod.DEFAULTS
		idx = config_mod.get_price_segment_index(config, "summer", 9.0)
		assert idx == 0

	#============================================
	def test_segment_index_above(self):
		"""Segment index is N-1 for price above last anchor."""
		config = config_mod.DEFAULTS
		# 4 anchors, above last -> index 3
		idx = config_mod.get_price_segment_index(config, "summer", 35.0)
		assert idx == 3

	#============================================
	def test_segment_bounds_below(self):
		"""Segment bounds for below range."""
		config = config_mod.DEFAULTS
		bounds = config_mod.get_price_segment_bounds(config, "summer", 5.0)
		assert bounds == (None, 8)

	#============================================
	def test_segment_bounds_between(self):
		"""Segment bounds for price between anchors."""
		config = config_mod.DEFAULTS
		bounds = config_mod.get_price_segment_bounds(config, "summer", 9.0)
		assert bounds == (8, 10)

	#============================================
	def test_segment_bounds_above(self):
		"""Segment bounds for above range."""
		config = config_mod.DEFAULTS
		bounds = config_mod.get_price_segment_bounds(config, "summer", 35.0)
		assert bounds == (30, None)

	#============================================
	def test_validate_anchors_too_few(self):
		"""validate_anchors raises on fewer than 2 anchors."""
		import pytest
		config_mod.validate_anchors([
			{"price_cents": 8, "soc_floor_pct": 50},
			{"price_cents": 10, "soc_floor_pct": 30},
		])
		with pytest.raises(ValueError):
			config_mod.validate_anchors([{"price_cents": 8, "soc_floor_pct": 50}])

	#============================================
	def test_validate_anchors_non_increasing(self):
		"""validate_anchors raises on non-increasing prices."""
		import pytest
		with pytest.raises(ValueError):
			config_mod.validate_anchors([
				{"price_cents": 10, "soc_floor_pct": 30},
				{"price_cents": 8, "soc_floor_pct": 50},
			])

	#============================================
	def test_seasonal_value(self):
		"""get_seasonal_value returns correct seasonal value."""
		config = config_mod.DEFAULTS
		assert config_mod.get_seasonal_value(config, "hard_reserve_pct", "summer") == 10
		assert config_mod.get_seasonal_value(config, "hard_reserve_pct", "winter") == 20


#============================================
class TestTokenFile:
	"""Tests for token-from-file loading in load_config."""

	#============================================
	def test_load_token_from_file(self, tmp_path):
		"""Token file contents become config epcube_token."""
		# write a token file
		token_file = tmp_path / "token"
		token_file.write_text("Bearer my_test_token")
		# write config pointing to token file
		config_path = tmp_path / "config.yml"
		config_data = {"epcube_token_file": str(token_file)}
		with open(config_path, "w") as f:
			yaml.dump(config_data, f)
		config = config_mod.load_config(str(config_path))
		assert config["epcube_token"] == "Bearer my_test_token"

	#============================================
	def test_token_file_overrides_inline(self, tmp_path):
		"""Token file takes precedence over inline epcube_token."""
		token_file = tmp_path / "token"
		token_file.write_text("Bearer from_file")
		config_path = tmp_path / "config.yml"
		config_data = {
			"epcube_token": "Bearer inline_value",
			"epcube_token_file": str(token_file),
		}
		with open(config_path, "w") as f:
			yaml.dump(config_data, f)
		config = config_mod.load_config(str(config_path))
		assert config["epcube_token"] == "Bearer from_file"

	#============================================
	def test_token_file_missing(self, tmp_path):
		"""Missing token file does not crash; token stays empty."""
		config_path = tmp_path / "config.yml"
		config_data = {"epcube_token_file": "/nonexistent/path/token"}
		with open(config_path, "w") as f:
			yaml.dump(config_data, f)
		config = config_mod.load_config(str(config_path))
		assert config["epcube_token"] == ""

	#============================================
	def test_token_file_strips_whitespace(self, tmp_path):
		"""Trailing newlines in token file are stripped."""
		token_file = tmp_path / "token"
		token_file.write_text("Bearer xxx\n\n")
		config_path = tmp_path / "config.yml"
		config_data = {"epcube_token_file": str(token_file)}
		with open(config_path, "w") as f:
			yaml.dump(config_data, f)
		config = config_mod.load_config(str(config_path))
		assert config["epcube_token"] == "Bearer xxx"
