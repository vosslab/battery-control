"""CAPTCHA solver for EP Cube authentication using OpenCV template matching."""

# Standard Library
import io
import os
import json
import time
import uuid
import random
import base64
import logging
import datetime
import platform
import subprocess

# PIP3 modules
import cv2
import numpy
import requests
import PIL.Image
import PIL.ImageDraw
import Crypto.Cipher.AES  # nosec B413 -- pycryptodome, not deprecated pyCrypto
import Crypto.Util.Padding  # nosec B413

logger = logging.getLogger(__name__)


#============================================
def decode_base64_image(b64_string: str) -> numpy.ndarray:
	"""
	Decode a base64-encoded image to an OpenCV BGR array.

	Args:
		b64_string: Base64-encoded image data.

	Returns:
		numpy.ndarray: OpenCV BGR image array (no alpha channel).
	"""
	# decode base64 to raw bytes
	image_data = base64.b64decode(b64_string)
	# open with PIL and normalize to RGB (drops alpha)
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
	response_json = response.json()
	logger.debug("CAPTCHA get response keys: %s", list(response_json.keys()))
	# extract the repData from response
	data_section = response_json.get("data", {})
	if data_section is None or "repData" not in data_section:
		raise RuntimeError(f"Unexpected CAPTCHA response: {response_json}")
	rep_data = data_section["repData"]
	return rep_data


#============================================
def _save_debug_images(bg_bgr: numpy.ndarray, piece_bgr: numpy.ndarray,
	attempt: int, method: str, x: float, max_val: float,
	accepted: bool) -> None:
	"""
	Save CAPTCHA images and metadata for offline debugging.

	Args:
		bg_bgr: Background image (OpenCV BGR).
		piece_bgr: Puzzle piece image (OpenCV BGR).
		attempt: Attempt number.
		method: Template matching method name.
		x: Computed X coordinate.
		max_val: Match confidence score.
		accepted: Whether the CAPTCHA check accepted the solution.
	"""
	debug_dir = _get_debug_dir()
	if not os.path.isdir(debug_dir):
		os.makedirs(debug_dir)
	# timestamp prefix for file grouping
	stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
	prefix = f"{stamp}_attempt{attempt}"
	# save images
	bg_path = os.path.join(debug_dir, f"{prefix}_bg.png")
	piece_path = os.path.join(debug_dir, f"{prefix}_piece.png")
	cv2.imwrite(bg_path, bg_bgr)
	cv2.imwrite(piece_path, piece_bgr)
	# save metadata
	meta = {
		"timestamp": stamp,
		"attempt": attempt,
		"bg_shape": list(bg_bgr.shape),
		"piece_shape": list(piece_bgr.shape),
		"method": method,
		"computed_x": x,
		"match_score": float(max_val),
		"captcha_accepted": accepted,
	}
	meta_path = os.path.join(debug_dir, f"{prefix}_meta.json")
	with open(meta_path, "w") as f:
		json.dump(meta, f, indent=2)
	logger.debug("Debug images saved to %s", debug_dir)


#============================================
def _verify_captcha(base_url: str, headers: dict, client_uid: str,
	captcha_token: str, secret_key: str, x: float, y: float) -> str | None:
	"""
	Submit CAPTCHA coordinates and return verification string if accepted.

	Args:
		base_url: API base URL.
		headers: HTTP headers.
		client_uid: CAPTCHA session UUID.
		captcha_token: Token from CAPTCHA response.
		secret_key: AES encryption key from CAPTCHA response.
		x: X coordinate of puzzle piece position.
		y: Y coordinate (typically 5).

	Returns:
		str: Encrypted captchaVerification string, or None if rejected.
	"""
	# encrypt the coordinates for verification
	point_json = encrypt_point_json(x, y, secret_key)
	# submit to the CAPTCHA check endpoint
	time.sleep(random.random())
	check_url = f"{base_url}/open/common/captcha/check"
	check_response = requests.post(
		check_url,
		json={"clientUid": client_uid, "token": captcha_token, "pointJson": point_json},
		headers=headers,
	)
	check_response.raise_for_status()
	check_data = check_response.json()
	logger.debug("CAPTCHA check response: %s", check_data)
	# safely extract result from nested response
	data_section = check_data.get("data", {})
	if data_section is None:
		data_section = {}
	rep_section = data_section.get("repData", {})
	if rep_section is None:
		rep_section = {}
	captcha_passed = rep_section.get("result", False)
	if captcha_passed:
		logger.info("CAPTCHA verification passed")
		verification = generate_captcha_verification(captcha_token, x, y, secret_key)
		return verification
	logger.warning("CAPTCHA verification failed, solution was not accepted")
	return None


