# Changelog

## 2026-04-06

### Additions and New Features

- Added `get_device_info()` and `get_energy_stats()` methods to
  `battcontrol/epcube_client.py` for `/device/userDeviceInfo` and
  `/device/queryDataElectricityV2` endpoints (from epcube HA integration)
- Added `epcube_device_info.py` standalone script to fetch and display
  device info, live status, and daily energy stats
- Documented `allowChargingXiaGrid` in [docs/EPCUBE_MODE_BEHAVIOR.md](docs/EPCUBE_MODE_BEHAVIOR.md):
  TOU-mode-only grid charging toggle, forbidden by electricity provider
- Added [docs/EPCUBE_HARDWARE_SPECS.md](docs/EPCUBE_HARDWARE_SPECS.md): EP Cube v1
  NA720G specs from datasheet, confirmed by invoice (19.9 kWh, 6 modules,
  93.93% CEC efficiency, 7.6 kW charge/discharge)
- Added `CONFIG_SCHEMA` in `battcontrol/config.py`: one canonical schema for all
  config keys with types, defaults, and range bounds. Replaces scattered `DEFAULTS`
  dict. Schema entries use explicit dicts (`{"type": int, "default": 5, "min": 0}`)
- Added `apply_defaults()`, `validate_config()`, and `get_defaults()` functions
  in config.py for schema-driven config loading
- Added `tests/test_config_validate.py` with 17 tests: unknown key rejection,
  type checks (bool rejected for int), range violations, experimental key
  absence/presence, nested structure validation for seasonal dicts and anchors
- Config validation now runs at load time: unknown keys raise ValueError (typo
  protection), wrong types raise, range violations raise
- Added `cutoff_scale` config key (default 1.0): multiplier on comedlib cutoff
  before strategy decision. Values below 1.0 lower the discharge threshold,
  causing more overnight battery use and creating headroom for solar.
  Replay testing showed 0.75 scale as most promising (+11.8c vs current over
  6 days), but not yet confirmed for live use.
- Added `print_usage_summary()` to `replay_strategy.py`: strategy-independent
  daily table showing import/export kWh, solar, load, and price stats (avg,
  peak, min). Prints first in compare mode.
- Added `configs/half_cutoff.yml`, `configs/cutoff_75pct.yml`,
  `configs/cutoff_60pct.yml` for cutoff scale testing
- Updated [docs/STRATEGY.md](docs/STRATEGY.md) with experimental cutoff scale
  section, replay results, cautions, and export constraint analysis

### Fixes and Maintenance

- Fixed missing group validation for pre-solar experimental config keys: if a user
  sets `pre_solar_soc_threshold` without the other three sibling keys
  (`pre_solar_target_floor`, `pre_solar_start_hour`, `pre_solar_end_hour`),
  `validate_config()` now raises ValueError at load time instead of KeyError at
  runtime in strategy.py

### Behavior or Interface Changes

- Replaced all `config.get("key", default)` calls with `config["key"]` across
  7 files: strategy.py, cutoff_adjust.py, command_buffer.py,
  battery_controller.py, hourly_logger.py, wemo_actuator.py, replay_strategy.py.
  Stable keys are guaranteed present by `apply_defaults()`. Experimental keys
  use `"key" in config` presence checks.
- Removed `negative_price_enabled` and `pre_solar_enabled` boolean flags from
  config; feature gating now uses key presence instead of sentinel values
- Removed 9 stale keys from `config.yml` that were no longer used by strategy:
  `afternoon_target_soc_pct`, `peak_window_start`, `peak_window_end`,
  `extreme_price_threshold`, `night_floor_pct`, `hysteresis_count`,
  `token_friction_count`, `solar_sunset_threshold_watts`,
  `solar_sunset_duration_minutes`

### Additions and New Features

- Extended `replay_strategy.py` with a battery simulation model for strategy
  comparison: tracks simulated SoC, models solar-first dispatch with charge/
  discharge efficiency (0.95/0.95) and max power limits (5 kWh/hr), computes
  replayed grid cost per hour based on strategy reserve decisions
