#!/usr/bin/env python3

"""Main battery controller - orchestrates config, data fetch, decision, and actuation."""

# Standard Library
import os
import json
import logging
import argparse
import datetime

# local repo modules
import battcontrol.config as config_mod
import battcontrol.state as state_mod
import battcontrol.decision_engine as decision_engine
import battcontrol.epcube_client as epcube_mod
import battcontrol.wemo_actuator as wemo_mod
import epcube_get_token

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

	Args:
		verbose: Verbosity count (0=WARNING, 1=INFO, 2=DEBUG).
	"""
	if verbose >= 2:
		level = logging.DEBUG
	elif verbose >= 1:
		level = logging.INFO
	else:
		level = logging.WARNING
	logging.basicConfig(
		level=level,
		format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
	)


#============================================
def _fetch_comed_price() -> tuple:
	"""
	Fetch predicted ComEd price and median for decision making.

	Uses getPredictedRate() which applies linear regression on the current
	hour's data points to estimate where the price is heading. This is better
	for proactive decisions than the instantaneous current rate.

	Returns:
		tuple: (predicted_price_cents, median_cents) or (None, None) on failure.
	"""
	try:
		import battcontrol.comedlib
		comlib = battcontrol.comedlib.ComedLib()
		predicted_price = comlib.getPredictedRate()
		current_price = comlib.getCurrentComedRate()
		median_price, _ = comlib.getMedianComedRate()
		logger.info(
			"ComEd price: predicted %.2fc, current %.2fc, median %.2fc",
			predicted_price, current_price, median_price,
		)
		return predicted_price, median_price
	except Exception as err:
		logger.error("Failed to fetch ComEd price: %s", err)
		return None, None


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
def _auto_renew_token(config: dict, control_state: state_mod.ControlState) -> str | None:
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
	new_token = epcube_get_token.generate_token(username, password, region)
	if new_token is None:
		logger.warning(
			"Auto-renewal failed. "
			"Run epcube_get_token.py manually to regenerate."
		)
		return None
	# save the new token to the token file
	token_file = config.get("epcube_token_file", "")
	if token_file:
		token_path = epcube_get_token.write_token(new_token, token_file)
		logger.info("New token saved to %s", token_path)
	# update config in memory
	config["epcube_token"] = new_token
	# clear the expired state
	control_state.mark_token_success()
	return new_token


#============================================
def _fetch_epcube_data(config: dict, control_state: state_mod.ControlState) -> tuple:
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
	token = config.get("epcube_token", "")
	device_sn = config.get("epcube_device_sn", "")
	has_creds = _has_auth_credentials(config)
	# track whether we already attempted renewal this run (prevent loops)
	already_renewed = False
	# if no token, try auto-renewal before giving up
	if not token:
		if has_creds:
			logger.info("No token file found, attempting auto-generation")
			token = _auto_renew_token(config, control_state)
			already_renewed = True
		if not token:
			if has_creds:
				logger.warning("No token and auto-generation failed. "
					"Run epcube_get_token.py manually.")
			else:
				logger.info("No EP Cube token or auth file configured")
			return None, None
	# if token is known to be expired, try auto-renewal
	if control_state.token_expired:
		expired_at = control_state.token_expired_at or "unknown"
		if has_creds and not already_renewed:
			logger.info("Token expired at %s, attempting auto-renewal", expired_at)
			renewed = _auto_renew_token(config, control_state)
			already_renewed = True
			if renewed:
				token = renewed
			else:
				logger.warning("Token expired and auto-renewal failed. "
					"Run epcube_get_token.py manually.")
				return None, None
		elif not has_creds:
			logger.warning(
				"Token expired at %s. No auth file configured. "
				"Run epcube_get_token.py to regenerate.",
				expired_at,
			)
			return None, None
	region = config.get("epcube_region", "US")
	client = epcube_mod.EpcubeClient(token, region, device_sn)
	try:
		device_data = client.get_device_data()
	except RuntimeError as err:
		logger.error("EP Cube API error: %s", err)
		return None, None
	if device_data is None:
		# likely token rejected (401), try one renewal if we have not already
		if has_creds and not already_renewed:
			logger.info("Token rejected by API, attempting auto-renewal")
			renewed = _auto_renew_token(config, control_state)
			if renewed:
				# retry once with the new token
				client = epcube_mod.EpcubeClient(renewed, region, device_sn)
				try:
					device_data = client.get_device_data()
				except RuntimeError as err:
					logger.error("EP Cube API error after renewal: %s", err)
					return None, None
				if device_data is None:
					logger.error("EP Cube still rejecting after token renewal")
					control_state.mark_token_expired()
					return None, None
			else:
				control_state.mark_token_expired()
				logger.warning("Token rejected and auto-renewal failed. "
					"Run epcube_get_token.py manually.")
				return None, None
		else:
			control_state.mark_token_expired()
			if already_renewed:
				logger.warning("Freshly generated token was rejected by EP Cube")
			else:
				logger.warning("Token rejected by EP Cube. No auth file configured. "
					"Run epcube_get_token.py to regenerate.")
			return None, None
	# token is working
	control_state.mark_token_success()
	# check token age warning
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
def _check_token_age(control_state: state_mod.ControlState, config: dict) -> None:
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
	Log the raw EP Cube API payload and normalized state at INFO level.

	Masks values for keys that look like serial numbers, tokens, or user IDs.

	Args:
		raw_data: Original dict from the API response.
		normalized: Normalized dict produced by epcube_client.
	"""
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
	logger.info("EP Cube raw payload: %s", json.dumps(masked_raw, indent=2))
	logger.info("EP Cube normalized state: %s", json.dumps(masked_norm, indent=2))


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
	config = config_mod.load_config(args.config_file)
	# override dry_run from CLI
	dry_run = args.dry_run
	if not dry_run:
		logger.warning("EXECUTE MODE: commands will be sent to devices")
	else:
		logger.info("DRY RUN MODE: no commands will be sent")
	# load state
	state_path = config.get("state_file_path")
	# default comes from config.DEFAULTS which uses tempfile.gettempdir()
	control_state = state_mod.ControlState(state_path)
	control_state.load()
	# reset daily state if needed (midnight rollover)
	if control_state.peak_mode_entered_at:
		entered_dt = datetime.datetime.fromisoformat(control_state.peak_mode_entered_at)
		if entered_dt.date() < now.date():
			logger.info("New day detected, resetting peak mode state")
			control_state.reset_daily()
	# fetch ComEd price
	comed_price, comed_median = _fetch_comed_price()
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
	# select load source: prefer smartHomePower, fall back to backUpPower
	smart_home_load = epcube_data.get("smart_home_power_watts", 0)
	backup_load = epcube_data.get("backup_power_watts", 0)
	if smart_home_load > 0:
		load_power = smart_home_load
		logger.info("Load source: smartHomePower (%.0fW)", load_power)
	else:
		load_power = backup_load
		logger.info("Load source: backUpPower fallback (%.0fW)", load_power)
	# run decision engine
	result = decision_engine.decide(
		battery_soc=battery_soc,
		solar_power_watts=solar_power,
		load_power_watts=load_power,
		comed_price_cents=comed_price,
		comed_median_cents=comed_median,
		config=config,
		control_state=control_state,
		current_time=now,
	)
	logger.info("Decision: %s", result)
	# check token friction: only act if action has been stable long enough
	friction_count = config.get("token_friction_count", 2)
	action_stable = control_state.action_stable_count >= friction_count
	# execute actuators
	if action_stable:
		# EP Cube actuator
		if epcube_client is not None:
			epcube_mod.execute_epcube(result, epcube_client, config, dry_run)
		# WeMo actuator (skip when no plugs configured)
		charge_plug = config.get("wemo_charge_plug_name", "")
		discharge_plug = config.get("wemo_discharge_plug_name", "")
		if charge_plug or discharge_plug:
			wemo_mod.execute_wemo(result.action, config, dry_run)
	else:
		logger.info(
			"Token friction: action %s stable for %d/%d cycles, waiting",
			result.action.value, control_state.action_stable_count, friction_count,
		)
	# save state
	control_state.save()
	# print summary line for cron log
	mode_name = decision_engine.ACTION_MODE_MAP.get(result.action, "?")
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
