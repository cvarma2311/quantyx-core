from __future__ import annotations

import uuid
from typing import Any

from services.ai.config import Settings
from services.ai.db import run_query, execute_non_query


def create_agent_run(settings: Settings, tenant_id: str, domain_id: str, status: str = "queued") -> str:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_runs (run_id, tenant_id, domain_id, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, now(), now())
        """,
        [run_id, tenant_id, domain_id, status],
    )
    return run_id


def update_agent_run_status(settings: Settings, run_id: str, status: str) -> None:
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_agent_runs
           SET status = %s,
               updated_at = now()
         WHERE run_id = %s
        """,
        [status, run_id],
    )


def append_agent_run_event(
    settings: Settings,
    run_id: str,
    agent_name: str,
    status: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
) -> str:
    event_id = f"event_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_run_events (
          event_id, run_id, agent_name, status, message, artifacts, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, now())
        """,
        [event_id, run_id, agent_name, status, message, artifacts],
    )
    return event_id


def append_plan_summary(settings: Settings, run_id: str, steps: list[str]) -> str:
    message = "Plan created: " + "; ".join(steps)
    return append_agent_chat_log(
        settings,
        run_id,
        sender="system",
        message=message,
        artifacts={"steps": steps, "status": "ready"},
    )


def list_agent_run_events(settings: Settings, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT event_id, run_id, agent_name, status, message, artifacts, created_at
          FROM public.quantyx_agent_run_events
         WHERE run_id = %s
         ORDER BY created_at ASC
         LIMIT %s
        """,
        [run_id, limit],
    )


def get_agent_run(settings: Settings, run_id: str) -> dict[str, Any] | None:
    rows = run_query(
        settings,
        """
        SELECT run_id, tenant_id, domain_id, status, created_at, updated_at
          FROM public.quantyx_agent_runs
         WHERE run_id = %s
         LIMIT 1
        """,
        [run_id],
    )
    return rows[0] if rows else None


def append_agent_chat_log(
    settings: Settings,
    run_id: str,
    sender: str,
    message: str,
    artifacts: dict[str, Any] | None = None,
) -> str:
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_agent_chat_log (
          message_id, run_id, sender, message, created_at
        )
        VALUES (%s, %s, %s, %s, now())
        """,
        [message_id, run_id, sender, message],
    )
    if artifacts is not None:
        append_agent_run_event(
            settings,
            run_id,
            sender,
            "stream",
            message,
            artifacts,
        )
    return message_id


def list_agent_chat_log(settings: Settings, run_id: str, limit: int = 200) -> list[dict[str, Any]]:
    return run_query(
        settings,
        """
        SELECT message_id, run_id, sender, message, created_at
          FROM public.quantyx_agent_chat_log
         WHERE run_id = %s
         ORDER BY created_at ASC
         LIMIT %s
        """,
        [run_id, limit],
    )
