"""Minimal client for the Vikunja REST API (/api/v1).

Endpoints and payloads follow the server's own OpenAPI spec (/api/v1/docs.json),
checked against v2.3.0.
"""

from __future__ import annotations

from typing import Any

import aiohttp


class VikunjaApiError(Exception):
    """Vikunja answered, but reported a failure or sent something unexpected."""


class VikunjaConnectionError(VikunjaApiError):
    """Vikunja could not be reached."""


class VikunjaAuthError(VikunjaApiError):
    """The API token was rejected, or lacks a permission the call needs."""


class VikunjaApiClient:
    """Talks to a Vikunja server with an API token."""

    def __init__(
        self, session: aiohttp.ClientSession, url: str, api_token: str
    ) -> None:
        self._session = session
        self.url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_token}"}
        # Replaced by the server's public URL once /info has been read.
        self.frontend_url = self.url

    def task_url(self, task_id: int) -> str:
        return f"{self.frontend_url}/tasks/{task_id}"

    def project_url(self, project_id: int) -> str:
        return f"{self.frontend_url}/projects/{project_id}"

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        payload: Any = None,
        auth: bool = True,
    ) -> tuple[Any, int]:
        """Return the decoded body and the x-pagination-total-pages header."""
        try:
            async with self._session.request(
                method,
                f"{self.url}/api/v1{path}",
                params=params,
                json=payload,
                headers=self._headers if auth else None,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json(content_type=None)
                pages = int(resp.headers.get("x-pagination-total-pages", 1))
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            raise VikunjaConnectionError(
                f"Cannot reach Vikunja at {self.url}: {err}"
            ) from err
        except ValueError as err:
            raise VikunjaApiError(f"Invalid JSON from {path}") from err

        if resp.status >= 400:
            message = (data.get("message") if isinstance(data, dict) else None) or (
                f"HTTP {resp.status} from {method} {path}"
            )
            if resp.status in (401, 403):
                raise VikunjaAuthError(message)
            raise VikunjaApiError(message)
        return data, pages

    async def _get_all(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """GET a paginated list, following x-pagination-total-pages."""
        params = {**(params or {}), "per_page": 50}
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            data, pages = await self._request("GET", path, {**params, "page": page})
            if not isinstance(data, list):
                raise VikunjaApiError(f"Expected a list from {path}")
            items.extend(data)
            if page >= pages or not data:
                return items
            page += 1

    async def get_info(self) -> dict[str, Any]:
        """GET /info (no auth) and remember the frontend URL for links."""
        data, _ = await self._request("GET", "/info", auth=False)
        if not isinstance(data, dict) or "version" not in data:
            raise VikunjaApiError("/info does not look like Vikunja")
        if frontend := data.get("frontend_url"):
            self.frontend_url = frontend.rstrip("/")
        return data

    async def get_user(self) -> dict[str, Any] | None:
        """GET /user. API tokens can't always read this, so failures give None."""
        try:
            data, _ = await self._request("GET", "/user")
        except VikunjaApiError:
            return None
        return data if isinstance(data, dict) and data.get("id") else None

    async def get_projects(self) -> list[dict[str, Any]]:
        """GET /projects: every project the token's user can see, unarchived."""
        return await self._get_all("/projects")

    async def get_tasks(
        self, filter_expr: str | None = None, search: str | None = None
    ) -> list[dict[str, Any]]:
        """GET /tasks across all projects. See https://vikunja.io/docs/filters."""
        params: dict[str, Any] = {"sort_by": "id", "order_by": "asc"}
        if filter_expr:
            params["filter"] = filter_expr
        if search:
            params["s"] = search
        return await self._get_all("/tasks", params)

    async def get_task(self, task_id: int) -> dict[str, Any]:
        """GET /tasks/{id}."""
        data, _ = await self._request("GET", f"/tasks/{task_id}")
        return data

    async def create_task(self, project_id: int, task: dict[str, Any]) -> dict[str, Any]:
        """PUT /projects/{id}/tasks."""
        data, _ = await self._request(
            "PUT", f"/projects/{project_id}/tasks", payload=task
        )
        return data

    async def update_task(self, task_id: int, **fields: Any) -> dict[str, Any]:
        """POST /tasks/{id}.

        Vikunja replaces the whole task (omitted fields are cleared), so this
        re-reads the task and sends it back with only `fields` changed.
        """
        task = await self.get_task(task_id)
        data, _ = await self._request(
            "POST", f"/tasks/{task_id}", payload={**task, **fields}
        )
        return data

    async def delete_task(self, task_id: int) -> None:
        """DELETE /tasks/{id}."""
        await self._request("DELETE", f"/tasks/{task_id}")

    async def get_labels(self) -> list[dict[str, Any]]:
        """GET /labels."""
        return await self._get_all("/labels")

    async def set_task_labels(self, task_id: int, labels: list[dict[str, Any]]) -> None:
        """POST /tasks/{id}/labels/bulk: replace the task's labels."""
        await self._request(
            "POST", f"/tasks/{task_id}/labels/bulk", payload={"labels": labels}
        )

    async def add_comment(self, task_id: int, comment: str) -> dict[str, Any]:
        """PUT /tasks/{id}/comments."""
        data, _ = await self._request(
            "PUT", f"/tasks/{task_id}/comments", payload={"comment": comment}
        )
        return data
