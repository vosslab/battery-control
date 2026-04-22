"""Command buffer with deadband for EP Cube update suppression."""

# Standard Library
import datetime

# local repo modules
import battcontrol.state


#============================================
def should_send_epcube_update(
	desired_mode: str,
	desired_reserve_soc: int,
	control_state: battcontrol.state.ControlState,
	config: dict,
	now: datetime.datetime,
	device_mode: str = None,
	device_reserve_soc: int = None,
) -> tuple:
	"""
	Determine if EP Cube update should be sent using deadband logic.

	When device_mode and device_reserve_soc are both provided (authoritative
	state fetched from the EP Cube cloud this cycle), suppression compares
	the desired command against what the device currently reports. This
	lets two daemons on different hosts converge without shared local state:
	whichever host wrote last is observable to both on the next cycle, so
	neither host keeps overwriting the other.

	When device state is None (API call failed, or single-host operation
	without the lookup), falls back to the local-memory path using
	control_state.last_epcube_mode / .last_epcube_reserve_soc.

	Sends update when: (1) mode changed, (2) reserve SoC changed beyond
	deadband, (3) resend interval expired (fallback path only, since the
	device-state path reads current reserve each cycle and does not need
	a keepalive), or (4) first-ever command / no prior state.

	Args:
		desired_mode: Target mode string (e.g., "self_consumption", "backup").
		desired_reserve_soc: Target reserve SoC percentage (0-100).
		control_state: ControlState object with last-command tracking.
		config: Config dict with "reserve_soc_buffer_pct" and
			"epcube_resend_interval_minutes" keys.
		now: Current datetime for interval calculation.
		device_mode: Optional authoritative mode string from the device.
		device_reserve_soc: Optional authoritative reserve SoC from the device.

	Returns:
		tuple: (should_send: bool, buffer_reason: str) where buffer_reason
			explains the decision.
	"""

	# Get config values
	buffer_pct = config["reserve_soc_buffer_pct"]
	resend_interval_minutes = config["epcube_resend_interval_minutes"]

	# device-state path: authoritative, used when both fields are available
	if device_mode is not None and device_reserve_soc is not None:
		if desired_mode != device_mode:
			reason = f"mode mismatch: device {device_mode} -> desired {desired_mode}"
			return (True, reason)
		delta = abs(desired_reserve_soc - device_reserve_soc)
		if delta >= buffer_pct:
			reason = (
				f"reserve SoC change: device {device_reserve_soc}% -> "
				f"desired {desired_reserve_soc}% (delta {delta}%)"
			)
			return (True, reason)
		reason = (
			f"unchanged: device already at mode {device_mode} reserve "
			f"{device_reserve_soc}% (delta {delta}% within {buffer_pct}%)"
		)
		return (False, reason)

	# fallback path: local memory (single-host or device state unavailable)
	last_mode = control_state.last_epcube_mode
	last_reserve = control_state.last_epcube_reserve_soc
	last_command_at = control_state.last_epcube_command_at

	# Rule 4: first-ever command (no previous state)
	if last_mode == "":
		reason = "first command: no previous state"
		return (True, reason)

	# Rule 1: mode changed
	if desired_mode != last_mode:
		reason = f"mode changed: {last_mode} -> {desired_mode}"
		return (True, reason)

	# Rule 2: reserve SoC changed beyond deadband
	if last_reserve is not None:
		delta = abs(desired_reserve_soc - last_reserve)
		if delta >= buffer_pct:
			reason = f"reserve SoC changed: {last_reserve}% -> {desired_reserve_soc}% (delta {delta}%)"
			return (True, reason)
		# reserve change is below buffer, will check interval below
	else:
		# last_reserve is None, treat as first command
		reason = "first command: no previous reserve state"
		return (True, reason)

	# Rule 3: optional periodic resend (fallback path only)
	if resend_interval_minutes > 0:
		if last_command_at is None:
			# No previous command timestamp, treat as expired
			reason = "resend interval expired: no previous timestamp"
			return (True, reason)
		# Parse last command timestamp and check elapsed time
		last_command_dt = datetime.datetime.fromisoformat(last_command_at)
		elapsed = now - last_command_dt
		elapsed_minutes = elapsed.total_seconds() / 60
		if elapsed_minutes >= resend_interval_minutes:
			reason = f"resend interval expired: {int(elapsed_minutes)} min since last command"
			return (True, reason)

	# No update needed
	if last_reserve is not None:
		delta = abs(desired_reserve_soc - last_reserve)
		reason = f"unchanged: reserve change {delta}% below {buffer_pct}% buffer"
	else:
		reason = "unchanged: no previous state"
	return (False, reason)
