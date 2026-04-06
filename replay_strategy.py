#!/usr/bin/env python3
"""Replay strategy decisions through battcontrol.strategy against historical data.

Includes a simplified battery simulation for comparing strategy parameter sets.
The simulation is accurate enough to rank strategies consistently, but does not
exactly reproduce realized savings due to simplified efficiency and power limits.
"""

# Standard Library
import csv
import glob
import argparse
import datetime
import os

# PIP3 modules
import tabulate

# local repo modules
import battcontrol.config
import battcontrol.strategy

# experimental config keys that disable auto-discovery when present
EXPERIMENTAL_KEYS = {
	"negative_price_floor",
	"pre_solar_soc_threshold",
	"pre_solar_target_floor",
	"pre_solar_start_hour",
	"pre_solar_end_hour",
}

# battery simulation constants
# per-leg efficiency: 0.92 charge, 0.92 discharge (0.8464 round-trip)
# NA720G inverter CEC is 93.93% per pass but real-world is lower;
# 0.92 per leg accounts for inverter losses plus battery internal losses
CHARGE_EFFICIENCY = 0.92
DISCHARGE_EFFICIENCY = 0.92
# inverter limits from EP Cube v1 datasheet (NA720G, 19.9 kWh, 240V)
# in practice, charge is bounded by (solar - load) and discharge by
# (load - solar), so these rarely bind with current solar/load levels
MAX_CHARGE_KWH = 7.6
MAX_DISCHARGE_KWH = 7.6


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
		default=None,
		help='Config file (triggers single-strategy mode)'
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
	parser.add_argument(
		'--compare',
		dest='compare_pairs',
		nargs='+',
		default=None,
		help='Compare strategies: config.yml:label config2.yml:label2 ...'
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
def fmt_dollars(cents: float) -> str:
	"""
	Format cents as dollars with sign before $.

	Args:
		cents: Value in cents.

	Returns:
		str: Formatted string like '$1.234' or '-$0.456'.
	"""
	dollars = cents / 100.0
	if dollars < 0:
		return f"-${abs(dollars):.3f}"
	return f"${dollars:.3f}"


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
	capacity_kwh = config['battery_capacity_kwh']

	# read hourly data
	hourly_data = []
	with open(input_path, 'r') as f:
		reader = csv.DictReader(f)
		for row in reader:
			hourly_data.append(row)

	# replay each hour
	replay_results = []
	# initialize SoC from first data row if available, else nominal 50%
	initial_soc = 50.0
	if hourly_data:
		first_soc = safe_float(hourly_data[0].get('start_soc', ''))
		if first_soc > 0:
			initial_soc = first_soc
	simulated_soc = initial_soc
	previous_state = None  # no previous state on first iteration

	for row in hourly_data:
		hour_start_str = row.get('hour_start', '')
		try:
			current_time = datetime.datetime.fromisoformat(hour_start_str)
		except (ValueError, TypeError):
			continue

		# extract actual values
		actual_solar_kwh = safe_float(row.get('solar_kwh', ''))
		actual_load_kwh = safe_float(row.get('load_kwh', ''))
		comed_price = safe_float(row.get('comed_price', ''))

		# skip rows with no price
		if comed_price == 0.0 and row.get('comed_price', '').strip() == '':
			continue

		# estimate power from hourly energy
		solar_power = estimate_power_from_kwh(actual_solar_kwh)
		load_power = estimate_power_from_kwh(actual_load_kwh)
		comed_median = safe_float(row.get('comed_price_median', ''))
		# cutoff from CSV if available, otherwise approximate from median
		comed_cutoff = safe_float(row.get('comed_cutoff', ''))
		if comed_cutoff == 0.0 and row.get('comed_cutoff', '').strip() in ('', None):
			comed_cutoff = comed_median

		# apply cutoff scale from config (default 1.0 = no change)
		cutoff_scale = config["cutoff_scale"]
		scaled_cutoff = comed_cutoff * cutoff_scale

		# call strategy.evaluate with simulated SoC (not actual)
		# this lets strategy decisions cascade across hours
		replay_soc = int(round(simulated_soc))
		decision = battcontrol.strategy.evaluate(
			battery_soc=replay_soc,
			solar_power_watts=solar_power,
			load_power_watts=load_power,
			comed_price_cents=comed_price,
			comed_median_cents=comed_median,
			comed_cutoff_cents=scaled_cutoff,
			current_time=current_time,
			config=config,
			previous_state=previous_state,
		)
		previous_state = decision.state

		# get hard reserve as physical minimum
		hard_reserve = battcontrol.config.get_seasonal_value(
			config,
			'hard_reserve_pct',
			battcontrol.config.get_season(config, current_time)
		)
		# clamp soc_floor to hard reserve minimum
		effective_floor = max(decision.soc_floor, hard_reserve)

		# simulate hourly energy flow
		net_load = actual_load_kwh - actual_solar_kwh
		replayed_grid_kwh = 0.0
		sim_charge = 0.0

		if net_load < 0:
			# excess solar charges battery, remainder exported to grid
			pv_excess = -net_load
			storable = pv_excess * CHARGE_EFFICIENCY
			available_capacity = (100.0 - simulated_soc) * capacity_kwh / 100.0
			sim_charge = min(storable, MAX_CHARGE_KWH, available_capacity)
			simulated_soc += sim_charge * 100.0 / capacity_kwh
			# energy absorbed by battery (in pre-efficiency terms)
			absorbed = sim_charge / CHARGE_EFFICIENCY if CHARGE_EFFICIENCY > 0 else 0.0
			# remainder exported to grid (negative = export)
			exported = pv_excess - absorbed
			replayed_grid_kwh = -exported
		elif net_load > 0 and effective_floor < 100:
			# battery discharges to cover load
			available = (simulated_soc - effective_floor) * capacity_kwh / 100.0
			# discharge needed (in battery-side kWh) to deliver net_load
			discharge = min(
				max(available, 0.0),
				net_load / DISCHARGE_EFFICIENCY,
				MAX_DISCHARGE_KWH,
			)
			delivered = discharge * DISCHARGE_EFFICIENCY
			simulated_soc -= discharge * 100.0 / capacity_kwh
			remaining_load = net_load - delivered
			replayed_grid_kwh = max(remaining_load, 0.0)
		else:
			# no battery action: grid covers full net load
			replayed_grid_kwh = max(net_load, 0.0)

		# clamp SoC to physical bounds
		simulated_soc = max(hard_reserve, min(100.0, simulated_soc))

		# cost calculations: supply-only and total (supply + delivery)
		delivery_rate = config["delivery_rate_cents"]
		baseline_grid_kwh = actual_load_kwh - actual_solar_kwh
		# supply-only costs (ComEd hourly price only)
		replayed_supply_cents = replayed_grid_kwh * comed_price
		baseline_supply_cents = baseline_grid_kwh * comed_price
		# total costs (supply + delivery)
		full_price = comed_price + delivery_rate
		replayed_total_cents = replayed_grid_kwh * full_price
		baseline_total_cents = baseline_grid_kwh * full_price
		# savings use total cost (supply + delivery)
		replayed_savings_cents = baseline_total_cents - replayed_total_cents

		replay_results.append({
			'hour_start': hour_start_str,
			'date': extract_date(hour_start_str),
			'replayed_supply_cents': replayed_supply_cents,
			'replayed_total_cents': replayed_total_cents,
			'baseline_supply_cents': baseline_supply_cents,
			'baseline_total_cents': baseline_total_cents,
			'replayed_savings_cents': replayed_savings_cents,
			'actual_action': row.get('policy_action', ''),
			'replayed_action': decision.state.value,
		})

	# group by date for summary
	daily_data = {}
	for result in replay_results:
		date = result['date']
		if date not in daily_data:
			daily_data[date] = {
				'date': date,
				'strategy_name': strategy_name,
				'replay_supply_cents': 0.0,
				'replay_total_cents': 0.0,
				'baseline_supply_cents': 0.0,
				'baseline_total_cents': 0.0,
				'replay_savings_cents': 0.0,
				'sample_hours': 0,
			}
		daily_data[date]['replay_supply_cents'] += result['replayed_supply_cents']
		daily_data[date]['replay_total_cents'] += result['replayed_total_cents']
		daily_data[date]['baseline_supply_cents'] += result['baseline_supply_cents']
		daily_data[date]['baseline_total_cents'] += result['baseline_total_cents']
		daily_data[date]['replay_savings_cents'] += result['replayed_savings_cents']
		daily_data[date]['sample_hours'] += 1

	daily_summaries = [daily_data[d] for d in sorted(daily_data.keys())]

	# write output if specified
	if output_path:
		output_dir = os.path.dirname(output_path)
		if output_dir and not os.path.isdir(output_dir):
			os.makedirs(output_dir, exist_ok=True)

		fieldnames = [
			'date', 'strategy_name',
			'replay_supply_cents', 'replay_total_cents',
			'baseline_supply_cents', 'baseline_total_cents',
			'replay_savings_cents', 'sample_hours',
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

	# convert cents to dollar strings for display
	dollar_keys = {
		'replay_supply_cents', 'replay_total_cents',
		'baseline_supply_cents', 'baseline_total_cents',
		'replay_savings_cents',
	}
	header_map = {
		'date': 'date',
		'strategy_name': 'strategy',
		'replay_supply_cents': 'supply',
		'replay_total_cents': 'total',
		'baseline_supply_cents': 'base sup',
		'baseline_total_cents': 'base tot',
		'replay_savings_cents': 'savings',
		'sample_hours': 'hours',
	}
	keys = list(daily_summaries[0].keys())
	headers = [header_map.get(k, k.replace("_", " ")) for k in keys]
	rows = []
	for d in daily_summaries:
		row = []
		for k in keys:
			if k in dollar_keys:
				row.append(fmt_dollars(d[k]))
			else:
				row.append(d[k])
		rows.append(row)
	table = tabulate.tabulate(rows, headers=headers, tablefmt='fancy_grid', maxcolwidths=12)
	print(table)


#============================================
def parse_compare_pair(pair_str: str) -> tuple:
	"""
	Parse a 'config_path:label' string into (path, label).

	Args:
		pair_str: String in format 'path:label' or just 'path'.

	Returns:
		tuple: (config_path, label).
	"""
	if ':' in pair_str:
		parts = pair_str.split(':', 1)
		config_path = parts[0]
		label = parts[1]
	else:
		# use filename without extension as label
		config_path = pair_str
		label = os.path.splitext(os.path.basename(pair_str))[0]
	return (config_path, label)


#============================================
def print_usage_summary(input_path: str) -> None:
	"""
	Print a daily usage summary table from hourly history data.

	Shows grid import/export, net grid, solar, load, and price stats
	per day. Independent of strategy -- just raw data.

	Args:
		input_path: Path to hourly history CSV.
	"""
	# read hourly data
	hourly_data = []
	with open(input_path, 'r') as f:
		reader = csv.DictReader(f)
		for row in reader:
			hourly_data.append(row)

	# accumulate daily stats
	daily = {}
	for row in hourly_data:
		date = extract_date(row.get('hour_start', ''))
		if date is None:
			continue
		grid = safe_float(row.get('grid_kwh', ''))
		solar = safe_float(row.get('solar_kwh', ''))
		load = safe_float(row.get('load_kwh', ''))
		price = safe_float(row.get('comed_price', ''))
		# skip rows with no price data
		if price == 0.0 and row.get('comed_price', '').strip() == '':
			continue
		if date not in daily:
			daily[date] = {
				'import_kwh': 0.0,
				'export_kwh': 0.0,
				'solar_kwh': 0.0,
				'load_kwh': 0.0,
				'prices': [],
				'hours': 0,
			}
		# positive grid = import, negative grid = export
		if grid >= 0:
			daily[date]['import_kwh'] += grid
		else:
			daily[date]['export_kwh'] += abs(grid)
		daily[date]['solar_kwh'] += solar
		daily[date]['load_kwh'] += load
		daily[date]['prices'].append(price)
		daily[date]['hours'] += 1

	# build table rows
	table_rows = []
	for date in sorted(daily.keys()):
		d = daily[date]
		prices = d['prices']
		net_grid = d['import_kwh'] - d['export_kwh']
		avg_price = sum(prices) / len(prices) if prices else 0.0
		max_price = max(prices) if prices else 0.0
		min_price = min(prices) if prices else 0.0
		table_rows.append({
			'date': date,
			'import': f"{d['import_kwh']:.1f}",
			'export': f"{d['export_kwh']:.1f}",
			'net grid': f"{net_grid:.1f}",
			'solar': f"{d['solar_kwh']:.1f}",
			'load': f"{d['load_kwh']:.1f}",
			'avg c': f"{avg_price:.1f}",
			'peak c': f"{max_price:.1f}",
			'min c': f"{min_price:.1f}",
			'hrs': str(d['hours']),
		})

	print("=== Daily usage summary (kWh and cents) ===")
	table = tabulate.tabulate(table_rows, headers="keys", tablefmt='fancy_grid', maxcolwidths=12)
	print(table)


#============================================
def run_compare(input_path: str, compare_pairs: list) -> None:
	"""
	Run multiple strategies and print a side-by-side comparison table.

	The first entry is the reference strategy. Output shows savings for
	each strategy and delta vs reference for non-reference strategies.

	Args:
		input_path: Path to hourly history CSV.
		compare_pairs: List of 'config:label' strings.
	"""
	# usage summary first (strategy-independent)
	print_usage_summary(input_path)

	# parse pairs and run each strategy
	# truncate labels to 10 chars for table readability
	strategies = []
	for pair_str in compare_pairs:
		config_path, label = parse_compare_pair(pair_str)
		short_label = label[:10]
		daily = run_replay(input_path, config_path, short_label)
		strategies.append((short_label, daily))

	# print detailed day-by-day table for each strategy
	for label, daily in strategies:
		print(f"\n=== {label} ===")
		print_table(daily)

	# reference strategy is the first one
	ref_label = strategies[0][0]

	# build cross-strategy summary table
	# index daily data by date for each strategy
	all_dates = set()
	strategy_by_date = {}
	for label, daily in strategies:
		day_map = {}
		for day in daily:
			all_dates.add(day['date'])
			day_map[day['date']] = day
		strategy_by_date[label] = day_map
	sorted_dates = sorted(all_dates)

	# track totals
	totals = {}
	for label, _ in strategies:
		totals[label] = {'savings': 0.0, 'delta': 0.0}

	# build comparison rows
	compare_rows = []
	for date in sorted_dates:
		row = {'date': date}
		ref_day = strategy_by_date[ref_label].get(date)
		ref_savings = ref_day['replay_savings_cents'] if ref_day else 0.0
		for label, _ in strategies:
			day_data = strategy_by_date[label].get(date)
			savings = day_data['replay_savings_cents'] if day_data else 0.0
			totals[label]['savings'] += savings
			# format as dollars
			sav_str = fmt_dollars(savings)
			if label == ref_label:
				row[label] = sav_str
			else:
				delta = savings - ref_savings
				totals[label]['delta'] += delta
				row[label] = f"{sav_str} ({fmt_dollars(delta)})"
		compare_rows.append(row)

	# totals row
	total_row = {'date': 'TOTAL'}
	for label, _ in strategies:
		total_sav = totals[label]['savings']
		sav_str = fmt_dollars(total_sav)
		if label == ref_label:
			total_row[label] = sav_str
		else:
			total_d = totals[label]['delta']
			total_row[label] = f"{sav_str} ({fmt_dollars(total_d)})"
	compare_rows.append(total_row)

	# print cross-strategy comparison, chunked to fit terminal
	# reference column always included; ~5 strategies per table
	max_per_table = 5
	non_ref = [s for s in strategies if s[0] != ref_label]
	chunks = []
	for i in range(0, len(non_ref), max_per_table - 1):
		chunks.append(non_ref[i:i + max_per_table - 1])
	if not chunks:
		chunks = [[]]
	for chunk_idx, chunk in enumerate(chunks):
		# build column subset: ref + this chunk
		chunk_labels = [ref_label] + [s[0] for s in chunk]
		chunk_rows = []
		for full_row in compare_rows:
			filtered = {k: v for k, v in full_row.items() if k in chunk_labels or k == 'date'}
			chunk_rows.append(filtered)
		part_label = f" (part {chunk_idx + 1}/{len(chunks)})" if len(chunks) > 1 else ""
		print(f"\n=== Strategy comparison, savings in dollars{part_label} ===")
		table = tabulate.tabulate(chunk_rows, headers="keys", tablefmt='fancy_grid', maxcolwidths=14)
		print(table)

	# summary table: total savings per strategy
	print("\nTotal savings vs no-battery baseline (positive = more savings = better)")
	summary_rows = []
	for label, _ in strategies:
		row = {'strategy': label, 'total savings': fmt_dollars(totals[label]['savings'])}
		if label == ref_label:
			row['vs reference'] = '(ref)'
		else:
			row['vs reference'] = fmt_dollars(totals[label]['delta'])
		summary_rows.append(row)
	print(tabulate.tabulate(summary_rows, headers="keys", tablefmt='fancy_grid'))


#============================================
def _has_experimental_keys(config_path: str) -> bool:
	"""
	Check if a config file contains experimental keys.

	Args:
		config_path: Path to YAML config file.

	Returns:
		bool: True if any experimental keys are present.
	"""
	import yaml
	with open(config_path, "r") as f:
		user_config = yaml.safe_load(f)
	if not user_config:
		return False
	found = EXPERIMENTAL_KEYS & set(user_config.keys())
	return len(found) > 0


#============================================
def _auto_discover_configs() -> list:
	"""
	Auto-discover config files for comparison.

	Returns config.yml as reference, plus all configs/*.yml that do not
	contain experimental keys.

	Returns:
		list: List of 'path:label' strings, or empty if configs/ not found.
	"""
	# find repo root for configs/ directory
	repo_root = os.path.dirname(os.path.abspath(__file__))
	configs_dir = os.path.join(repo_root, "configs")
	if not os.path.isdir(configs_dir):
		return []
	# start with config.yml as reference
	pairs = ["config.yml:current"]
	# add configs/*.yml that do not have experimental keys
	config_files = sorted(glob.glob(os.path.join(configs_dir, "*.yml")))
	for config_path in config_files:
		if _has_experimental_keys(config_path):
			basename = os.path.basename(config_path)
			print(f"Skipping {basename} (has experimental keys)")
			continue
		# use filename without extension as label
		label = os.path.splitext(os.path.basename(config_path))[0]
		pairs.append(f"{config_path}:{label}")
	return pairs


#============================================
def main() -> None:
	"""
	Main entry point.
	"""
	args = parse_args()

	# explicit compare mode
	if args.compare_pairs:
		run_compare(args.input_file, args.compare_pairs)
		return

	# single strategy mode when -c is explicitly provided
	if args.config_file:
		daily_summaries = run_replay(
			args.input_file,
			args.config_file,
			args.strategy_name,
			args.output_file,
		)
		if not args.output_file:
			print_table(daily_summaries)
		return

	# default: auto-discover configs/ and run comparison
	pairs = _auto_discover_configs()
	if pairs:
		run_compare(args.input_file, pairs)
	else:
		# fallback: single strategy with config.yml
		daily_summaries = run_replay(
			args.input_file,
			'config.yml',
			args.strategy_name,
		)
		print_table(daily_summaries)


if __name__ == '__main__':
	main()
