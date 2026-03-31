#!/usr/bin/env python3

"""Interactive setup script to create the EP Cube auth credentials file.

Creates ~/.config/battcontrol/epcube_auth.yml with the user's EP Cube
credentials for use by the battery controller's auto-renewal feature.
"""

# Standard Library
import os
import stat
import getpass
import argparse

# PIP3 modules
import yaml


# default auth file location
DEFAULT_AUTH_PATH = "~/.config/battcontrol/epcube_auth.yml"


#============================================
def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Set up EP Cube authentication credentials file"
	)
	parser.add_argument(
		'-o', '--output', dest='output_file', default=DEFAULT_AUTH_PATH,
		help=f"Output file path (default: {DEFAULT_AUTH_PATH})",
	)
	args = parser.parse_args()
	return args


#============================================
def prompt_credentials() -> dict:
	"""
	Interactively prompt for EP Cube credentials.

	Returns:
		dict: Credentials with region, device_sn, username, password.
	"""
	print("EP Cube credentials setup")
	print("=" * 40)
	print()
	# region selection
	print("Available regions: US, EU, JP")
	region = input("EP Cube region [US]: ").strip().upper()
	if not region:
		region = "US"
	if region not in ("US", "EU", "JP"):
		raise ValueError(f"Invalid region: {region}. Must be US, EU, or JP.")
	# device serial number
	device_sn = input("EP Cube device serial number: ").strip()
	if not device_sn:
		raise ValueError("Device serial number is required.")
	# email/username
	username = input("EP Cube email/username: ").strip()
	if not username:
		raise ValueError("Email/username is required.")
	# password (hidden input)
	password = getpass.getpass("EP Cube password: ")
	if not password:
		raise ValueError("Password is required.")
	credentials = {
		"epcube_region": region,
		"epcube_device_sn": device_sn,
		"epcube_username": username,
		"epcube_password": password,
	}
	return credentials


#============================================
def write_auth_file(credentials: dict, output_path: str) -> str:
	"""
	Write credentials to a YAML auth file with restricted permissions.

	Args:
		credentials: Dict with region, device_sn, username, password.
		output_path: File path (may contain ~ for home directory).

	Returns:
		str: Expanded absolute path where the file was written.
	"""
	# expand ~ to home directory
	expanded_path = os.path.expanduser(output_path)
	# create parent directories if needed
	parent_dir = os.path.dirname(expanded_path)
	if parent_dir and not os.path.isdir(parent_dir):
		os.makedirs(parent_dir, mode=0o700)
	# write YAML with restricted permissions
	with open(expanded_path, "w") as f:
		yaml.dump(credentials, f, default_flow_style=False)
	# set file permissions to owner-only read/write
	os.chmod(expanded_path, stat.S_IRUSR | stat.S_IWUSR)
	return expanded_path


#============================================
def main() -> None:
	"""
	Main entry point for EP Cube credentials setup.

	Prompts for credentials and writes them to the auth file.
	"""
	args = parse_args()
	# check if file already exists
	expanded = os.path.expanduser(args.output_file)
	if os.path.isfile(expanded):
		print(f"Auth file already exists: {expanded}")
		overwrite = input("Overwrite? [y/N]: ").strip().lower()
		if overwrite != "y":
			print("Aborted.")
			return
	# prompt for credentials
	credentials = prompt_credentials()
	# write the auth file
	auth_path = write_auth_file(credentials, args.output_file)
	print()
	print(f"Credentials written to: {auth_path}")
	print("File permissions: 600 (owner read/write only)")
	print()
	print("IMPORTANT: This file contains your password. Do not commit it to git.")
	print("  It is already excluded by .gitignore (epcube_auth.yml pattern).")
	print()
	print("Next steps:")
	print(f"  1. Ensure config.yml has: epcube_auth_file: \"{args.output_file}\"")
	print("  2. Run the battery controller -- it will auto-generate tokens")
	print("  3. Or manually: source source_me.sh && python3 epcube_get_token.py -e <email>")


#============================================
if __name__ == '__main__':
	main()
