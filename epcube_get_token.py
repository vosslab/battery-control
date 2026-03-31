#!/usr/bin/env python3

"""CLI tool to obtain an EP Cube authentication token.

Automates the CAPTCHA-based login flow for the EP Cube cloud API.
Solves the jigsaw CAPTCHA using OpenCV template matching, then
logs in with user credentials to obtain a Bearer token.

The token is written to a file (default ~/.epcube_token) for use
by the battery controller via the epcube_token_file config key.
"""

# Standard Library
import io
import os
import json
import uuid
import time
import random
import base64
import getpass
import logging
import argparse

# PIP3 modules
import cv2
import numpy
import PIL.Image
import requests
import Crypto.Cipher.AES  # nosec B413 -- pycryptodome, not deprecated pyCrypto
import Crypto.Util.Padding  # nosec B413

logger = logging.getLogger(__name__)

# EP Cube API base URLs by region
BASE_URLS = {
	"US": "https://epcube-monitoring.com/app-api",
	"EU": "https://monitoring-eu.epcube.com/api",
	"JP": "https://monitoring-jp.epcube.com/api",
}

# spoofed iOS app user-agent (matches epcube_client.py)
USER_AGENT = "ReservoirMonitoring/2.1.0 (iPhone; iOS 18.3.2; Scale/3.00)"


#============================================
def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Generate an EP Cube authentication token"
	)
	parser.add_argument(
		'-e', '--email', dest='email', required=True,
		help="EP Cube account email address",
	)
	parser.add_argument(
		'-r', '--region', dest='region', default="US",
		choices=["US", "EU", "JP"],
		help="EP Cube cloud region (default: US)",
	)
	parser.add_argument(
		'-o', '--output', dest='output_file', default="~/.epcube_token",
		help="Output file path for token (default: ~/.epcube_token)",
	)
	parser.add_argument(
		'-v', '--verbose', dest='verbose', action='count', default=0,
		help="Increase logging verbosity",
	)
	args = parser.parse_args()
	return args


#============================================
def get_base_url(region: str) -> str:
	"""
	Get the EP Cube API base URL for a region.

	Args:
		region: Region code (US, EU, or JP).

	Returns:
		str: API base URL without trailing slash.
	"""
	url = BASE_URLS[region]
	return url


#============================================
def get_headers() -> dict:
	"""
	Build standard HTTP headers for EP Cube API requests.

	Returns:
		dict: Headers dictionary with spoofed User-Agent.
	"""
	headers = {
		"accept": "*/*",
		"content-type": "application/json",
		"user-agent": USER_AGENT,
		"accept-language": "en-US",
		"accept-encoding": "gzip, deflate, br",
	}
	return headers


#============================================
def decode_base64_image(b64_string: str) -> numpy.ndarray:
	"""
	Decode a base64-encoded image to an OpenCV BGR array.

	Args:
		b64_string: Base64-encoded image data.

	Returns:
		numpy.ndarray: OpenCV BGR image array.
	"""
	# decode base64 to raw bytes
	image_data = base64.b64decode(b64_string)
	# open with PIL and normalize to RGB
	pil_image = PIL.Image.open(io.BytesIO(image_data)).convert("RGB")
	# convert to numpy array then to OpenCV BGR format
	rgb_array = numpy.array(pil_image)
	bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
	return bgr_array


#============================================
def encrypt_point_json(x: float, y: float, secret_key: str) -> str:
	"""
	AES-ECB encrypt the CAPTCHA coordinate point as JSON.

	Args:
		x: X coordinate of the puzzle piece position.
		y: Y coordinate (typically hardcoded to 5).
		secret_key: AES encryption key from CAPTCHA response.

	Returns:
		str: Base64-encoded encrypted point JSON.
	"""
	# build compact JSON with no spaces
	data = json.dumps({"x": float(x), "y": float(y)}, separators=(",", ":"))
	data_bytes = data.encode("utf-8")
	# AES-ECB encrypt with PKCS7 padding
	cipher = Crypto.Cipher.AES.new(secret_key.encode("utf-8"), Crypto.Cipher.AES.MODE_ECB)
	padded = Crypto.Util.Padding.pad(data_bytes, Crypto.Cipher.AES.block_size)
	encrypted = cipher.encrypt(padded)
	result = base64.b64encode(encrypted).decode("utf-8")
	return result


#============================================
def generate_captcha_verification(captcha_token: str, x: float, y: float, secret_key: str) -> str:
	"""
	Generate the encrypted captchaVerification string for login.

	Combines the CAPTCHA token with the solved coordinates,
	separated by '---', then AES-ECB encrypts the result.

	Args:
		captcha_token: Token from the CAPTCHA response.
		x: Solved X coordinate.
		y: Solved Y coordinate.
		secret_key: AES encryption key from CAPTCHA response.

	Returns:
		str: Base64-encoded encrypted verification string.
	"""
	# build the token---coordinates string
	coords_json = json.dumps({"x": float(x), "y": float(y)}, separators=(",", ":"))
	raw = f"{captcha_token}---{coords_json}"
	raw_bytes = raw.encode("utf-8")
	# AES-ECB encrypt with PKCS7 padding
	cipher = Crypto.Cipher.AES.new(secret_key.encode("utf-8"), Crypto.Cipher.AES.MODE_ECB)
	padded = Crypto.Util.Padding.pad(raw_bytes, Crypto.Cipher.AES.block_size)
	encrypted = cipher.encrypt(padded)
	result = base64.b64encode(encrypted).decode("utf-8")
	return result


