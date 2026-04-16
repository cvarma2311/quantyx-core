import services.ai.semantic_runtime as runtime


def test_join_constraints_filter_restricted_and_excluded_edges() -> None:
    state = {
        "refinements": {
            "join_rules": [
                {
                    "artifact_json": {
                        "rule_type": "join_restriction",
                        "left_table": "Fact_Sales",
                        "right_table": "Dim_Reference",
                        "allowed": False,
                    }
                },
                {
                    "artifact_json": {
                        "rule_type": "reference_table_usage",
                        "table": "Dim_Label",
                        "usage": "labels_only",
                    }
                },
            ]
        }
    }

    constraints = runtime.semantic_join_constraints(state)
    allowed, removed = runtime.apply_join_constraints_to_edges(
        [
            {"left_table": "fact_sales", "right_table": "dim_reference"},
            {"left_table": "fact_sales", "right_table": "dim_label"},
            {"left_table": "fact_sales", "right_table": "dim_customer"},
        ],
        constraints,
    )

    assert len(removed) == 2
    assert allowed == [{"left_table": "fact_sales", "right_table": "dim_customer"}]


def test_merge_semantic_glossary_overrides_column_annotation() -> None:
    state = {
        "refinements": {
            "column_annotations": [
                {
                    "artifact_json": {
                        "column": "ship_to_id",
                        "business_label": "Ship-To Customer",
                        "description": "Business customer identifier",
                    }
                }
            ]
        }
    }

    merged = runtime.merge_semantic_glossary(
        [{"term": "Old Ship To", "normalized_term": "ship_to_id", "definition": "old"}],
        state,
    )

    assert merged == [
        {
            "term": "Ship-To Customer",
            "normalized_term": "ship_to_id",
            "definition": "Business customer identifier",
            "synonyms": ["ship_to_id", "Ship-To Customer"],
            "abbreviations": [],
            "source": "semantic_refinement",
        }
    ]


def test_semantic_interpretation_context_collects_refinement_payloads() -> None:
    state = {
        "refinements": {
            "interpretation_rules": [{"artifact_json": {"rule": "Ignore weekend dips"}}],
            "metric_overrides": [{"artifact_json": {"metric_name": "growth_rate"}}],
            "chart_guidance": [{"artifact_json": {"guidance": "Prefer trends"}}],
            "business_context": [{"artifact_json": {"text": "Use commercial context"}}],
        }
    }

    context = runtime.semantic_interpretation_context(state)

    assert context["interpretation_rules"] == [{"rule": "Ignore weekend dips"}]
    assert context["metric_refinements"] == [{"metric_name": "growth_rate"}]
    assert context["chart_guidance"] == [{"guidance": "Prefer trends"}]
    assert context["business_context"] == [{"text": "Use commercial context"}]
