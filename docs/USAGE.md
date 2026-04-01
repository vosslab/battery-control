# Usage

## Prerequisites

- Python 3.12
- Runtime dependencies: `pip install -r pip_requirements.txt`
- ComEd pricing: `battcontrol/comedlib.py` (requires `numpy`, `requests`, `scipy`)
- EP Cube token: generate with `epcube_get_token.py` (see below)

## Configuration

Copy `config_example.yml` to `config.yml` and fill in:

- `epcube_auth_file` - path to credentials YAML for auto-renewal (default `~/.config/battcontrol/epcube_auth.yml`)
- `epcube_token_file` - path to file containing the EP Cube token (default `~/.epcube_token`)
- `epcube_device_sn` - device serial number (also loadable from auth file)
- `wemo_charge_plug_name` - WeMo plug name for grid charging (optional)
- `wemo_discharge_plug_name` - WeMo plug name for grid discharging (optional)

All other parameters have sensible defaults from
[docs/STRATEGY.md](STRATEGY.md).

## CLI

```bash
# dry-run mode (default, logs decisions without sending commands)
source source_me.sh && python3 run_battery_controller.py -n

# execute mode (sends real commands to EP Cube and WeMo)
source source_me.sh && python3 run_battery_controller.py -x

# verbose output shows decision reasoning (use -vv for debug level)
source source_me.sh && python3 run_battery_controller.py -n -v
```

### Arguments

| Flag | Description |
| --- | --- |
| `-c`, `--config` | Path to YAML config file (default: `config.yml`) |
| `-n`, `--dry-run` | Log decisions without sending commands (default) |
| `-x`, `--execute` | Send real commands to devices |
| `-v`, `--verbose` | Show decision reasoning trace (repeat for debug) |

## Cron setup

Run every 3 minutes to match ComEd's 5-minute price feed:

```
*/3 * * * * cd /path/to/battery-control && source source_me.sh && python3 run_battery_controller.py -x >> /tmp/battery_control.log 2>&1
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

### Automatic renewal (recommended)

Set up credentials once with the interactive setup script:

```bash
source source_me.sh && python3 epcube_setup.py
```

This creates `~/.config/battcontrol/epcube_auth.yml` with your EP Cube region,
device serial number, email, and password (chmod 600). The controller will
auto-renew the token when it expires by solving the CAPTCHA automatically.

### Manual token generation

Generate a token manually without storing credentials:

```bash
source source_me.sh && python3 epcube_get_token.py -e your@email.com -r US
```

The script solves the jigsaw CAPTCHA using OpenCV, logs in, and writes the
Bearer token to `~/.epcube_token`.

### Fallback order

The controller tries this order:

1. Use valid token from `epcube_token_file`
2. If missing or rejected (401), auto-generate from `epcube_auth_file` credentials
3. Save new token back to `epcube_token_file`
4. If auto-renewal fails, log a warning to run `epcube_get_token.py` manually

## Output

Each run prints a one-line summary suitable for cron logs:

```
[DRY] 2025-07-15 18:03 discharge_enabled | Mode: Self-consumption | reserve 45% | Peak mid_high: SoC 70% above 45% floor, discharge enabled
```
