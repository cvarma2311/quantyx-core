from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LangSmithEventForwarder:
    """Best-effort forwarder for agent events to LangSmith.

    This is intentionally optional and non-blocking:
    - disabled if langsmith sdk or env config is missing
    - all errors are swallowed after debug logging
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.project = (
            os.getenv("LANGSMITH_PROJECT")
            or os.getenv("LANGCHAIN_PROJECT")
            or "default"
        )
        self.enabled = os.getenv("LANGSMITH_TRACING", "").lower() in {"1", "true", "yes"}
        self._client = None
        self._parent_run_id = None

        if not self.enabled:
            return
        try:
            # Optional dependency; keep import local and guarded.
            from langsmith import Client  # type: ignore

            self._client = Client()
        except Exception as exc:  # noqa: BLE001
            logger.warning("langsmith forwarder disabled: %s", exc)
            self.enabled = False
            return

        try:
            parent_id = uuid.uuid4()
            self._parent_run_id = parent_id
            self._client.create_run(
                name="agentic_run",
                run_type="chain",
                id=parent_id,
                project_name=self.project,
                inputs={"run_id": run_id},
                start_time=_utc_now(),
                tags=["agentic", "progress-forwarded"],
            )
        except Exception:  # noqa: BLE001
            logger.exception("langsmith parent run creation failed")
            self.enabled = False

    def on_event(self, payload: dict[str, Any]) -> None:
        if not self.enabled or not self._client:
            return
        try:
            event_run_id = uuid.uuid4()
            self._client.create_run(
                name=f"agentic.{payload.get('agent_name')}",
                run_type="tool",
                id=event_run_id,
                parent_run_id=self._parent_run_id,
                project_name=self.project,
                inputs={
                    "run_id": payload.get("run_id"),
                    "agent_name": payload.get("agent_name"),
                    "status": payload.get("status"),
                    "message": payload.get("message"),
                },
                outputs={"artifacts": payload.get("artifacts") or {}},
                start_time=_utc_now(),
                end_time=_utc_now(),
                tags=["agentic", "event", str(payload.get("status") or "unknown")],
            )
        except Exception:  # noqa: BLE001
            logger.exception("langsmith event forward failed")

    def close(self, status: str = "completed", error: str | None = None) -> None:
        if not self.enabled or not self._client or not self._parent_run_id:
            return
        try:
            kwargs: dict[str, Any] = {
                "run_id": self._parent_run_id,
                "end_time": _utc_now(),
                "outputs": {"status": status},
            }
            if error:
                kwargs["error"] = error
            self._client.update_run(**kwargs)
        except Exception:  # noqa: BLE001
            logger.exception("langsmith parent run update failed")

