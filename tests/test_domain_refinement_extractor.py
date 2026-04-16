from services.ai.domain_refinement_extractor import (
    extract_refinement_artifacts,
    validate_refinement_artifact,
)


def _artifact(artifacts: list[dict], artifact_type: str) -> dict:
    return next(item for item in artifacts if item["artifact_type"] == artifact_type)


def test_extracts_hierarchy_from_business_context_text() -> None:
    artifacts = extract_refinement_artifacts(
        {
            "refinement_kind": "business_context",
            "source_text": "Use hierarchy country > state > district > location > site",
            "source_payload_json": {},
        }
    )

    hierarchy = _artifact(artifacts, "hierarchy_override")["artifact_json"]
    assert hierarchy["levels"] == ["country", "state", "district", "location", "site"]
    assert validate_refinement_artifact("hierarchy_override", hierarchy) == ("valid", [])


def test_extracts_column_annotation_from_text() -> None:
    artifacts = extract_refinement_artifacts(
        {
            "refinement_kind": "column_annotation",
            "source_text": "fact_transactions.business_entity_id means customer-facing business identifier.",
            "source_payload_json": {},
        }
    )

    annotation = _artifact(artifacts, "column_annotation")["artifact_json"]
    assert annotation["table"] == "fact_transactions"
    assert annotation["column"] == "business_entity_id"
    assert annotation["display_priority"] == "high"
    assert validate_refinement_artifact("column_annotation", annotation) == ("valid", [])


def test_extracts_metric_refinement_from_growth_text() -> None:
    artifacts = extract_refinement_artifacts(
        {
            "refinement_kind": "metric_refinement",
            "source_text": "Growth rate should compare to prior month, not prior day.",
            "source_payload_json": {},
        }
    )

    metric = _artifact(artifacts, "metric_refinement")["artifact_json"]
    assert metric["metric_name"] == "growth_rate"
    assert metric["formula"] == "month_over_month_growth"
    assert metric["grain"] == "month"
    assert validate_refinement_artifact("metric_refinement", metric) == ("valid", [])


def test_extracts_join_restriction_from_text() -> None:
    artifacts = extract_refinement_artifacts(
        {
            "refinement_kind": "join_rule",
            "source_text": "Do not join fact_transactions to external_reference.",
            "source_payload_json": {},
        }
    )

    rule = _artifact(artifacts, "join_rule")["artifact_json"]
    assert rule["rule_type"] == "join_restriction"
    assert rule["left_table"] == "fact_transactions"
    assert rule["right_table"] == "external_reference"
    assert rule["allowed"] is False
    assert validate_refinement_artifact("join_rule", rule) == ("valid", [])


def test_context_question_answer_can_derive_hierarchy() -> None:
    artifacts = extract_refinement_artifacts(
        {
            "refinement_kind": "context_question_answer",
            "source_text": "",
            "source_payload_json": {
                "question_id": "preferred_drill_path",
                "group_id": "hierarchy_and_grain",
                "answer_text": "zone > region > sales_area > distributor",
                "maps_to": ["hierarchy_override"],
            },
        }
    )

    answer = _artifact(artifacts, "context_question_answer")["artifact_json"]
    hierarchy = _artifact(artifacts, "hierarchy_override")["artifact_json"]
    assert answer["question_id"] == "preferred_drill_path"
    assert hierarchy["levels"] == ["zone", "region", "sales_area", "distributor"]


def test_schema_validation_rejects_unknown_hierarchy_level() -> None:
    status, errors = validate_refinement_artifact(
        "hierarchy_override",
        {"levels": ["zone", "unknown_region"]},
        {"available": True, "columns": {"zone"}, "tables": set(), "columns_by_table": {}, "metrics": set()},
    )

    assert status == "invalid"
    assert errors == [{"field": "levels", "message": "unknown column 'unknown_region' for this semantic scope"}]


def test_schema_validation_checks_table_scoped_columns() -> None:
    context = {
        "available": True,
        "tables": {"fact_transactions"},
        "columns": {"business_entity_id"},
        "columns_by_table": {"fact_transactions": {"business_entity_id"}},
        "metrics": set(),
    }

    assert validate_refinement_artifact(
        "column_annotation",
        {"table": "fact_transactions", "column": "business_entity_id", "description": "Business identifier"},
        context,
    ) == ("valid", [])

    status, errors = validate_refinement_artifact(
        "column_annotation",
        {"table": "fact_transactions", "column": "not_a_column", "description": "Missing"},
        context,
    )

    assert status == "invalid"
    assert errors == [
        {
            "field": "column",
            "message": "unknown column 'not_a_column' on table 'fact_transactions' for this semantic scope",
        }
    ]


def test_schema_validation_checks_metric_references_when_registry_context_exists() -> None:
    context = {
        "available": True,
        "tables": set(),
        "columns": set(),
        "columns_by_table": {},
        "metrics": {"total_volume"},
    }

    assert validate_refinement_artifact(
        "metric_refinement",
        {"metric_name": "total_volume", "description": "Use monthly grain"},
        context,
    ) == ("valid", [])

    status, errors = validate_refinement_artifact(
        "metric_refinement",
        {"metric_name": "unknown_metric", "description": "Use monthly grain"},
        context,
    )

    assert status == "invalid"
    assert errors == [{"field": "metric_name", "message": "unknown metric 'unknown_metric' for this semantic scope"}]


def test_schema_validation_is_skipped_when_context_is_unavailable() -> None:
    status, errors = validate_refinement_artifact(
        "column_annotation",
        {"table": "missing_table", "column": "missing_column", "description": "Still structurally valid"},
        {"available": False, "tables": set(), "columns": set(), "columns_by_table": {}, "metrics": set()},
    )

    assert status == "valid"
    assert errors == []