- Added `--compare` flag to `replay_strategy.py` for side-by-side multi-strategy
  comparison: accepts `config:label` pairs, first entry is the reference, output
  shows savings and delta columns per strategy with a TOTAL row
- Created `configs/` directory with four alternative strategy configs for testing:
  `aggressive.yml` (lower floors, less evening conservatism),
  `moderate.yml` (slightly lower floors),
  `evening_focus.yml` (larger time-of-day contrast),
  `max_discharge.yml` (lowest possible floors, zero time adjustment)

### Additions and New Features

- Added negative-price discharge rule and pre-solar positioning rule to
  `battcontrol/strategy.py`, both **disabled by default** (negative_price_floor=100,
  pre_solar_soc_threshold=101). These rules lower the reserve during negative
  prices or before solar peak to create headroom, but are ineffective under
  current EP Cube hardware constraints because the reserve only controls
  discharge -- excess PV always charges the battery regardless of reserve setting.
  Retained as documented design work for future hardware changes.
- Created `configs/` directory with strategy comparison configs:
  `early_headroom.yml`, `pre_position.yml`, `neg_price_aggressive.yml`,
  `neg_price_combined.yml`, plus earlier variants (`aggressive.yml`,
  `moderate.yml`, `evening_focus.yml`, `max_discharge.yml`)
- Added `tabulate` to `pip_requirements.txt` for replay comparison output

### Decisions and Failures

- Ran multi-strategy comparison over Apr 1-6 hourly data (117 hours): all
  strategies produced nearly identical results (~120c total savings), with the
  only measurable difference on Apr 3 (+4.6c for aggressive/moderate vs current).
  Conclusion: 6 days of shoulder season data is insufficient to justify config
  changes; the current strategy performs well for this price environment.
- Negative-price strategy investigation revealed a likely hardware limitation:
  EP Cube self-consumption reserve is a discharge floor only, not a charge cap
  per the user manual. Data is mixed: Apr 5 10:00 shows battery charging with
  reserve=50% (SoC 92->95, supports manual), but Apr 3 15:00 shows no charging
  with reserve=60% (SoC stayed at 95%, ambiguous due to data anomalies).
  Live test needed to confirm: set low reserve during sunny period with SoC
  below 100% and observe. Rules retained in code but disabled by default until
  confirmed.

## 2026-04-02

### Additions and New Features

- Added SoC-based cutoff adjustment wrapper (`battcontrol/cutoff_adjust.py`):
  lowers comedlib cutoff when battery is full (more willing to discharge),
  raises it when battery is low (conserve for expensive peaks); follows the
  same additive wrapper pattern used by `wemoPlug-comed-multi.py` and
  `thermostat-comed.py`; pure function with monotonic linear interpolation
  between configurable SoC thresholds, final cutoff clamped to [2.0, 12.0]c
- Added 6 config keys (`cutoff_adjust_soc_high_threshold`,
  `cutoff_adjust_soc_low_threshold`, `cutoff_adjust_soc_high_cents`,
  `cutoff_adjust_soc_low_cents`, `cutoff_adjust_min_cents`,
  `cutoff_adjust_max_cents`) with sensible defaults
- Added cutoff adjustment section to `config_example.yml`
- Added `tests/test_cutoff_adjust.py` with 12 test cases covering
  midpoint passthrough, threshold endpoints, monotonic interpolation,
  bounds clamping, and invalid config validation
- Updated [docs/STRATEGY.md](STRATEGY.md) with comedlib design context
  (load-adding device origin), SoC wrapper documentation, overlap analysis,
  and four-layer decision pipeline description

## 2026-04-01

### Additions and New Features

- Added STARTUP row to hourly CSV logger: on first daemon cycle, writes a row
  with real prices, SoC, mode, and snapshot power projected over one hour for
  kWh estimates; `policy_action` = `"STARTUP"` and `sample_count` = 0
  distinguish it from regular hourly rows

### Fixes and Maintenance

- Rewrote [docs/CODE_ARCHITECTURE.md](CODE_ARCHITECTURE.md) to match current
  two-state strategy model; removed all references to hysteresis, daylight/night
  routing, sections A-F, and old three-action vocabulary
