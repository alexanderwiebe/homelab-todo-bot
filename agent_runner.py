"""Wraps the `claude` CLI for the plan -> approve -> execute workflow.

Three call shapes:
  start_plan()   new session, --permission-mode plan (read-only investigation)
  revise_plan()  resume same session, still plan mode, prompt = user feedback
  execute_plan() resume same session, --permission-mode acceptEdits (after "approve")

Never uses --dangerously-skip-permissions. See CLAUDE.md "Safety" section.
"""

import json
import logging
import os
import subprocess
import uuid

import todo_store

log = logging.getLogger(__name__)

CLAUDE_BIN = "claude"
PLAN_TIMEOUT = 300
EXECUTE_TIMEOUT = 1800
INTENT_TIMEOUT = 20

ALLOWED_TOOLS = "Bash,Read,Edit,Write,Grep,Glob"


def _run_claude(args: list[str], timeout: int) -> tuple[dict | None, str | None]:
    try:
        result = subprocess.run(
            [CLAUDE_BIN, *args],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "TERM": "dumb"},
        )
    except subprocess.TimeoutExpired:
        return None, f"claude CLI timed out after {timeout}s"
    except FileNotFoundError:
        return None, "claude CLI not found in PATH"

    if result.returncode != 0:
        return None, f"claude CLI error (exit {result.returncode}): {result.stderr.strip()[:500]}"
    if not result.stdout.strip():
        return None, "claude CLI returned empty output"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return None, f"claude CLI returned malformed JSON: {e}"
    if data.get("is_error"):
        return None, f"claude reported error: {str(data.get('result', ''))[:500]}"
    return data, None


def build_plan_prompt(list_name: str, user_request: str) -> str:
    raw_list = todo_store.read_raw(list_name)
    return (
        f"You are helping with a homelab todo list called '{list_name}'.\n"
        f"Current contents of lists/{list_name}.md:\n\n{raw_list}\n\n"
        f"The user asked: {user_request}\n\n"
        "Investigate what's needed and propose a concrete step-by-step plan "
        "to complete the outstanding (unchecked) item(s) relevant to this request. "
        "Do not make any changes yet — this is a planning step only. "
        "There is no interactive user available right now to approve a plan through "
        "a tool — just write the finished plan directly as your final response text, "
        "in plain language suitable for sending over Telegram. Do not mention "
        "approval tools or planning-tool mechanics in your response."
    )


def start_plan(list_name: str, user_request: str, add_dirs: list[str]) -> tuple[dict | None, str | None]:
    session_id = str(uuid.uuid4())
    prompt = build_plan_prompt(list_name, user_request)
    args = ["-p", prompt, "--permission-mode", "plan", "--output-format", "json",
             "--session-id", session_id]
    for d in add_dirs:
        args += ["--add-dir", d]
    args += ["--allowedTools", ALLOWED_TOOLS]
    data, err = _run_claude(args, PLAN_TIMEOUT)
    if err:
        return None, err
    return {"session_id": session_id, "plan_text": data["result"]}, None


def revise_plan(session_id: str, feedback: str, add_dirs: list[str]) -> tuple[dict | None, str | None]:
    args = ["-p", feedback, "--resume", session_id, "--permission-mode", "plan",
             "--output-format", "json"]
    for d in add_dirs:
        args += ["--add-dir", d]
    args += ["--allowedTools", ALLOWED_TOOLS]
    data, err = _run_claude(args, PLAN_TIMEOUT)
    if err:
        return None, err
    return {"session_id": session_id, "plan_text": data["result"]}, None


def execute_plan(session_id: str, list_name: str, add_dirs: list[str]) -> tuple[dict | None, str | None]:
    prompt = (
        "Proceed with the plan. "
        f"When you complete an item, check it off in lists/{list_name}.md "
        "by changing '- [ ]' to '- [x]' for that line. "
        "Do not check off items you did not actually complete."
    )
    args = ["-p", prompt, "--resume", session_id, "--permission-mode", "acceptEdits",
             "--output-format", "json"]
    for d in add_dirs:
        args += ["--add-dir", d]
    args += ["--allowedTools", ALLOWED_TOOLS]
    data, err = _run_claude(args, EXECUTE_TIMEOUT)
    if err:
        return None, err
    return {"summary": data["result"], "cost_usd": data.get("total_cost_usd")}, None
