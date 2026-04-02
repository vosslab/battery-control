# File structure

## Top-level layout

```text
battery-control/
+- battcontrol/          core Python package
+- tests/                pytest test suite
+- docs/                 project documentation
+- devel/                developer utility scripts
+- OTHER_REPOS/          reference third-party code
+- output/               generated output (git-ignored)
+- run_battery_controller.py   single-run CLI entry point
+- run_daemon.py               repeating loop runner
+- epcube_get_token.py         EP Cube token generator
+- epcube_setup.py             interactive EP Cube setup wizard
+- replay_strategy.py          replay strategy against historical CSV
+- daily_summary.py            aggregate hourly history into daily metrics
+- config.yml                  active config (git-ignored)
+- config_example.yml          example config (committed)
+- source_me.sh                Python environment bootstrap
+- pip_requirements.txt        runtime dependencies
+- pip_requirements-dev.txt    dev/test dependencies
+- README.md                   project overview and quick start
+- AGENTS.md                   AI agent instructions
`- CLAUDE.md                   Claude Code config
```

## Key subtrees

### [battcontrol/](battcontrol/)

Core package with no `__init__.py` (imported via `sys.path` or module path).

| File | Purpose |
| --- | --- |
| [battery_controller.py](battcontrol/battery_controller.py) | Main orchestrator: fetch data, decide, actuate |
| [strategy.py](battcontrol/strategy.py) | Pure policy function (price vs cutoff, reserve SoC) |
| [decision_engine.py](battcontrol/decision_engine.py) | Thin orchestrator, delegates to strategy.py |
| [command_buffer.py](battcontrol/command_buffer.py) | Deadband filter for EP Cube command suppression |
| [config.py](battcontrol/config.py) | YAML config loader, defaults, price interpolation |
| [state.py](battcontrol/state.py) | JSON-persisted control state and command tracking |
| [hourly_logger.py](battcontrol/hourly_logger.py) | Hourly CSV logger for cycle data |
| [epcube_login.py](battcontrol/epcube_login.py) | EP Cube login flow and token management |
| [epcube_captcha.py](battcontrol/epcube_captcha.py) | CAPTCHA solver using OpenCV template matching |
| [comedlib.py](battcontrol/comedlib.py) | ComEd real-time pricing client |
| [epcube_client.py](battcontrol/epcube_client.py) | EP Cube cloud API client |
| [wemo_actuator.py](battcontrol/wemo_actuator.py) | WeMo smart plug controller |

### [tests/](tests/)

Pytest test suite. All files follow the `test_*.py` naming convention.

| File | Covers |
| --- | --- |
| test_config.py | Config loading, price interpolation, validation |
| test_epcube_client.py | EP Cube API client |
| test_epcube_get_token.py | Token generation |
| test_wemo_actuator.py | WeMo plug control |
| test_pyflakes_code_lint.py | Repo-wide pyflakes lint gate |
| test_ascii_compliance.py | ASCII character compliance |
| test_indentation.py | Tab indentation enforcement |
| test_whitespace.py | Trailing whitespace checks |
| test_shebangs.py | Shebang line validation |
| test_init_files.py | Empty `__init__.py` enforcement |
| test_import_dot.py | Import style checks |
| test_import_star.py | No `import *` enforcement |
| test_import_requirements.py | Dependency availability |
| test_bandit_security.py | Security lint |

Utility scripts in tests:
- [git_file_utils.py](tests/git_file_utils.py): shared `get_repo_root()` helper
- [conftest.py](tests/conftest.py): pytest fixtures
- [check_ascii_compliance.py](tests/check_ascii_compliance.py): single-file ASCII checker
- [fix_ascii_compliance.py](tests/fix_ascii_compliance.py): single-file ASCII fixer
- [fix_whitespace.py](tests/fix_whitespace.py): whitespace fixer

### [docs/](docs/)

| File | Purpose |
| --- | --- |
| [STRATEGY.md](docs/STRATEGY.md) | Battery control strategy flowchart |
| [USAGE.md](docs/USAGE.md) | CLI usage, cron setup, token management |
| [CODE_ARCHITECTURE.md](docs/CODE_ARCHITECTURE.md) | System design and data flow |
| [CHANGELOG.md](docs/CHANGELOG.md) | Change history |
| [AUTHORS.md](docs/AUTHORS.md) | Maintainers and contributors |
| [PYTHON_STYLE.md](docs/PYTHON_STYLE.md) | Python coding conventions |
| [REPO_STYLE.md](docs/REPO_STYLE.md) | Repository layout conventions |
| [MARKDOWN_STYLE.md](docs/MARKDOWN_STYLE.md) | Markdown formatting rules |
| [EPCUBE_API_FIELDS.md](docs/EPCUBE_API_FIELDS.md) | EP Cube API field reference |
| [EPCUBE_MODE_BEHAVIOR.md](docs/EPCUBE_MODE_BEHAVIOR.md) | EP Cube mode behavior and capabilities |
| [CLAUDE_HOOK_USAGE_GUIDE.md](docs/CLAUDE_HOOK_USAGE_GUIDE.md) | Claude Code permissions hook guide |
| [FILE_STRUCTURE.md](docs/FILE_STRUCTURE.md) | Directory layout and file purposes |

PDF datasheets for the EP Cube hardware are also stored in `docs/`.

### [devel/](devel/)

Developer utility scripts, not part of the main application.

| File | Purpose |
| --- | --- |
| [commit_changelog.py](devel/commit_changelog.py) | Helper for committing changelog updates |

## Generated artifacts

| Artifact | Location | Git status |
| --- | --- | --- |
| Controller log | `battery_controller.log` | ignored |
| Active config | `config.yml` | ignored |
| Auth credentials | `epcube_auth.yml` | ignored |
| Raw EP Cube dumps | `epcube_*.json` | ignored |
| CAPTCHA debug output | `output/` | ignored |
| Hourly history CSV | `data/hourly_history.csv` | ignored |
| Temp scratch files | `_*.py`, `_*.sh` | ignored |

## Where to add new work

- **Production code**: add modules to [battcontrol/](battcontrol/).
- **Tests**: add `test_*.py` files to [tests/](tests/).
- **Documentation**: add `SCREAMING_SNAKE_CASE.md` files to [docs/](docs/).
- **Scripts**: add single-purpose scripts at the repo root.
- **Config options**: add defaults to `DEFAULTS` in [battcontrol/config.py](battcontrol/config.py)
  and document in [config_example.yml](config_example.yml).
