"""Tests for epcube_client.py - EP Cube API client."""

# Standard Library
from unittest import mock

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

import sys
sys.path.insert(0, REPO_ROOT)
import battcontrol.epcube_client as epcube_client


#============================================
class TestEpcubeClient:
	"""Tests for EpcubeClient class."""

	#============================================
	def test_init(self):
		"""Client initializes with correct base URL."""
		client = epcube_client.EpcubeClient("test_token", "US", "SN123")
		assert client.token == "test_token"
		assert client.region == "US"
		assert client.device_sn == "SN123"
		assert "epcube-monitoring.com" in client.base_url

	#============================================
	def test_init_eu_region(self):
		"""EU region uses correct base URL."""
		client = epcube_client.EpcubeClient("token", "EU", "SN123")
		assert "monitoring-eu.epcube.com" in client.base_url

	#============================================
	@mock.patch("battcontrol.epcube_client.requests.get")
	@mock.patch("battcontrol.epcube_client.time.sleep")
	def test_get_device_data_success(self, mock_sleep, mock_get):
		"""Successful device data fetch returns normalized dict."""
		mock_resp = mock.Mock()
		mock_resp.status_code = 200
		mock_resp.json.return_value = {
			"data": {
				"batterySoc": 75,
				"solarPower": 300,
				"gridPower": 50,
				"backupPower": 200,
				"workStatus": "1",
				"devId": "DEV123",
			}
		}
		mock_get.return_value = mock_resp
		client = epcube_client.EpcubeClient("token", "US", "SN123")
		data = client.get_device_data()
		assert data is not None
		assert data["battery_soc"] == 75
		# power values multiplied by 10
		assert data["solar_power_watts"] == 3000.0
		assert data["grid_power_watts"] == 500.0
		assert data["backup_power_watts"] == 2000.0
		assert data["work_status"] == "1"
		assert data["device_id"] == "DEV123"

	#============================================
	@mock.patch("battcontrol.epcube_client.requests.get")
	@mock.patch("battcontrol.epcube_client.time.sleep")
	def test_get_device_data_401(self, mock_sleep, mock_get):
		"""401 response returns None (token expired)."""
		mock_resp = mock.Mock()
		mock_resp.status_code = 401
		mock_resp.text = "Unauthorized"
		mock_get.return_value = mock_resp
		client = epcube_client.EpcubeClient("bad_token", "US", "SN123")
		data = client.get_device_data()
		assert data is None

	#============================================
	@mock.patch("battcontrol.epcube_client.requests.post")
	@mock.patch("battcontrol.epcube_client.time.sleep")
	def test_set_mode_self_consumption(self, mock_sleep, mock_post):
		"""Set mode 1 (Self-consumption) with reserve SoC."""
		mock_resp = mock.Mock()
		mock_resp.status_code = 200
		mock_resp.json.return_value = {"code": 200}
		mock_post.return_value = mock_resp
		client = epcube_client.EpcubeClient("token", "US", "SN123")
		client._device_id = "DEV123"
		success = client.set_mode(1, reserve_soc=15)
		assert success is True
		# verify payload
		call_kwargs = mock_post.call_args
		payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
		assert payload["workStatus"] == "1"
		assert payload["selfConsumptioinReserveSoc"] == "15"

	#============================================
	@mock.patch("battcontrol.epcube_client.requests.post")
	@mock.patch("battcontrol.epcube_client.time.sleep")
	def test_set_mode_backup(self, mock_sleep, mock_post):
		"""Set mode 3 (Backup) with reserve SoC."""
		mock_resp = mock.Mock()
		mock_resp.status_code = 200
		mock_resp.json.return_value = {"code": 200}
		mock_post.return_value = mock_resp
		client = epcube_client.EpcubeClient("token", "US", "SN123")
		client._device_id = "DEV123"
		success = client.set_mode(3, reserve_soc=50)
		assert success is True
		call_kwargs = mock_post.call_args
		payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
		assert payload["workStatus"] == "3"
		assert payload["backupPowerReserveSoc"] == "50"

	#============================================
	def test_set_mode_no_device_id(self):
		"""set_mode without device_id returns False."""
		client = epcube_client.EpcubeClient("token", "US", "SN123")
		success = client.set_mode(1, reserve_soc=15)
		assert success is False

	#============================================
	@mock.patch("battcontrol.epcube_client.requests.get")
	@mock.patch("battcontrol.epcube_client.time.sleep")
	def test_get_device_data_electricity_counters(self, mock_sleep, mock_get):
		"""All 6 electricity counter fields present with realistic values."""
		mock_resp = mock.Mock()
		mock_resp.status_code = 200
		mock_resp.json.return_value = {
			"data": {
				"batterySoc": 75,
				"solarPower": 300,
				"gridPower": 50,
				"backupPower": 200,
				"workStatus": "1",
				"devId": "DEV123",
				"gridElectricity": 1234.56,
				"solarElectricity": 5678.90,
				"smartHomeElectricity": 234.5,
				"backupElectricity": 123.4,
				"batteryCurrentElectricity": 456.78,
				"nonBackupElectricity": 89.01,
			}
		}
		mock_get.return_value = mock_resp
		client = epcube_client.EpcubeClient("token", "US", "SN123")
		data = client.get_device_data()
		assert data is not None
		assert data["grid_electricity_kwh"] == 1234.56
		assert data["solar_electricity_kwh"] == 5678.90
		assert data["smart_home_electricity_kwh"] == 234.5
		assert data["backup_electricity_kwh"] == 123.4
		assert data["battery_electricity_kwh"] == 456.78
		assert data["non_backup_electricity_kwh"] == 89.01

	#============================================
	@mock.patch("battcontrol.epcube_client.requests.get")
	@mock.patch("battcontrol.epcube_client.time.sleep")
	def test_get_device_data_missing_electricity_fields(self, mock_sleep, mock_get):
		"""All 6 electricity fields missing return None."""
		mock_resp = mock.Mock()
		mock_resp.status_code = 200
		mock_resp.json.return_value = {
			"data": {
				"batterySoc": 75,
				"solarPower": 300,
				"gridPower": 50,
				"backupPower": 200,
				"workStatus": "1",
				"devId": "DEV123",
			}
		}
		mock_get.return_value = mock_resp
		client = epcube_client.EpcubeClient("token", "US", "SN123")
		data = client.get_device_data()
		assert data is not None
		assert data["grid_electricity_kwh"] is None
		assert data["solar_electricity_kwh"] is None
		assert data["smart_home_electricity_kwh"] is None
		assert data["backup_electricity_kwh"] is None
		assert data["battery_electricity_kwh"] is None
		assert data["non_backup_electricity_kwh"] is None

	#============================================
	@mock.patch("battcontrol.epcube_client.requests.get")
	@mock.patch("battcontrol.epcube_client.time.sleep")
	def test_get_device_data_zero_electricity_fields(self, mock_sleep, mock_get):
		"""All 6 electricity fields = 0.0 return 0.0 (not None)."""
		mock_resp = mock.Mock()
		mock_resp.status_code = 200
		mock_resp.json.return_value = {
			"data": {
				"batterySoc": 75,
				"solarPower": 300,
				"gridPower": 50,
				"backupPower": 200,
				"workStatus": "1",
				"devId": "DEV123",
				"gridElectricity": 0.0,
				"solarElectricity": 0.0,
				"smartHomeElectricity": 0.0,
				"backupElectricity": 0.0,
				"batteryCurrentElectricity": 0.0,
				"nonBackupElectricity": 0.0,
			}
		}
		mock_get.return_value = mock_resp
		client = epcube_client.EpcubeClient("token", "US", "SN123")
		data = client.get_device_data()
		assert data is not None
		assert data["grid_electricity_kwh"] == 0.0
		assert data["solar_electricity_kwh"] == 0.0
		assert data["smart_home_electricity_kwh"] == 0.0
		assert data["backup_electricity_kwh"] == 0.0
		assert data["battery_electricity_kwh"] == 0.0
		assert data["non_backup_electricity_kwh"] == 0.0

	#============================================
	@mock.patch("battcontrol.epcube_client.requests.get")
	@mock.patch("battcontrol.epcube_client.time.sleep")
	def test_get_device_data_partial_electricity_fields(self, mock_sleep, mock_get):
		"""Mix of present and missing electricity fields."""
		mock_resp = mock.Mock()
		mock_resp.status_code = 200
		mock_resp.json.return_value = {
			"data": {
				"batterySoc": 75,
				"solarPower": 300,
				"gridPower": 50,
				"backupPower": 200,
				"workStatus": "1",
				"devId": "DEV123",
				"gridElectricity": 999.99,
				"solarElectricity": 888.88,
				"backupElectricity": 0.0,
			}
		}
		mock_get.return_value = mock_resp
		client = epcube_client.EpcubeClient("token", "US", "SN123")
		data = client.get_device_data()
		assert data is not None
		assert data["grid_electricity_kwh"] == 999.99
		assert data["solar_electricity_kwh"] == 888.88
		assert data["smart_home_electricity_kwh"] is None
		assert data["backup_electricity_kwh"] == 0.0
		assert data["battery_electricity_kwh"] is None
		assert data["non_backup_electricity_kwh"] is None


#============================================
class TestExecuteEpcube:
	"""Tests for execute_epcube actuator function."""

	#============================================
	def test_dry_run_backup_mode(self):
		"""Dry run logs backup mode change without sending."""
		from battcontrol.decision_engine import Action, DecisionResult
		result = DecisionResult(
			action=Action.DISCHARGE_DISABLED,
			reason="test",
			soc_floor=50,
			target_mode="backup",
		)
		client = mock.Mock()
		client.get_device_data.return_value = {"work_status": "1"}
		config = {}
		success = epcube_client.execute_epcube(result, client, config, dry_run=True)
		assert success is True
		# should not call set_mode in dry run
		client.set_mode.assert_not_called()

	#============================================
	def test_no_client(self):
		"""No client returns False."""
		from battcontrol.decision_engine import Action, DecisionResult
		result = DecisionResult(
			action=Action.DISCHARGE_DISABLED,
			reason="test",
			soc_floor=50,
			target_mode="backup",
		)
		success = epcube_client.execute_epcube(result, None, {}, dry_run=False)
		assert success is False


