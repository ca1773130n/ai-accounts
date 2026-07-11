#!/usr/bin/env node
// aia-council — convene a decision council from the command line.
//
// Node port of ai_accounts_core/cli_council.py with the identical contract:
// thin HTTP/SSE client for POST /api/v1/council on a running ai-accounts
// server. Deliberation progress streams to stderr; the final decision JSON
// prints to stdout. Exit codes: 0 decision · 1 failure/no decision · 2 usage.
//
// Zero dependencies — global fetch (Node >= 18.17) and node:util parseArgs.

import { parseArgs } from "node:util";
import { readFileSync, realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
import process from "node:process";

const DEFAULT_URL = "http://127.0.0.1:30000";

const USAGE = `usage: aia-council -q QUESTION -o OPTION -o OPTION [...]
                   [-c CONTEXT] [--context-file FILE] [--rounds N]
                   [--url URL] [--api-key KEY] [--json]

Convene a council of your AI accounts to debate and decide.
  -q, --question   the decision question (required)
  -o, --option     a candidate option (repeat; at least two)
  -c, --context    context brief for the council
      --context-file  read the context brief from a file
      --rounds     rebuttal rounds (default 1)
      --url        ai-accounts server URL (env AIA_URL, default ${DEFAULT_URL})
      --api-key    bearer key when the server uses ApiKeyAuth (env AI_ACCOUNTS_API_KEY)
      --json       print only the decision JSON (no progress lines)`;

/** Incremental SSE parser: consume text, return [events, remainder]. */
export function drainSse(buffer) {
  const events = [];
  const lines = buffer.split("\n");
  const rest = lines.pop() ?? "";
  for (const line of lines) {
    if (!line.startsWith("data:")) continue;
    const raw = line.slice(5).trim();
    if (!raw) continue;
    try {
      events.push(JSON.parse(raw));
    } catch {
      // tolerated, skipped — mirrors the Python CLI
    }
  }
  return [events, rest];
}

/** One human-readable stderr line per interesting event (null = silent). */
export function progressLine(event) {
  const kind = event.kind;
  if (kind === "council_start") {
    const members = event.payload?.members ?? [];
    const seats = members
      .map((m) => `${m.role}→${m.account_label ?? m.backend_kind ?? "?"}`)
      .join(", ");
    return `council convened: ${seats}`;
  }
  if (kind === "position") return `position [${event.role}] votes ${event.option}`;
  if (kind === "rebuttal")
    return `rebuttal r${event.round} [${event.role}] votes ${event.option}`;
  if (kind === "member_error") return `member error [${event.role ?? "?"}]: ${event.error}`;
  if (kind === "votes") return `votes: ${JSON.stringify(event.payload?.tally ?? {})}`;
  if (kind === "council_error") return `council error: ${event.error}`;
  return null;
}

export async function main(argv) {
  let args;
  try {
    args = parseArgs({
      args: argv,
      options: {
        question: { type: "string", short: "q" },
        option: { type: "string", short: "o", multiple: true },
        context: { type: "string", short: "c", default: "" },
        "context-file": { type: "string" },
        rounds: { type: "string", default: "1" },
        url: { type: "string", default: process.env.AIA_URL || DEFAULT_URL },
        "api-key": { type: "string", default: process.env.AI_ACCOUNTS_API_KEY || "" },
        json: { type: "boolean", default: false },
        help: { type: "boolean", short: "h", default: false },
      },
    }).values;
  } catch (err) {
    console.error(`aia-council: ${err.message}\n${USAGE}`);
    return 2;
  }
  if (args.help) {
    console.log(USAGE);
    return 0;
  }
  if (!args.question || (args.option ?? []).length < 2) {
    console.error(`aia-council: need --question and at least two --option values\n${USAGE}`);
    return 2;
  }
  let context = args.context;
  if (args["context-file"]) {
    try {
      context = readFileSync(args["context-file"], "utf-8");
    } catch (err) {
      console.error(`aia-council: cannot read --context-file: ${err.message}`);
      return 2;
    }
  }

  const headers = { "Content-Type": "application/json" };
  if (args["api-key"]) headers.Authorization = `Bearer ${args["api-key"]}`;

  let res;
  try {
    res = await fetch(`${args.url.replace(/\/+$/, "")}/api/v1/council/`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        question: args.question,
        options: args.option,
        context,
        rounds: Number.parseInt(args.rounds, 10) || 0,
      }),
      signal: AbortSignal.timeout(600_000),
    });
  } catch (err) {
    console.error(
      `aia-council: cannot reach ${args.url} (${err.cause?.message ?? err.message}) — is the ai-accounts server running?`,
    );
    return 1;
  }
  if (res.status !== 200) {
    const body = (await res.text()).slice(0, 300);
    console.error(`aia-council: server returned ${res.status}: ${body}`);
    return 1;
  }

  let decision = null;
  let failure = null;
  let buffer = "";
  const decoder = new TextDecoder();
  const handle = (event) => {
    if (!args.json) {
      const line = progressLine(event);
      if (line) console.error(line);
    }
    if (event.kind === "decision") decision = event.payload;
    else if (event.kind === "council_error") failure = event.error;
  };
  try {
    for await (const chunk of res.body) {
      buffer += decoder.decode(chunk, { stream: true });
      const [events, rest] = drainSse(buffer);
      buffer = rest;
      events.forEach(handle);
    }
    drainSse(buffer + "\n")[0].forEach(handle);
  } catch (err) {
    // Mid-stream drop: the server WAS reachable — keep a received decision.
    if (decision === null) {
      console.error(`aia-council: stream interrupted (${err.message})`);
      return 1;
    }
    console.error(`aia-council: stream interrupted after the decision was received (${err.message})`);
  }

  if (decision === null) {
    console.error(`aia-council: no decision (${failure ?? "stream ended early"})`);
    return 1;
  }
  console.log(JSON.stringify(decision, null, 2));
  return 0;
}

// npm installs the bin as a SYMLINK in node_modules/.bin — resolve it before
// comparing, or the guard never matches and the CLI silently does nothing.
let entryHref = null;
try {
  if (process.argv[1]) entryHref = pathToFileURL(realpathSync(process.argv[1])).href;
} catch {
  entryHref = null;
}
if (entryHref === import.meta.url) {
  main(process.argv.slice(2)).then((code) => process.exit(code));
}
