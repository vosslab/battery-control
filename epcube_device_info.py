#!/usr/bin/env python3
"""Fetch and display EP Cube device info and energy stats."""

# Standard Library
import json
import logging
import datetime

# local repo modules
import battcontrol.config
import battcontrol.epcube_client

logger = logging.getLogger(__name__)


#============================================
def main() -> None:
	"""
	Connect to EP Cube and print device info and today's energy stats.
	"""
	logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
	# load config
	config = battcontrol.config.load_config("config.yml")
	token = config["epcube_token"]
	region = config["epcube_region"]
	device_sn = config["epcube_device_sn"]
	if not token:
		logger.error("No EP Cube token configured. Run epcube_get_token.py first.")
		raise SystemExit(1)
	# create client and fetch live data first (to get device_id)
	client = battcontrol.epcube_client.EpcubeClient(token, region, device_sn)
	live_data = client.get_device_data()
	if live_data is None:
		logger.error("Failed to connect to EP Cube API")
		raise SystemExit(1)
	print("=== Live status ===")
	print(f"  SoC: {live_data['battery_soc']}%")
	print(f"  Solar: {live_data['solar_power_watts']:.0f} W")
	print(f"  Grid: {live_data['grid_power_watts']:.0f} W")
	print(f"  Load: {live_data['smart_home_power_watts']:.0f} W")
	print(f"  Battery: {live_data['battery_power_watts']:.0f} W")
	print(f"  Mode: {live_data['work_status']}")
	# fetch device info
	print("\n=== Device info ===")
	device_info = client.get_device_info()
	if device_info:
		print(json.dumps(device_info, indent=2, default=str))
	else:
		print("  (not available)")
	# fetch today's energy stats
	today_str = datetime.date.today().strftime("%Y-%m-%d")
	print(f"\n=== Energy stats for {today_str} ===")
	daily_stats = client.get_energy_stats(today_str, scope_type=1)
	if daily_stats:
		print(json.dumps(daily_stats, indent=2, default=str))
	else:
		print("  (not available)")


if __name__ == '__main__':
	main()
