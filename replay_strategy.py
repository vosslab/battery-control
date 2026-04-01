#!/usr/bin/env python3
"""Replay strategy decisions through battcontrol.strategy against historical data."""

# Standard Library
import csv
import argparse
import datetime
import os

# local repo modules
import battcontrol.config
import battcontrol.strategy


#============================================
def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Replay strategy decisions against hourly history"
	)
	parser.add_argument(
		'-i', '--input',
		dest='input_file',
		default='data/hourly_history.csv',
		help='Input hourly CSV file'
	)
	parser.add_argument(
		'-c', '--config',
		dest='config_file',
		default='config.yml',
		help='Config file (use alternative for comparison)'
	)
	parser.add_argument(
		'-o', '--output',
		dest='output_file',
		default=None,
		help='Output CSV (default: print table to stdout)'
	)
	parser.add_argument(
		'-s', '--strategy-name',
		dest='strategy_name',
		default='replay',
		help='Label for this strategy run'
	)
	args = parser.parse_args()
	return args


#============================================
def extract_date(hour_start_str: str) -> str:
	"""
	Extract date from hour_start timestamp string.

	Args:
		hour_start_str: Timestamp string (ISO format).

	Returns:
		str: Date in YYYY-MM-DD format.
	"""
	if not hour_start_str:
		return None
	try:
		dt = datetime.datetime.fromisoformat(hour_start_str)
		return dt.strftime('%Y-%m-%d')
	except (ValueError, AttributeError):
		return None


#============================================
def safe_float(value: str) -> float:
	"""
	Convert string to float, treating empty/blank as 0.0.

	Args:
		value: String value (may be empty or None).

	Returns:
		float: Parsed float or 0.0 if blank.
	"""
	if not value or not str(value).strip():
		return 0.0
	try:
		return float(value)
	except (ValueError, TypeError):
		return 0.0


#============================================
def safe_int(value: str) -> int:
	"""
	Convert string to int, treating empty/blank as 0.

	Args:
		value: String value (may be empty or None).

	Returns:
		int: Parsed int or 0 if blank.
	"""
	if not value or not str(value).strip():
		return 0
	try:
		return int(float(value))
	except (ValueError, TypeError):
		return 0


#============================================
def estimate_power_from_kwh(energy_kwh: float) -> float:
	"""
	Estimate power in watts from hourly energy in kWh.

	Assumes 1-hour interval: power = energy * 1000.

	Args:
		energy_kwh: Energy in kWh over 1 hour.

	Returns:
		float: Power in watts.
	"""
	return energy_kwh * 1000.0