- Updated [docs/FILE_STRUCTURE.md](FILE_STRUCTURE.md): added missing modules
  (strategy.py, command_buffer.py, hourly_logger.py, epcube_login.py,
  epcube_captcha.py), added missing scripts (replay_strategy.py,
  daily_summary.py), added devel/ subtree, added missing docs
  (EPCUBE_API_FIELDS.md, EPCUBE_MODE_BEHAVIOR.md), added missing generated
  artifacts (epcube_*.json, hourly CSV), removed references to nonexistent
  test files (test_decision_engine.py, test_state.py), fixed stale
  descriptions of decision_engine.py and state.py
- Updated [docs/USAGE.md](USAGE.md) state file description to list actual fields
  (last strategy state, last EP Cube command, token status) instead of old
  hysteresis fields
- Updated [README.md](../README.md) overview to describe reserve SoC management
  instead of charge/discharge/hold decisions; fixed strategy doc reference
- Cleaned live config.yml: removed 6 stale keys (afternoon_target_soc_pct,
  peak_window_start, peak_window_end, extreme_price_threshold, night_floor_pct,
  solar_sunset_threshold_watts, solar_sunset_duration_minutes), added
  time-period adjustment keys

### Additions and New Features

- Added time-period reserve adjustment on top of price-mapped floor in
  ABOVE_CUTOFF: evening (13:00-23:00) adds `time_adjust_soc_pct` (default +5%),
  morning (02:00-10:00) subtracts `time_adjust_soc_pct` (default -5%),
  neutral hours have no adjustment; all values configurable, fixed year-round
- Added `validate_time_adjust()` in config.py to validate hour ranges,
  non-overlap, and non-negative adjustment

### Fixes and Maintenance

- Fixed `HourlyLogger` never flushing hourly CSV rows: the logger was
  re-created inside `main()` every cycle, so `current_hour` was always
  `None` and hour boundaries were never detected; moved to a module-level
  `HOURLY_LOGGER` that persists across `run_daemon.py` cycles

### Removals and Deprecations

- Removed night clamp from ABOVE_CUTOFF path: `_is_solar_available()`,
  `night_floor_pct` config, `solar_sunset_threshold_watts` config, and
  `solar_sunset_duration_minutes` config; solar availability no longer
  shapes the reserve floor, replaced by explicit time-period adjustment

### Behavior or Interface Changes

- Replaced three-action model (`CHARGE_FROM_SOLAR`, `DISCHARGE_ENABLED`,
  `DISCHARGE_DISABLED`) with two-state price-first model (`BELOW_CUTOFF`,
  `ABOVE_CUTOFF`); primary decision axis is now price vs cutoff, not
  solar/load flow direction
- Below cutoff always sets reserve to 100% (battery holds, no discharge);
  previously set reserve to current SoC which allowed unintended discharge
  of newly charged energy
- Above cutoff uses price-to-SoC interpolation for reserve floor; night
  clamp ensures floor is at least `night_floor_pct` when no solar
- Removed day/night and surplus/deficit routing as top-level decision
  branches; solar availability only affects the night floor clamp
- Always uses self-consumption mode; removed backup mode from strategy
  (backup mode grid-charges when reserve exceeds SoC, violating site
  constraint)
- Added cutoff deadband (default 0.5c) to prevent state chattering near
  the cutoff boundary; previous state is preserved within the deadband
- Added `last_strategy_state` to control state for deadband persistence
- Updated [docs/STRATEGY.md](docs/STRATEGY.md) to document price-first
  model, deadband behavior, and simplified flow chart
- Updated WeMo actuator to use `StrategyState` instead of `Action`:
  discharge plug ON when above cutoff, both plugs OFF when below cutoff

### Removals and Deprecations

- Removed `_peak_logic()` and `_is_in_peak_window()` from strategy; peak-window
  routing bypassed the comedlib cutoff check, causing discharge at cheap prices
  (observed: 0.8c discharge when cutoff was 6.6c because peak anchors set floor
  to 55% and SoC was 80%)
- Removed `peak_window_start` and `peak_window_end` from config defaults and
  `config_example.yml`; time-of-day effects now come through the comedlib
  time-aware cutoff, not a separate peak-window state machine
