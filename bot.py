#!/usr/bin/env python3
"""
Homelab Todo Bot — Telegram message listener.

Long-polls getUpdates() and routes messages:
  - slash commands (/lists, /todo, /work, /help, /cancel)
  - pending-plan replies (approve / cancel / feedback)
  - free text -> intent classification -> list_tasks | start_work | unknown
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

import agent_runner
import intent
import state
import todo_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

TELEGRAM_MAX_LEN = 4000

APPROVE_WORDS = {"approve", "yes", "y", "lgtm", "go", "do it"}
CANCEL_WORDS = {"cancel", "stop", "no", "abort"}


# ── Env loading (mirrors ai-briefing/bot.py) ───────────────────────────────
def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    env["TELEGRAM_TOKEN"] = os.environ.get("TELEGRAM_TOKEN", env.get("TELEGRAM_TOKEN", ""))
    env["TELEGRAM_CHAT_ID"] = os.environ.get("TELEGRAM_CHAT_ID", env.get("TELEGRAM_CHAT_ID", ""))
    env["CLAUDE_ADD_DIRS"] = os.environ.get("CLAUDE_ADD_DIRS", env.get("CLAUDE_ADD_DIRS", ""))
    return env


def get_add_dirs(env) -> list[str]:
    raw = env.get("CLAUDE_ADD_DIRS", "")
    dirs = [d.strip() for d in raw.split(",") if d.strip()]
    return dirs or [str(BASE_DIR)]


# ── Telegram helpers ────────────────────────────────────────────────────────
def telegram_post(token, method, payload):
    url = TELEGRAM_API.format(token=token, method=method)
    req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=35) as resp:
        return json.loads(resp.read())


def get_updates(token, offset, timeout=30):
    result = telegram_post(token, "getUpdates", {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": ["message"],
    })
    if not result.get("ok"):
        raise RuntimeError(f"getUpdates failed: {result}")
    return result.get("result", [])


def _chunk_text(text: str, max_len: int = TELEGRAM_MAX_LEN) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    remaining = text
    while len(remaining) > max_len:
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


def send_message(token, chat_id, text, retries=1):
    for chunk in _chunk_text(text):
        for attempt in range(retries + 1):
            try:
                telegram_post(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
                break
            except (URLError, OSError) as e:
                log.warning("send_message failed (attempt %d): %s", attempt + 1, e)
                if attempt < retries:
                    time.sleep(2)


# ── Command handlers ─────────────────────────────────────────────────────────
def cmd_lists(token, chat_id):
    names = todo_store.list_names()
    if not names:
        send_message(token, chat_id, "No lists yet. Add a markdown file under lists/.")
        return
    send_message(token, chat_id, "<b>Lists</b>\n" + "\n".join(f"• {n}" for n in names))


def cmd_todo(token, chat_id, arg: str | None):
    if arg and not todo_store.ensure_list_exists(arg):
        names = ", ".join(todo_store.list_names()) or "(none)"
        send_message(token, chat_id, f"⚠️ No such list: <code>{arg}</code>\nAvailable: {names}")
        return
    items = todo_store.outstanding_items(arg)
    send_message(token, chat_id, todo_store.format_outstanding(items))


def cmd_help(token, chat_id):
    send_message(token, chat_id,
        "<b>Homelab Todo Bot</b>\n"
        "/lists — show available lists\n"
        "/todo [list] — show outstanding tasks\n"
        "/work &lt;list&gt; — propose a plan to work on a list\n"
        "/cancel — discard a pending plan\n"
        "/help — this message\n\n"
        "You can also just ask in plain English, e.g. \"what's outstanding\".")


def cmd_cancel(token, chat_id):
    pending = state.get_pending_plan(chat_id)
    if not pending:
        send_message(token, chat_id, "Nothing pending.")
        return
    state.clear_pending_plan(chat_id)
    send_message(token, chat_id, "Cancelled.")


def cmd_work(token, chat_id, arg: str, add_dirs: list[str]):
    if not arg:
        send_message(token, chat_id, "Usage: /work &lt;list&gt;")
        return
    if not todo_store.ensure_list_exists(arg):
        names = ", ".join(todo_store.list_names()) or "(none)"
        send_message(token, chat_id, f"⚠️ No such list: <code>{arg}</code>\nAvailable: {names}")
        return
    if state.get_pending_plan(chat_id):
        send_message(token, chat_id,
            "⚠️ A plan is already pending approval. Reply approve/cancel/feedback first, "
            "or /cancel to discard it.")
        return

    send_message(token, chat_id, f"🔍 Planning for <b>{arg}</b>... (this can take a few minutes)")
    result, err = agent_runner.start_plan(arg, f"Start working on the list '{arg}'.", add_dirs)
    if err:
        send_message(token, chat_id, f"❌ Claude CLI error: {err}")
        return
    state.set_pending_plan(chat_id, arg, result["session_id"])
    send_message(token, chat_id,
        f"<b>Plan for {arg}</b>\n\n{result['plan_text']}\n\n"
        "Reply <b>approve</b> to execute, give feedback to revise, or /cancel.")


# ── Pending-plan reply triage ─────────────────────────────────────────────────
def handle_plan_reply(token, chat_id, text, pending, add_dirs):
    normalized = text.strip().lower()
    list_name = pending["list"]
    session_id = pending["session_id"]

    if normalized in APPROVE_WORDS:
        send_message(token, chat_id, f"⚙️ Executing plan for <b>{list_name}</b>...")
        result, err = agent_runner.execute_plan(session_id, list_name, add_dirs)
        if err:
            send_message(token, chat_id,
                f"⚠️ Execution error: {err}\n"
                f"It may have partially completed. Session: <code>{session_id}</code>")
            return
        state.clear_pending_plan(chat_id)
        send_message(token, chat_id, f"✅ <b>Done</b>\n\n{result['summary']}")
        return

    if normalized in CANCEL_WORDS:
        state.clear_pending_plan(chat_id)
        send_message(token, chat_id, "Cancelled.")
        return

    # treat as feedback -> revise the same session
    send_message(token, chat_id, "🔄 Revising plan...")
    result, err = agent_runner.revise_plan(session_id, text, add_dirs)
    if err:
        send_message(token, chat_id, f"❌ Claude CLI error: {err}")
        return
    send_message(token, chat_id,
        f"<b>Revised plan for {list_name}</b>\n\n{result['plan_text']}\n\n"
        "Reply <b>approve</b> to execute, give feedback to revise again, or /cancel.")


# ── Intent dispatch ────────────────────────────────────────────────────────────
def dispatch_intent(token, chat_id, parsed, add_dirs):
    action = parsed["action"]
    if action == "list_tasks":
        cmd_todo(token, chat_id, parsed["list"])
    elif action == "start_work":
        if not parsed["list"]:
            names = ", ".join(todo_store.list_names()) or "(none)"
            send_message(token, chat_id, f"Which list? Available: {names}")
            return
        cmd_work(token, chat_id, parsed["list"], add_dirs)
    else:
        send_message(token, chat_id,
            "🤔 Not sure what you'd like. Try /help for commands, "
            "or ask something like \"what's outstanding\".")


# ── Top-level message handler ───────────────────────────────────────────────────
def dispatch_command(token, chat_id, text, add_dirs):
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else None

    if cmd == "/lists":
        cmd_lists(token, chat_id)
    elif cmd == "/todo":
        cmd_todo(token, chat_id, arg)
    elif cmd == "/work":
        cmd_work(token, chat_id, arg, add_dirs)
    elif cmd == "/help" or cmd == "/start":
        cmd_help(token, chat_id)
    elif cmd == "/cancel":
        cmd_cancel(token, chat_id)
    else:
        send_message(token, chat_id, f"Unknown command: {cmd}\nTry /help.")


def handle_message(token, chat_id, text, expected_chat_id, add_dirs):
    if str(chat_id) != str(expected_chat_id):
        log.warning("Ignoring message from unauthorized chat_id=%s", chat_id)
        return

    text = text.strip()
    if not text:
        return

    if text.startswith("/"):
        dispatch_command(token, chat_id, text, add_dirs)
        return

    pending = state.get_pending_plan(chat_id)
    if pending:
        handle_plan_reply(token, chat_id, text, pending, add_dirs)
        return

    parsed = intent.classify_intent(text, todo_store.list_names())
    dispatch_intent(token, chat_id, parsed, add_dirs)


# ── Main polling loop ───────────────────────────────────────────────────────────
def main():
    env = load_env()
    token = env.get("TELEGRAM_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    add_dirs = get_add_dirs(env)

    if not token or not chat_id:
        log.error("TELEGRAM_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        sys.exit(1)

    log.info("Starting — long-polling for messages (add_dirs=%s)", add_dirs)

    offset = 0
    while True:
        try:
            updates = get_updates(token, offset, timeout=30)
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message")
                if msg and "text" in msg:
                    handle_message(token, msg["chat"]["id"], msg["text"], chat_id, add_dirs)
        except Exception as e:
            log.warning("Poll error: %s — retrying in 5s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
