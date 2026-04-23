#!/bin/bash

# Launch the battery controller daemon in a named tmux session.
# No-op if the session already exists, so this script is safe to
# re-run (for example from login hooks or cron) and provides a
# simple per-host mutex for the daemon.
#
# Usage:
#   ./run_daemon_tmux.sh                # primary host, live commands (default)
#   ./run_daemon_tmux.sh --dry-run      # override: no device writes
#   ./run_daemon_tmux.sh -d 3           # any extra run_daemon.py flags pass through
#
# run_daemon.py itself injects --execute when no intent flag is given,
# so this wrapper just forwards args.
#
# Attach with:
#   tmux attach -t battery_control
#
# The Python logger in battcontrol/battery_controller.py writes to
# battery_controller.log in the current working directory; we cd to
# REPO_ROOT so that log ends up at the repo root regardless of where
# this script was invoked from.

SESSION_NAME="battery_control"
REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
LOGFILE="$REPO_ROOT/battery_controller.log"

export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# If the session already exists, do nothing and exit cleanly.
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
	echo "Session '$SESSION_NAME' already running."
	echo "  attach: tmux attach -t $SESSION_NAME"
	exit 0
fi

echo "Starting tmux session '$SESSION_NAME'..."
# Forward all script args to run_daemon.py via "$@". run_daemon.py
# defaults to --execute when no intent flag is given.
tmux new-session -d -s "$SESSION_NAME" \
	"cd $REPO_ROOT && source source_me.sh && python3 run_daemon.py $@"

echo "Session '$SESSION_NAME' started."
echo "  attach: tmux attach -t $SESSION_NAME"
echo "  log:    $LOGFILE"
