"""Hysteresis and state persistence for battery control system."""

# Standard Library
import os
import json
import tempfile
import datetime


# default state values
_DEFAULT_STATE = {
	"price_band_counter": 0,
	"current_price_band": "",
	"last_action": "",
	"action_stable_count": 0,
	"peak_mode_active": False,
	"peak_mode_entered_at": None,
	"last_solar_above_threshold_at": None,
	"token_expired": False,
	"token_expired_at": None,
	"token_last_success_at": None,
}


#============================================
class ControlState:
	"""
	Manages hysteresis counters and last-action state.

	Persists to a JSON file for continuity between scheduler runs.
	"""

	#============================================
	def __init__(self, file_path: str = None):
		"""
		Initialize state manager.

		Args:
			file_path: Path to the JSON state file.
		"""
		if file_path is None:
			file_path = os.path.join(tempfile.gettempdir(), "battery_control_state.json")
		self.file_path = file_path
		self.price_band_counter = 0
		self.current_price_band = ""
		self.last_action = ""
		self.action_stable_count = 0
		self.peak_mode_active = False
		self.peak_mode_entered_at = None
		self.last_solar_above_threshold_at = None
		self.token_expired = False
		self.token_expired_at = None
		self.token_last_success_at = None

	#============================================
	def load(self) -> None:
		"""
		Load state from JSON file. Handles missing file gracefully.
		"""
		if not os.path.isfile(self.file_path):
			return
		with open(self.file_path, "r") as f:
			data = json.load(f)
		self.price_band_counter = data.get("price_band_counter", 0)
		self.current_price_band = data.get("current_price_band", "")
		self.last_action = data.get("last_action", "")
		self.action_stable_count = data.get("action_stable_count", 0)
		self.peak_mode_active = data.get("peak_mode_active", False)
		self.peak_mode_entered_at = data.get("peak_mode_entered_at", None)
		self.last_solar_above_threshold_at = data.get("last_solar_above_threshold_at", None)
		self.token_expired = data.get("token_expired", False)
		self.token_expired_at = data.get("token_expired_at", None)
		self.token_last_success_at = data.get("token_last_success_at", None)

	#============================================
	def save(self) -> None:
		"""
		Save state to JSON file atomically (write to tmp, rename).
		"""
		data = {
			"price_band_counter": self.price_band_counter,
			"current_price_band": self.current_price_band,
			"last_action": self.last_action,
			"action_stable_count": self.action_stable_count,
			"peak_mode_active": self.peak_mode_active,
			"peak_mode_entered_at": self.peak_mode_entered_at,
			"last_solar_above_threshold_at": self.last_solar_above_threshold_at,
			"token_expired": self.token_expired,
			"token_expired_at": self.token_expired_at,
			"token_last_success_at": self.token_last_success_at,
		}
		tmp_path = self.file_path + ".tmp"
		with open(tmp_path, "w") as f:
			json.dump(data, f, indent=2)
		os.replace(tmp_path, self.file_path)

	#============================================
	def reset_daily(self) -> None:
		"""
		Clear peak mode state for a new day.
		"""
		self.peak_mode_active = False
		self.peak_mode_entered_at = None

	#============================================
	def update_price_band(self, new_band: str) -> bool:
		"""
		Update price band tracking with hysteresis.

		Args:
			new_band: The newly detected price band name.

		Returns:
			bool: True if band has changed (counter reset), False if same band.
		"""
		if new_band == self.current_price_band:
			self.price_band_counter += 1
			return False
		# band changed, reset counter
		self.current_price_band = new_band
		self.price_band_counter = 1
		return True

	#============================================
	def update_action(self, new_action: str) -> None:
		"""
		Track action stability for token friction.

		Args:
			new_action: The action string from the decision engine.
		"""
		if new_action == self.last_action:
			self.action_stable_count += 1
		else:
			self.last_action = new_action
			self.action_stable_count = 1

	#============================================
	def mark_token_expired(self) -> None:
		"""
		Record that the EP Cube token has expired.
		"""
		self.token_expired = True
		self.token_expired_at = datetime.datetime.now().isoformat()

	#============================================
	def mark_token_success(self) -> None:
		"""
		Record a successful EP Cube API call.
		"""
		self.token_expired = False
		self.token_expired_at = None
		self.token_last_success_at = datetime.datetime.now().isoformat()

	#============================================
	def to_dict(self) -> dict:
		"""
		Return state as a dictionary.

		Returns:
			dict: Current state values.
		"""
		return {
			"price_band_counter": self.price_band_counter,
			"current_price_band": self.current_price_band,
			"last_action": self.last_action,
			"action_stable_count": self.action_stable_count,
			"peak_mode_active": self.peak_mode_active,
			"peak_mode_entered_at": self.peak_mode_entered_at,
			"last_solar_above_threshold_at": self.last_solar_above_threshold_at,
			"token_expired": self.token_expired,
			"token_expired_at": self.token_expired_at,
			"token_last_success_at": self.token_last_success_at,
		}
