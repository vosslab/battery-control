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
		assert config["hysteresis_count"] == 2

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
class TestPriceBands:
	"""Tests for price band functions."""

	#============================================
	def test_summer_low_band(self):
		"""Price below 8c in summer gives 50% floor."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_band_floor(config, "summer", 5.0)
		assert floor == 50

	#============================================
	def test_summer_high_band(self):
		"""Price above 20c in summer gives 10% floor."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_band_floor(config, "summer", 25.0)
		assert floor == 10

	#============================================
	def test_winter_low_band(self):
		"""Price below 8c in winter gives 60% floor."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_band_floor(config, "winter", 5.0)
		assert floor == 60

	#============================================
	def test_winter_high_band(self):
		"""Price above 20c in winter gives 20% floor."""
		config = config_mod.DEFAULTS
		floor = config_mod.get_price_band_floor(config, "winter", 25.0)
		assert floor == 20

	#============================================
	def test_band_name_boundaries(self):
		"""Band names match at boundary values."""
		config = config_mod.DEFAULTS
		assert config_mod.get_price_band_name(config, "summer", 5.0) == "low"
		assert config_mod.get_price_band_name(config, "summer", 9.0) == "mid_low"
		assert config_mod.get_price_band_name(config, "summer", 15.0) == "mid_high"
		assert config_mod.get_price_band_name(config, "summer", 25.0) == "high"

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
