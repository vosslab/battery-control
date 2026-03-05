# Usage

## Prerequisites

- Python 3.12
- Runtime dependencies: `pip install -r pip_requirements.txt`
- ComEd pricing: `battcontrol/comedlib.py` (requires `numpy`, `requests`, `scipy`)
- EP Cube token: generate via the `epcube-token/` app (requires CAPTCHA)

## Configuration

Copy `config_example.yml` to `config.yml` and fill in:

- `epcube_token` - authorization token from epcube-token app
- `epcube_device_sn` - device serial number (printed on EP Cube or found in app)
- `wemo_charge_plug_name` - WeMo plug name for grid charging (optional)
- `wemo_discharge_plug_name` - WeMo plug name for grid discharging (optional)

All other parameters have sensible defaults from
[docs/STRATEGY.md](STRATEGY.md).

## CLI

```bash
# dry-run mode (default, logs decisions without sending commands)
source source_me.sh && python3 -m battcontrol.battery_controller -c config.yml -n

# execute mode (sends real commands to EP Cube and WeMo)
source source_me.sh && python3 -m battcontrol.battery_controller -c config.yml -x

# verbose output (use -vv for debug level)
source source_me.sh && python3 -m battcontrol.battery_controller -c config.yml -n -v
```

### Arguments

| Flag | Description |
| --- | --- |
| `-c`, `--config` | Path to YAML config file (required) |
| `-n`, `--dry-run` | Log decisions without sending commands (default) |
| `-x`, `--execute` | Send real commands to devices |
| `-v`, `--verbose` | Increase logging verbosity (repeat for more) |

## Cron setup

Run every 3 minutes to match ComEd's 5-minute price feed:

```
*/3 * * * * cd /path/to/battery-control && source source_me.sh && python3 -m battcontrol.battery_controller -c config.yml -x >> /tmp/battery_control.log 2>&1
```

## State file

The controller writes hysteresis and tracking state to a JSON file (default
`/tmp/battery_control_state.json`). This file persists between runs and tracks:

- Price band counters for hysteresis
- Action stability counters for token friction
- Peak mode activation state
- Token expiration status
- Last known battery SoC (fallback when EP Cube is unreachable)

## Token management

The EP Cube token expires periodically and requires CAPTCHA-based re-login via
the `epcube-token/` app. When the token expires:

1. The controller logs a prominent warning
2. EP Cube commands are skipped (WeMo-only mode)
3. The controller continues operating with cached SoC data

To refresh: regenerate the token and update `epcube_token` in `config.yml`.

## Output

Each run prints a one-line summary suitable for cron logs:

```
[DRY] 2025-07-15 18:03 action=discharge_paced | Peak mid_high: price 15.2c, paced to 2.0 kWh/hr
```