#============================================
def _crop_to_alpha_bbox(b64_string: str) -> tuple:
	"""
	Decode a base64 image and crop to the non-transparent bounding box.

	The EP Cube puzzle piece PNG has a small opaque jigsaw shape
	surrounded by large transparent padding. Cropping removes the
	padding so template matching focuses on the actual piece shape.

	Returns both the cropped BGR image and the cropped alpha mask.
	The alpha mask is needed for contour-based matching.

	Args:
		b64_string: Base64-encoded image data.

	Returns:
		tuple: (cropped_bgr, cropped_alpha) where cropped_alpha is a
		       single-channel mask (255=opaque), or None if no alpha.
	"""
	image_data = base64.b64decode(b64_string)
	pil_image = PIL.Image.open(io.BytesIO(image_data))
	if pil_image.mode != "RGBA":
		# no alpha, return full image as BGR with no mask
		pil_image = pil_image.convert("RGB")
		rgb_array = numpy.array(pil_image)
		bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
		return bgr_array, None
	# extract alpha channel and find bounding box of opaque pixels
	rgba_array = numpy.array(pil_image)
	alpha = rgba_array[:, :, 3]
	# find rows and columns with any opaque pixels
	opaque_rows, opaque_cols = numpy.where(alpha > 0)
	if len(opaque_rows) == 0:
		# fully transparent, fall back to full image
		logger.warning("Puzzle piece is fully transparent, using full image")
		rgb_array = rgba_array[:, :, :3]
		bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
		return bgr_array, None
	# crop to tight bounding box around opaque region
	y0 = opaque_rows.min()
	y1 = opaque_rows.max() + 1
	x0 = opaque_cols.min()
	x1 = opaque_cols.max() + 1
	cropped_rgb = rgba_array[y0:y1, x0:x1, :3]
	cropped_alpha = alpha[y0:y1, x0:x1]
	logger.debug("Cropped piece from (%d,%d) full to (%d,%d) opaque bbox",
		rgba_array.shape[1], rgba_array.shape[0],
		x1 - x0, y1 - y0)
	bgr_array = cv2.cvtColor(cropped_rgb, cv2.COLOR_RGB2BGR)
	return bgr_array, cropped_alpha


#============================================
def _make_contour_template(alpha_mask: numpy.ndarray) -> numpy.ndarray:
	"""
	Build an edge template from the alpha mask silhouette.

	Extracts the boundary of the jigsaw shape from the alpha channel.
	This is the strongest matching signal because the background image
	has a visible jigsaw-shaped discontinuity at the cutout location.

	Args:
		alpha_mask: Single-channel alpha mask (0-255).

	Returns:
		numpy.ndarray: Binary edge image of the jigsaw contour.
	"""
	# binarize the alpha mask
	binary = (alpha_mask > 128).astype(numpy.uint8) * 255
	# extract edges of the silhouette shape
	contour_edges = cv2.Canny(binary, 50, 150)
	return contour_edges


#============================================
def _find_top_peaks(match_result: numpy.ndarray, n: int = 3, min_dist: int = 40) -> list:
	"""
	Find the top N peaks in a template matching result array.

	Peaks are suppressed within min_dist pixels of each other to
	avoid returning overlapping matches.

	Args:
		match_result: 2D array from cv2.matchTemplate.
		n: Number of peaks to return.
		min_dist: Minimum pixel distance between peaks.

	Returns:
		list: List of (x, score) tuples sorted by score descending.
	"""
	# flatten to 1D by taking max across rows (we only care about X)
	scores_1d = match_result.max(axis=0)
	peaks = []
	# copy so we can suppress without modifying original
	working = scores_1d.copy()
	for _ in range(n):
		if len(working) == 0:
			break
		best_x = int(numpy.argmax(working))
		best_score = float(working[best_x])
		peaks.append((best_x, best_score))
		# suppress the region around the peak
		suppress_start = max(0, best_x - min_dist)
		suppress_end = min(len(working), best_x + min_dist + 1)
		working[suppress_start:suppress_end] = -1.0
	return peaks