- Removed `afternoon_target_soc_pct` from config defaults and
  `config_example.yml`; hardcoded to 100% in strategy since all seasons
  already used 100%
- Removed STRATEGY.md sections C (transition trigger), E (peak logic), and F
  (hysteresis/hold-time); replaced with price-floor interpolation subsection
  and command buffering note
- Simplified strategy routing: no solar always routes to night logic, solar
  available always routes to daylight logic; both gate discharge on price > cutoff

### Behavior or Interface Changes

- Removed `extreme_price_threshold` (hard-coded 20c gate) from strategy, config,
  and config example; this was a stopgap that predated `comed_cutoff_cents` being
  wired through the strategy
- B.2b headroom, B.3a no-surplus, and D.2 night discharge gates now use the
  comedlib cutoff price (`comed_cutoff_cents`) instead of the removed threshold;
  discharge floors use interpolated price-to-SoC anchors instead of
  `hard_reserve_pct` or `band_low`
- Night logic (D.2) now receives `comed_cutoff_cents` and clamps the interpolated
  price floor to at least `night_floor_pct` so night discharge never goes below
  the configured night floor
- Updated [docs/STRATEGY.md](docs/STRATEGY.md) to replace all "extreme" language
  with cutoff-based language in sections B.2b, B.3a, and D.2

### Additions and New Features

- Added shoulder season (Mar-Apr, Oct-Nov) to three-season model: summer
  (May-Sep), shoulder (Mar-Apr, Oct-Nov), winter (Dec-Feb); previously April
  was classified as winter which prevented aggressive solar charging
- Raised summer `afternoon_target_soc_pct` from 90% to 100% (60kWh solar
  production easily fills battery during cheap hours)
- Set shoulder `afternoon_target_soc_pct` to 100% (same rationale, no AC spike)
- Added shoulder defaults for all seasonal config values: `hard_reserve_pct` 15%,
  `night_floor_pct` 30%, and new shoulder price floor anchors (midpoint between
  summer and winter)
- Updated [docs/STRATEGY.md](docs/STRATEGY.md) to document three-season model
- Set `afternoon_target_soc_pct` to 100% for all seasons; charge to full whenever
  solar is available, seasonal differences are in discharge floors and reserves
- Added negative price headroom logic in daylight B.2b: when SoC >= 95% and price
  is negative, discharge to 85% to absorb solar instead of exporting at a loss;
  initial implementation, likely needs refinement with real negative price data
- Updated [docs/EPCUBE_API_FIELDS.md](docs/EPCUBE_API_FIELDS.md) from fresh
  `--dump-raw` output at 10:00 AM: added 6 missing raw fields (`evPower`,
  `generatorPower`, `evLight`, `generatorLight`, `fromType`, `isNewDevice`),
  added normalized keys to energy fields table (now 15 normalized fields
  including electricity in kWh), replaced example payloads with complete
  56-field dump, noted `systemStatus` value 6 and `workStatus` value "1"

### Behavior or Interface Changes

- Added comedlib usage cutoff to daylight surplus logic (new section B.2x):
  when solar surplus exists and predicted price exceeds the comedlib
  `getReasonableCutOff()` threshold, export surplus to grid instead of
  charging the battery; uses price-to-SoC anchors for the discharge floor
  so battery is ready to respond instantly if a load spike exceeds solar;
  cutoff is time-aware (adjusts for weekends, late night, solar peak hours)
  so the conserve/consume decision adapts throughout the day; previously
  surplus always charged the battery regardless of price
- Added `comed_cutoff` column to hourly CSV for replay strategy testing
- Added cutoff to strategy log line for replay tracing
- Created [docs/EPCUBE_MODE_BEHAVIOR.md](docs/EPCUBE_MODE_BEHAVIOR.md) documenting
  hardware behavior of each EP Cube mode (self-consumption, backup, TOU) with
  details from the EP Cube 2.0 User Manual: charging source priorities, TOU
  sub-mode behavior (off-peak grid charging to 100%, super peak discharge to 5%),
  reserve semantics, grid charging observations, strategy implications, and
  long-term storage guidance
