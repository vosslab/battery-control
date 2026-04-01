"""Hysteresis and state persistence for battery control system."""

# Standard Library
import os
import json
import tempfile
import datetime


# default state values
_DEFAULT_STATE = {
	"price_segment_counter": 0,
	"current_price_segment": -999,
	"last_action": "",
	"action_stable_count": 0,
	"peak_mode_active": False,
	"peak_mode_entered_at": None,
	"last_solar_above_threshold_at": None,
	"last_commanded_floor": None,
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
		# initialize all fields from defaults
		for key, default in _DEFAULT_STATE.items():
			setattr(self, key, default)

	#============================================
	def load(self) -> None:
		"""
		Load state from JSON file. Handles missing file gracefully.
		"""
		if not os.path.isfile(self.file_path):
			return
		with open(self.file_path, "r") as f:
			data = json.load(f)
		# restore each field from saved data, falling back to defaults
		for key, default in _DEFAULT_STATE.items():
			setattr(self, key, data.get(key, default))

	#============================================
	def save(self) -> None:
		"""
		Save state to JSON file atomically (write to tmp, rename).
		"""
		data = {k: getattr(self, k) for k in _DEFAULT_STATE}
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
	def update_price_segment(self, new_segment: int) -> bool:
		"""
		Update price segment tracking with hysteresis.

		Args:
			new_segment: The segment index from get_price_segment_index().

		Returns:
			bool: True if segment changed (counter reset), False if same.
		"""
		if new_segment == self.current_price_segment:
			self.price_segment_counter += 1
			return False
		# segment changed, reset counter
		self.current_price_segment = new_segment
		self.price_segment_counter = 1
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
		return {k: getattr(self, k) for k in _DEFAULT_STATE}
