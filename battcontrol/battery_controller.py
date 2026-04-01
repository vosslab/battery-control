#!/usr/bin/env python3

"""Main battery controller - orchestrates config, data fetch, decision, and actuation."""

# Standard Library
import os
import json
import logging
import argparse
import datetime

# PIP3 modules
import requests

# local repo modules
import battcontrol.config
import battcontrol.state
import battcontrol.decision_engine
import battcontrol.command_buffer
import battcontrol.hourly_logger
import battcontrol.epcube_client
import battcontrol.wemo_actuator
import battcontrol.epcube_login

logger = logging.getLogger(__name__)


#============================================
def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Battery control system for EP Cube and WeMo batteries"
	)
	parser.add_argument(
		'-c', '--config', dest='config_file', default='config.yml',
		help="Path to YAML configuration file (default: config.yml)",
	)
	parser.add_argument(
		'-n', '--dry-run', dest='dry_run',
		action='store_true',
		help="Log decisions without sending commands (default)",
	)
	parser.add_argument(
		'-x', '--execute', dest='dry_run',
		action='store_false',
		help="Actually send commands to devices",
	)
	parser.add_argument(
		'-v', '--verbose', dest='verbose',
		action='count', default=0,
		help="Increase logging verbosity",
	)
	parser.add_argument(
		'--dump-raw', dest='dump_raw',
		action='store_true', default=False,
		help="Log raw EP Cube API payload and normalized state once",
	)
	parser.set_defaults(dry_run=True)
	args = parser.parse_args()
	return args


#============================================
def _setup_logging(verbose: int) -> None:
	"""
	Configure logging based on verbosity level.

	Logs to both the terminal and battery_controller.log in the current
	working directory. The file log always uses INFO level regardless of
	the terminal verbosity setting.

	Args:
		verbose: Verbosity count (0=WARNING, 1=INFO, 2=DEBUG).
	"""
	if verbose >= 2:
		console_level = logging.DEBUG
	elif verbose >= 1:
		console_level = logging.INFO
	else:
		console_level = logging.WARNING
	# set root logger to the most permissive level needed
	file_level = logging.INFO
	root_level = min(console_level, file_level)
	root_logger = logging.getLogger()
	# clear existing handlers to avoid accumulation when called repeatedly
	for handler in list(root_logger.handlers):
		root_logger.removeHandler(handler)
		handler.close()
	root_logger.setLevel(root_level)
	# console handler (short format for scannability)
	console_format = "  %(levelname)-7s %(module)s: %(message)s"
	console_handler = logging.StreamHandler()
	console_handler.setLevel(console_level)
	console_handler.setFormatter(logging.Formatter(console_format))
	root_logger.addHandler(console_handler)
	# file handler (full format with timestamps, always INFO, append mode)
	file_format = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
	file_date_format = "%Y-%m-%d %H:%M:%S"
	file_handler = logging.FileHandler("battery_controller.log", mode="a")
	file_handler.setLevel(file_level)
	file_handler.setFormatter(logging.Formatter(file_format, datefmt=file_date_format))
	root_logger.addHandler(file_handler)


#============================================
def _fetch_comed_price() -> tuple:
	"""
	Fetch predicted ComEd price, median, and usage cutoff for decision making.

	Uses getPredictedRate() which applies linear regression on the current
	hour's data points to estimate where the price is heading. This is better
	for proactive decisions than the instantaneous current rate.

	Returns:
		tuple: (predicted_price_cents, median_cents, cutoff_cents) or
			(None, None, None) on failure.
	"""
	try:
		import battcontrol.comedlib
		comlib = battcontrol.comedlib.ComedLib()
		# getPredictedRate() is a worst-case estimator, not the instantaneous rate
		# (see docs/STRATEGY.md "Price input: worst-case predictor")
		predicted_price = comlib.getPredictedRate()
		median_price, _ = comlib.getMedianComedRate()
		cutoff_price = comlib.getReasonableCutOff()
		logger.info(
			"ComEd price: predicted %.2fc, current %.2fc, median %.2fc, cutoff %.2fc",
			predicted_price, comlib.getCurrentComedRate(), median_price, cutoff_price,
		)
		return predicted_price, median_price, cutoff_price
	except (RuntimeError, ValueError, requests.RequestException) as err:
		logger.error("Failed to fetch ComEd price: %s", err)
		return None, None, None


#============================================
def _has_auth_credentials(config: dict) -> bool:
	"""
	Check if EP Cube auth credentials are available for auto-renewal.

	Args:
		config: Configuration dictionary.

	Returns:
		bool: True if username and password are present.
	"""
	has_creds = bool(config.get("epcube_username")) and bool(config.get("epcube_password"))
	return has_creds