- Fixed mode display bug: `DecisionResult.__repr__` and `[LIVE]` summary now
  show actual `target_mode` instead of inferring mode from action; previously
  `discharge_disabled` always displayed "Backup" even when target was
  self-consumption; replaced `ACTION_MODE_MAP` with `TARGET_MODE_DISPLAY`
- Changed daylight B.3b strategy from backup mode to self-consumption mode
  (reserve stays at current SoC); self-consumption charges from PV only so
  solar surplus will charge the battery without grid charging; live test
  needed to confirm discharge is blocked and solar capture works
- Attempted and reverted backup mode at 100% reserve -- caused ~6.3kW grid
  charging at 62% SoC; backup mode always grid-charges when reserve > SoC;
  `allowChargingXiaGrid` toggle is TOU-only per the app UI

### Fixes and Maintenance

- Renamed misleading "holding" reason string at SoC=100% with solar surplus to
  "Battery full, exporting surplus"; the behavior was correct (self-consumption
  mode, surplus exports to grid) but "holding" implied idle rather than export
- Rewrote `tests/test_decision_engine.py` to test only orchestrator mechanics
  (returns DecisionResult, valid enum action, updates last_action in state);
  removed all strategy decision assertions that blocked strategy changes
- Rewrote `tests/test_strategy.py` to test only contract (returns valid
  DecisionResult, soc_floor in range, valid target_mode) and robustness
  (extreme inputs like 200c, -20c, zero solar/load, full/empty SoC);
  removed all mid-range strategy decision assertions since strategy is
  actively evolving and decision correctness is validated by
  `replay_strategy.py` against historical data

### Additions and New Features

- Created `daily_summary.py` script (executable) that reads `data/hourly_history.csv`,
  groups by date, computes daily metrics (grid/solar/load/battery energy totals,
  actual vs. baseline cost, savings), and writes `data/daily_summary.csv`; includes
  hindsight optimizer that computes optimal discharge timing with perfect price
  foresight; handles blank fields (treats as 0), skips hours without price data,
  and uses SoC deltas as fallback energy estimation
- Created `replay_strategy.py` script (executable) that reads hourly history, loads
  config, replays `battcontrol.strategy.evaluate()` for each hour to compare actual
  vs. replayed policy outcomes; groups results by date with daily cost/savings
  comparison; outputs CSV or formatted table to stdout; supports alternative configs
  for strategy comparison (e.g., testing config changes on historical data)
- Created `tests/test_daily_summary.py` with 9 comprehensive unit tests covering
  single/multi-day aggregation, cost calculations (actual/baseline/savings),
  blank field handling, price-data skipping, and missing file error handling
- Created `tests/test_replay_strategy.py` with 7 unit tests covering replay output
  generation, config comparison, SoC simulation tracking, blank battery field
  fallback, cost comparison, and missing file error handling
- Updated `docs/EPCUBE_API_FIELDS.md` with how-to-dump instructions, added second
  and third raw payload snapshots, and documented field behavior confirmed by
  comparing three snapshots: electricity fields are daily kWh counters,
  `batteryCurrentElectricity` is current stored energy (~12.28 kWh at 61% SoC
  implies ~20 kWh total capacity), `smartHomePower` = `backUpPower` + `nonBackUpPower`,
  flow fields duplicate primary power fields
- Created `battcontrol/command_buffer.py` module with
  `should_send_epcube_update()` function implementing deadband filter for
  EP Cube command suppression; sends update only on mode change, reserve
  SoC change exceeding buffer threshold, resend interval expiry, or first
  command; returns (should_send: bool, buffer_reason: str) tuple
- Created `tests/test_command_buffer.py` with 19 comprehensive unit tests:
  mode change detection, reserve SoC deadband behavior (below/at/above
  threshold), resend interval logic (disabled/not expired/expired), first
  commands (empty mode or None reserve), custom config values, and edge
  cases (zero/max SoC, negative deltas, None timestamps); all tests pass
