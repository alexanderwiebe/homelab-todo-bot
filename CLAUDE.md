# homelab-todo-bot

Telegram bot for a homelab todo list. Lists live as markdown checkboxes in the Obsidian vault at `~/vaults/Bitovi/Tasks/Homelab/*.md` (outside this repo, so they version with the vault, not with this code). The bot answers "what's outstanding" queries directly, and gates any actual work behind an approval step using Claude Code's own `--permission-mode plan` / `--resume` mechanism — see `agent_runner.py`.

## Architecture

```
bot.py        long-polls Telegram, routes messages
todo_store.py reads ~/vaults/Bitovi/Tasks/Homelab/*.md (bot never writes to these — only the approved agent does)
agent_runner.py  claude CLI subprocess calls: plan / revise / execute
intent.py     free-text -> {action, list} via a fast tool-free claude call
state.py      per-chat pending_plan state (state.json)
```

## Safety — do not relax without a deliberate decision

- `--add-dir` is scoped via `CLAUDE_ADD_DIRS` in `.env` — keep it narrow (`vaults/Bitovi/Tasks/Homelab` + `docker`, not the whole vault and not `~`).
- `--allowedTools` is explicitly restricted to `Bash,Read,Edit,Write,Grep,Glob` — no `WebFetch`/`WebSearch`, no MCP tools.
- Execute phase uses `--permission-mode acceptEdits`, never `--dangerously-skip-permissions`. `acceptEdits` still respects `--add-dir`/`--allowedTools`; skip-permissions does not.
- Every incoming Telegram message is checked against `TELEGRAM_CHAT_ID` before any processing. Unauthorized senders are dropped silently.
- The bot writes list files directly *only* for additive, low-risk operations: creating a new list (`/newlist`) and appending a new item (`/add`), via `todo_store.create_list`/`add_item`. Checking off or otherwise modifying existing items still goes through the Claude agent + human approval (`/work`) — that path is not relaxed.

## Patterns borrowed from `~/ai-briefing/`

- Raw `urllib.request` Telegram client (no `python-telegram-bot`), long-polling `getUpdates`.
- `.env` parsing: manual `K=V` parser, real env vars override file values.
- `subprocess.run([...], capture_output=True, text=True, timeout=..., env={**os.environ, "TERM": "dumb"})` for `claude` CLI calls.
