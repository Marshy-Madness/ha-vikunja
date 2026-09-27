"""Convert Vikunja's task fields to and from what Home Assistant uses."""

from __future__ import annotations

from datetime import datetime
from html import escape, unescape
import re
from typing import Any

from homeassistant.util import dt as dt_util

# Vikunja has no null dates; unset ones come back as the zero time.
_ZERO_DATE_PREFIX = "0001-01-01"

_BLOCK_END_RE = re.compile(r"</(p|div|li|h[1-6]|blockquote|pre)>|<br\s*/?>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_date(value: str | None) -> datetime | None:
    """A Vikunja timestamp as a local datetime, or None if unset."""
    if not value or value.startswith(_ZERO_DATE_PREFIX):
        return None
    if (parsed := dt_util.parse_datetime(value)) is None:
        return None
    return dt_util.as_local(parsed)


def format_date(value: datetime | None) -> str | None:
    """A datetime as Vikunja expects it; None clears the date."""
    return None if value is None else dt_util.as_utc(value).isoformat()


def html_to_text(value: str | None) -> str:
    """Plain text from a description or comment written in Vikunja's editor."""
    if not value:
        return ""
    text = _TAG_RE.sub("", _BLOCK_END_RE.sub("\n", value))
    return re.sub(r"\n{3,}", "\n\n", unescape(text)).strip()


def text_to_html(value: str) -> str:
    """Plain text as paragraphs for Vikunja's editor."""
    paragraphs = re.split(r"\n\s*\n", value.strip())
    return "".join(
        f"<p>{'<br>'.join(escape(line) for line in p.splitlines())}</p>"
        for p in paragraphs
        if p.strip()
    )


def project_paths(projects: list[dict[str, Any]]) -> dict[int, str]:
    """Project id -> "Parent / Child" title."""
    by_id = {p["id"]: p for p in projects}
    paths: dict[int, str] = {}

    def path(project: dict[str, Any], depth: int = 0) -> str:
        parent = by_id.get(project.get("parent_project_id") or 0)
        if parent is None or depth > 10:
            return project["title"]
        return f"{path(parent, depth + 1)} / {project['title']}"

    for project in projects:
        paths[project["id"]] = path(project)
    return paths


def public_task(
    task: dict[str, Any], frontend_url: str, paths: dict[int, str]
) -> dict[str, Any]:
    """Task fields worth exposing as state attributes or service responses."""
    due = parse_date(task.get("due_date"))
    done_at = parse_date(task.get("done_at"))
    return {
        "id": task["id"],
        "identifier": task.get("identifier") or None,
        "title": task.get("title"),
        "description": html_to_text(task.get("description")) or None,
        "project_id": task.get("project_id"),
        "project": paths.get(task.get("project_id", 0)),
        "done": task.get("done", False),
        "done_at": done_at.isoformat() if done_at else None,
        "due_date": due.isoformat() if due else None,
        "priority": task.get("priority", 0),
        "percent_done": task.get("percent_done", 0),
        "labels": [label["title"] for label in task.get("labels") or []],
        "assignees": [user["username"] for user in task.get("assignees") or []],
        "is_favorite": task.get("is_favorite", False),
        "repeating": bool(task.get("repeat_after") or task.get("repeat_mode")),
        "url": f"{frontend_url}/tasks/{task['id']}",
    }
