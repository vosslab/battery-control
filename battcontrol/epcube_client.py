"""Synchronous EP Cube cloud API client for battery control system."""

# Standard Library
import time
import random
import logging

# PIP3 modules
import requests

# EP Cube API constants (from epcube/custom_components/epcube/const.py)
USER_AGENT = "ReservoirMonitoring/2.1.0 (iPhone; iOS 18.3.2; Scale/3.00)"
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 1

BASE_URLS = {
	"EU": "https://monitoring-eu.epcube.com/api",
	"US": "https://epcube-monitoring.com/app-api",
	"JP": "https://monitoring-jp.epcube.com/api",
}

# EP Cube operating mode names (from official datasheet)
MODE_MAP = {
	"1": "Self-consumption",
	"2": "Time of Use",
	"3": "Backup",
}
REVERSE_MODE_MAP = {v: k for k, v in MODE_MAP.items()}

logger = logging.getLogger(__name__)


#============================================
def get_base_url(region: str) -> str:
	"""
	Get the API base URL for a region.

	Args:
		region: Region code ('US', 'EU', or 'JP').

	Returns:
		str: Base URL for the region.
	"""
	return BASE_URLS.get(region.upper(), BASE_URLS["EU"])


#============================================
def get_headers() -> dict:
	"""
	Build standard HTTP headers for EP Cube API requests.

	Returns:
		dict: Headers dictionary with spoofed User-Agent.
	"""
	headers = {
		"accept": "*/*",
		"content-type": "application/json",
		"user-agent": USER_AGENT,
		"accept-language": "en-US",
		"accept-encoding": "gzip, deflate, br",
	}
	return headers


