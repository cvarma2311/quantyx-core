"""
LLM-based context enrichment.

Takes raw user-provided context text (any format) and produces a structured
business analytics brief that chart and metric agents can reason over effectively.
"""
from __future__ import annotations

import logging
import os

from services.ai.config import Settings

logger = logging.getLogger(__name__)

_ENRICH_SYSTEM_PROMPT = """\
You are a senior business analytics architect. Your job is to read raw business context
provided by a customer and rewrite it as a structured analytics brief that an AI chart
generation system can use to produce meaningful dashboards.

The customer may have written the context as bullet points, SQL comments, data dictionary
entries, or conversational notes — in any style or quality.

Your output MUST follow this exact structure (use these section headers verbatim):

DOMAIN OVERVIEW
One paragraph describing what this dataset/system is about and what business process it tracks.

KEY DIMENSIONS
A bulleted list of fields that should be used as chart breakdowns and categories.
For each dimension:
- Field name and table (e.g. alerts.product_code)
- Human-readable label (e.g. "Product Type")
- If numeric/coded: include the decode mapping (e.g. 2811000 = MS / Petrol)
- Never list primary keys, UUIDs, or raw identifier fields as dimensions.

KEY METRICS
A bulleted list of measurable KPIs. For each metric:
- Metric name
- How to compute it (SQL expression or description)
- Which table(s) it comes from

FILTERS & SCOPE
Any default filters, validity conditions, or data quality rules that should always be applied
(e.g. exclude cancelled records, scope to a specific business unit).

DERIVED / COMPUTED FIELDS
Any fields that need CASE/WHEN decoding, grouping, or expression-based transformation before use.
Include the SQL expression.

BUSINESS QUESTIONS
5 to 8 analytical questions this data can answer, written as plain English questions a
business manager would ask. Do NOT say "create a chart for X" — write actual questions.
These drive the chart generation system to pick appropriate chart types automatically.

RULES
- Be concise within each section.
- Do not invent fields or metrics not present or inferable from the context.
- If the context is sparse, work with what is given — do not hallucinate.
- Do not include any commentary outside these sections.
"""


def enrich_context_text(settings: Settings, raw_text: str) -> str | None:
    """
    Run an LLM call to convert raw user context into a structured business analytics brief.
    Returns the enriched text, or None if enrichment fails (raw_text is preserved regardless).
    """
    if not raw_text or not raw_text.strip():
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        model = os.getenv("CONTEXT_ENRICHMENT_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _ENRICH_SYSTEM_PROMPT},
                {"role": "user", "content": f"Here is the raw business context provided by the customer:\n\n{raw_text[:12000]}"},
            ],
            temperature=0.2,
            max_tokens=2000,
        )
        enriched = response.choices[0].message.content
        if enriched:
            logger.info("context_enrichment.complete | raw_len=%s enriched_len=%s", len(raw_text), len(enriched))
            return enriched.strip()
        return None
    except Exception as exc:
        logger.warning("context_enrichment.failed | err=%s", exc)
        return None