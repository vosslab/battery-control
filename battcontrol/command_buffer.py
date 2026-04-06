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
) -> tuple:
	"""
	Determine if EP Cube update should be sent using deadband logic.

	Sends update when: (1) mode changed, (2) reserve SoC changed beyond
	deadband, (3) resend interval expired, or (4) first-ever command.
	Otherwise returns (False, reason_string).

	Args:
		desired_mode: Target mode string (e.g., "self_consumption", "backup").
		desired_reserve_soc: Target reserve SoC percentage (0-100).
		control_state: ControlState object with last-command tracking.
		config: Config dict with "reserve_soc_buffer_pct" and
			"epcube_resend_interval_minutes" keys.
		now: Current datetime for interval calculation.

	Returns:
		tuple: (should_send: bool, buffer_reason: str) where buffer_reason
			explains the decision (e.g., "mode changed: old -> new",
			"unchanged: same mode and reserve within buffer").
	"""

	# Get config values
	buffer_pct = config["reserve_soc_buffer_pct"]
	resend_interval_minutes = config["epcube_resend_interval_minutes"]

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

	# Rule 3: optional periodic resend
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