- Extended `battcontrol/state.py` `_DEFAULT_STATE` with 3 new fields for
  command buffering: `last_epcube_mode` (string, default ""),
  `last_epcube_reserve_soc` (int or None, default None),
  `last_epcube_command_at` (ISO timestamp string or None, default None)
- Added electricity counter normalization to `epcube_client.py:get_device_data()`;
  now returns 6 cumulative kWh fields: `grid_electricity_kwh`, `solar_electricity_kwh`,
  `smart_home_electricity_kwh`, `backup_electricity_kwh`, `battery_electricity_kwh`,
  `non_backup_electricity_kwh`; fields are None when missing, 0.0 when present as
  zero (valid counter state)
- Added 4 test functions to `test_epcube_client.py`: all 6 fields present,
  all missing, all zero, and partial mix; validates correct None/float handling

### Behavior or Interface Changes

- Changed `--dump-raw` to write JSON files instead of logging to console:
  writes `epcube_raw_YYYYMMDD_HHMMSS.json` and
  `epcube_normalized_YYYYMMDD_HHMMSS.json` to the current directory with
  alphabetically sorted keys for easier reading
- All new state fields (`last_epcube_mode`, `last_epcube_reserve_soc`,
  `last_epcube_command_at`) now persist/restore through `save()`, `load()`,
  and `to_dict()` via single `_DEFAULT_STATE` source of truth; adding a new
  state field requires editing only one place

### Fixes and Maintenance

- Deleted dead `_compute_pacing()` function from `decision_engine.py` (lines
  178-211) and removed the discarded call at line 400; the same calculation
  is done inline where the result is actually used
- Fixed tautological assertion in `test_decision_engine.py:75` that could
  never fail: replaced `A or B` double-negative with a direct action check
- Inlined unused `current_price` variable in
  `battery_controller.py:_fetch_comed_price()`; the value was fetched via
  `getCurrentComedRate()` but only appeared in a log line and was never
  returned
- Eliminated 5-way field duplication in `state.py`: `__init__`, `load()`,
  `save()`, and `to_dict()` now all drive from the single `_DEFAULT_STATE`
  dict; adding a new state field requires editing only one place
- Extracted `_ensure_valid_token()` and `_try_renew_after_rejection()` from
  `_fetch_epcube_data()` in `battery_controller.py`; eliminated triple-repeated
  token check/renew/retry blocks tracked by `already_renewed` flag; function
  dropped from 106 to 28 lines
- Moved policy stabilization (token friction) into `_apply_hysteresis()` in
  `decision_engine.py`; added `stabilized` field to `DecisionResult` so the
  decision engine owns friction logic; controller still owns actuator-level
  command suppression (anti-churn)
- Replaced magic number `2` in anti-churn floor threshold with
  `config.get("anti_churn_floor_threshold", 2)` for configurability
- Narrowed `except Exception` in `_fetch_comed_price()` to
  `(RuntimeError, ValueError, requests.RequestException)`
- Removed `as` import aliases across `battery_controller.py`,
  `decision_engine.py`, and `wemo_actuator.py` per PYTHON_STYLE.md;
  all references now use full `battcontrol.module` paths
- Split `epcube_get_token.py` (922 lines) into three modules:
  `battcontrol/epcube_captcha.py` (CAPTCHA solver, ~540 lines),
  `battcontrol/epcube_login.py` (login flow + token management, ~140 lines),
  and a thin CLI wrapper at root (~120 lines)
- Centralized `BASE_URLS`, `USER_AGENT`, `get_base_url()`, and
  `get_headers()` in `battcontrol/epcube_client.py`; removed duplicate
  definitions from the token generation code
- Made `_get_base_url()` public as `get_base_url()` in `epcube_client.py`
- Replaced fragile `import epcube_get_token` in `battery_controller.py` with
  `import battcontrol.epcube_login` (package-internal import)
- Extracted `_select_load_source()` helper from `main()` in
  `battery_controller.py` for load power source selection
- Updated `tests/test_epcube_get_token.py` to import from new module paths
- Removed low-value tests: `_safe_float`/`_safe_int` (testing builtins),
  wemo dry-run-only tests, argparse tests in `test_epcube_get_token.py`