#============================================
class EpcubeClient:
	"""
	Synchronous client for the EP Cube cloud API.

	Provides methods to read battery state and switch operating modes.
	"""

	#============================================
	def __init__(self, token: str, region: str = "US", device_sn: str = ""):
		"""
		Initialize EP Cube client.

		Args:
			token: Authorization token from epcube-token app.
			region: Region code ('US', 'EU', 'JP').
			device_sn: Device serial number for API queries.
		"""
		self.token = token
		self.region = region
		self.device_sn = device_sn
		self.base_url = get_base_url(region)
		self._device_id = None
		# stores the last raw API response for debugging
		self.last_raw_data = None
		self._headers = {
			"accept": "*/*",
			"content-type": "application/json",
			"authorization": self.token,
			"user-agent": USER_AGENT,
			"accept-language": "en-US",
			"accept-encoding": "gzip, deflate, br",
		}

	#============================================
	def _request(self, method: str, endpoint: str, json_data: dict = None) -> dict:
		"""
		Make an API request with retry logic.

		Args:
			method: HTTP method ('GET' or 'POST').
			endpoint: API endpoint path (appended to base_url).
			json_data: JSON payload for POST requests.

		Returns:
			dict: Parsed JSON response data, or None on auth failure.

		Raises:
			RuntimeError: If all retries exhausted.
		"""
		url = f"{self.base_url}{endpoint}"
		last_error = None
		for attempt in range(MAX_RETRIES):
			# rate limit courtesy delay
			time.sleep(random.random())
			try:
				if method == "GET":
					resp = requests.get(url, headers=self._headers, timeout=HTTP_TIMEOUT)
				else:
					resp = requests.post(url, headers=self._headers, json=json_data, timeout=HTTP_TIMEOUT)
				# handle HTTP status codes
				if resp.status_code == 200:
					return resp.json()
				if resp.status_code == 401:
					logger.error("EP Cube token invalid or expired (401). Please regenerate token.")
					return None
				if resp.status_code == 403:
					logger.error("EP Cube access denied (403).")
					return None
				if resp.status_code == 429:
					logger.warning(
						"EP Cube rate limit hit, attempt %d/%d",
						attempt + 1, MAX_RETRIES
					)
					time.sleep(RETRY_DELAY * 2)
					continue
				if resp.status_code >= 500:
					logger.warning(
						"EP Cube server error %d, attempt %d/%d",
						resp.status_code, attempt + 1, MAX_RETRIES
					)
					time.sleep(RETRY_DELAY * (attempt + 1))
					continue
				# other errors
				logger.error("EP Cube HTTP %d: %s", resp.status_code, resp.text[:200])
				return None
			except requests.exceptions.Timeout:
				last_error = "timeout"
				logger.warning("EP Cube request timeout, attempt %d/%d", attempt + 1, MAX_RETRIES)
				time.sleep(RETRY_DELAY * (attempt + 1))
			except requests.exceptions.ConnectionError as err:
				last_error = str(err)
				logger.warning("EP Cube connection error, attempt %d/%d", attempt + 1, MAX_RETRIES)
				time.sleep(RETRY_DELAY * (attempt + 1))
		raise RuntimeError(f"EP Cube API request failed after {MAX_RETRIES} retries: {last_error}")

	#============================================
	def get_device_data(self) -> dict:
		"""
		Fetch live device data from the EP Cube API.

		Returns:
			dict: Normalized device data with keys:
				battery_soc (int), solar_power_watts (float),
				grid_power_watts (float), backup_power_watts (float),
				smart_home_power_watts (float), non_backup_power_watts (float),
				battery_power_watts (float), work_status (str), device_id (str).
			Returns None if token is expired or request fails.
		"""
		endpoint = f"/device/homeDeviceInfo?&sgSn={self.device_sn}"
		result = self._request("GET", endpoint)
		if result is None:
			return None
		raw_data = result.get("data", {})
		if not raw_data:
			logger.warning("EP Cube returned empty device data")
			return None
		# store raw payload for debugging (available via client.last_raw_data)
		self.last_raw_data = raw_data
		# normalize keys to lowercase for consistent access
		data = {k.lower(): v for k, v in raw_data.items()}
		# extract and store device ID for mode switching
		device_id = data.get("devid", "")
		if device_id:
			self._device_id = device_id
		# power values are raw * 10 to get watts (per epcube sensor.py patterns)
		solar_power = _safe_float(data.get("solarpower", 0)) * 10
		grid_power = _safe_float(data.get("gridpower", 0)) * 10
		backup_power = _safe_float(data.get("backuppower", 0)) * 10
		smart_home_power = _safe_float(data.get("smarthomepower", 0)) * 10
		non_backup_power = _safe_float(data.get("nonbackuppower", 0)) * 10
		battery_power = _safe_float(data.get("batterypower", 0)) * 10
		battery_soc = _safe_int(data.get("batterysoc", 0))
		work_status = str(data.get("workstatus", ""))
		normalized = {
			"battery_soc": battery_soc,
			"solar_power_watts": solar_power,
			"grid_power_watts": grid_power,
			"backup_power_watts": backup_power,
			"smart_home_power_watts": smart_home_power,
			"non_backup_power_watts": non_backup_power,
			"battery_power_watts": battery_power,
			"work_status": work_status,
			"device_id": str(device_id),
		}
		return normalized

	#============================================
	def get_switch_mode(self) -> dict:
		"""
		Fetch current switch mode settings.

		Returns:
			dict: Switch mode data, or None on failure.
		"""
		if not self._device_id:
			logger.warning("No device ID available, cannot fetch switch mode")
			return None
		endpoint = f"/device/getSwitchMode?devId={self._device_id}"
		result = self._request("GET", endpoint)
		if result is None:
			return None
		return result.get("data", {})

	#============================================
	def set_mode(self, mode: int, reserve_soc: int = None) -> bool:
		"""
		Set the EP Cube operating mode.

		Args:
			mode: Mode number (1=Self-consumption, 3=Backup).
			reserve_soc: Reserve SoC percentage for the mode.

		Returns:
			bool: True if mode was set successfully.
		"""
		if not self._device_id:
			logger.error("No device ID available, cannot set mode")
			return False
		payload = {
			"devId": self._device_id,
			"workStatus": str(mode),
			"weatherWatch": "0",
			"onlySave": "0",
		}
		# add mode-specific parameters
		if mode == 1:
			# Self-consumption: set reserve SoC
			soc_value = reserve_soc if reserve_soc is not None else 15
			payload["selfConsumptioinReserveSoc"] = str(soc_value)
		elif mode == 3:
			# Backup: set backup power reserve SoC
			soc_value = reserve_soc if reserve_soc is not None else 50
			payload["backupPowerReserveSoc"] = str(soc_value)
		logger.info("Setting EP Cube mode %d (reserve SoC: %s)", mode, reserve_soc)
		result = self._request("POST", "/device/switchMode", json_data=payload)
		if result is None:
			return False
		logger.info("EP Cube mode change response: %s", result)
		return True


