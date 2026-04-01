#!/usr/bin/env python3
"""Run the battery controller in a loop for live terminal monitoring."""

# Standard Library
import sys
import time
import datetime
import argparse

#============================================
def parse_daemon_args() -> tuple:
	"""
	Parse daemon-specific args, pass the rest through to the controller.

	Returns:
		tuple: (delay_minutes, remaining_argv)
	"""
	parser = argparse.ArgumentParser(add_help=False)
	parser.add_argument(
		'-d', '--delay', dest='delay_minutes', type=int, default=5,
		help="Delay between runs in minutes (default: 5)",
	)
	daemon_args, remaining = parser.parse_known_args()
	delay_minutes = daemon_args.delay_minutes
	return delay_minutes, remaining

#============================================
def run_one_cycle(cycle_num: int) -> None:
	"""
	Run a single battery controller cycle.

	Args:
		cycle_num: The current loop iteration number.
	"""
	now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
	print(f"\n{'=' * 60}")
	print(f"  Cycle {cycle_num} | {now_str}")
	print(f"{'=' * 60}")
	import battcontrol.battery_controller
	battcontrol.battery_controller.main()

#============================================
def main() -> None:
	"""Run the battery controller in a repeating loop."""
	delay_minutes, remaining_argv = parse_daemon_args()
	# patch sys.argv so the controller's parse_args sees only its flags
	sys.argv = [sys.argv[0]] + remaining_argv
	delay_seconds = delay_minutes * 60
	print(f"Battery controller daemon starting (delay={delay_minutes}m)")
	print(f"  Controller args: {remaining_argv}")
	print("  Press Ctrl+C to stop")
	cycle_num = 0
	while True:
		cycle_num += 1
		# run one cycle, catch errors so the loop continues
		try:
			run_one_cycle(cycle_num)
		except KeyboardInterrupt:
			raise
		except Exception as err:
			now_str = datetime.datetime.now().strftime("%H:%M:%S")
			print(f"  [{now_str}] ERROR in cycle {cycle_num}: {err}")
		# wait for next cycle
		try:
			next_run = datetime.datetime.now() + datetime.timedelta(seconds=delay_seconds)
			next_str = next_run.strftime("%H:%M:%S")
			print(f"\n  Next run at {next_str} (sleeping {delay_minutes}m)...")
			time.sleep(delay_seconds)
		except KeyboardInterrupt:
			raise

#============================================
if __name__ == '__main__':
	try:
		main()
	except KeyboardInterrupt:
		print("\n\nDaemon stopped by user.")