#============================================
def solve_captcha(base_url: str, headers: dict, attempt: int = 0) -> str | None:
	"""
	Solve the EP Cube jigsaw CAPTCHA using alpha contour matching.

	Decodes the puzzle piece RGBA, crops to the opaque bounding box,
	extracts the jigsaw silhouette from the alpha channel, and matches
	it against edges in the background image.

	Args:
		base_url: API base URL.
		headers: HTTP headers.
		attempt: Attempt number for debug logging.

	Returns:
		str: Encrypted captchaVerification string if solved, None if failed.
	"""
	# generate a unique session ID for this CAPTCHA attempt
	client_uid = str(uuid.uuid4())
	# fetch the CAPTCHA challenge
	rep_data = fetch_captcha(base_url, headers, client_uid)
	secret_key = rep_data["secretKey"]
	captcha_token = rep_data["token"]
	# decode background and extract edges
	original = decode_base64_image(rep_data["originalImageBase64"])
	bg_gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
	bg_edges = cv2.Canny(bg_gray, 50, 150)
	# decode piece with alpha-aware cropping
	puzzle, alpha_mask = _crop_to_alpha_bbox(rep_data["jigsawImageBase64"])
	# build contour template from the alpha silhouette
	method = "alpha_contour"
	if alpha_mask is not None:
		contour_template = _make_contour_template(alpha_mask)
	else:
		# no alpha available, use piece edges as fallback
		logger.warning("Piece has no alpha channel, falling back to piece edges")
		piece_gray = cv2.cvtColor(puzzle, cv2.COLOR_BGR2GRAY)
		contour_template = cv2.Canny(piece_gray, 50, 150)
	# match contour against background edges
	match_result = cv2.matchTemplate(bg_edges, contour_template, cv2.TM_CCOEFF_NORMED)
	_, max_val, _, max_loc = cv2.minMaxLoc(match_result)
	x = float(max_loc[0])
	y = 5
	# log top peaks for diagnostics
	peaks = _find_top_peaks(match_result)
	gap = peaks[0][1] - peaks[1][1] if len(peaks) > 1 else 0.0
	logger.info("CAPTCHA auto-solve: x=%.1f, score=%.4f, gap=%.3f, method=%s, "
		"bg=%s, piece=%s", x, max_val, gap, method,
		bg_gray.shape, puzzle.shape)
	# verify the solution with the API
	verification = _verify_captcha(
		base_url, headers, client_uid, captcha_token, secret_key, x, y)
	accepted = verification is not None
	# always save CAPTCHA images for offline analysis
	_save_debug_images(original, puzzle, attempt, method, x, max_val, accepted)
	return verification