#============================================
def fetch_captcha(base_url: str, headers: dict, client_uid: str) -> dict:
	"""
	Request a CAPTCHA challenge from the EP Cube API.

	Args:
		base_url: API base URL.
		headers: HTTP headers.
		client_uid: Random UUID identifying this CAPTCHA session.

	Returns:
		dict: CAPTCHA response data containing images, secretKey, and token.
	"""
	# throttle to avoid overloading the server
	time.sleep(random.random())
	url = f"{base_url}/open/common/captcha/get"
	logger.debug("Requesting CAPTCHA from %s", url)
	response = requests.post(url, json={"clientUid": client_uid}, headers=headers)
	response.raise_for_status()
	# extract the repData from response
	rep_data = response.json()["data"]["repData"]
	return rep_data


#============================================
def solve_captcha(base_url: str, headers: dict) -> str | None:
	"""
	Solve the EP Cube jigsaw CAPTCHA using OpenCV template matching.

	Fetches the CAPTCHA images, finds where the puzzle piece fits
	using template matching, encrypts the coordinates, and verifies
	the solution with the API.

	Args:
		base_url: API base URL.
		headers: HTTP headers.

	Returns:
		str: Encrypted captchaVerification string if solved, None if failed.
	"""
	# generate a unique session ID for this CAPTCHA attempt
	client_uid = str(uuid.uuid4())
	# fetch the CAPTCHA challenge
	rep_data = fetch_captcha(base_url, headers, client_uid)
	# decode the background and puzzle piece images
	original = decode_base64_image(rep_data["originalImageBase64"])
	puzzle = decode_base64_image(rep_data["jigsawImageBase64"])
	secret_key = rep_data["secretKey"]
	captcha_token = rep_data["token"]
	# convert to grayscale for template matching
	bg_gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
	piece_gray = cv2.cvtColor(puzzle, cv2.COLOR_BGR2GRAY)
	# safety check: swap if piece is larger than background
	if piece_gray.shape[0] > bg_gray.shape[0] or piece_gray.shape[1] > bg_gray.shape[1]:
		bg_gray, piece_gray = piece_gray, bg_gray
	# find the best match position using template matching
	match_result = cv2.matchTemplate(bg_gray, piece_gray, cv2.TM_CCOEFF_NORMED)
	_, _, _, max_loc = cv2.minMaxLoc(match_result)
	# X is the horizontal position where the piece fits
	x = float(max_loc[0])
	# Y is hardcoded to 5 (matches the reference implementation)
	y = 5
	logger.debug("CAPTCHA solved: x=%.1f, y=%d", x, y)
	# encrypt the coordinates for verification
	point_json = encrypt_point_json(x, y, secret_key)
	# verify the CAPTCHA solution with the API
	time.sleep(random.random())
	check_url = f"{base_url}/open/common/captcha/check"
	check_response = requests.post(
		check_url,
		json={"clientUid": client_uid, "token": captcha_token, "pointJson": point_json},
		headers=headers,
	)
	check_response.raise_for_status()
	check_data = check_response.json()
	# check if the solution was accepted
	captcha_passed = check_data["data"]["repData"]["result"]
	if captcha_passed:
		logger.info("CAPTCHA verification passed")
		# generate the encrypted verification string for login
		verification = generate_captcha_verification(captcha_token, x, y, secret_key)
		return verification
	logger.warning("CAPTCHA verification failed, solution was not accepted")
	return None


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

	This is the programmatic entry point for auto-renewal. It retries
	up to 3 times since CAPTCHA template matching can fail.

	Args:
		email: EP Cube account email.
		password: EP Cube account password.
		region: Region code (US, EU, or JP).

	Returns:
		str: Bearer token string, or None if all attempts fail.
	"""
	base_url = get_base_url(region)
	headers = get_headers()
	max_attempts = 3
	for attempt in range(1, max_attempts + 1):
		logger.info("Token generation attempt %d of %d", attempt, max_attempts)
		# solve the jigsaw CAPTCHA
		verification = solve_captcha(base_url, headers)
		if verification is None:
			logger.warning("CAPTCHA failed on attempt %d", attempt)
			continue
		# log in with credentials
		token = login(base_url, headers, email, password, verification)
		if token is not None:
			return token
		logger.warning("Login failed on attempt %d", attempt)
	logger.error("Failed to obtain token after %d attempts", max_attempts)
	return None


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

	Prompts for password, solves CAPTCHA, logs in, and writes token to file.
	Retries up to 3 times since CAPTCHA template matching can fail.
	"""
	args = parse_args()
	_setup_logging(args.verbose)
	# prompt for password interactively (keeps it out of shell history)
	password = getpass.getpass("EP Cube password: ")
	logger.info("Using region %s", args.region)
	# generate token with retry loop
	token = generate_token(args.email, password, args.region)
	if token is None:
		raise RuntimeError("Failed to obtain token after 3 attempts")
	# write token to file
	token_path = write_token(token, args.output_file)
	print(f"Token written to: {token_path}")
	print(token)


#============================================
if __name__ == '__main__':
	main()