#============================================
def _auto_renew_token(config: dict, control_state: battcontrol.state.ControlState) -> str | None:
	"""
	Attempt to auto-renew the EP Cube token using stored credentials.

	Uses the CAPTCHA solver from epcube_get_token to generate a fresh token.
	On success, writes the token to the token file and updates config.

	Args:
		config: Configuration dictionary with epcube_username and epcube_password.
		control_state: Control state for token tracking.

	Returns:
		str: New token string, or None if renewal failed.
	"""
	username = config.get("epcube_username", "")
	password = config.get("epcube_password", "")
	region = config.get("epcube_region", "US")
	logger.info("Attempting auto-renewal of EP Cube token for region %s", region)
	# call the CAPTCHA solver and login
	new_token = battcontrol.epcube_login.generate_token(username, password, region)
	if new_token is None:
		logger.warning(
			"Auto-renewal failed. "
			"Run epcube_get_token.py manually to regenerate."
		)
		return None
	# save the new token to the token file
	token_file = config.get("epcube_token_file", "")
	if token_file:
		token_path = battcontrol.epcube_login.write_token(new_token, token_file)
		logger.info("New token saved to %s", token_path)
	# update config in memory
	config["epcube_token"] = new_token
	# clear the expired state
	control_state.mark_token_success()
	return new_token


#============================================
def _ensure_valid_token(
	config: dict,
	control_state: battcontrol.state.ControlState,
) -> str | None:
	"""
	Return a valid EP Cube token, attempting auto-renewal if needed.

	Checks in order: current token in config, known-expired flag in state,
	and auto-renewal via stored credentials. Returns None with appropriate
	logging if no valid token can be obtained.

	Args:
		config: Configuration dictionary.
		control_state: Control state for token tracking.

	Returns:
		str: A valid token string, or None if unavailable.
	"""
	token = config.get("epcube_token", "")
	has_creds = _has_auth_credentials(config)
	# no token at all -- try generating one
	if not token:
		if has_creds:
			logger.info("No token file found, attempting auto-generation")
			token = _auto_renew_token(config, control_state)
		if not token:
			if has_creds:
				logger.warning("No token and auto-generation failed. "
					"Run epcube_get_token.py manually.")
			else:
				logger.info("No EP Cube token or auth file configured")
			return None
		# auto-generation succeeded, token is fresh
		return token
	# token exists but is known expired -- try renewal
	if control_state.token_expired:
		expired_at = control_state.token_expired_at or "unknown"
		if has_creds:
			logger.info("Token expired at %s, attempting auto-renewal", expired_at)
			renewed = _auto_renew_token(config, control_state)
			if renewed:
				return renewed
			logger.warning("Token expired and auto-renewal failed. "
				"Run epcube_get_token.py manually.")
			return None
		logger.warning(
			"Token expired at %s. No auth file configured. "
			"Run epcube_get_token.py to regenerate.",
			expired_at,
		)
		return None
	# token exists and not known expired
	return token


#============================================
def _try_renew_after_rejection(
	config: dict,
	control_state: battcontrol.state.ControlState,
) -> tuple:
	"""
	Handle token rejection (401) by attempting one renewal and retry.

	Args:
		config: Configuration dictionary.
		control_state: Control state for token tracking.

	Returns:
		tuple: (device_data_dict, epcube_client) or (None, None) on failure.
	"""
	has_creds = _has_auth_credentials(config)
	if not has_creds:
		control_state.mark_token_expired()
		logger.warning("Token rejected by EP Cube. No auth file configured. "
			"Run epcube_get_token.py to regenerate.")
		return None, None
	logger.info("Token rejected by API, attempting auto-renewal")
	renewed = _auto_renew_token(config, control_state)
	if not renewed:
		control_state.mark_token_expired()
		logger.warning("Token rejected and auto-renewal failed. "
			"Run epcube_get_token.py manually.")
		return None, None
	# retry once with the new token
	region = config.get("epcube_region", "US")
	device_sn = config.get("epcube_device_sn", "")
	client = battcontrol.epcube_client.EpcubeClient(renewed, region, device_sn)
	try:
		device_data = client.get_device_data()
	except RuntimeError as err:
		logger.error("EP Cube API error after renewal: %s", err)
		return None, None
	if device_data is None:
		logger.error("EP Cube still rejecting after token renewal")
		control_state.mark_token_expired()
		return None, None
	return device_data, client


