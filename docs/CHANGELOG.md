# Changelog

## 2026-03-31

### Additions and New Features

- Created `epcube_get_token.py` standalone CLI script for EP Cube token generation
  - Solves jigsaw CAPTCHA using alpha-contour matching: extracts the jigsaw
    silhouette from the piece PNG alpha channel and matches it against Canny
    edges in the background image; grayscale template matching was tested and
    rejected because it matches scene texture instead of the cutout shape
  - Reads credentials from `~/.config/battcontrol/epcube_auth.yml` by default;
    prompts interactively for missing email or password
  - Writes Bearer token to `~/.epcube_token`
  - Retries auto-solve up to 2 times, then falls back to manual CAPTCHA
    (opens image with grid overlay, user enters X pixel position)
  - Manual fallback is cross-platform (macOS `open`, Linux `xdg-open`,
    headless detection via `DISPLAY` env var)
  - Exposes `generate_token()` for programmatic use by the controller
  - `--test` mode replays cached images from `output/epcube_captcha_debug/`,
    compares canny_edges and alpha_contour methods, shows top-3 peaks with
    confidence gaps, ground truth error when manual accepted_x is available,
    and writes results to CSV
  - All CAPTCHA images are saved to `output/epcube_captcha_debug/` with
    timestamped filenames and metadata JSON for offline analysis
- Created `epcube_setup.py` interactive setup script for EP Cube credentials
  - Creates `~/.config/battcontrol/epcube_auth.yml` with region, device SN,
    username, and password (chmod 600)
  - Prompts interactively; password uses getpass for hidden input
- Added `epcube_token_file` config key to load EP Cube token from a separate file
- Added `epcube_auth_file` config key to load EP Cube credentials from a
  separate YAML file (`~/.config/battcontrol/epcube_auth.yml`)
- Added `opencv-python`, `pillow`, and `pycryptodome` to `pip_requirements.txt`
- Added `config.yml`, `epcube_auth.yml`, and `output/` to `.gitignore`

### Behavior or Interface Changes

- Token is now loaded from a file path (`epcube_token_file`) rather than pasted
  inline (`epcube_token`) in the config; the file path supports `~` expansion and
  strips trailing whitespace
- EP Cube credentials (region, device SN, username, password) are loaded from
  `epcube_auth_file` and override corresponding values in `config.yml`
- Controller auto-renews expired tokens when credentials are available in auth
  file; fallback order: valid token file, auto-generate from auth, manual renewal;
  renewal is attempted at most once per controller run to prevent loops
- Warning messages distinguish: missing token, expired token, missing auth file,
  failed auto-renewal, and freshly generated token rejected
- WeMo actuator execution is skipped when `wemo_charge_plug_name` and
  `wemo_discharge_plug_name` are both empty (reduces log noise)

### Decisions and Failures

- Grayscale template matching was removed after offline testing showed it
  matches scene texture (battery edges, wall gradients) instead of the jigsaw
  cutout shape; it produced high-confidence wrong answers (score 0.42 at x=320
  when the correct answer was x=104)
- The reference app.py algorithm (full-rectangle grayscale TM_CCOEFF_NORMED)
  fails on EP Cube CAPTCHAs because the piece PNG is padded to full image
  height with transparency, making the template 352x94 mostly-empty
- Alpha-contour matching (silhouette edges vs background edges) was validated
  as correct on cached image pairs using the `--test` offline mode
- Canny edge matching on raw piece content also finds the correct X but is
  less grounded than alpha contour because it depends on background noise

### Developer Tests and Notes

- Added `tests/test_epcube_get_token.py` with parse_args, write_token, and
  mocked login tests
- Added `TestTokenFile` class to `tests/test_config.py` with 4 token-file
  loading tests (load, override, missing, whitespace stripping)
- Updated `tests/test_smoke_battery_controller.py` to use `epcube_token_file`
  instead of inline `epcube_token`
- CAPTCHA debug images accumulate in `output/epcube_captcha_debug/` with
  per-attempt metadata; `--test` mode reads these for offline method comparison

## 2026-03-05

### Additions and New Features

- Created `battcontrol/` package with all battery control modules:
  - `config.py` - YAML configuration loader with deep-merge defaults for all
    STRATEGY.md parameters (price bands, seasonal SoC floors, peak window,
    hysteresis counts, EP Cube and WeMo settings)
  - `state.py` - hysteresis and state persistence with atomic JSON writes, tracks
    price band counters, action stability, peak mode, and token expiration
  - `epcube_client.py` - synchronous EP Cube cloud API client extracted from async
    HA patterns; supports device data fetch, switch mode read, and mode setting
    with retry logic and token expiration detection
  - `decision_engine.py` - complete STRATEGY.md flowchart implementation
    (sections A-F) as pure logic functions; includes Action enum, DecisionResult
    dataclass, daylight/night/peak logic, pacing, hysteresis, and token friction
  - `wemo_actuator.py` - WeMo smart plug control mapping actions to
    charge/discharge relay on/off states with dry-run support
  - `battery_controller.py` - main entry point orchestrating config load, state
    load, ComEd price fetch, EP Cube data fetch, decision engine, and actuator
    execution with argparse CLI
- Created `pip_requirements.txt` - runtime dependencies (pywemo, pyyaml, requests)
- Created `docs/USAGE.md` - CLI usage, cron setup, and token management docs
- Updated `README.md` - project overview, quick start, and documentation links
- Created test suite: `tests/test_config.py` (14 tests), `tests/test_state.py`
  (11 tests), `tests/test_decision_engine.py` (16 tests),
  `tests/test_epcube_client.py` (15 tests), `tests/test_wemo_actuator.py`
  (5 tests), `tests/test_smoke_battery_controller.py` (5 tests) - 70 tests total

### Behavior or Interface Changes

- Removed `last_known_soc` from `state.py` - battery SoC is now always read from
  devices (EP Cube API) rather than cached in the state file; when EP Cube data is
  unavailable, the controller holds current state instead of using stale cached values
- Updated `battery_controller.py` to return early with HOLD when EP Cube data is
  unavailable, removing the cached SoC fallback path

### Decisions and Failures

- EP Cube API power values use raw * 10 multiplier (per epcube sensor.py patterns)
- Made pywemo import optional with graceful fallback since it may not be installed
  on all systems; WeMo actuator logs error and returns False when unavailable
- Copied `comedlib.py` into `battcontrol/` package to remove dependency on
  vendored `energy/` folder
- Decision engine is stateless per invocation; hysteresis state persists via JSON
  file between 3-minute scheduler runs
- Dry-run is the default mode for safety; requires explicit `--execute` flag

### Developer Tests and Notes

- All 70 tests pass with `pytest`
- All source files pass `pyflakes` lint
- Tests use mocked API responses for EP Cube client (no network calls)
- Decision engine tests are pure logic with parameterized datetime/price inputs
- Smoke test covers full pipeline with mocked data and token-expired scenarios