- Replaced hardcoded interpolation assertions in `test_config.py` with
  behavioral range checks (floor decreases with price, interpolated values
  fall between anchor floors)
- Updated test imports in `test_smoke_battery_controller.py` to use full
  module paths matching production code style

### Additions and New Features

- Added "Price input: worst-case predictor" section to `docs/STRATEGY.md`
  documenting that `comedlib.getPredictedRate()` is intentionally pessimistic
  (clamps negatives, floors slope, returns max of three estimates)
- Added comment near `getPredictedRate()` call site in `battery_controller.py`
  pointing to the STRATEGY.md documentation

### Developer Tests and Notes

- Added `TestSolarAndPeakTransition` tests for solar availability and
  peak mode transitions (night vs peak by time, solar timestamp reset)
- Added `TestStabilizedField` tests verifying friction stabilization: first
  decision is unstabilized, repeated same decision reaches stabilized=True
- Added `TestSelectLoadSource` tests for load source fallback logic
  (prefers smartHomePower, falls back to backUpPower, handles missing keys)
- Added `test_reset_daily_clears_peak_mode` and
  `test_round_trip_preserves_all_fields` to `test_state.py`

### Decisions and Failures

- Discovered that the solar fade trigger in `_should_transition_to_peak()`
  is unreachable: it checks if solar dropped below threshold, but is only
  called when `_is_solar_available()` already confirmed solar is above
  threshold. The function always returns False via the "solar is strong"
  branch. Filed as a known issue for future fix.

## 2026-03-31

### Additions and New Features

- Replaced hard price band step function with piecewise linear interpolation
  using `numpy.interp()` for SoC floor calculation; anchor points in
  `config.yml` define the curve, floor changes smoothly between them instead
  of jumping at band boundaries (e.g., 9c summer now gives 40% instead of
  jumping from 50% to 30% at 8c)
- Added `validate_anchors()` to enforce >= 2 anchors with strictly increasing
  prices; anchors are defensively sorted before use
- Added `get_price_segment_index()` and `get_price_segment_bounds()` for
  hysteresis tracking and log display using segment indices instead of
  named bands
- Added anti-churn logic to `battery_controller.py`: EP Cube reserve command
  is skipped when mode is unchanged and floor delta is < 2%, preventing
  rapid small updates from smooth interpolation
- Added `last_commanded_floor` field to `ControlState` for anti-churn tracking

### Behavior or Interface Changes

- Renamed config key `price_band_floors` to `price_floor_anchors`; format
  changed from named bands with `max_price_cents` to ordered anchor lists
  with `price_cents` and `soc_floor_pct`
- Renamed `get_price_band_floor()` to `get_price_floor()` in `config.py`
- Removed `get_price_band_name()` entirely; band names no longer exist
- Renamed `DecisionResult.price_band` (str) to `price_segment` (int)
- Renamed state fields: `current_price_band` to `current_price_segment`,
  `price_band_counter` to `price_segment_counter`,
  `update_price_band()` to `update_price_segment()`
- Updated `docs/STRATEGY.md` to describe interpolation with anchor tables

### Additions and New Features (docs)

- Created `docs/CODE_ARCHITECTURE.md` with system overview, component descriptions,
  data flow diagram, entry points, testing, and extension points
- Created `docs/FILE_STRUCTURE.md` with top-level layout, key subtree tables,
  generated artifact inventory, and guidance for adding new work
- Added links to both new docs in `README.md` documentation section

- Added file logging to `battery_controller.log` in CWD (append mode, always
  INFO level); terminal verbosity is still controlled by `-v` flags
- Switched decision engine price input from `getCurrentComedRate()` to
  `getPredictedRate()` which uses linear regression on the current hour's data
  to estimate where price is heading; current rate is still logged for reference
- Simplified decision engine Action enum from 6 values to 3: `CHARGE_FROM_SOLAR`,
  `DISCHARGE_ENABLED`, `DISCHARGE_DISABLED`; each maps to an EP Cube mode and
  a SoC reserve rule; removed `CHARGE_FROM_GRID` (violates site constraint),
  collapsed `HOLD`, `ALLOW_DISCHARGE`, `FORCE_NO_DISCHARGE`, `DISCHARGE_TO_FLOOR`,
  `DISCHARGE_ALLOWED` into the 3 new actions
