# Code architecture

## Overview

The battery controller reads real-time ComEd electricity prices and EP Cube
battery state, then decides whether to charge, discharge, or hold two physically
separate batteries. Decisions run every 3-5 minutes via a daemon loop or cron.

## Major components

- [battcontrol/battery_controller.py](battcontrol/battery_controller.py):
  main orchestrator. Fetches data, calls the decision engine, and dispatches
  actuator commands. Handles EP Cube token renewal, logging setup, and CLI
  argument parsing.
- [battcontrol/decision_engine.py](battcontrol/decision_engine.py):
  stateless policy engine implementing the
  [docs/STRATEGY.md](docs/STRATEGY.md) flowchart. Takes battery SoC, solar
  power, load, price, and config; returns a `DecisionResult` with action,
  SoC floor, target mode, and reason string.
- [battcontrol/config.py](battcontrol/config.py):
  YAML config loader with defaults, seasonal value helpers, and piecewise
  linear interpolation for price-to-floor mapping using `numpy.interp()`.
- [battcontrol/state.py](battcontrol/state.py):
  JSON-persisted hysteresis tracker. Tracks price segment stability,
  action stability (token friction), peak mode, and anti-churn floor.
- [battcontrol/comedlib.py](battcontrol/comedlib.py):
  ComEd real-time pricing client. Fetches current and historical prices,
  computes predicted rate using linear regression (`scipy.stats`).
- [battcontrol/epcube_client.py](battcontrol/epcube_client.py):
  synchronous EP Cube cloud API client. Reads battery state (SoC, solar,
  load, mode) and sends mode/reserve commands.
- [battcontrol/wemo_actuator.py](battcontrol/wemo_actuator.py):
  WeMo smart plug controller for a second battery system. Uses `pywemo`
  to toggle charge and discharge plugs.

## Data flow

```text
ComEd API --> comedlib.py --> predicted price
EP Cube API --> epcube_client.py --> battery SoC, solar, load, mode
                        |
                        v
              battery_controller.py
                        |
          config.yml + state.json
                        |
                        v
              decision_engine.py
              (guards -> daylight/night/peak logic)
                        |
                        v
                  DecisionResult
                 /              \
  epcube_client.py          wemo_actuator.py
  (set mode + reserve)      (toggle plugs)
```

1. `battery_controller.py` fetches price from `comedlib` and device state from
   `epcube_client`.
2. It passes all inputs plus config and persisted state to `decision_engine.decide()`.
3. The decision engine runs guards (hard reserve, solar check), then routes to
   daylight, night, or peak logic. Peak logic interpolates SoC floor from price
   anchors.
4. Hysteresis is applied: segment stability and action friction prevent rapid
   switching.
5. If the action is stable and the floor change is material (>= 2%), actuator
   commands are sent to the EP Cube and/or WeMo plugs.
6. State is saved to JSON for the next cycle.

## Entry points

- [run_battery_controller.py](run_battery_controller.py): single-run CLI entry
  point. Delegates to `battcontrol.battery_controller.main()`.
- [run_daemon.py](run_daemon.py): repeating loop runner for testing. Calls the
  controller in a loop with configurable delay.
- [epcube_get_token.py](epcube_get_token.py): standalone token generator with
  CAPTCHA solver for EP Cube API authentication.
- [epcube_setup.py](epcube_setup.py): interactive setup wizard for EP Cube
  credentials.

## Testing

Tests live in [tests/](tests/) and run with pytest:

```bash
source source_me.sh && python3 -m pytest tests/ -v
```

Key test files:
- [tests/test_config.py](tests/test_config.py): config loading, interpolation, validation
- [tests/test_decision_engine.py](tests/test_decision_engine.py): strategy flowchart paths
- [tests/test_state.py](tests/test_state.py): hysteresis and state persistence
- [tests/test_smoke_battery_controller.py](tests/test_smoke_battery_controller.py): CLI arg parsing
- [tests/test_pyflakes_code_lint.py](tests/test_pyflakes_code_lint.py): repo-wide lint gate

## Extension points

- **Add price anchors**: edit `price_floor_anchors` in [config.yml](config.yml).
  The interpolation adapts automatically to any number of anchor points.
- **Add a new actuator**: create a module under `battcontrol/`, call it from
  `battery_controller.py` alongside the EP Cube and WeMo actuators.
- **Change decision logic**: modify the relevant section function in
  `strategy.py` (`_daylight_logic`, `_night_logic`).

## Known gaps

- No `docs/INSTALL.md` exists; setup steps are in [README.md](README.md) quick start.
- `pywemo` is an optional dependency; WeMo tests mock it. Confirm whether it
  belongs in `pip_requirements.txt`.
