#!/usr/bin/env bash
# kill-port.sh PORT [PORT ...]
#
# For each TCP port, find any local listener and kill it (SIGTERM, then SIGKILL
# after 500 ms if it didn't exit). Used by the `just playground` recipe to
# evict stale processes left over from a previous run that got Ctrl-C'd or
# crashed without reaping cleanly.
#
# Silent when nothing is listening. Logs the PID it kills otherwise.
#
# macOS / Linux. Requires `lsof`.
set -euo pipefail

if [ $# -eq 0 ]; then
    echo "usage: $0 PORT [PORT ...]" >&2
    exit 2
fi

if ! command -v lsof >/dev/null 2>&1; then
    echo "kill-port: lsof not found — skipping port cleanup" >&2
    exit 0
fi

for port in "$@"; do
    # `lsof -ti tcp:PORT -s TCP:LISTEN` returns just the PIDs of listeners.
    pids=$(lsof -ti "tcp:${port}" -s TCP:LISTEN 2>/dev/null || true)
    if [ -z "$pids" ]; then
        continue
    fi
    echo "kill-port: evicting listener on :${port} (pid ${pids//$'\n'/ })"
    # shellcheck disable=SC2086 # intentional word-splitting on whitespace
    kill -TERM $pids 2>/dev/null || true
    # Give the process up to ~500 ms to exit cleanly.
    for _ in 1 2 3 4 5; do
        sleep 0.1
        still=$(lsof -ti "tcp:${port}" -s TCP:LISTEN 2>/dev/null || true)
        if [ -z "$still" ]; then
            break
        fi
    done
    # Anyone still hanging on gets SIGKILL.
    still=$(lsof -ti "tcp:${port}" -s TCP:LISTEN 2>/dev/null || true)
    if [ -n "$still" ]; then
        # shellcheck disable=SC2086
        kill -KILL $still 2>/dev/null || true
        echo "kill-port: SIGKILL sent to ${still//$'\n'/ }"
    fi
done
