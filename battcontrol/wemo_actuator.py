"""WeMo smart plug actuator for battery control system."""

# Standard Library
import logging

# PIP3 modules
try:
	import pywemo
	PYWEMO_AVAILABLE = True
except ImportError:
	PYWEMO_AVAILABLE = False

# local repo modules
import battcontrol.decision_engine as decision_engine

logger = logging.getLogger(__name__)


#============================================
def _discover_device(device_name: str):
	"""
	Discover a WeMo device by name on the local network.

	Args:
		device_name: Name of the WeMo device to find.

	Returns:
		WeMo device object, or None if not found.
	"""
	if not device_name:
		return None
	if not PYWEMO_AVAILABLE:
		logger.error("pywemo module not installed, cannot control WeMo devices")
		return None
	devices = pywemo.discover_devices()
	for device in devices:
		if device.name == device_name:
			return device
	logger.warning("WeMo device '%s' not found on network", device_name)
	return None


#============================================
def _set_plug_state(device_name: str, state_on: bool, dry_run: bool) -> bool:
	"""
	Set a WeMo plug on or off.

	Args:
		device_name: Name of the WeMo device.
		state_on: True to turn on, False to turn off.
		dry_run: If True, log but do not send commands.

	Returns:
		bool: True if successful.
	"""
	state_str = "ON" if state_on else "OFF"
	if not device_name:
		logger.debug("No WeMo device name configured, skipping")
		return False
	if dry_run:
		logger.info("[DRY RUN] Would set WeMo '%s' to %s", device_name, state_str)
		return True
	device = _discover_device(device_name)
	if device is None:
		return False
	if state_on:
		device.on()
	else:
		device.off()
	logger.info("WeMo '%s' set to %s", device_name, state_str)
	return True


#============================================
def execute_wemo(action: decision_engine.Action, config: dict, dry_run: bool) -> bool:
	"""
	Translate a decision action into WeMo smart plug commands.

	Args:
		action: Action enum from the decision engine.
		config: Configuration dictionary with plug names.
		dry_run: If True, log but do not send commands.

	Returns:
		bool: True if commands were sent successfully.
	"""
	charge_plug = config.get("wemo_charge_plug_name", "")
	discharge_plug = config.get("wemo_discharge_plug_name", "")
	# skip if no WeMo plugs configured
	if not charge_plug and not discharge_plug:
		logger.info("No WeMo plugs configured, skipping WeMo actuator")
		return False
	if action == decision_engine.Action.CHARGE_FROM_GRID:
		# turn on charge plug, turn off discharge plug
		logger.info("WeMo: charging from grid")
		success_charge = _set_plug_state(charge_plug, True, dry_run)
		success_discharge = _set_plug_state(discharge_plug, False, dry_run)
		return success_charge
	if action in (
		decision_engine.Action.ALLOW_DISCHARGE,
		decision_engine.Action.DISCHARGE_TO_FLOOR,
		decision_engine.Action.DISCHARGE_ALLOWED,
	):
		# turn on discharge plug, turn off charge plug
		logger.info("WeMo: discharging to grid")
		success_charge = _set_plug_state(charge_plug, False, dry_run)
		success_discharge = _set_plug_state(discharge_plug, True, dry_run)
		return success_discharge
	# HOLD or FORCE_NO_DISCHARGE: turn off both plugs
	logger.info("WeMo: holding (both plugs off)")
	_set_plug_state(charge_plug, False, dry_run)
	_set_plug_state(discharge_plug, False, dry_run)
	return True
