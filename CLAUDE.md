# homelab-todo-bot

Telegram bot for a homelab todo list. Lists live as markdown checkboxes in `lists/*.md`. The bot answers "what's outstanding" queries directly, and gates any actual work behind an approval step using Claude Code's own `--permission-mode plan` / `--resume` mechanism — see `agent_runner.py`.

## Architecture

```
bot.py        long-polls Telegram, routes messages
todo_store.py reads lists/*.md (bot never writes to these — only the approved agent does)
agent_runner.py  claude CLI subprocess calls: plan / revise / execute
intent.py     free-text -> {action, list} via a fast tool-free claude call
state.py      per-chat pending_plan state (state.json)
```

## Safety — do not relax without a deliberate decision

- `--add-dir` is scoped via `CLAUDE_ADD_DIRS` in `.env` — keep it narrow (`homelab-todo-bot` + `docker`, not `~`).
- `--allowedTools` is explicitly restricted to `Bash,Read,Edit,Write,Grep,Glob` — no `WebFetch`/`WebSearch`, no MCP tools.
- Execute phase uses `--permission-mode acceptEdits`, never `--dangerously-skip-permissions`. `acceptEdits` still respects `--add-dir`/`--allowedTools`; skip-permissions does not.
- Every incoming Telegram message is checked against `TELEGRAM_CHAT_ID` before any processing. Unauthorized senders are dropped silently.
- The bot itself never edits `lists/*.md` — only the Claude agent does, only after a human "approve" reply.

## Patterns borrowed from `~/ai-briefing/`

- Raw `urllib.request` Telegram client (no `python-telegram-bot`), long-polling `getUpdates`.
- `.env` parsing: manual `K=V` parser, real env vars override file values.
- `subprocess.run([...], capture_output=True, text=True, timeout=..., env={**os.environ, "TERM": "dumb"})` for `claude` CLI calls.
