"""Tests for ComEd price freshness and _fetch_comed_price None-safety.

Data fixture shape: list of dicts with keys 'millisUTC' (int ms since epoch)
and 'price' (float cents). getLastPriceTimestampSeconds finds the max
millisUTC value across all items; getAgeOfLastPriceSeconds subtracts it
from now_seconds. isPriceDataFresh returns age <= STALE_PRICE_SECONDS.
"""

# local repo modules
import battcontrol.comedlib
import battcontrol.battery_controller

#============================================
def _make_data(age_seconds: float, now_seconds: float) -> list:
	"""
	Build a minimal comed data list with one sample at the given age.

	Args:
		age_seconds: How many seconds old the sample should be.
		now_seconds: Injected reference time in seconds since epoch.

	Returns:
		list: One-item list of {'millisUTC': int, 'price': float}.
	"""
	sample_seconds = now_seconds - age_seconds
	sample_ms = int(sample_seconds * 1000)
	return [{"millisUTC": sample_ms, "price": 5.0}]


#============================================
def test_is_price_data_fresh_recent_returns_true():
	"""A sample that is 60 seconds old should be considered fresh."""
	now = 1_700_000_000.0
	# 60 seconds is well within any reasonable stale window
	data = _make_data(age_seconds=60, now_seconds=now)
	comlib = battcontrol.comedlib.ComedLib()
	result = comlib.isPriceDataFresh(data=data, now_seconds=now)
	assert result is True


#============================================
def test_is_price_data_fresh_old_returns_false():
	"""A sample that is 2 hours old should be stale regardless of the threshold."""
	now = 1_700_000_000.0
	# 7200 seconds is far beyond any plausible stale window
	data = _make_data(age_seconds=7200, now_seconds=now)
	comlib = battcontrol.comedlib.ComedLib()
	result = comlib.isPriceDataFresh(data=data, now_seconds=now)
	assert result is False


#============================================
def test_is_price_data_fresh_items_missing_millis_returns_false():
	"""Data whose items all lack millisUTC cannot determine age; treated as stale."""
	comlib = battcontrol.comedlib.ComedLib()
	# Items with no millisUTC key: getLastPriceTimestampSeconds returns None
	data = [{"price": 5.0}, {"price": 6.0}]
	result = comlib.isPriceDataFresh(data=data, now_seconds=1_700_000_000.0)
	assert result is False


#============================================
def test_is_price_data_fresh_empty_list_returns_false():
	"""An empty data list should be treated as stale."""
	comlib = battcontrol.comedlib.ComedLib()
	result = comlib.isPriceDataFresh(data=[], now_seconds=1_700_000_000.0)
	assert result is False


#============================================
def test_fetch_comed_price_stale_data_returns_none_triple(monkeypatch):
	"""_fetch_comed_price returns (None, None, None) when data is stale, no TypeError raised."""
	now = 1_700_000_000.0
	# 2-hour-old data; isPriceDataFresh will return False via real logic
	old_data = _make_data(age_seconds=7200, now_seconds=now)

	def fake_download(self, url=None):
		return old_data

	# Monkeypatch downloadComedJsonData to return stale data without network
	# Monkeypatch isPriceDataFresh to use injected now_seconds (avoids real clock)
	monkeypatch.setattr(
		battcontrol.comedlib.ComedLib,
		"downloadComedJsonData",
		fake_download,
	)

	original_fresh = battcontrol.comedlib.ComedLib.isPriceDataFresh

	def fresh_with_injected_now(self, data=None, now_seconds=None):
		# forward the stale data with a fixed now so the check is deterministic
		return original_fresh(self, data=data, now_seconds=now)

	monkeypatch.setattr(
		battcontrol.comedlib.ComedLib,
		"isPriceDataFresh",
		fresh_with_injected_now,
	)

	result = battcontrol.battery_controller._fetch_comed_price()
	assert result == (None, None, None)


#============================================
def test_fetch_comed_price_none_predicted_rate_returns_none_triple(monkeypatch):
	"""_fetch_comed_price returns (None, None, None) when getPredictedRate returns None.

	This is the regression guard for the '%.2f % None' TypeError crash: if
	getPredictedRate returns None, the function must collapse to the hold path
	rather than propagating None into a format string.
	"""
	now = 1_700_000_000.0
	# Fresh data so the stale guard does not fire first
	fresh_data = _make_data(age_seconds=60, now_seconds=now)

	def fake_download(self, url=None):
		return fresh_data

	monkeypatch.setattr(
		battcontrol.comedlib.ComedLib,
		"downloadComedJsonData",
		fake_download,
	)

	# Force isPriceDataFresh to return True (fresh) with our deterministic now
	original_fresh = battcontrol.comedlib.ComedLib.isPriceDataFresh

	def always_fresh(self, data=None, now_seconds=None):
		return original_fresh(self, data=data, now_seconds=now)

	monkeypatch.setattr(
		battcontrol.comedlib.ComedLib,
		"isPriceDataFresh",
		always_fresh,
	)

	# Named stubs (not lambdas) per docs/PYTHON_STYLE.md: lambda is reserved
	# for short key= callbacks, not for substituted method bodies.
	# getPredictedRate returns None to simulate a parse failure.
	def stub_predicted_none(self, data=None):
		return None

	# getCurrentComedRate returns a float so this test isolates the
	# predicted-rate None path specifically.
	def stub_current_rate(self, data=None):
		return 5.0

	# getMedianComedRate and getReasonableCutOff must not raise.
	def stub_median(self, data=None):
		return (5.0, 1.0)

	def stub_cutoff(self):
		return 6.0

	monkeypatch.setattr(battcontrol.comedlib.ComedLib, "getPredictedRate", stub_predicted_none)
	monkeypatch.setattr(battcontrol.comedlib.ComedLib, "getCurrentComedRate", stub_current_rate)
	monkeypatch.setattr(battcontrol.comedlib.ComedLib, "getMedianComedRate", stub_median)
	monkeypatch.setattr(battcontrol.comedlib.ComedLib, "getReasonableCutOff", stub_cutoff)

	result = battcontrol.battery_controller._fetch_comed_price()
	assert result == (None, None, None)
