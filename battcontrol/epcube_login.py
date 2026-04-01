"""EP Cube login flow and token management."""

# Standard Library
import os
import time
import random
import logging

# PIP3 modules
import yaml
import requests

# local repo modules
import battcontrol.epcube_client
import battcontrol.epcube_captcha


logger = logging.getLogger(__name__)

# default auth file location
DEFAULT_AUTH_FILE = "~/.config/battcontrol/epcube_auth.yml"

# number of auto-solve attempts before giving up or falling back to manual
MAX_AUTO_ATTEMPTS = 2


#============================================
def load_auth_file(auth_path: str) -> dict:
	"""
	Load EP Cube credentials from a YAML auth file.

	Args:
		auth_path: Path to auth YAML file (may contain ~).

	Returns:
		dict: Auth data with epcube_username, epcube_password, epcube_region,
		      epcube_device_sn. Empty dict if file not found.
	"""
	expanded = os.path.expanduser(auth_path)
	if not os.path.isfile(expanded):
		return {}
	with open(expanded, "r") as f:
		data = yaml.safe_load(f)
	if not data or not isinstance(data, dict):
		return {}
	return data


#============================================
def login(base_url: str, headers: dict, email: str, password: str, captcha_verification: str) -> str | None:
	"""
	Log in to the EP Cube API and obtain a Bearer token.

	Args:
		base_url: API base URL.
		headers: HTTP headers.
		email: EP Cube account email.
		password: EP Cube account password.
		captcha_verification: Encrypted CAPTCHA verification string.

	Returns:
		str: Bearer token string, or None if login response is malformed.
	"""
	# throttle to avoid overloading the server
	time.sleep(random.random())
	login_url = f"{base_url}/open/common/login"
	logger.debug("Logging in to %s", login_url)
	payload = {
		"userName": email,
		"password": password,
		"captchaVerification": captcha_verification,
	}
	response = requests.post(login_url, json=payload, headers=headers)
	response.raise_for_status()
	response_data = response.json()
	# extract token from response
	data_section = response_data.get("data", {})
	if data_section is None:
		logger.error("Login response missing 'data' field: %s", response_data)
		return None
	token = data_section.get("token")
	if not token:
		logger.error("Login response missing token: %s", response_data)
		return None
	logger.info("Login successful, token obtained")
	return token


#============================================
def write_token(token: str, output_path: str) -> str:
	"""
	Write the token to a file.

	Args:
		token: Bearer token string.
		output_path: File path (may contain ~ for home directory).

	Returns:
		str: Expanded absolute path where the token was written.
	"""
	# expand ~ to the user's home directory
	expanded_path = os.path.expanduser(output_path)
	# write the stripped token to the file
	clean_token = token.strip()
	with open(expanded_path, "w") as f:
		f.write(clean_token)
	return expanded_path


#============================================
def generate_token(email: str, password: str, region: str) -> str | None:
	"""
	Generate an EP Cube token using CAPTCHA solver and login.

	This is the programmatic entry point for auto-renewal.
	Retries up to MAX_AUTO_ATTEMPTS times since CAPTCHA template
	matching can fail.

	Args:
		email: EP Cube account email.
		password: EP Cube account password.
		region: Region code (US, EU, or JP).
	Returns:
		str: Bearer token string, or None if all attempts fail.
	"""
	base_url = battcontrol.epcube_client.get_base_url(region)
	headers = battcontrol.epcube_client.get_headers()
	for attempt in range(1, MAX_AUTO_ATTEMPTS + 1):
		logger.info("Auto-solve attempt %d of %d", attempt, MAX_AUTO_ATTEMPTS)
		verification = battcontrol.epcube_captcha.solve_captcha(base_url, headers, attempt=attempt)
		if verification is None:
			logger.warning("CAPTCHA auto-solve failed on attempt %d", attempt)
			continue
		token = login(base_url, headers, email, password, verification)
		if token is not None:
			return token
		logger.warning("Login failed on attempt %d", attempt)
	logger.error("Auto-solve failed after %d attempts", MAX_AUTO_ATTEMPTS)
	return None