#============================================
def _fetch_epcube_data(config: dict, control_state: battcontrol.state.ControlState) -> tuple:
	"""
	Fetch EP Cube device data.

	Tries the current token first. If the token is missing or expired,
	attempts auto-renewal using stored credentials from the auth file.

	Args:
		config: Configuration dictionary.
		control_state: Control state for token tracking.

	Returns:
		tuple: (device_data_dict, epcube_client) or (None, None) on failure.
	"""
	token = _ensure_valid_token(config, control_state)
	if not token:
		return None, None
	region = config.get("epcube_region", "US")
	device_sn = config.get("epcube_device_sn", "")
	client = battcontrol.epcube_client.EpcubeClient(token, region, device_sn)
	try:
		device_data = client.get_device_data()
	except RuntimeError as err:
		logger.error("EP Cube API error: %s", err)
		return None, None
	# token rejected (likely 401), try one renewal
	if device_data is None:
		device_data, client = _try_renew_after_rejection(config, control_state)
		if device_data is None:
			return None, None
	# token is working
	control_state.mark_token_success()
	_check_token_age(control_state, config)
	logger.info(
		"EP Cube: SoC=%d%%, Solar=%.0fW, Grid=%.0fW, "
		"Load=%.0fW, Backup=%.0fW, NonBackup=%.0fW, Batt=%.0fW, Mode=%s",
		device_data.get("battery_soc", 0),
		device_data.get("solar_power_watts", 0),
		device_data.get("grid_power_watts", 0),
		device_data.get("smart_home_power_watts", 0),
		device_data.get("backup_power_watts", 0),
		device_data.get("non_backup_power_watts", 0),
		device_data.get("battery_power_watts", 0),
		device_data.get("work_status", "?"),
	)
	return device_data, client


#============================================
def _check_token_age(control_state: battcontrol.state.ControlState, config: dict) -> None:
	"""
	Check if the EP Cube token is nearing expiration.

	Args:
		control_state: Control state with token timestamps.
		config: Configuration dictionary.
	"""
	last_success = control_state.token_last_success_at
	if last_success is None:
		return
	last_dt = datetime.datetime.fromisoformat(last_success)
	age_hours = (datetime.datetime.now() - last_dt).total_seconds() / 3600.0
	max_hours = config.get("token_warning_age_hours", 168)
	if age_hours > max_hours:
		logger.warning(
			"EP Cube token is %.0f hours old (warning threshold: %d hours). "
			"Consider regenerating soon.",
			age_hours, max_hours,
		)


#============================================
# keys in raw payload that may contain sensitive identifiers
_SENSITIVE_KEYS = {"devid", "sgsn", "sn", "token", "userid", "username"}


#============================================
def _dump_raw_payload(raw_data: dict, normalized: dict) -> None:
	"""
	Write the raw EP Cube API payload and normalized state to JSON files.

	Masks values for keys that look like serial numbers, tokens, or user IDs.
	Files are written to the current working directory with timestamped names.

	Args:
		raw_data: Original dict from the API response.
		normalized: Normalized dict produced by epcube_client.
	"""
	# build timestamp string for filenames
	now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
	# mask sensitive fields in a copy of the raw data
	masked_raw = {}
	for key, value in raw_data.items():
		if key.lower() in _SENSITIVE_KEYS:
			str_val = str(value)
			if len(str_val) > 4:
				masked_val = str_val[:2] + "***" + str_val[-2:]
			else:
				masked_val = "***"
			masked_raw[key] = masked_val
		else:
			masked_raw[key] = value
	# mask device_id in normalized copy
	masked_norm = dict(normalized)
	dev_id = masked_norm.get("device_id", "")
	if dev_id and len(dev_id) > 4:
		masked_norm["device_id"] = dev_id[:2] + "***" + dev_id[-2:]
	# write raw payload to JSON file (keys sorted alphabetically)
	raw_path = f"epcube_raw_{now_str}.json"
	with open(raw_path, "w") as f:
		json.dump(masked_raw, f, indent=2, sort_keys=True)
	print(f"Wrote {len(masked_raw)} entries to {raw_path}")
	# write normalized state to JSON file (keys sorted alphabetically)
	norm_path = f"epcube_normalized_{now_str}.json"
	with open(norm_path, "w") as f:
		json.dump(masked_norm, f, indent=2, sort_keys=True)
	print(f"Wrote {len(masked_norm)} entries to {norm_path}")


#============================================
def _select_load_source(epcube_data: dict) -> float:
	"""
	Select the best load power source from EP Cube data.

	Prefers smartHomePower (total house load) over backUpPower (backup
	circuits only). Falls back to backUpPower when smartHomePower is zero
	or unavailable.

	Args:
		epcube_data: Normalized EP Cube device data dictionary.

	Returns:
		float: Load power in watts.
	"""
	smart_home_load = epcube_data.get("smart_home_power_watts", 0)
	backup_load = epcube_data.get("backup_power_watts", 0)
	if smart_home_load > 0:
		logger.info("Load source: smartHomePower (%.0fW)", smart_home_load)
		return smart_home_load
	logger.info("Load source: backUpPower fallback (%.0fW)", backup_load)
	return backup_load


