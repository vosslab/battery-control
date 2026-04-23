#!/usr/bin/env python3
"""Run the battery controller."""

#============================================
def main() -> None:
	"""Entry point for battery controller."""
	import battcontrol.battery_controller
	battcontrol.battery_controller.main()

#============================================
if __name__ == "__main__":
	main()
