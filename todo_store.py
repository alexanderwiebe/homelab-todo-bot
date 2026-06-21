"""Read-only access to markdown todo lists stored in the Obsidian vault.

The bot never writes to these files itself — only the approved Claude
agent does, and only after a human "approve" reply. See agent_runner.py.
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).parent
LISTS_DIR = Path("/home/alexander/vaults/Bitovi/Tasks/Homelab")

CHECKBOX_RE = re.compile(r'^\s*-\s\[(?P<mark>[ xX])\]\s(?P<text>.*)$')


def list_names() -> list[str]:
    if not LISTS_DIR.exists():
        return []
    return sorted(p.stem for p in LISTS_DIR.glob("*.md"))


def list_path(name: str) -> Path:
    if not name or "/" in name or ".." in name:
        raise ValueError(f"invalid list name: {name!r}")
    path = (LISTS_DIR / f"{name}.md").resolve()
    if LISTS_DIR.resolve() not in path.parents:
        raise ValueError(f"invalid list name: {name!r}")
    return path


def ensure_list_exists(name: str) -> bool:
    try:
        return list_path(name).is_file()
    except ValueError:
        return False


def read_raw(name: str) -> str:
    path = list_path(name)
    if not path.is_file():
        return ""
    return path.read_text()


def read_items(name: str) -> list[dict]:
    items = []
    for line_no, line in enumerate(read_raw(name).splitlines(), start=1):
        m = CHECKBOX_RE.match(line)
        if m:
            items.append({
                "line_no": line_no,
                "text": m.group("text"),
                "checked": m.group("mark").lower() == "x",
            })
    return items


def outstanding_items(name: str | None = None) -> dict[str, list[str]]:
    names = [name] if name else list_names()
    result = {}
    for n in names:
        unchecked = [item["text"] for item in read_items(n) if not item["checked"]]
        if unchecked:
            result[n] = unchecked
    return result


def format_outstanding(items_by_list: dict[str, list[str]]) -> str:
    if not items_by_list:
        return "✅ Nothing outstanding."
    parts = []
    for name, texts in items_by_list.items():
        lines = "\n".join(f"• {t}" for t in texts)
        parts.append(f"<b>{name}</b>\n{lines}")
    return "\n\n".join(parts)
