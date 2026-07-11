"""`aia-council` — convene a decision council from the command line.

Thin HTTP client for POST /api/v1/council on a running ai-accounts sidecar
(the playground server by default). Streams deliberation progress to stderr
and prints the final decision JSON to stdout, so callers (humans, scripts,
or a Claude Code skill) can pipe stdout straight into a JSON parser.

Exit codes: 0 decision reached · 1 council failed / no decision · 2 usage.

Examples:
    aia-council -q "Which storage layer?" -o "SQLite" -o "Postgres" \\
        -c "Single-node deployment, <10k rows, ops team of one."
    aia-council -q "..." -o "A" -o "B" --context-file brief.md --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Iterator
from typing import Any

import httpx

_DEFAULT_URL = "http://127.0.0.1:30000"


def _parse_sse(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    """Yield the JSON payload of each `data:` line (comments/blank skipped)."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        raw = line.removeprefix("data:").strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def _progress(event: dict[str, Any]) -> str | None:
    """One human-readable stderr line per interesting event."""
    kind = event.get("kind")
    if kind == "council_start":
        members = (event.get("payload") or {}).get("members", [])
        seats = ", ".join(
            f"{m['role']}→{m.get('account_label') or m.get('backend_kind')}" for m in members
        )
        return f"council convened: {seats}"
    if kind == "position":
        return f"position [{event.get('role')}] votes {event.get('option')}"
    if kind == "rebuttal":
        return f"rebuttal r{event.get('round')} [{event.get('role')}] votes {event.get('option')}"
    if kind == "member_error":
        return f"member error [{event.get('role') or '?'}]: {event.get('error')}"
    if kind == "votes":
        return f"votes: {json.dumps((event.get('payload') or {}).get('tally', {}))}"
    if kind == "council_error":
        return f"council error: {event.get('error')}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aia-council",
        description="Convene a council of your AI accounts to debate and decide.",
    )
    parser.add_argument("-q", "--question", required=True, help="the decision question")
    parser.add_argument(
        "-o",
        "--option",
        action="append",
        dest="options",
        required=True,
        help="a candidate option (repeat; at least two)",
    )
    parser.add_argument("-c", "--context", default="", help="context brief for the council")
    parser.add_argument("--context-file", help="read the context brief from a file")
    parser.add_argument("--rounds", type=int, default=1, help="rebuttal rounds (default 1)")
    parser.add_argument(
        "--url",
        default=os.environ.get("AIA_URL", _DEFAULT_URL),
        help=f"ai-accounts server URL (env AIA_URL, default {_DEFAULT_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("AI_ACCOUNTS_API_KEY", ""),
        help="bearer key when the server uses ApiKeyAuth (env AI_ACCOUNTS_API_KEY)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print only the decision JSON (no progress lines)"
    )
    args = parser.parse_args(argv)

    if len(args.options) < 2:
        parser.error("need at least two --option values")
    context = args.context
    if args.context_file:
        try:
            with open(args.context_file, encoding="utf-8") as f:
                context = f.read()
        except OSError as exc:
            parser.error(f"cannot read --context-file: {exc}")

    body = {
        "question": args.question,
        "options": args.options,
        "context": context,
        "rounds": args.rounds,
    }
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    decision: dict[str, Any] | None = None
    failure: str | None = None
    try:
        with (
            httpx.Client(timeout=httpx.Timeout(10.0, read=600.0)) as client,
            client.stream(
                "POST",
                f"{args.url.rstrip('/')}/api/v1/council/",
                json=body,
                headers=headers,
            ) as resp,
        ):
            if resp.status_code != 200:
                resp.read()
                print(
                    f"aia-council: server returned {resp.status_code}: {resp.text[:300]}",
                    file=sys.stderr,
                )
                return 1
            for event in _parse_sse(resp.iter_lines()):
                if not args.json:
                    line = _progress(event)
                    if line:
                        print(line, file=sys.stderr)
                if event.get("kind") == "decision":
                    decision = event.get("payload")
                elif event.get("kind") == "council_error":
                    failure = event.get("error")
    except httpx.ConnectError as exc:
        print(
            f"aia-council: cannot reach {args.url} ({exc}) — is the ai-accounts server running?",
            file=sys.stderr,
        )
        return 1
    except httpx.HTTPError as exc:
        # Mid-stream drop: the server WAS reachable. Keep an already-received
        # decision instead of discarding it; only fail when none arrived.
        if decision is None:
            print(f"aia-council: stream interrupted ({exc})", file=sys.stderr)
            return 1
        print(
            f"aia-council: stream interrupted after the decision was received ({exc})",
            file=sys.stderr,
        )

    if decision is None:
        print(f"aia-council: no decision ({failure or 'stream ended early'})", file=sys.stderr)
        return 1
    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
