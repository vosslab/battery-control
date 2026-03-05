#!/usr/bin/env python3

"""Main battery controller - orchestrates config, data fetch, decision, and actuation."""

# Standard Library
import logging
import argparse
import datetime

# local repo modules
import battcontrol.config as config_mod
import battcontrol.state as state_mod
import battcontrol.decision_engine as decision_engine
import battcontrol.epcube_client as epcube_mod
import battcontrol.wemo_actuator as wemo_mod

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
		'-c', '--config', dest='config_file', required=True,
		help="Path to YAML configuration file",
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
	Fetch current ComEd price and median.

	Returns:
		tuple: (current_price_cents, median_cents) or (None, None) on failure.
	"""
	try:
		import battcontrol.comedlib
		comlib = battcontrol.comedlib.ComedLib()
		current_price = comlib.getCurrentComedRate()
		median_price, _ = comlib.getMedianComedRate()
		logger.info("ComEd price: %.2fc (median: %.2fc)", current_price, median_price)
		return current_price, median_price
	except Exception as err:
		logger.error("Failed to fetch ComEd price: %s", err)
		return None, None


#============================================
def _fetch_epcube_data(config: dict, control_state: state_mod.ControlState) -> tuple:
	"""
	Fetch EP Cube device data.

	Args:
		config: Configuration dictionary.
		control_state: Control state for token tracking.

	Returns:
		tuple: (device_data_dict, epcube_client) or (None, None) on failure.
	"""
	token = config.get("epcube_token", "")
	device_sn = config.get("epcube_device_sn", "")
	if not token:
		logger.info("No EP Cube token configured, running without EP Cube")
		return None, None
	# skip if token is known to be expired
	if control_state.token_expired:
		expired_at = control_state.token_expired_at or "unknown"
		logger.warning(
			"EP Cube token expired at %s. "
			"Regenerate at epcube-token app and update config. "
			"Running in WeMo-only mode.",
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
		# likely token expired (401)
		control_state.mark_token_expired()
		logger.warning(
			"EP Cube token expired. "
			"Regenerate at epcube-token app and update config. "
			"Running in WeMo-only mode."
		)
		return None, None
	# token is working
	control_state.mark_token_success()
	# check token age warning
	_check_token_age(control_state, config)
	logger.info(
		"EP Cube: SoC=%d%%, Solar=%.0fW, Grid=%.0fW, Backup=%.0fW, Mode=%s",
		device_data.get("battery_soc", 0),
		device_data.get("solar_power_watts", 0),
		device_data.get("grid_power_watts", 0),
		device_data.get("backup_power_watts", 0),
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
def main() -> None:
	"""
	Main entry point for the battery controller.
	"""
	args = parse_args()
	_setup_logging(args.verbose)
	now = datetime.datetime.now()
	# load config
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
		_print_summary("HOLD", "ComEd unavailable", dry_run)
		return
	# fetch EP Cube data
	epcube_data, epcube_client = _fetch_epcube_data(config, control_state)
	# determine battery SoC and solar power from device
	if epcube_data is None:
		# no device data available, hold current state
		logger.warning("EP Cube data unavailable, holding current state")
		control_state.save()
		_print_summary("HOLD", "EP Cube unavailable", dry_run)
		return
	battery_soc = epcube_data.get("battery_soc", 0)
	solar_power = epcube_data.get("solar_power_watts", 0)
	backup_power = epcube_data.get("backup_power_watts", 0)
	# run decision engine
	result = decision_engine.decide(
		battery_soc=battery_soc,
		solar_power_watts=solar_power,
		backup_power_watts=backup_power,
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
		# WeMo actuator
		wemo_mod.execute_wemo(result.action, config, dry_run)
	else:
		logger.info(
			"Token friction: action %s stable for %d/%d cycles, waiting",
			result.action.value, control_state.action_stable_count, friction_count,
		)
	# save state
	control_state.save()
	# print summary line for cron log
	_print_summary(result.action.value, result.reason, dry_run)


#============================================
def _print_summary(action: str, reason: str, dry_run: bool) -> None:
	"""
	Print a one-line summary suitable for cron logs.

	Args:
		action: Action name.
		reason: Decision reason.
		dry_run: Whether in dry-run mode.
	"""
	mode_tag = "[DRY]" if dry_run else "[LIVE]"
	now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
	print(f"{mode_tag} {now_str} action={action} | {reason}")


#============================================
if __name__ == '__main__':
	main()