#============================================
def main() -> None:
	"""
	Main entry point for the battery controller.
	"""
	args = parse_args()
	_setup_logging(args.verbose)
	now = datetime.datetime.now()
	# load config
	if not os.path.isfile(args.config_file):
		raise FileNotFoundError(
			f"Config file not found: {args.config_file}\n"
			f"Copy config_example.yml to config.yml or pass -c <path>"
		)
	config = battcontrol.config.load_config(args.config_file)
	# override dry_run from CLI
	dry_run = args.dry_run
	if not dry_run:
		logger.warning("EXECUTE MODE: commands will be sent to devices")
	else:
		logger.info("DRY RUN MODE: no commands will be sent")
	# load state
	state_path = config.get("state_file_path")
	# default comes from config.DEFAULTS which uses tempfile.gettempdir()
	control_state = battcontrol.state.ControlState(state_path)
	control_state.load()
	# initialize hourly logger for persistent CSV history
	csv_path = config.get("hourly_csv_path", "data/hourly_history.csv")
	hourly_logger = battcontrol.hourly_logger.HourlyLogger(csv_path)
	# fetch ComEd price
	comed_price, comed_median, comed_cutoff = _fetch_comed_price()
	if comed_price is None:
		logger.warning("ComEd price unavailable, holding current state")
		control_state.save()
		_print_summary("discharge_disabled", "Backup", 0, "ComEd unavailable", dry_run)
		return
	# fetch EP Cube data
	epcube_data, epcube_client = _fetch_epcube_data(config, control_state)
	# dump raw payload if requested
	if args.dump_raw and epcube_data is not None and epcube_client is not None:
		raw = epcube_client.last_raw_data or {}
		_dump_raw_payload(raw, epcube_data)
	# determine battery SoC and solar power from device
	if epcube_data is None:
		# no device data available, hold current state
		logger.warning("EP Cube data unavailable, holding current state")
		control_state.save()
		_print_summary("discharge_disabled", "Backup", 0, "EP Cube unavailable", dry_run)
		return
	battery_soc = epcube_data.get("battery_soc", 0)
	solar_power = epcube_data.get("solar_power_watts", 0)
	load_power = _select_load_source(epcube_data)
	# run decision engine
	result = battcontrol.decision_engine.decide(
		battery_soc=battery_soc,
		solar_power_watts=solar_power,
		load_power_watts=load_power,
		comed_price_cents=comed_price,
		comed_median_cents=comed_median,
		comed_cutoff_cents=comed_cutoff,
		config=config,
		control_state=control_state,
		current_time=now,
	)
	# record cycle data for hourly CSV history
	hourly_logger.record_cycle(
		now=now,
		epcube_data=epcube_data,
		comed_price=comed_price,
		comed_median=comed_median,
		comed_cutoff=comed_cutoff,
		result=result,
		config=config,
	)
	# command buffer: only send EP Cube update when command changes materially
	desired_mode = result.target_mode
	desired_reserve = result.soc_floor
	should_send, buffer_reason = battcontrol.command_buffer.should_send_epcube_update(
		desired_mode=desired_mode,
		desired_reserve_soc=desired_reserve,
		control_state=control_state,
		config=config,
		now=now,
	)
	if should_send:
		logger.info("Sending EP Cube update: %s", buffer_reason)
		# EP Cube actuator
		if epcube_client is not None:
			battcontrol.epcube_client.execute_epcube(result, epcube_client, config, dry_run)
		# update command buffer state
		control_state.last_epcube_mode = desired_mode
		control_state.last_epcube_reserve_soc = desired_reserve
		control_state.last_epcube_command_at = now.isoformat()
		control_state.last_commanded_floor = result.soc_floor
		# WeMo actuator (skip when no plugs configured)
		charge_plug = config.get("wemo_charge_plug_name", "")
		discharge_plug = config.get("wemo_discharge_plug_name", "")
		if charge_plug or discharge_plug:
			battcontrol.wemo_actuator.execute_wemo(result.action, config, dry_run)
	else:
		logger.info("No EP Cube update: %s", buffer_reason)
	# save state
	control_state.save()
	# print summary line for cron log
	mode_name = battcontrol.decision_engine.TARGET_MODE_DISPLAY.get(result.target_mode, result.target_mode)
	_print_summary(result.action.value, mode_name, result.soc_floor, result.reason, dry_run)


#============================================
def _print_summary(action: str, mode_name: str, reserve_soc: int, reason: str, dry_run: bool) -> None:
	"""
	Print a one-line summary suitable for cron logs.

	Args:
		action: Policy action name.
		mode_name: EP Cube mode name.
		reserve_soc: Reserve SoC percentage.
		reason: Decision reason.
		dry_run: Whether in dry-run mode.
	"""
	run_tag = "[DRY]" if dry_run else "[LIVE]"
	now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
	print(f"{run_tag} {now_str} {action} | Mode: {mode_name} | reserve {reserve_soc}% | {reason}")


#============================================
if __name__ == '__main__':
	main()
