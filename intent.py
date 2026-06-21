"""Free-text -> {action, list} classification via a single fast, tool-free claude call.

Never raises — any failure (timeout, malformed JSON, unexpected schema) falls
back to {"action": "unknown", "list": None}.
"""

import json
import logging
import re

import agent_runner

log = logging.getLogger(__name__)

INTENT_PROMPT = """You are a routing classifier for a homelab todo bot. Given a user's free-text Telegram message and a list of available todo lists, decide what they want.

Available lists: {list_names}

Respond with ONLY a single JSON object, no other text:
{{"action": "list_tasks" | "start_work" | "unknown", "list": "<one of the available lists, or null for all lists>"}}

Rules:
- "list_tasks": user wants to see outstanding/unfinished tasks (overall or for one list).
- "start_work": user wants the bot to begin working on a list (e.g. "start working on docker maintenance", "can you handle X").
- "unknown": message doesn't clearly match either, or names a list not in the available list.
- "list" must be null or exactly one of: {list_names}. Never invent a list name.

User message: {message}
"""

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)


def _extract_json(text: str):
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError("no JSON object found")
    return json.loads(m.group(0))


def classify_intent(message: str, available_lists: list[str]) -> dict:
    fallback = {"action": "unknown", "list": None}
    if not available_lists:
        return fallback

    prompt = INTENT_PROMPT.format(list_names=", ".join(available_lists), message=message)
    args = ["-p", prompt, "--output-format", "json", "--allowedTools", ""]
    data, err = agent_runner._run_claude(args, agent_runner.INTENT_TIMEOUT)
    if err:
        log.warning("intent classification failed: %s", err)
        return fallback

    try:
        parsed = _extract_json(data["result"])
    except Exception as e:
        log.warning("intent classification returned unparseable JSON: %s", e)
        return fallback

    action = parsed.get("action")
    if action not in ("list_tasks", "start_work"):
        return fallback

    lst = parsed.get("list")
    if lst is not None and lst not in available_lists:
        lst = None
    return {"action": action, "list": lst}
