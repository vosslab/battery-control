# battery-control

Battery arbitrage controller for ComEd real-time pricing with EP Cube and
WeMo-controlled battery systems.

## Overview

This system manages two physically separate battery systems:

- **EP Cube (20 kWh)**: Cloud API control. Charges from solar, self-consumes
  (powers the house). Modes: Autoconsumo, Backup.
- **WeMo-controlled battery**: Physical relay control via smart plugs. Can charge
  from grid and discharge to grid for full arbitrage.

The decision engine runs every 3 minutes, reading ComEd real-time prices and
EP Cube solar/battery state to decide whether to charge, discharge, or hold.

## Quick start

```bash
# copy and edit the config file
cp config_example.yml config.yml
# edit config.yml with your EP Cube token, device SN, and WeMo plug names

# dry-run (no commands sent)
source source_me.sh && python3 -m battcontrol.battery_controller -c config.yml -n -v

# execute mode (sends real commands)
source source_me.sh && python3 -m battcontrol.battery_controller -c config.yml -x -v
```

## Strategy

The decision engine implements the flowchart in [docs/STRATEGY.md](docs/STRATEGY.md):

- **Section A**: Guard checks (hard reserve, solar availability)
- **Section B**: Daylight logic (solar capture, headroom management)
- **Section C**: Transition trigger (time-based and solar-fade detection)
- **Section D**: Night logic (preserve battery unless extreme prices)
- **Section E**: Peak logic (evening arbitrage with seasonal price bands and pacing)
- **Section F**: Reliability (hysteresis, minimum hold times, token friction)

## Configuration

All tunable parameters live in a YAML config file. See
[config_example.yml](config_example.yml) for all options with comments.

## Dependencies

Runtime: see [pip_requirements.txt](pip_requirements.txt)

Development: see [pip_requirements-dev.txt](pip_requirements-dev.txt)

ComEd price data is handled by `battcontrol/comedlib.py`.

## Testing

```bash
source source_me.sh && python3 -m pytest tests/ -v
```

## Documentation

- [docs/STRATEGY.md](docs/STRATEGY.md) - battery control strategy flowchart
- [docs/USAGE.md](docs/USAGE.md) - CLI usage and cron setup
- [docs/CHANGELOG.md](docs/CHANGELOG.md) - change history

## Author

Neil Voss, https://bsky.app/profile/neilvosslab.bsky.social
