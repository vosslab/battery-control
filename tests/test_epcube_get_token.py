"""Tests for epcube_get_token.py - EP Cube token CLI."""

# Standard Library
import os
import sys
import unittest.mock

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

sys.path.insert(0, REPO_ROOT)
import battcontrol.epcube_login
import battcontrol.epcube_client


#============================================
class TestWriteToken:
	"""Tests for write_token function."""

	#============================================
	def test_writes_correct_contents(self, tmp_path):
		"""Token is written to the specified file."""
		output_file = str(tmp_path / "test_token")
		result_path = battcontrol.epcube_login.write_token("Bearer abc123", output_file)
		assert result_path == output_file
		with open(output_file, "r") as f:
			contents = f.read()
		assert contents == "Bearer abc123"

	#============================================
	def test_strips_whitespace(self, tmp_path):
		"""Token is stripped before writing."""
		output_file = str(tmp_path / "test_token")
		battcontrol.epcube_login.write_token("Bearer abc123\n\n", output_file)
		with open(output_file, "r") as f:
			contents = f.read()
		assert contents == "Bearer abc123"

	#============================================
	def test_expanduser(self, tmp_path):
		"""Tilde in path is expanded."""
		# use a real path to avoid writing to actual home
		output_file = str(tmp_path / "token_file")
		result_path = battcontrol.epcube_login.write_token("token", output_file)
		assert "~" not in result_path
		assert os.path.isfile(result_path)


#============================================
class TestHappyPathLogin:
	"""Test the full login flow with mocked HTTP responses."""

	#============================================
	def test_login_extracts_token(self):
		"""Login returns the token from the response."""
		# mock the login POST response
		mock_response = unittest.mock.Mock()
		mock_response.raise_for_status = unittest.mock.Mock()
		mock_response.json.return_value = {
			"data": {"token": "Bearer test_token_value"}
		}
		with unittest.mock.patch("requests.post", return_value=mock_response):
			with unittest.mock.patch("time.sleep"):
				token = battcontrol.epcube_login.login(
					"https://example.com/api",
					battcontrol.epcube_client.get_headers(),
					"user@example.com",
					"password123",
					"captcha_verification_string",
				)
		assert token == "Bearer test_token_value"

	#============================================
	def test_login_returns_none_for_missing_token(self):
		"""Login returns None when response has no token."""
		mock_response = unittest.mock.Mock()
		mock_response.raise_for_status = unittest.mock.Mock()
		mock_response.json.return_value = {"data": {}}
		with unittest.mock.patch("requests.post", return_value=mock_response):
			with unittest.mock.patch("time.sleep"):
				token = battcontrol.epcube_login.login(
					"https://example.com/api",
					battcontrol.epcube_client.get_headers(),
					"user@example.com",
					"password123",
					"captcha_verification_string",
				)
		assert token is None
