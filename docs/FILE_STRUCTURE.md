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
| [decision_engine.py](battcontrol/decision_engine.py) | Strategy flowchart logic (sections A-F) |
| [config.py](battcontrol/config.py) | YAML config loader, defaults, price interpolation |
| [state.py](battcontrol/state.py) | JSON-persisted hysteresis and control state |
| [comedlib.py](battcontrol/comedlib.py) | ComEd real-time pricing client |
| [epcube_client.py](battcontrol/epcube_client.py) | EP Cube cloud API client |
| [wemo_actuator.py](battcontrol/wemo_actuator.py) | WeMo smart plug controller |

### [tests/](tests/)

Pytest test suite. All files follow the `test_*.py` naming convention.

| File | Covers |
| --- | --- |
| test_config.py | Config loading, price interpolation, validation |
| test_decision_engine.py | Strategy flowchart decision paths |
| test_state.py | Hysteresis and state persistence |
| test_smoke_battery_controller.py | CLI argument parsing |
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
| [CLAUDE_HOOK_USAGE_GUIDE.md](docs/CLAUDE_HOOK_USAGE_GUIDE.md) | Claude Code permissions hook guide |

PDF datasheets for the EP Cube hardware are also stored in `docs/`.

## Generated artifacts

| Artifact | Location | Git status |
| --- | --- | --- |
| Controller log | `battery_controller.log` | ignored |
| Active config | `config.yml` | ignored |
| Auth credentials | `epcube_auth.yml` | ignored |
| CAPTCHA debug output | `output/` | ignored |
| Temp scratch files | `_*.py`, `_*.sh` | ignored |

## Where to add new work

- **Production code**: add modules to [battcontrol/](battcontrol/).
- **Tests**: add `test_*.py` files to [tests/](tests/).
- **Documentation**: add `SCREAMING_SNAKE_CASE.md` files to [docs/](docs/).
- **Scripts**: add single-purpose scripts at the repo root.
- **Config options**: add defaults to `DEFAULTS` in [battcontrol/config.py](battcontrol/config.py)
  and document in [config_example.yml](config_example.yml).