#============================================
def execute_epcube(decision_result, client: EpcubeClient, config: dict, dry_run: bool) -> bool:
	"""
	Translate a decision result into EP Cube mode changes.

	Args:
		decision_result: DecisionResult from the decision engine.
		client: EpcubeClient instance.
		config: Configuration dictionary.
		dry_run: If True, log but do not send commands.

	Returns:
		bool: True if command was sent (or would be sent in dry-run).
	"""
	if client is None:
		logger.info("No EP Cube client available, skipping EP Cube actuator")
		return False
	action = decision_result.action
	soc_floor = decision_result.soc_floor
	target_mode = decision_result.target_mode
	# map action to EP Cube mode and reserve SoC
	# CHARGE_FROM_SOLAR -> Self-consumption (mode 1) with target SoC as reserve
	# DISCHARGE_ENABLED -> Self-consumption (mode 1) with price-band floor
	# DISCHARGE_DISABLED -> Backup (mode 3) with max(soc_floor, current SoC)
	if target_mode == "self_consumption":
		mode_num = 1
		reserve_soc = soc_floor
	elif target_mode == "backup":
		mode_num = 3
		# clamp reserve to at least current SoC to truly block discharge
		current_data_for_clamp = client.get_device_data()
		current_soc = 0
		if current_data_for_clamp is not None:
			current_soc = current_data_for_clamp.get("battery_soc", 0)
		reserve_soc = max(soc_floor, current_soc)
		logger.info(
			"Backup SoC clamp: floor %d%%, current %d%%, using %d%%",
			soc_floor, current_soc, reserve_soc,
		)
	else:
		logger.info("EP Cube: no mode change needed for action %s", action)
		return False
	# check if mode actually needs to change
	current_data = client.get_device_data()
	if current_data is not None:
		current_mode = current_data.get("work_status", "")
		if current_mode == str(mode_num):
			logger.debug("EP Cube already in mode %d, checking reserve SoC", mode_num)
	if dry_run:
		logger.info(
			"[DRY RUN] Would set EP Cube to mode %d (%s) with reserve SoC %d",
			mode_num, MODE_MAP.get(str(mode_num), "unknown"), reserve_soc
		)
		return True
	# send the command
	success = client.set_mode(mode_num, reserve_soc=reserve_soc)
	return success


#============================================
def _safe_float(value) -> float:
	"""
	Safely convert a value to float.

	Args:
		value: Value to convert.

	Returns:
		float: Converted value, or 0.0 on failure.
	"""
	if value is None:
		return 0.0
	try:
		return float(value)
	except (ValueError, TypeError):
		return 0.0


#============================================
def _safe_int(value) -> int:
	"""
	Safely convert a value to int.

	Args:
		value: Value to convert.

	Returns:
		int: Converted value, or 0 on failure.
	"""
	if value is None:
		return 0
	try:
		return int(value)
	except (ValueError, TypeError):
		return 0
