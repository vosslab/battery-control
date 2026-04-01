# battery-control

Battery arbitrage controller for ComEd real-time pricing with EP Cube and
WeMo-controlled battery systems. Manages two physically separate batteries
(EP Cube 20 kWh via cloud API, WeMo-controlled battery via smart plugs),
making charge/discharge/hold decisions every 3 minutes based on real-time
electricity prices and solar production.

## Quick start

```bash
# install dependencies
source source_me.sh && pip install -r pip_requirements.txt

# set up EP Cube credentials for auto-renewal (interactive prompts)
source source_me.sh && python3 epcube_setup.py

# copy and edit the config file
cp config_example.yml config.yml
# edit config.yml (credentials and device SN are in the auth file)

# dry-run (no commands sent, -c defaults to config.yml)
source source_me.sh && python3 run_battery_controller.py -n -v

# execute mode (sends real commands)
source source_me.sh && python3 run_battery_controller.py -x -v
```

See [config_example.yml](config_example.yml) for all tunable parameters with comments.

## Testing

```bash
source source_me.sh && python3 -m pytest tests/ -v
```

## Documentation

- [docs/STRATEGY.md](docs/STRATEGY.md): battery control strategy flowchart (sections A-F).
- [docs/USAGE.md](docs/USAGE.md): CLI usage, cron setup, and token management.
- [docs/CODE_ARCHITECTURE.md](docs/CODE_ARCHITECTURE.md): system design and data flow.
- [docs/FILE_STRUCTURE.md](docs/FILE_STRUCTURE.md): directory layout and file purposes.
- [docs/CHANGELOG.md](docs/CHANGELOG.md): change history.
- [docs/PYTHON_STYLE.md](docs/PYTHON_STYLE.md): Python coding conventions.
- [docs/REPO_STYLE.md](docs/REPO_STYLE.md): repository layout and file conventions.
- [docs/MARKDOWN_STYLE.md](docs/MARKDOWN_STYLE.md): Markdown formatting rules.
- [docs/AUTHORS.md](docs/AUTHORS.md): maintainers and contributors.

## Author

Neil Voss, https://bsky.app/profile/neilvosslab.bsky.social