#============================================
def _open_image_viewer(image_path: str) -> None:
	"""
	Open an image file with the platform's default viewer.

	Args:
		image_path: Path to the image file.
	"""
	system = platform.system()
	if system == "Darwin":
		# macOS
		subprocess.Popen(["open", image_path],
			stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	elif system == "Linux":
		# try xdg-open (works on most Linux desktops)
		subprocess.Popen(["xdg-open", image_path],
			stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
	else:
		# no viewer available, user can open manually
		print(f"Open this file manually: {image_path}")


#============================================
def manual_solve_captcha(base_url: str, headers: dict) -> str | None:
	"""
	Solve the EP Cube jigsaw CAPTCHA with human assistance.

	Shows the CAPTCHA background image with vertical grid lines
	and asks the user to estimate the X pixel position where the
	puzzle piece gap begins.

	Args:
		base_url: API base URL.
		headers: HTTP headers.

	Returns:
		str: Encrypted captchaVerification string if solved, None if failed.
	"""
	# check if we have a display (headless Linux has no viewer)
	if platform.system() == "Linux" and not os.environ.get("DISPLAY"):
		print("No display available for manual CAPTCHA on headless Linux.")
		print("Run epcube_get_token.py on a machine with a display.")
		return None
	# generate a unique session ID
	client_uid = str(uuid.uuid4())
	rep_data = fetch_captcha(base_url, headers, client_uid)
	secret_key = rep_data["secretKey"]
	captcha_token = rep_data["token"]
	# decode images
	original = decode_base64_image(rep_data["originalImageBase64"])
	puzzle = decode_base64_image(rep_data["jigsawImageBase64"])
	# save raw images to debug dir for the library
	debug_dir = _get_debug_dir()
	if not os.path.isdir(debug_dir):
		os.makedirs(debug_dir)
	stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
	bg_path = os.path.join(debug_dir, f"{stamp}_manual_bg.png")
	piece_path = os.path.join(debug_dir, f"{stamp}_manual_piece.png")
	cv2.imwrite(bg_path, original)
	cv2.imwrite(piece_path, puzzle)
	# create grid overlay version for the user
	bg_pil = PIL.Image.fromarray(cv2.cvtColor(original, cv2.COLOR_BGR2RGB))
	draw = PIL.ImageDraw.Draw(bg_pil)
	img_width = bg_pil.width
	img_height = bg_pil.height
	# grid lines every 25 pixels, labels every 50
	for px in range(0, img_width, 25):
		line_width = 2 if px % 50 == 0 else 1
		line_color = (255, 0, 0) if px % 50 == 0 else (200, 0, 0)
		draw.line([(px, 0), (px, img_height)], fill=line_color, width=line_width)
		if px % 50 == 0 and px > 0:
			draw.text((px + 2, 2), str(px), fill=(255, 255, 0))
	grid_path = os.path.join(debug_dir, f"{stamp}_manual_grid.png")
	bg_pil.save(grid_path)
	# open grid image for user to view
	_open_image_viewer(grid_path)
	print()
	print("Find the LEFT EDGE of the puzzle piece gap in the background image.")
	print(f"Grid image: {grid_path}")
	# ask user for the X position
	x_input = input("Enter the X pixel position of the left edge (or 'q' to quit): ").strip()
	if x_input.lower() == 'q':
		return None
	x = float(x_input)
	y = 5
	logger.info("Manual CAPTCHA: x=%.1f, y=%d", x, y)
	verification = _verify_captcha(base_url, headers, client_uid, captcha_token, secret_key, x, y)
	# save ground truth to meta.json when accepted
	if verification is not None:
		meta = {
			"timestamp": stamp,
			"attempt": "manual",
			"bg_shape": list(original.shape),
			"piece_shape": list(puzzle.shape),
			"method": "manual",
			"computed_x": x,
			"match_score": 1.0,
			"captcha_accepted": True,
			"accepted_x": x,
		}
		meta_path = os.path.join(debug_dir, f"{stamp}_manual_meta.json")
		with open(meta_path, "w") as f:
			json.dump(meta, f, indent=2)
	return verification


#============================================
def _get_debug_dir() -> str:
	"""
	Get the debug image output directory path.

	Returns:
		str: Absolute path to output/epcube_captcha_debug/.
	"""
	repo_root = subprocess.check_output(
		["git", "rev-parse", "--show-toplevel"], text=True).strip()
	debug_dir = os.path.join(repo_root, "output", "epcube_captcha_debug")
	return debug_dir


#============================================
def _run_method(bg_gray: numpy.ndarray, piece_gray: numpy.ndarray,
	method_name: str) -> list:
	"""
	Run a single template matching method and return top peaks.

	Args:
		bg_gray: Grayscale background image.
		piece_gray: Grayscale piece image (cropped).
		method_name: One of 'canny_edges' or 'alpha_contour'.

	Returns:
		list: Top 3 peaks as (x, score) tuples.
	"""
	if method_name == "alpha_contour":
		# derive contour from piece shape: threshold the piece to get
		# a binary silhouette, then extract edges of that silhouette
		# this approximates the alpha contour for saved images
		_, binary = cv2.threshold(piece_gray, 10, 255, cv2.THRESH_BINARY)
		piece_input = cv2.Canny(binary, 50, 150)
		bg_input = cv2.Canny(bg_gray, 50, 150)
	else:
		# canny edge detection on both images
		bg_input = cv2.Canny(bg_gray, 50, 150)
		piece_input = cv2.Canny(piece_gray, 50, 150)
	# safety check
	if piece_input.shape[0] > bg_input.shape[0] or piece_input.shape[1] > bg_input.shape[1]:
		return [(0, 0.0)]
	match_result = cv2.matchTemplate(bg_input, piece_input, cv2.TM_CCOEFF_NORMED)
	peaks = _find_top_peaks(match_result)
	return peaks


#============================================
def run_offline_test() -> None:
	"""
	Test the CAPTCHA solver on cached images in output/epcube_captcha_debug/.

	Runs multiple matching methods on each image pair and prints a
	comparison table with top peaks, confidence gaps, and error vs
	ground truth when available. Saves results to CSV.
	"""
	debug_dir = _get_debug_dir()
	if not os.path.isdir(debug_dir):
		print(f"No debug images found at {debug_dir}")
		return
	# find all background images, skip manual grid overlays
	bg_files = sorted([f for f in os.listdir(debug_dir)
		if f.endswith("_bg.png") and "_manual_" not in f])
	if not bg_files:
		print(f"No auto-solve *_bg.png files found in {debug_dir}")
		return
	# collect ground truth from manual solves
	ground_truth = {}
	meta_files = [f for f in os.listdir(debug_dir) if f.endswith("_meta.json")]
	for mf in meta_files:
		with open(os.path.join(debug_dir, mf), "r") as fh:
			meta = json.load(fh)
		if meta.get("accepted_x") is not None:
			ground_truth[meta.get("timestamp", "")] = meta["accepted_x"]
	# methods to compare
	methods = ["canny_edges", "alpha_contour"]
	# print header
	print(f"Testing {len(bg_files)} cached CAPTCHA image pairs")
	print(f"Methods: {', '.join(methods)}")
	print()
	print(f"{'prefix':<28} {'method':<14} {'piece':<10} "
		f"{'x1':>5} {'s1':>7} {'x2':>5} {'s2':>7} {'gap':>6} "
		f"{'truth':>6} {'error':>6} {'status':<10}")
	print("-" * 120)
	# collect CSV rows
	csv_rows = []
	csv_header = [
		"prefix", "method", "piece_shape", "x1", "score1",
		"x2", "score2", "gap", "truth_x", "error", "status",
	]
	csv_rows.append(csv_header)
	for bg_file in bg_files:
		prefix = bg_file.replace("_bg.png", "")
		piece_file = f"{prefix}_piece.png"
		meta_file = f"{prefix}_meta.json"
		piece_path = os.path.join(debug_dir, piece_file)
		if not os.path.isfile(piece_path):
			print(f"{prefix:<28} MISSING piece file")
			continue
		# load images
		bg_bgr = cv2.imread(os.path.join(debug_dir, bg_file))
		piece_bgr = cv2.imread(piece_path)
		piece_shape = f"{piece_bgr.shape[0]}x{piece_bgr.shape[1]}"
		bg_gray = cv2.cvtColor(bg_bgr, cv2.COLOR_BGR2GRAY)
		piece_gray = cv2.cvtColor(piece_bgr, cv2.COLOR_BGR2GRAY)
		# load meta for status and find matching ground truth
		status = ""
		meta_path = os.path.join(debug_dir, meta_file)
		if os.path.isfile(meta_path):
			with open(meta_path, "r") as fh:
				meta = json.load(fh)
			if meta.get("captcha_accepted"):
				status = "ACCEPTED"
			else:
				status = "REJECTED"
		# find ground truth by matching timestamp prefix (first 15 chars)
		timestamp_prefix = prefix[:15]
		truth_x = ground_truth.get(timestamp_prefix)
		# run each method
		for method_name in methods:
			peaks = _run_method(bg_gray, piece_gray, method_name)
			x1 = peaks[0][0]
			s1 = peaks[0][1]
			x2 = peaks[1][0] if len(peaks) > 1 else 0
			s2 = peaks[1][1] if len(peaks) > 1 else 0.0
			gap = s1 - s2
			# compute error vs ground truth
			truth_str = ""
			error_str = ""
			if truth_x is not None:
				truth_str = f"{truth_x:.0f}"
				error = abs(x1 - truth_x)
				error_str = f"{error:.0f}"
			# print row
			print(f"{prefix:<28} {method_name:<14} {piece_shape:<10} "
				f"{x1:>5.0f} {s1:>7.4f} {x2:>5.0f} {s2:>7.4f} {gap:>6.3f} "
				f"{truth_str:>6} {error_str:>6} {status:<10}")
			# collect CSV row
			csv_row = [
				prefix, method_name, piece_shape,
				f"{x1:.0f}", f"{s1:.4f}", f"{x2:.0f}", f"{s2:.4f}", f"{gap:.3f}",
				truth_str, error_str, status,
			]
			csv_rows.append(csv_row)
		# blank line between image pairs
		print()
	# write CSV
	csv_path = os.path.join(debug_dir, "test_results.csv")
	with open(csv_path, "w") as fh:
		for row in csv_rows:
			fh.write(",".join(row) + "\n")
	print(f"Results saved to {csv_path}")