- Removed `max_discharge_kwh_this_hour` from `DecisionResult`; pacing calculation
  remains internal to floor selection only
- Decision engine now takes `load_power_watts` (renamed from `backup_power_watts`);
  `battery_controller.py` passes `smart_home_power_watts` with fallback to
  `backup_power_watts` and logs which source was used
- Summary log line now shows EP Cube mode name and reserve SoC:
  `discharge_enabled | Mode: Self-consumption | reserve 45% | reason`
- Updated `docs/STRATEGY.md` with 3-action policy model, seasonal targets
  (100% summer for A/C, 70% winter), softened TOU and Backup constraint wording
- Added `smart_home_power_watts`, `non_backup_power_watts`, and
  `battery_power_watts` to `epcube_client.py` normalized output; `smartHomePower`
  is the best candidate for total house load; updated controller status log to
  show Load, Backup, NonBackup, and Batt fields
- Added `--dump-raw` flag to `battery_controller.py` CLI; logs the raw EP Cube
  API payload and normalized state dict at INFO level once per run, with sensitive
  fields (device IDs, serial numbers) masked; in daemon mode, dumps only on the
  first cycle then auto-strips the flag
- Created `run_daemon.py` terminal loop runner for testing; calls the battery
  controller in a repeating loop with configurable delay (`-d`/`--delay`, default
  5 minutes), passes all other flags through to the controller, catches per-cycle
  errors so the loop continues, and exits cleanly on Ctrl+C
- Created `run_battery_controller.py` root stub script for discoverable entry point;
  delegates to `battcontrol.battery_controller.main()` with no logic duplication
- Added decision-path logging to `battcontrol/decision_engine.py` so verbose mode
  (`-v`) shows a reasoning trace: inputs, which logic block was chosen, and why the
  final action won; logs are tied to returns so they stay aligned with actual behavior

### Fixes and Maintenance

- Fixed duplicate log lines in daemon mode: `_setup_logging()` was adding new
  handlers to the root logger on every cycle without clearing old ones, causing
  cycle N to print every line N times; now clears and closes existing handlers
  before rebuilding
- Changed console log format to shorter `%(levelname)-7s %(module)s: %(message)s`
  dropping timestamps (redundant with cycle headers) and `battcontrol.` prefix;
  file log retains full timestamps and dotted module paths

### Behavior or Interface Changes

- Adopted EP Cube official mode names throughout: `Autoconsumo` renamed to
  `Self-consumption`, `Tariffazione` renamed to `Time of Use`, `Backup` kept;
  `target_mode` values changed from `"autoconsumo"` to `"self_consumption"`;
  MODE_MAP updated in `epcube_client.py`
- Rewrote `docs/STRATEGY.md` with full EP Cube hardware reference section
  documenting all three modes (Self-consumption, Backup, Time of Use), their
  charging sources, power priorities, and API data fields; documented the site
  constraint that grid charging is not permitted, which means Backup mode should
  only be used for short-term discharge blocking and Time of Use mode is not
  suitable; added API field table mapping raw fields to normalized keys
- Renamed `DISCHARGE_PACED` action to `DISCHARGE_ALLOWED` across the codebase;
  the controller cannot set a discharge rate, only allow/block discharge and set
  the reserve SoC floor; reason text now says "SoC X% above Y% floor, discharge
  allowed" instead of "paced to N kWh/hr"
- Changed `-c`/`--config` from required to optional with default `config.yml`;
  clear error message when missing suggests copying `config_example.yml`
- Verbose mode (`-v`) now shows full decision reasoning at INFO level: season,
  guard check, solar availability, path entered, price band, pacing, and final
  decision; debug mode (`-vv`) adds hysteresis counters and sub-checks
- Updated `README.md` and `docs/USAGE.md` run commands to use
  `run_battery_controller.py`

### Developer Tests and Notes

- Added `TestParseArgs` class to `tests/test_smoke_battery_controller.py` with
  tests for default config path, config override, and dry-run default

### Previous additions and new features

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
