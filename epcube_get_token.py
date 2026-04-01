#!/usr/bin/env python3

"""CLI tool to obtain an EP Cube authentication token.

Automates the CAPTCHA-based login flow for the EP Cube cloud API.
Solves the jigsaw CAPTCHA using OpenCV template matching, then
logs in with user credentials to obtain a Bearer token.

The token is written to a file (default ~/.epcube_token) for use
by the battery controller via the epcube_token_file config key.
"""

# Standard Library
import sys
import getpass
import logging
import argparse

# local repo modules
import battcontrol.epcube_client
import battcontrol.epcube_captcha
import battcontrol.epcube_login


#============================================
def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Generate an EP Cube authentication token. "
		f"Reads credentials from {battcontrol.epcube_login.DEFAULT_AUTH_FILE} by default."
	)
	parser.add_argument(
		'-t', '--test', dest='test_mode', action='store_true',
		help="Test solver on cached images in output/epcube_captcha_debug/",
	)
	parser.add_argument(
		'-v', '--verbose', dest='verbose', action='count', default=0,
		help="Increase logging verbosity (-vv for debug)",
	)
	args = parser.parse_args()
	return args


#============================================
def _setup_logging(verbose: int) -> None:
	"""
	Configure logging based on verbosity level.

	Args:
		verbose: Verbosity count (0=WARNING, 1=INFO, 2+=DEBUG).
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
def main() -> None:
	"""
	Main entry point for EP Cube token generation.

	Reads credentials from auth file or prompts interactively.
	Tries auto-solve, then falls back to manual CAPTCHA if available.
	"""
	args = parse_args()
	_setup_logging(args.verbose)
	# offline test mode: run solver on cached images and exit
	if args.test_mode:
		battcontrol.epcube_captcha.run_offline_test()
		return
	# load credentials from auth file
	auth_data = battcontrol.epcube_login.load_auth_file(
		battcontrol.epcube_login.DEFAULT_AUTH_FILE)
	email = auth_data.get("epcube_username", "")
	region = auth_data.get("epcube_region", "US")
	password = auth_data.get("epcube_password", "")
	# prompt for missing credentials
	if not email:
		email = input("EP Cube email: ").strip()
	if not email:
		raise RuntimeError("Email is required")
	if not password:
		password = getpass.getpass("EP Cube password: ")
	if not password:
		raise RuntimeError("Password is required")
	logger = logging.getLogger(__name__)
	logger.info("Using region %s", region)
	# try auto-solve first
	output_file = "~/.epcube_token"
	token = battcontrol.epcube_login.generate_token(email, password, region)
	# if auto-solve failed and running interactively, try manual CAPTCHA
	if token is None and sys.stdin.isatty():
		print()
		print("Auto-solve failed. Falling back to manual CAPTCHA.")
		base_url = battcontrol.epcube_client.get_base_url(region)
		headers_dict = battcontrol.epcube_client.get_headers()
		verification = battcontrol.epcube_captcha.manual_solve_captcha(
			base_url, headers_dict)
		if verification is not None:
			token = battcontrol.epcube_login.login(
				base_url, headers_dict, email, password, verification)
	if token is None:
		raise RuntimeError("Failed to obtain token")
	# write token to file
	token_path = battcontrol.epcube_login.write_token(token, output_file)
	print(f"Token written to: {token_path}")
	print(token)


#============================================
if __name__ == '__main__':
	main()
