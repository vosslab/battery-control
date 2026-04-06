#!/usr/bin/env python3
"""Aggregate hourly history into daily summary metrics with cost analysis."""

# Standard Library
import csv
import argparse
import datetime
import os

# PIP3 modules
import tabulate


#============================================
def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Aggregate hourly history into daily summaries with cost analysis"
	)
	parser.add_argument(
		'-i', '--input',
		dest='input_file',
		default='data/hourly_history.csv',
		help='Input hourly CSV file'
	)
	parser.add_argument(
		'-o', '--output',
		dest='output_file',
		default='data/daily_summary.csv',
		help='Output daily summary CSV file'
	)
	args = parser.parse_args()
	return args


#============================================
def extract_date(hour_start_str: str) -> str:
	"""
	Extract date from hour_start timestamp string.

	Args:
		hour_start_str: Timestamp string (ISO format, e.g., '2025-03-15T14:00:00').

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
def _fmt_dollars(cents: float) -> str:
	"""
	Format cents as dollars with sign before $.

	Negative values are shown in red using ANSI escape codes.

	Args:
		cents: Value in cents.

	Returns:
		str: Formatted string like '$1.23' or red '-$0.45'.
	"""
	dollars = cents / 100.0
	if dollars < 0:
		return f"-${abs(dollars):.2f}"
	return f"${dollars:.2f}"


#============================================
def compute_daily_metrics(hourly_rows: list, capacity_kwh: float = 20.0) -> dict:
	"""
	Compute daily summary metrics from hourly rows.

	Args:
		hourly_rows: List of dicts from CSV (one day's data).
		capacity_kwh: Battery capacity in kWh (for hindsight estimation).

	Returns:
		dict: Daily metrics (cost_cents, savings_cents, etc).
	"""
	if not hourly_rows:
		return None

	# extract date from first row
	first_row = hourly_rows[0]
	date = extract_date(first_row.get('hour_start', ''))
	if not date:
		return None

	season = first_row.get('season', '')

	# delivery charge per kWh (distribution + IL distribution)
	# import: pay delivery; export: get delivery credit
	# these are fixed per-kWh, not tied to hourly supply price
	delivery_cents_per_kwh = 6.354

	# accumulate totals
	total_grid_kwh = 0.0
	total_solar_kwh = 0.0
	total_load_kwh = 0.0
	total_battery_charge_kwh = 0.0
	total_battery_discharge_kwh = 0.0
	total_actual_cost_cents = 0.0
	total_no_battery_cost_cents = 0.0
	total_no_solar_cost_cents = 0.0
	# delivery-inclusive totals (comed price + delivery fee)
	total_actual_delivered_cents = 0.0
	total_no_battery_delivered_cents = 0.0
	total_no_solar_delivered_cents = 0.0

	# first pass: count valid hours
	valid_hour_count = 0
	for row in hourly_rows:
		comed_price_str = row.get('comed_price', '').strip()
		if comed_price_str:
			valid_hour_count += 1
	if valid_hour_count == 0:
		return None

	# process each hour
	for row in hourly_rows:
		grid_kwh = safe_float(row.get('grid_kwh', ''))
		solar_kwh = safe_float(row.get('solar_kwh', ''))
		load_kwh = safe_float(row.get('load_kwh', ''))
		battery_charge_kwh = safe_float(row.get('battery_charge_kwh', ''))
		battery_discharge_kwh = safe_float(row.get('battery_discharge_kwh', ''))
		comed_price = safe_float(row.get('comed_price', ''))
		# skip hours with no price data
		comed_price_str = row.get('comed_price', '').strip()
		if not comed_price_str:
			continue
		total_grid_kwh += grid_kwh
		total_solar_kwh += solar_kwh
		total_load_kwh += load_kwh
		total_battery_charge_kwh += battery_charge_kwh
		total_battery_discharge_kwh += battery_discharge_kwh
		# all three scenarios use the same (load - solar) net model
		# for consistent comparison; actual grid_kwh from CSV can
		# include metering anomalies that break the subtraction
		net_load = load_kwh - solar_kwh
		# actual: net load minus battery contribution
		# battery discharge reduces grid draw, charge increases it
		actual_net = net_load - battery_discharge_kwh + battery_charge_kwh
		total_actual_cost_cents += actual_net * comed_price
		# no battery: solar offsets load, excess exports
		total_no_battery_cost_cents += net_load * comed_price
		# no solar: all load from grid
		total_no_solar_cost_cents += load_kwh * comed_price
		# delivery-inclusive: supply price + delivery per kWh
		# import pays (supply + delivery), export gets (supply + delivery credit)
		# since delivery credit ~ delivery charge, same formula both directions
		full_price = comed_price + delivery_cents_per_kwh
		total_actual_delivered_cents += actual_net * full_price
		total_no_battery_delivered_cents += net_load * full_price
		# no solar scenario: only imports, never exports
		total_no_solar_delivered_cents += load_kwh * full_price

	# compute savings
	# battery savings: what the battery saved beyond just having solar
	battery_savings = total_no_battery_cost_cents - total_actual_cost_cents
	# solar savings: what solar saved vs grid-only (without battery)
	solar_savings = total_no_solar_cost_cents - total_no_battery_cost_cents
	# delivery-inclusive savings
	delivered_battery_savings = total_no_battery_delivered_cents - total_actual_delivered_cents
	delivered_solar_savings = total_no_solar_delivered_cents - total_no_battery_delivered_cents

	return {
		'date': date,
		'season': season,
		'grid_kwh': total_grid_kwh,
		'solar_kwh': total_solar_kwh,
		'load_kwh': total_load_kwh,
		'battery_charge_kwh': total_battery_charge_kwh,
		'battery_discharge_kwh': total_battery_discharge_kwh,
		'actual_cost_cents': total_actual_cost_cents,
		'no_battery_cost_cents': total_no_battery_cost_cents,
		'battery_savings_cents': battery_savings,
		'no_solar_cost_cents': total_no_solar_cost_cents,
		'solar_savings_cents': solar_savings,
		'sample_hours': valid_hour_count,
		# delivery-inclusive fields
		'actual_delivered_cents': total_actual_delivered_cents,
		'no_battery_delivered_cents': total_no_battery_delivered_cents,
		'battery_delivered_savings_cents': delivered_battery_savings,
		'no_solar_delivered_cents': total_no_solar_delivered_cents,
		'solar_delivered_savings_cents': delivered_solar_savings,
	}


#============================================
def process_daily_summary(input_path: str, output_path: str) -> None:
	"""
	Read hourly CSV, group by date, compute daily metrics, write output.

	Args:
		input_path: Path to hourly history CSV.
		output_path: Path to output daily summary CSV.
	"""
	if not os.path.isfile(input_path):
		raise FileNotFoundError(f"Input file not found: {input_path}")

	# read hourly data
	hourly_data = []
	with open(input_path, 'r') as f:
		reader = csv.DictReader(f)
		for row in reader:
			hourly_data.append(row)

	# group by date
	daily_groups = {}
	for row in hourly_data:
		date = extract_date(row.get('hour_start', ''))
		if date:
			if date not in daily_groups:
				daily_groups[date] = []
			daily_groups[date].append(row)

	# compute metrics for each day and write output
	output_dir = os.path.dirname(output_path)
	if output_dir and not os.path.isdir(output_dir):
		os.makedirs(output_dir, exist_ok=True)

	daily_summaries = []
	for date in sorted(daily_groups.keys()):
		metrics = compute_daily_metrics(daily_groups[date])
		if metrics:
			daily_summaries.append(metrics)

	# write output CSV
	fieldnames = [
		'date', 'season', 'grid_kwh', 'solar_kwh', 'load_kwh',
		'battery_charge_kwh', 'battery_discharge_kwh',
		'actual_cost_cents', 'no_battery_cost_cents', 'battery_savings_cents',
		'no_solar_cost_cents', 'solar_savings_cents', 'sample_hours',
		'actual_delivered_cents', 'no_battery_delivered_cents',
		'battery_delivered_savings_cents', 'no_solar_delivered_cents',
		'solar_delivered_savings_cents',
	]
	with open(output_path, 'w', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		for summary in daily_summaries:
			writer.writerow(summary)

	return daily_summaries


#============================================
def print_summary(daily_summaries: list) -> None:
	"""
	Print daily summaries as a formatted table.

	Args:
		daily_summaries: List of daily metric dicts.
	"""
	if not daily_summaries:
		print("No data to display")
		return
	# build display rows with rounded values
	# two tables: energy (kWh) and cost (cents)
	energy_rows = []
	cost_rows = []
	for d in daily_summaries:
		energy_rows.append({
			'date': d['date'],
			'grid': f"{d['grid_kwh']:.1f}",
			'solar': f"{d['solar_kwh']:.1f}",
			'load': f"{d['load_kwh']:.1f}",
			'chg': f"{d['battery_charge_kwh']:.1f}",
			'dis': f"{d['battery_discharge_kwh']:.1f}",
			'hrs': d['sample_hours'],
		})
		cost_rows.append({
			'date': d['date'],
			'actual': _fmt_dollars(d['actual_cost_cents']),
			'no batt': _fmt_dollars(d['no_battery_cost_cents']),
			'batt sav': _fmt_dollars(d['battery_savings_cents']),
			'no solar': _fmt_dollars(d['no_solar_cost_cents']),
			'solar sav': _fmt_dollars(d['solar_savings_cents']),
		})
	# add totals row to energy table
	energy_rows.append({
		'date': 'TOTAL',
		'grid': f"{sum(d['grid_kwh'] for d in daily_summaries):.1f}",
		'solar': f"{sum(d['solar_kwh'] for d in daily_summaries):.1f}",
		'load': f"{sum(d['load_kwh'] for d in daily_summaries):.1f}",
		'chg': f"{sum(d['battery_charge_kwh'] for d in daily_summaries):.1f}",
		'dis': f"{sum(d['battery_discharge_kwh'] for d in daily_summaries):.1f}",
		'hrs': sum(d['sample_hours'] for d in daily_summaries),
	})
	# add totals row to cost table
	cost_rows.append({
		'date': 'TOTAL',
		'actual': _fmt_dollars(sum(d['actual_cost_cents'] for d in daily_summaries)),
		'no batt': _fmt_dollars(sum(d['no_battery_cost_cents'] for d in daily_summaries)),
		'batt sav': _fmt_dollars(sum(d['battery_savings_cents'] for d in daily_summaries)),
		'no solar': _fmt_dollars(sum(d['no_solar_cost_cents'] for d in daily_summaries)),
		'solar sav': _fmt_dollars(sum(d['solar_savings_cents'] for d in daily_summaries)),
	})
	# build delivery-inclusive cost table
	deliv_rows = []
	for d in daily_summaries:
		deliv_rows.append({
			'date': d['date'],
			'actual': _fmt_dollars(d['actual_delivered_cents']),
			'no batt': _fmt_dollars(d['no_battery_delivered_cents']),
			'batt sav': _fmt_dollars(d['battery_delivered_savings_cents']),
			'no solar': _fmt_dollars(d['no_solar_delivered_cents']),
			'solar sav': _fmt_dollars(d['solar_delivered_savings_cents']),
		})
	deliv_rows.append({
		'date': 'TOTAL',
		'actual': _fmt_dollars(sum(d['actual_delivered_cents'] for d in daily_summaries)),
		'no batt': _fmt_dollars(sum(d['no_battery_delivered_cents'] for d in daily_summaries)),
		'batt sav': _fmt_dollars(sum(d['battery_delivered_savings_cents'] for d in daily_summaries)),
		'no solar': _fmt_dollars(sum(d['no_solar_delivered_cents'] for d in daily_summaries)),
		'solar sav': _fmt_dollars(sum(d['solar_delivered_savings_cents'] for d in daily_summaries)),
	})
	# right-align cost columns (first col is date = left)
	cost_align = ("left", "right", "right", "right", "right", "right")
	print("Energy (kWh)")
	print(tabulate.tabulate(energy_rows, headers="keys", tablefmt='fancy_grid'))
	print("\nComEd supply cost only (dollars)")
	print(tabulate.tabulate(
		cost_rows, headers="keys", tablefmt='fancy_grid', colalign=cost_align,
	))
	print("\nTotal cost with delivery at 6.354c/kWh (dollars)")
	print(tabulate.tabulate(
		deliv_rows, headers="keys", tablefmt='fancy_grid', colalign=cost_align,
	))


#============================================
def main() -> None:
	"""
	Main entry point.
	"""
	args = parse_args()
	daily_summaries = process_daily_summary(args.input_file, args.output_file)
	print_summary(daily_summaries)
	print(f"\nWrote {len(daily_summaries)} days to {args.output_file}")


if __name__ == '__main__':
	main()