#============================================
def run_replay(
	input_path: str,
	config_path: str,
	strategy_name: str,
	output_path: str = None,
) -> list:
	"""
	Replay strategy on historical data.

	Args:
		input_path: Path to hourly history CSV.
		config_path: Path to config YAML.
		strategy_name: Label for this strategy run.
		output_path: Optional output CSV path.

	Returns:
		list: List of daily comparison dicts.
	"""
	if not os.path.isfile(input_path):
		raise FileNotFoundError(f"Input file not found: {input_path}")

	if not os.path.isfile(config_path):
		raise FileNotFoundError(f"Config file not found: {config_path}")

	# load config
	config = battcontrol.config.load_config(config_path)
	capacity_kwh = config.get('battery_capacity_kwh', 20.0)

	# read hourly data
	hourly_data = []
	with open(input_path, 'r') as f:
		reader = csv.DictReader(f)
		for row in reader:
			hourly_data.append(row)

	# replay each hour
	replay_results = []
	simulated_soc = 50.0  # start at nominal

	for row in hourly_data:
		hour_start_str = row.get('hour_start', '')
		try:
			current_time = datetime.datetime.fromisoformat(hour_start_str)
		except (ValueError, TypeError):
			continue

		# extract actual values
		actual_grid_kwh = safe_float(row.get('grid_kwh', ''))
		actual_solar_kwh = safe_float(row.get('solar_kwh', ''))
		actual_load_kwh = safe_float(row.get('load_kwh', ''))
		actual_battery_charge_kwh = safe_float(row.get('battery_charge_kwh', ''))
		actual_battery_discharge_kwh = safe_float(row.get('battery_discharge_kwh', ''))
		comed_price = safe_float(row.get('comed_price', ''))

		# skip rows with no price
		if comed_price == 0.0 and row.get('comed_price', '').strip() == '':
			continue

		# estimate power from hourly energy
		solar_power = estimate_power_from_kwh(actual_solar_kwh)
		load_power = estimate_power_from_kwh(actual_load_kwh)
		comed_median = safe_float(row.get('comed_price_median', ''))

		# call strategy.evaluate with simulated SoC (not actual)
		# this lets strategy decisions cascade across hours
		replay_soc = int(round(simulated_soc))
		decision = battcontrol.strategy.evaluate(
			battery_soc=replay_soc,
			solar_power_watts=solar_power,
			load_power_watts=load_power,
			comed_price_cents=comed_price,
			comed_median_cents=comed_median,
			current_time=current_time,
			config=config,
		)

		# simulate SoC transition
		if decision.action == battcontrol.strategy.Action.CHARGE_FROM_SOLAR:
			simulated_soc += actual_battery_charge_kwh * 100.0 / capacity_kwh
		elif decision.action == battcontrol.strategy.Action.DISCHARGE_ENABLED:
			simulated_soc -= actual_battery_discharge_kwh * 100.0 / capacity_kwh

		# clamp to hard reserve and 100
		hard_reserve = battcontrol.config.get_seasonal_value(
			config,
			'hard_reserve_pct',
			battcontrol.config.get_season(config, current_time)
		)
		simulated_soc = max(hard_reserve, min(100.0, simulated_soc))

		# compute replayed grid cost
		# under the replayed action, what would grid_kwh have been?
		# for simplicity, use the baseline approach: grid = max(load - solar, 0)
		replayed_grid_kwh = max(actual_load_kwh - actual_solar_kwh, 0.0)
		replayed_cost_cents = replayed_grid_kwh * comed_price

		# actual cost
		actual_cost_cents = actual_grid_kwh * comed_price

		# baseline cost (no battery)
		baseline_grid_kwh = max(actual_load_kwh - actual_solar_kwh, 0.0)
		baseline_cost_cents = baseline_grid_kwh * comed_price

		# actual savings (what was achieved)
		actual_savings_cents = baseline_cost_cents - actual_cost_cents

		# replayed savings (what would be achieved)
		replayed_savings_cents = baseline_cost_cents - replayed_cost_cents

		# improvement
		improvement_cents = replayed_savings_cents - actual_savings_cents

		replay_results.append({
			'hour_start': hour_start_str,
			'date': extract_date(hour_start_str),
			'actual_cost_cents': actual_cost_cents,
			'baseline_cost_cents': baseline_cost_cents,
			'actual_savings_cents': actual_savings_cents,
			'replayed_cost_cents': replayed_cost_cents,
			'replayed_savings_cents': replayed_savings_cents,
			'improvement_cents': improvement_cents,
			'actual_action': row.get('policy_action', ''),
			'replayed_action': decision.action.value,
		})

	# group by date for summary
	daily_data = {}
	for result in replay_results:
		date = result['date']
		if date not in daily_data:
			daily_data[date] = {
				'date': date,
				'strategy_name': strategy_name,
				'actual_cost_cents': 0.0,
				'replay_cost_cents': 0.0,
				'actual_savings_cents': 0.0,
				'replay_savings_cents': 0.0,
				'improvement_cents': 0.0,
				'sample_hours': 0,
			}
		daily_data[date]['actual_cost_cents'] += result['actual_cost_cents']
		daily_data[date]['replay_cost_cents'] += result['replayed_cost_cents']
		daily_data[date]['actual_savings_cents'] += result['actual_savings_cents']
		daily_data[date]['replay_savings_cents'] += result['replayed_savings_cents']
		daily_data[date]['improvement_cents'] += result['improvement_cents']
		daily_data[date]['sample_hours'] += 1

	daily_summaries = [daily_data[d] for d in sorted(daily_data.keys())]

	# write output if specified
	if output_path:
		output_dir = os.path.dirname(output_path)
		if output_dir and not os.path.isdir(output_dir):
			os.makedirs(output_dir, exist_ok=True)

		fieldnames = [
			'date', 'strategy_name', 'actual_cost_cents', 'replay_cost_cents',
			'actual_savings_cents', 'replay_savings_cents', 'improvement_cents',
			'sample_hours',
		]
		with open(output_path, 'w', newline='') as f:
			writer = csv.DictWriter(f, fieldnames=fieldnames)
			writer.writeheader()
			for summary in daily_summaries:
				writer.writerow(summary)

	return daily_summaries


#============================================
def print_table(daily_summaries: list) -> None:
	"""
	Print daily summaries as a formatted table.

	Args:
		daily_summaries: List of daily summary dicts.
	"""
	if not daily_summaries:
		print("No data to display")
		return

	# try to use tabulate if available
	try:
		import tabulate
		headers = list(daily_summaries[0].keys())
		table = tabulate.tabulate(daily_summaries, headers=headers, tablefmt='grid')
		print(table)
	except ImportError:
		# fallback: simple column printing
		headers = list(daily_summaries[0].keys())
		col_widths = {h: len(h) for h in headers}
		for row in daily_summaries:
			for h in headers:
				val_str = str(row[h])
				col_widths[h] = max(col_widths[h], len(val_str))

		# print header
		header_line = ' | '.join(h.ljust(col_widths[h]) for h in headers)
		print(header_line)
		print('-' * len(header_line))

		# print rows
		for row in daily_summaries:
			row_line = ' | '.join(str(row[h]).ljust(col_widths[h]) for h in headers)
			print(row_line)


#============================================
def main() -> None:
	"""
	Main entry point.
	"""
	args = parse_args()
	daily_summaries = run_replay(
		args.input_file,
		args.config_file,
		args.strategy_name,
		args.output_file,
	)
	if not args.output_file:
		print_table(daily_summaries)


if __name__ == '__main__':
	main()
