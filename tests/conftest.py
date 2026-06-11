# Standard Library
import sys

# local repo modules
import git_file_utils

# Put the repo root on sys.path so tests can `import battcontrol.*` under a
# bare `pytest` invocation, not only `python3 -m pytest` (which adds cwd).
# pytest's prepend import mode only adds tests/ (the first dir without an
# __init__.py), so the package root must be inserted explicitly here.
_repo_root = git_file_utils.get_repo_root()
if _repo_root not in sys.path:
	sys.path.insert(0, _repo_root)

# Exclude both end-to-end tiers from pytest collection. tests/playwright/
# holds browser-driven tests (Playwright), and tests/e2e/ holds heavier
# shell/Python whole-system runners. Both run outside pytest -- see
# docs/PLAYWRIGHT_USAGE.md and docs/E2E_TESTS.md.
collect_ignore = ["e2e", "playwright"]
