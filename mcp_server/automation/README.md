# Session-start automation

`graphiti_session_start.py` is a [Claude Code `SessionStart` hook](https://docs.claude.com/en/docs/claude-code/hooks)
that keeps a project's Graphiti memory in sync without any manual step to trigger it. It fires on every session
start, resume, and clear, in every project, and decides on its own what to do:

| Situation | Behavior |
|---|---|
| Neo4j not reachable on `localhost:7687` | Tells the assistant to skip Graphiti this session; no retries, no blocking. |
| First session for a project (no state file yet) | Scans the codebase's structural signals (README, manifests, entrypoints, directory layout — not every file) and stores a summary episode. Emits `Successful Ideation` on success. |
| Returning session, `git HEAD` unchanged since last visit | Does one cheap memory lookup to recall prior context. No rescan, no extra API calls. |
| Returning session, `git HEAD` changed since last visit | Re-scans only the diff (`git diff --stat` against the previous commit) and updates the graph. Emits `Successful Ideation` on success. |

## Why git HEAD, not a timer or a full rescan every time

Free-tier LLM and embedding keys (this setup uses Gemini + Voyage) have real rate and quota limits. Re-ingesting
an entire codebase on every session start would burn through that budget in days for no benefit, since most
sessions touch a repo that hasn't changed since the last one. Tracking the last-seen commit hash per project
(`~/.claude/graphiti/initialized/<group_id>.json`) means a full or partial rescan only happens when the code
actually moved — not on a schedule, and not "just in case."

## Why it isn't silent

An earlier version of this hook instructed the assistant not to narrate what it was doing before acting — fully
invisible automation. Claude Code's own permission layer rejected that version: automation that hides its own
actions from the user is auditable by no one, which defeats the point of staying in control of what's touching
your API quota and your data. This version keeps every automatic trigger (no manual step needed to invoke it)
but surfaces a short note when it's syncing memory, instead of operating invisibly.

## Setup

1. Copy this script to `~/.claude/hooks/graphiti_session_start.py` (or point directly at this path in the repo).
2. Register it in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "python /path/to/graphiti_session_start.py" }
        ]
      }
    ]
  }
}
```

3. Make sure Neo4j is running before starting a session — the hook detects and reports if it isn't, but won't
   start it for you.

Scoped to Claude Code today. Any MCP-compatible client can reach the same Graphiti server, but only Claude Code
has an equivalent hook mechanism to trigger this automatically; other clients would need their own equivalent, or
manual invocation of the `graphiti` MCP tools.
