# Code architecture

## Overview

The battery controller reads real-time ComEd electricity prices and EP Cube
battery state, then sets a reserve SoC floor every 3 minutes. The EP Cube
runs in self-consumption mode at all times; the reserve floor controls how
much battery is available to serve house load.

The primary decision axis is price vs cutoff:

- **Below cutoff**: cheap grid, reserve 100% (battery holds for later).
- **Above cutoff**: expensive grid, reserve set by price-to-SoC interpolation
  plus a time-period adjustment (evening/morning).

## Major components

- [battcontrol/battery_controller.py](battcontrol/battery_controller.py):
  main orchestrator. Fetches data, calls the decision engine, applies the
  command buffer, dispatches actuator commands. Handles EP Cube token
  renewal, logging setup, and CLI argument parsing.
- [battcontrol/strategy.py](battcontrol/strategy.py):
  pure policy function. Takes price, cutoff, SoC, time, and config; returns
  a `DecisionResult` with state (below/above cutoff), reserve SoC floor,
  target mode, and reason string. No I/O, no state mutation.
- [battcontrol/decision_engine.py](battcontrol/decision_engine.py):
  thin orchestrator that recovers the previous strategy state from
  `ControlState` and delegates to `strategy.evaluate()`.
- [battcontrol/command_buffer.py](battcontrol/command_buffer.py):
  deadband filter for EP Cube commands. Suppresses redundant API calls
  when mode and reserve SoC have not changed materially.
- [battcontrol/config.py](battcontrol/config.py):
  YAML config loader with defaults, seasonal value helpers, and piecewise
  linear interpolation for price-to-floor mapping using `numpy.interp()`.
- [battcontrol/state.py](battcontrol/state.py):
  JSON-persisted control state. Tracks last action, last strategy state
  (for deadband), last EP Cube command (mode, reserve, timestamp), and
  token expiration status.
- [battcontrol/comedlib.py](battcontrol/comedlib.py):
  ComEd real-time pricing client. Fetches current and historical prices,
  computes predicted rate using linear regression (`scipy.stats`), and
  calculates a reasonable usage cutoff.
- [battcontrol/epcube_client.py](battcontrol/epcube_client.py):
  synchronous EP Cube cloud API client. Reads battery state (SoC, solar,
  load, mode) and sends mode/reserve commands.
- [battcontrol/epcube_login.py](battcontrol/epcube_login.py):
  EP Cube login flow with CAPTCHA solver for token generation and renewal.
- [battcontrol/epcube_captcha.py](battcontrol/epcube_captcha.py):
  CAPTCHA solver for EP Cube authentication using OpenCV template matching.
- [battcontrol/wemo_actuator.py](battcontrol/wemo_actuator.py):
  WeMo smart plug controller for a second battery system. Uses `pywemo`
  to toggle charge and discharge plugs.
- [battcontrol/hourly_logger.py](battcontrol/hourly_logger.py):
  hourly CSV logger. Records cycle data (SoC, price, decision) and flushes
  one summary row per hour to `data/hourly_history.csv`.

## Data flow

```text
ComEd API --> comedlib.py --> predicted price, cutoff
EP Cube API --> epcube_client.py --> battery SoC, solar, load, mode
                        |
                        v
              battery_controller.py
                        |
          config.yml + state.json
                        |
                        v
              decision_engine.py
              (delegates to strategy.py)
                        |
                        v
                  DecisionResult
                  (state, reserve SoC, mode, reason)
                        |
                        v
              command_buffer.py
              (suppress if unchanged)
                        |
                        v
                 /              \
  epcube_client.py          wemo_actuator.py
  (set mode + reserve)      (toggle plugs)
```

1. `battery_controller.py` fetches price from `comedlib` and device state from
   `epcube_client`.
2. It passes all inputs plus config and persisted state to `decision_engine.decide()`.
3. The decision engine recovers the previous strategy state and delegates to
   `strategy.evaluate()`.
4. `strategy.evaluate()` runs guards (hard reserve), determines economic state
   with deadband (below/above cutoff), and computes the reserve SoC floor.
   Above cutoff, the floor comes from price-to-SoC interpolation plus a
   time-period adjustment (evening +N%, morning -N%).
5. The command buffer checks whether mode or reserve changed materially
   since the last EP Cube command. If not, the API call is suppressed.
6. If the command passes the buffer, actuator commands are sent to the EP Cube
   and/or WeMo plugs.
7. State is saved to JSON for the next cycle.

## Strategy model

The strategy has two states and one guard:

- **Hard reserve guard**: if SoC is at or below the hard reserve floor,
  force below-cutoff behavior regardless of price.
- **Below cutoff**: cheap grid. Reserve 100%, battery holds. One exception:
  negative price headroom lowers reserve when battery is near-full and price
  is negative (avoids exporting at a loss).
- **Above cutoff**: expensive grid. Reserve = `price_floor_anchors`
  interpolation + time-period adjustment. Evening hours add reserve
  (preserve for later), morning hours subtract (solar is coming).

Self-consumption is the only operating mode. There is no backup mode, no
hold action, and no solar/load policy branching.

## Entry points

- [run_battery_controller.py](run_battery_controller.py): single-run CLI entry
  point. Delegates to `battcontrol.battery_controller.main()`.
- [run_daemon.py](run_daemon.py): repeating loop runner for testing. Calls the
  controller in a loop with configurable delay.
- [epcube_get_token.py](epcube_get_token.py): standalone token generator with
  CAPTCHA solver for EP Cube API authentication.
- [epcube_setup.py](epcube_setup.py): interactive setup wizard for EP Cube
  credentials.
- [replay_strategy.py](replay_strategy.py): replay strategy decisions against
  historical CSV data for validation and tuning.
- [daily_summary.py](daily_summary.py): aggregate hourly history into daily
  summary metrics with cost analysis.

## Testing

Tests live in [tests/](tests/) and run with pytest:

```bash
source source_me.sh && python3 -m pytest tests/ -v
```

Key test files:
- [tests/test_config.py](tests/test_config.py): config loading, price interpolation, validation
- [tests/test_epcube_client.py](tests/test_epcube_client.py): EP Cube API client
- [tests/test_wemo_actuator.py](tests/test_wemo_actuator.py): WeMo plug control
- [tests/test_epcube_get_token.py](tests/test_epcube_get_token.py): token generation
- [tests/test_pyflakes_code_lint.py](tests/test_pyflakes_code_lint.py): repo-wide lint gate

## Extension points

- **Add price anchors**: edit `price_floor_anchors` in [config.yml](config.yml).
  The interpolation adapts automatically to any number of anchor points.
- **Add a new actuator**: create a module under `battcontrol/`, call it from
  `battery_controller.py` alongside the EP Cube and WeMo actuators.
- **Change decision logic**: modify `strategy.evaluate()` in
  [battcontrol/strategy.py](battcontrol/strategy.py).

## Known gaps

- No `docs/INSTALL.md` exists; setup steps are in [README.md](README.md) quick start.
- `pywemo` is an optional dependency; WeMo tests mock it.
- No dedicated test file for `strategy.evaluate()` yet.
