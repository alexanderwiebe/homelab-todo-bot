"""Per-chat pending-plan state, persisted as JSON (mirrors ai-briefing's state.json)."""

import json
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).parent / "state.json"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"chats": {}}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"chats": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_pending_plan(chat_id) -> dict | None:
    state = load_state()
    return state.get("chats", {}).get(str(chat_id), {}).get("pending_plan")


def set_pending_plan(chat_id, list_name: str, session_id: str) -> None:
    state = load_state()
    chats = state.setdefault("chats", {})
    chats[str(chat_id)] = {
        "pending_plan": {
            "list": list_name,
            "session_id": session_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "awaiting_approval",
        }
    }
    save_state(state)


def clear_pending_plan(chat_id) -> None:
    state = load_state()
    chats = state.setdefault("chats", {})
    if str(chat_id) in chats:
        chats[str(chat_id)]["pending_plan"] = None
        save_state(state)
