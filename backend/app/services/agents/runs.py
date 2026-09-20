"""Step-by-step record of every agent graph run (shown as a timeline in the UI)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from app.repositories.automation import AgentRunRepository
from app.services.automation.communications import now


class RunRecorder:
    """Records one graph run. With no repository it records nothing (unit tests, scripts)."""

    def __init__(self, repo: Optional[AgentRunRepository], organization_id: str, graph: str,
                 input: dict[str, Any], created_by: Optional[str] = None):
        self.repo, self.org_id = repo, organization_id
        self.doc = {"graph": graph, "status": "running", "input": input, "steps": [], "output": None,
                    "created_by": created_by}
        self.id: Optional[str] = None

    @classmethod
    def attach(cls, repo: AgentRunRepository, run: dict) -> "RunRecorder":
        """Continue recording into an existing run (used when a paused run resumes)."""
        recorder = cls(repo, str(run["organization_id"]), run["graph"], run.get("input") or {}, run.get("created_by"))
        recorder.id = str(run["id"])
        recorder.doc["steps"] = list(run.get("steps") or [])
        return recorder

    async def start(self) -> "RunRecorder":
        if self.repo:
            self.id = (await self.repo.create(self.org_id, self.doc))["id"]
        return self

    @asynccontextmanager
    async def step(self, agent: str, action: str) -> AsyncIterator[dict[str, Any]]:
        """`with recorder.step(...) as s: s["summary"] = "..."`. Errors are recorded, then re-raised."""
        entry: dict[str, Any] = {"agent": agent, "action": action, "summary": "", "started_at": now(), "error": None}
        try:
            yield entry
        except Exception as exc:
            entry["error"] = str(exc)
            raise
        finally:
            entry["finished_at"] = now()
            self.doc["steps"].append(entry)
            if self.repo and self.id:
                await self.repo.raw_update(self.org_id, self.id, {"$push": {"steps": entry}})

    async def save_state(self, state: dict[str, Any]) -> None:
        """Persist the run's own state so a paused run can be resumed later."""
        if self.repo and self.id:
            await self.repo.update(self.org_id, self.id, {"state": state})
        self.doc["state"] = state

    async def finish(self, status: str, output: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self.doc.update(status=status, output=output)
        if self.repo and self.id:
            return await self.repo.update(self.org_id, self.id, {"status": status, "output": output})
        return self.doc
