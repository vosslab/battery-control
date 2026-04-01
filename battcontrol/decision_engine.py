"""Decision engine orchestrator - calls strategy and returns result."""

# Standard Library
import logging
import datetime

# local repo modules
import battcontrol.strategy

logger = logging.getLogger(__name__)

# re-export for backward compatibility with callers
StrategyState = battcontrol.strategy.StrategyState
DecisionResult = battcontrol.strategy.DecisionResult


#============================================
def decide(
	battery_soc: int,
	solar_power_watts: float,
	load_power_watts: float,
	comed_price_cents: float,
	comed_median_cents: float,
	comed_cutoff_cents: float,
	config: dict,
	control_state: object,
	current_time: datetime.datetime = None,
) -> DecisionResult:
	"""
	Main decision function - delegates to strategy.evaluate().

	This is a thin orchestrator. All policy logic lives in strategy.py.
	Command buffering (whether to actually send the command) is handled
	separately by command_buffer.py in the controller.

	Args:
		battery_soc: Current battery state of charge percentage.
		solar_power_watts: Current solar generation in watts.
		load_power_watts: Current house load in watts.
		comed_price_cents: Current ComEd price in cents.
		comed_median_cents: 24-hour median ComEd price in cents.
		comed_cutoff_cents: Reasonable cutoff price from comedlib.
		config: Configuration dictionary.
		control_state: ControlState instance (kept for interface compatibility).
		current_time: Current datetime (defaults to now).

	Returns:
		DecisionResult: The battery control decision.
	"""
	if current_time is None:
		current_time = datetime.datetime.now()
	# recover previous strategy state for deadband
	previous_state = None
	last_state_str = getattr(control_state, "last_strategy_state", "")
	if last_state_str:
		# convert stored string back to enum
		for member in battcontrol.strategy.StrategyState:
			if member.value == last_state_str:
				previous_state = member
				break
	# delegate to pure strategy function
	result = battcontrol.strategy.evaluate(
		battery_soc=battery_soc,
		solar_power_watts=solar_power_watts,
		load_power_watts=load_power_watts,
		comed_price_cents=comed_price_cents,
		comed_median_cents=comed_median_cents,
		comed_cutoff_cents=comed_cutoff_cents,
		current_time=current_time,
		config=config,
		previous_state=previous_state,
	)
	# track state for deadband and logging
	control_state.last_action = result.state.value
	control_state.last_strategy_state = result.state.value
	logger.info("Decision: %s", result)
	return result
