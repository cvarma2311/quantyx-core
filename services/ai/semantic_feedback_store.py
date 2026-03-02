from __future__ import annotations

import uuid

from services.ai.config import Settings
from services.ai.db import execute_non_query, run_query


def create_semantic_feedback(
    settings: Settings,
    tenant_id: str,
    domain_id: str,
    edge_id: str,
    action: str,
    delta_confidence: float | None,
    notes: str | None,
) -> dict:
    feedback_id = f"fb_{uuid.uuid4().hex[:12]}"
    execute_non_query(
        settings,
        """
        INSERT INTO public.quantyx_semantic_feedback (
          feedback_id, tenant_id, domain_id, edge_id, action, delta_confidence, notes, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, now())
        """,
        [feedback_id, tenant_id, domain_id, edge_id, action, delta_confidence, notes],
    )
    return {
        "feedback_id": feedback_id,
        "tenant_id": tenant_id,
        "domain_id": domain_id,
        "edge_id": edge_id,
        "action": action,
        "delta_confidence": delta_confidence,
        "notes": notes,
    }


def list_semantic_feedback(settings: Settings, tenant_id: str, domain_id: str | None) -> list[dict]:
    if domain_id:
        return run_query(
            settings,
            """
            SELECT feedback_id, tenant_id, domain_id, edge_id, action, delta_confidence, notes, created_at
              FROM public.quantyx_semantic_feedback
             WHERE tenant_id = %s AND domain_id = %s
             ORDER BY created_at DESC
            """,
            [tenant_id, domain_id],
        )
    return run_query(
        settings,
        """
        SELECT feedback_id, tenant_id, domain_id, edge_id, action, delta_confidence, notes, created_at
          FROM public.quantyx_semantic_feedback
         WHERE tenant_id = %s
         ORDER BY created_at DESC
        """,
        [tenant_id],
    )


def apply_semantic_feedback(settings: Settings, edge_id: str, delta_confidence: float | None) -> None:
    if delta_confidence is None:
        return
    execute_non_query(
        settings,
        """
        UPDATE public.quantyx_semantic_edges
           SET confidence = COALESCE(confidence, 0) + %s,
               updated_at = now()
         WHERE edge_id = %s
        """,
        [delta_confidence, edge_id],
    )
