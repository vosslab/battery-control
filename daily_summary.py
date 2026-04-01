#!/usr/bin/env python3
"""Aggregate hourly history into daily summary metrics with cost analysis."""

# Standard Library
import csv
import argparse
import datetime
import os


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

	# accumulate totals
	total_grid_kwh = 0.0
	total_solar_kwh = 0.0
	total_load_kwh = 0.0
	total_battery_charge_kwh = 0.0
	total_battery_discharge_kwh = 0.0
	total_actual_cost_cents = 0.0
	total_baseline_cost_cents = 0.0
	total_hindsight_cost_cents = 0.0
	soc_values = []

	# first pass: count valid hours and check if we have any
	valid_hour_count = 0
	for row in hourly_rows:
		comed_price_str = row.get('comed_price', '').strip()
		if comed_price_str:
			valid_hour_count += 1
	# if no valid hours, return None
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
		start_soc = safe_float(row.get('start_soc', ''))
		end_soc = safe_float(row.get('end_soc', ''))

		# skip hours with no price data
		comed_price_str = row.get('comed_price', '').strip()
		if not comed_price_str:
			continue

		total_grid_kwh += grid_kwh
		total_solar_kwh += solar_kwh
		total_load_kwh += load_kwh
		total_battery_charge_kwh += battery_charge_kwh
		total_battery_discharge_kwh += battery_discharge_kwh

		# actual cost: what was paid for grid power
		actual_cost_this_hour = grid_kwh * comed_price
		total_actual_cost_cents += actual_cost_this_hour

		# baseline cost: what would be paid without battery
		# solar still offsets load, so use max(load - solar, 0)
		baseline_load = max(load_kwh - solar_kwh, 0.0)
		baseline_cost_this_hour = baseline_load * comed_price
		total_baseline_cost_cents += baseline_cost_this_hour

		# for hindsight, we'll use the same baseline
		# (we compute optimal displacement after sorting all hours)
		total_hindsight_cost_cents += baseline_cost_this_hour

		# track SoC for fallback estimation
		if start_soc > 0:
			soc_values.append(start_soc)
		if end_soc > 0:
			soc_values.append(end_soc)

	# compute simple hindsight: shift grid consumption from expensive to cheap
	# using available battery energy (sum of battery_charge_kwh for the day)
	available_battery_kwh = total_battery_charge_kwh

	# estimate max available solar energy
	max_daily_soc = max(soc_values) if soc_values else 50.0
	min_daily_soc = min(soc_values) if soc_values else 50.0
	estimated_energy_kwh = (max_daily_soc - min_daily_soc) * capacity_kwh / 100.0
	# use the better estimate
	if estimated_energy_kwh > 0 and total_battery_charge_kwh == 0:
		available_battery_kwh = estimated_energy_kwh

	# sort hours by price descending
	priced_hours = []
	for row in hourly_rows:
		comed_price = safe_float(row.get('comed_price', ''))
		load_kwh = safe_float(row.get('load_kwh', ''))
		solar_kwh = safe_float(row.get('solar_kwh', ''))
		if comed_price > 0 or row.get('comed_price', '').strip() != '':
			baseline_load = max(load_kwh - solar_kwh, 0.0)
			priced_hours.append({
				'price': comed_price,
				'baseline_load': baseline_load,
			})

	# discharge during most expensive hours first
	priced_hours_sorted = sorted(priced_hours, key=lambda h: h['price'], reverse=True)
	hindsight_savings_cents = 0.0
	remaining_battery = available_battery_kwh

	for hour_data in priced_hours_sorted:
		price = hour_data['price']
		baseline_load = hour_data['baseline_load']
		# discharge up to available battery, up to this hour's load
		discharge_kwh = min(remaining_battery, baseline_load)
		if discharge_kwh > 0:
			hindsight_savings_cents += discharge_kwh * price
			remaining_battery -= discharge_kwh

	# finalize savings
	actual_savings_cents = total_baseline_cost_cents - total_actual_cost_cents
	hindsight_best_savings_cents = total_baseline_cost_cents - (
		total_hindsight_cost_cents - hindsight_savings_cents
	)

	return {
		'date': date,
		'season': season,
		'grid_kwh': total_grid_kwh,
		'solar_kwh': total_solar_kwh,
		'load_kwh': total_load_kwh,
		'battery_charge_kwh': total_battery_charge_kwh,
		'battery_discharge_kwh': total_battery_discharge_kwh,
		'actual_cost_cents': total_actual_cost_cents,
		'baseline_cost_cents': total_baseline_cost_cents,
		'savings_cents': actual_savings_cents,
		'hindsight_best_savings_cents': hindsight_best_savings_cents,
		'sample_hours': valid_hour_count,
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
		'actual_cost_cents', 'baseline_cost_cents', 'savings_cents',
		'hindsight_best_savings_cents', 'sample_hours',
	]
	with open(output_path, 'w', newline='') as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		for summary in daily_summaries:
			writer.writerow(summary)


#============================================
def main() -> None:
	"""
	Main entry point.
	"""
	args = parse_args()
	process_daily_summary(args.input_file, args.output_file)


if __name__ == '__main__':
	main()
