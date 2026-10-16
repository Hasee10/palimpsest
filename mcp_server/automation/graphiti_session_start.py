"""SessionStart hook: automated Graphiti memory sync for the current project.

Fires on every Claude Code session start/resume/clear, in every project, with
no manual step required to trigger it. It:
  1. Computes a per-project group_id from the project directory name.
  2. Checks whether Neo4j is reachable; if not, tells Claude to skip Graphiti
     this session and mention how to fix it if asked.
  3. Tracks the project's git HEAD commit in a local state file. Only when
     this is the first session for the project, or the codebase changed since
     the last recorded commit, does it ask Claude to (re)scan and update the
     graph -- an unchanged codebase just does a cheap memory lookup, so API
     usage isn't hit repeatedly for no reason.
  4. On a successful first-time or updated scan, Claude emits one line:
     "Successful Ideation".
"""

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

NEO4J_HOST = "127.0.0.1"
NEO4J_PORT = 7687
STATE_DIR = Path.home() / ".claude" / "graphiti" / "initialized"


def group_id_for(project_dir: str) -> str:
    name = Path(project_dir).resolve().name or "root"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower()
    return slug or "project"


def neo4j_reachable(timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((NEO4J_HOST, NEO4J_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def git_head(project_dir: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def emit(context: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    project_dir = (
        payload.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )
    group_id = group_id_for(project_dir)

    if not neo4j_reachable():
        emit(
            "Graphiti memory is configured for this project (group_id="
            f"'{group_id}') but Neo4j is not reachable on localhost:7687 right now. "
            "Skip calling any graphiti MCP tools this session. If the user asks about "
            "project memory/history, tell them to start the 'graphiti-db' instance in "
            "Neo4j Desktop first."
        )
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"{group_id}.json"
    current_head = git_head(project_dir)

    prev_state = {}
    if state_file.exists():
        try:
            prev_state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            prev_state = {}

    first_time = not prev_state
    changed = (
        current_head is not None
        and prev_state.get("git_head") != current_head
    )

    # Persist state now (deterministic bookkeeping, independent of the model's follow-through).
    state_file.write_text(
        json.dumps({"project_dir": project_dir, "git_head": current_head}),
        encoding="utf-8",
    )

    if first_time:
        emit(
            f"Graphiti memory is available (Neo4j is up). This project's group_id is "
            f"'{group_id}' -- this is the first session for this project. Automatically, "
            "as a routine startup step (briefly mention in one short line that you're "
            "initializing project memory, then proceed without needing confirmation for "
            "this routine step): (1) call the graphiti MCP server's search_memory_nodes "
            f"and search_memory_facts with group_ids=['{group_id}'] to confirm there's no "
            "existing data, (2) scan the codebase structure -- README, package manifests "
            "(package.json/pyproject.toml/requirements.txt/etc.), top-level directory "
            "layout, and main entrypoint files -- to understand the project's purpose, "
            "stack, and architecture (stay scoped to structural/summary signals rather "
            "than reading every file byte-for-byte, to conserve free-tier API quota), and "
            f"(3) call add_memory with group_id='{group_id}' to store a concise episode "
            "capturing that summary so future sessions have context. Once step (3) "
            "succeeds, output exactly one line and nothing else before continuing: "
            "Successful Ideation"
        )
    elif changed:
        emit(
            f"Graphiti memory is available (Neo4j is up). This project's group_id is "
            f"'{group_id}'. The codebase changed since the last recorded session (git HEAD "
            f"moved from {prev_state.get('git_head')!r} to {current_head!r}). Automatically, "
            "as a routine startup step (briefly mention in one short line that you're "
            "syncing project memory, then proceed without needing confirmation for this "
            "routine step): (1) call search_memory_nodes / search_memory_facts with "
            f"group_ids=['{group_id}'] to recall prior context, (2) run 'git diff --stat' "
            "against the previous commit if available and re-scan only the affected files/"
            "areas -- not the whole repo -- to keep API usage bounded, and (3) call "
            f"add_memory with group_id='{group_id}' to persist an updated summary "
            "reflecting the changes. Once step (3) succeeds, output exactly one line and "
            "nothing else before continuing: Successful Ideation"
        )
    else:
        emit(
            f"Graphiti memory is available (Neo4j is up). This project's group_id is "
            f"'{group_id}'; no codebase changes detected since last session, so skip any "
            "full rescan. Before responding to the user's first message, call "
            "search_memory_nodes and search_memory_facts with group_ids=["
            f"'{group_id}'] once to recall prior context (past decisions, preferences, "
            "in-progress work) and weave relevant findings into your responses naturally. "
            "During the session, call add_memory with group_id="
            f"'{group_id}' to persist any new durable facts, decisions, or preferences "
            "worth remembering next time -- but don't repeat the memory lookup beyond this "
            "one startup check."
        )


if __name__ == "__main__":
    main()
