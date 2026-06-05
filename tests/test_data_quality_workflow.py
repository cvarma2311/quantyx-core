from __future__ import annotations

import json
import importlib
import pytest
import zipfile
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from services.ai import dashboards_store
from services.ai import data_quality_api_payloads as dq_api_payloads
from services.ai import data_quality_anomalies as dq_anomalies
from services.ai import data_quality_dashboard as dq_dashboard
from services.ai import data_quality_duplicates as dq_duplicates
from services.ai import data_quality_enrichment as dq_enrichment
from services.ai import data_quality_enrichment_questions as dq_enrichment_questions
from services.ai import data_quality_evidence as dq_evidence
from services.ai import data_quality_freshness as dq_freshness
from services.ai import data_quality_issues as dq_issues
from services.ai import data_quality_orchestrator as dq_orchestrator
from services.ai import data_quality_rule_review as dq_rule_review
from services.ai import data_quality_remediation as dq_remediation
from services.ai import data_quality_report as dq_report
from services.ai import data_quality_rules as dq_rules
from services.ai import data_quality_stages as dq_stages
from services.ai import data_quality_store as dq_store
from services.ai import data_quality_trust as dq_trust
from services.ai import data_quality_trends as dq_trends
from services.ai import data_quality_workspace as dq_workspace
from services.ai import glossary as dq_glossary
from services.ai import agentic_store
from services.ai import agentic_agents
from services.ai import chart_interactions
from services.ai import hierarchy_store


def test_dashboard_store_json_default_serializes_decimal() -> None:
    payload = {
        "chart_plan": [
            {
                "title": "Quality Trends",
                "rows": [{"metric_name": "trust_score", "current_value_num": Decimal("82.4")}],
            }
        ]
    }

    serialized = json.dumps(payload, default=dashboards_store._json_default)

    assert '"current_value_num": 82.4' in serialized


def test_get_dashboard_endpoint_includes_chart_drilldown_metadata(monkeypatch) -> None:
    from services.ai import catalog as ai_catalog

    monkeypatch.setattr(ai_catalog, "load_catalog_with_registry", lambda settings, path: {})
    api_main = importlib.import_module("services.api.main")
    monkeypatch.setattr(
        api_main,
        "_ds_get_with_charts",
        lambda settings, dashboard_id, tenant_id=None: {
            "dashboard_id": dashboard_id,
            "tenant_id": "TAS_DEMO_006",
            "domain_id": "retail_fuel_monitoring",
            "name": "TAS Alert Volume and Status Overview",
            "dashboard_type": "system",
            "status": "active",
            "run_id": "run_06ee70bd7780",
            "latest_refresh_id": None,
            "quality_score": 0.9,
            "quality_gate_passed": True,
            "description": None,
            "created_by": None,
            "created_at": None,
            "updated_at": None,
            "chart_plan": [],
            "charts": [
                {
                    "entry_id": "dc_1",
                    "chart_id": "chart_1",
                    "position": 0,
                    "title_override": None,
                    "title": "Total Alert Count by Location",
                    "chart_type": "bar",
                    "chart_source": "agentic_run",
                    "status": "ready",
                    "sql": "SELECT location_name AS category, COUNT(*) AS value FROM alerts GROUP BY 1",
                    "question": "Total alerts by location",
                    "query_payload": {
                        "table": "alerts",
                        "dimensions": ["location_name"],
                        "metrics": ["total_alert_count"],
                    },
                    "chart_payload": {"chart": {"type": "XYChart"}},
                    "chart_data": [{"category": "Plant A", "value": 5}],
                    "rows_json": [{"category": "Plant A", "value": 5}],
                    "insight_text": "Test insight",
                    "narrative_text": "Test narrative",
                    "interaction_context_json": {
                        "source_scope": {"schema_name": "public", "base_table": "alerts", "base_view": "fact_alerts"},
                        "query_shape": {
                            "metric_expressions": [{"metric_id": "total_alert_count", "expression": None}],
                            "group_dimensions": ["location_name"],
                            "time_dimension": None,
                            "query_grain": None,
                            "chart_intent": "breakdown",
                        },
                        "filters": [],
                        "current_level": "location_name",
                        "hierarchy_bindings": {
                            "location_name": {
                                "hierarchy_id": "override_retail_fuel_monitoring_tas_operational_hierarchy",
                                "current_level_id": "location_name",
                                "next_level_id": "equipment_type",
                            }
                        },
                        "available_filter_fields": [{"field": "location_name", "kind": "dimension", "label": "Location Name"}],
                        "available_drilldowns": [
                            {
                                "hierarchy_id": "override_retail_fuel_monitoring_tas_operational_hierarchy",
                                "source_level_id": "location_name",
                                "target_level_id": "equipment_type",
                                "action_type": "drill_down",
                                "label": "View by Equipment Type",
                            }
                        ],
                        "available_dimension_navigation": [
                            {
                                "hierarchy_id": "override_retail_fuel_monitoring_tas_operational_hierarchy",
                                "source_level_id": "location_name",
                                "target_level_id": "equipment_type",
                                "action_type": "drill_down",
                                "label": "View by Equipment Type",
                            }
                        ],
                        "suggested_drilldowns": [
                            {
                                "hierarchy_id": "override_retail_fuel_monitoring_tas_operational_hierarchy",
                                "source_level_id": "location_name",
                                "target_level_id": "equipment_type",
                                "action_type": "drill_down",
                                "label": "View by Equipment Type",
                            }
                        ],
                        "lineage": {
                            "root_chart_id": "chart_1",
                            "parent_chart_id": None,
                            "interaction_type": None,
                        },
                    },
                    "drill_hierarchy_id": "override_retail_fuel_monitoring_tas_operational_hierarchy",
                    "drill_level_id": "location_name",
                    "parent_chart_id": None,
                    "root_chart_id": "chart_1",
                    "added_by": "DashboardAgent",
                    "added_at": None,
                }
            ],
        },
    )
    monkeypatch.setattr(
        api_main,
        "list_business_hierarchies",
        lambda settings, tenant_id, domain_id=None: [],
    )

    response = api_main.get_dashboard_endpoint("db_test")

    assert response.charts
    chart = response.charts[0]
    assert chart["drill_hierarchy_id"] == "override_retail_fuel_monitoring_tas_operational_hierarchy"
    assert chart["drill_level_id"] == "location_name"
    assert chart["available_drilldowns"]
    assert chart["available_drilldowns"][0]["target_level_id"] == "equipment_type"
    assert chart["suggested_drilldowns"]


def test_build_chart_interaction_context_uses_physical_category_column_for_hierarchy_binding() -> None:
    hierarchies = [
        {
            "hierarchy_id": "override_retail_fuel_monitoring_tas_asset_hierarchy",
            "preferred": True,
            "confidence_score": 0.96,
            "levels_json": [
                {"level_id": "bu", "column": "bu", "label": "Bu"},
                {"level_id": "location_name", "column": "location_name", "label": "Location Name"},
                {"level_id": "equipment_type", "column": "equipment_type", "label": "Equipment Type"},
                {"level_id": "device_type", "column": "device_type", "label": "Device Type"},
            ],
        }
    ]

    interaction_context = chart_interactions.build_chart_interaction_context(
        chart_row={
            "chart_id": "chart_1",
            "title": "Alert Count by Equipment Type",
            "query_payload": {
                "metrics": ["equipment_type_alert_count"],
                "dimensions": ["category"],
                "category_column": "equipment_type",
                "table": "alerts",
                "chart": "bar",
            },
            "sql": 'SELECT t."equipment_type" AS category, COUNT(*) AS "equipment_type_alert_count" FROM "public"."fact_alerts" t GROUP BY t."equipment_type"',
            "rows_json": [{"category": "BCU", "equipment_type_alert_count": 10}],
        },
        hierarchies=hierarchies,
    )

    assert interaction_context["current_level"] == "equipment_type"
    assert interaction_context["hierarchy_bindings"]["equipment_type"]["hierarchy_id"] == "override_retail_fuel_monitoring_tas_asset_hierarchy"
    assert interaction_context["available_drilldowns"]
    assert interaction_context["available_drilldowns"][0]["target_level_id"] == "device_type"


def test_is_data_quality_workflow_by_builtin_pack() -> None:
    assert dq_orchestrator.is_data_quality_workflow("data_quality_observability", {}) is True


def test_is_data_quality_workflow_by_explicit_mode() -> None:
    assert dq_orchestrator.is_data_quality_workflow("some_domain", {"workflow_mode": "data_quality"}) is True


def test_quality_run_id_for_is_stable() -> None:
    assert dq_store.quality_run_id_for("run_abc123") == "dqrun_abc123"


def test_merge_phase58_summary_preserves_stage_and_lineage_fields() -> None:
    merged = dq_orchestrator._merge_phase58_summary(
        {
            "dataset_stage_count": 7,
            "join_stage_count": 3,
            "filter_stage_count": 2,
            "lineage_edge_count": 14,
            "final_dataset_row_count": 120,
            "final_dataset_readiness_status": "ready",
        },
        {
            "profiled_tables": 4,
            "failed_rule_count": 0,
        },
    )

    assert merged["profiled_tables"] == 4
    assert merged["dataset_stage_count"] == 7
    assert merged["join_stage_count"] == 3
    assert merged["filter_stage_count"] == 2
    assert merged["lineage_edge_count"] == 14
    assert merged["final_dataset_row_count"] == 120
    assert merged["final_dataset_readiness_status"] == "ready"


def test_upsert_quality_artifacts_from_profiling_flattens_tables_and_columns(monkeypatch) -> None:
    calls: list[tuple[str, list[object]]] = []
    monkeypatch.setattr(dq_store, "execute_non_query", lambda settings, sql, params: calls.append((sql, params)))
    profiling = {
        "tables": [
            {
                "name": "customer",
                "row_count": 10,
                "quality_summary": {
                    "row_count": 10,
                    "table_trust_score": 72.5,
                    "table_completeness_score": 80.0,
                    "freshness_lag_days": 2,
                    "duplicate_risk_columns_count": 1,
                },
                "column_profiles": [
                    {
                        "name": "email",
                        "data_type": "text",
                        "null_count": 2,
                        "null_pct": 20.0,
                        "blank_count": 1,
                        "blank_pct": 10.0,
                        "distinct_count": 8,
                        "distinct_ratio": 0.8,
                        "completeness_score": 80.0,
                        "is_sparse": False,
                        "is_very_sparse": False,
                    }
                ],
            }
        ]
    }

    result = dq_store.upsert_quality_artifacts_from_profiling(
        object(),
        quality_run_id="dqrun_1",
        run_id="run_1",
        tenant_id="tenant",
        domain_id="data_quality_observability",
        connection_id="conn",
        database_name="db",
        schema_name="public",
        profiling_json=profiling,
    )

    assert result == {"tables": 1, "columns": 1}
    assert len(calls) == 2
    assert calls[0][1][8] == "customer"
    assert calls[0][1][14] == "warning"
    assert calls[1][1][9] == "email"


def test_extract_quality_rules_from_context_resolves_known_patterns() -> None:
    schema_graph = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "customer_id"},
                    {"name": "amount"},
                ],
            },
            {"name": "customer", "columns": [{"name": "customer_id"}, {"name": "email"}]},
        ]
    }

    rules = dq_rules.extract_quality_rules_from_context(
        "orders.customer_id must exist in customer.customer_id. Customer email must be present and valid. Orders amount cannot be negative.",
        schema_graph,
    )

    assert [rule["rule_type"] for rule in rules] == [
        "referential_integrity",
        "not_null",
        "email_pattern",
        "numeric_min",
    ]
    assert rules[0]["table_name"] == "orders"
    assert rules[0]["reference_table"] == "customer"
    assert rules[1]["table_name"] == "customer"
    assert rules[3]["column_name"] == "amount"


def test_extract_quality_rules_from_customer_data_context_covers_nine_rules() -> None:
    schema_graph = {
        "tables": [
            {
                "name": "customer_data",
                "columns": [
                    {"name": "customer_id"},
                    {"name": "email"},
                    {"name": "phone_number"},
                    {"name": "account_number"},
                    {"name": "dob"},
                    {"name": "created_date"},
                    {"name": "account_type"},
                    {"name": "balance"},
                ],
            }
        ]
    }

    rules = dq_rules.extract_quality_rules_from_context(
        (
            "customer_data.customer_id must be present and not null. "
            "customer_data.email must be present and not null. "
            "customer_data.phone_number must be present and not null. "
            "customer_data.customer_id must be unique. "
            "Each customer_data.account_number must map to only one customer_data.customer_id. "
            "customer_data.email must match a basic email pattern. "
            "Customer age must be between 18 and 80, calculated using customer_data.dob and customer_data.created_date. "
            "customer_data.account_type must be one of Savings, Current, or Business. "
            "customer_data.balance must not be negative."
        ),
        schema_graph,
    )

    assert len(rules) == 9
    assert [rule["rule_type"] for rule in rules] == [
        "not_null",
        "not_null",
        "not_null",
        "unique",
        "custom_sql",
        "email_pattern",
        "custom_sql",
        "allowed_values",
        "numeric_min",
    ]
    assert rules[4]["column_name"] == "account_number"
    assert rules[6]["column_name"] == "dob"
    assert rules[7]["condition_json"]["allowed_values"] == ["Savings", "Current", "Business"]


def test_extract_context_parses_explicit_hierarchy_definition_lines() -> None:
    schema_graph = {
        "tables": [
            {
                "name": "alerts",
                "columns": [
                    {"name": "bu"},
                    {"name": "location_name"},
                    {"name": "alert_section"},
                    {"name": "equipment_type"},
                    {"name": "device_type"},
                    {"name": "interlock_name"},
                ],
            }
        ]
    }

    extracted = agentic_agents.extract_context(
        SimpleNamespace(openai_api_key=None),
        (
            "Hierarchy Definition:\n"
            "- hierarchy_name: tas_operational_hierarchy\n"
            "- levels: bu > location_name > alert_section > equipment_type > device_type > interlock_name\n"
        ),
        schema_graph,
    )

    assert extracted["hierarchy_hints"] == [
        "bu > location_name > alert_section > equipment_type > device_type > interlock_name"
    ]


def test_hierarchy_backed_chart_candidates_prefer_hierarchy_levels() -> None:
    profiling = {
        "tables": [
            {
                "name": "alerts",
                "categorical_columns": [
                    "terminal_plant_name",
                    "servicing_plant_name",
                    "location_name",
                    "equipment_type",
                    "device_type",
                    "interlock_name",
                ],
                "time_columns": ["created_at"],
                "sample_values": {
                    "terminal_plant_name": ["", "A", "B"],
                    "servicing_plant_name": ["", "X", "Y"],
                    "location_name": ["LOC1", "LOC2", "LOC3"],
                    "equipment_type": ["BCU", "Tank", "ESD"],
                    "device_type": ["Radar", "Valve", "Pump"],
                    "interlock_name": ["I1", "I2", "I3"],
                },
                "column_profiles": [
                    {"name": "terminal_plant_name", "blank_pct": 95.0, "null_pct": 0.0, "distinct_count": 20, "distinct_ratio": 0.0001, "completeness_score": 100.0},
                    {"name": "servicing_plant_name", "blank_pct": 94.0, "null_pct": 0.0, "distinct_count": 20, "distinct_ratio": 0.0001, "completeness_score": 100.0},
                    {"name": "location_name", "blank_pct": 1.0, "null_pct": 0.0, "distinct_count": 15, "distinct_ratio": 0.01, "completeness_score": 100.0},
                    {"name": "equipment_type", "blank_pct": 2.0, "null_pct": 0.0, "distinct_count": 8, "distinct_ratio": 0.005, "completeness_score": 100.0},
                    {"name": "device_type", "blank_pct": 3.0, "null_pct": 0.0, "distinct_count": 10, "distinct_ratio": 0.006, "completeness_score": 100.0},
                    {"name": "interlock_name", "blank_pct": 5.0, "null_pct": 0.0, "distinct_count": 25, "distinct_ratio": 0.02, "completeness_score": 100.0},
                ],
                "candidate_keys": [],
            }
        ]
    }
    metrics = [
        {
            "metric_name": "total_alert_count",
            "base_table": "alerts",
            "formula": "COUNT(CASE WHEN bu = 'TAS' THEN 1 END)",
            "metric_intent": "volume",
            "measure_confidence": 0.95,
            "metric_source": "context_override",
            "is_executive_kpi": True,
        }
    ]
    hierarchies = [
        {
            "hierarchy_id": "override_retail_fuel_monitoring_tas_operational_hierarchy",
            "preferred": True,
            "base_scope_json": {"base_table": "alerts"},
            "levels_json": [
                {"level_id": "bu", "column": "bu", "table": "alerts"},
                {"level_id": "location_name", "column": "location_name", "table": "alerts"},
                {"level_id": "equipment_type", "column": "equipment_type", "table": "alerts"},
                {"level_id": "device_type", "column": "device_type", "table": "alerts"},
                {"level_id": "interlock_name", "column": "interlock_name", "table": "alerts"},
            ],
        }
    ]

    candidates = agentic_agents.propose_chart_candidates(
        profiling,
        metrics,
        [],
        domain_id="retail_fuel_monitoring",
        business_hierarchies=hierarchies,
    )
    selected, _diag = agentic_agents.select_charts(
        candidates,
        min_charts=4,
        max_charts=8,
        domain_id="retail_fuel_monitoring",
        business_hierarchies=hierarchies,
    )

    hierarchy_selected = [
        item for item in selected
        if str(item.get("category_column") or "") in {"location_name", "equipment_type", "device_type", "interlock_name"}
    ]

    assert hierarchy_selected
    assert any(item.get("drill_hierarchy_id") == "override_retail_fuel_monitoring_tas_operational_hierarchy" for item in hierarchy_selected)
    assert not any(str(item.get("category_column") or "") == "servicing_plant_name" for item in hierarchy_selected)


def test_rank_breakdown_columns_penalizes_blank_heavy_categories() -> None:
    table = {
        "name": "alerts",
        "categorical_columns": [
            "servicing_plant_name",
            "location_name",
            "equipment_type",
        ],
        "sample_values": {
            "servicing_plant_name": ["", "A", "B"],
            "location_name": ["LOC1", "LOC2", "LOC3"],
            "equipment_type": ["BCU", "Tank", "ESD"],
        },
        "column_profiles": [
            {"name": "servicing_plant_name", "blank_pct": 97.0, "null_pct": 0.0, "distinct_count": 25, "distinct_ratio": 0.0001, "completeness_score": 100.0},
            {"name": "location_name", "blank_pct": 1.0, "null_pct": 0.0, "distinct_count": 12, "distinct_ratio": 0.01, "completeness_score": 100.0},
            {"name": "equipment_type", "blank_pct": 2.0, "null_pct": 0.0, "distinct_count": 7, "distinct_ratio": 0.004, "completeness_score": 100.0},
        ],
        "candidate_keys": [],
    }

    ranked = agentic_agents._rank_breakdown_columns(table, domain_id="retail_fuel_monitoring")

    assert ranked.index("servicing_plant_name") > ranked.index("location_name")
    assert ranked.index("servicing_plant_name") > ranked.index("equipment_type")


def test_derive_business_hierarchies_uses_explicit_context_hierarchy_levels(monkeypatch) -> None:
    profiling = {
        "tables": [
            {
                "name": "alerts",
                "categorical_columns": [
                    "bu",
                    "location_name",
                    "alert_section",
                    "equipment_type",
                    "device_type",
                    "interlock_name",
                ],
                "columns": [
                    {"name": "bu"},
                    {"name": "location_name"},
                    {"name": "alert_section"},
                    {"name": "equipment_type"},
                    {"name": "device_type"},
                    {"name": "interlock_name"},
                ],
            }
        ]
    }
    monkeypatch.setattr(hierarchy_store, "load_hierarchy_overrides_all", lambda settings, tenant_id, domain_id: [])

    hierarchies = hierarchy_store.derive_business_hierarchies(
        SimpleNamespace(openai_api_key=None),
        tenant_id="TAS_DEMO_TEST",
        domain_id="retail_fuel_monitoring",
        profiling_stats=profiling,
        context_text=(
            "Hierarchy Definition:\n"
            "- hierarchy_name: tas_operational_hierarchy\n"
            "- levels: bu > location_name > alert_section > equipment_type > device_type > interlock_name\n"
        ),
        join_edges=[],
    )

    target = next(
        item for item in hierarchies
        if str(item.get("hierarchy_id") or "") == "override_retail_fuel_monitoring_tas_operational_hierarchy"
    )
    assert [level["level_id"] for level in target["levels_json"]] == [
        "bu",
        "location_name",
        "alert_section",
        "equipment_type",
        "device_type",
        "interlock_name",
    ]
    assert target["preferred"] is True


def test_ensure_business_hierarchies_merges_existing_and_derived(monkeypatch) -> None:
    existing = [
        {
            "hierarchy_id": "override_retail_fuel_monitoring_bu",
            "tenant_id": "TAS_DEMO_TEST",
            "domain_id": "retail_fuel_monitoring",
            "name": "BU Override",
            "base_scope_json": {"base_table": "alerts"},
            "levels_json": [
                {"level_id": "bu", "column": "bu", "table": "alerts"},
                {"level_id": "location_name", "column": "location_name", "table": "alerts"},
            ],
            "preferred": True,
        }
    ]
    derived = [
        {
            "hierarchy_id": "override_retail_fuel_monitoring_tas_operational_hierarchy",
            "tenant_id": "TAS_DEMO_TEST",
            "domain_id": "retail_fuel_monitoring",
            "name": "tas_operational_hierarchy",
            "base_scope_json": {"base_table": "alerts"},
            "levels_json": [
                {"level_id": "location_name", "column": "location_name", "table": "alerts"},
                {"level_id": "equipment_type", "column": "equipment_type", "table": "alerts"},
                {"level_id": "device_type", "column": "device_type", "table": "alerts"},
            ],
            "preferred": False,
        }
    ]
    persisted: list[dict] = []
    call_count = {"list": 0}

    def fake_list(_settings, _tenant_id, _domain_id):
        call_count["list"] += 1
        if call_count["list"] == 1:
            return list(existing)
        return list(persisted)

    monkeypatch.setattr(hierarchy_store, "list_business_hierarchies", fake_list)
    monkeypatch.setattr(hierarchy_store, "derive_business_hierarchies", lambda *args, **kwargs: list(derived))
    monkeypatch.setattr(hierarchy_store, "_llm_rank_hierarchies", lambda *args, **kwargs: None)
    monkeypatch.setattr(hierarchy_store, "_apply_hierarchy_ranking", lambda items, ranking: items)
    monkeypatch.setattr(
        hierarchy_store,
        "upsert_business_hierarchies",
        lambda _settings, items: persisted.extend(items),
    )

    result = hierarchy_store.ensure_business_hierarchies(
        SimpleNamespace(openai_api_key=None),
        tenant_id="TAS_DEMO_TEST",
        domain_id="retail_fuel_monitoring",
        profiling_stats={"tables": []},
        context_text="",
        join_edges=[],
    )

    ids = {str(item.get("hierarchy_id") or "") for item in result}
    assert "override_retail_fuel_monitoring_bu" in ids
    assert "override_retail_fuel_monitoring_tas_operational_hierarchy" in ids


def test_plan_quality_rules_discards_context_blob_llm_rules_and_keeps_deterministic_controls(monkeypatch) -> None:
    schema_graph = {
        "tables": [
            {
                "name": "customer_data",
                "columns": [
                    {"name": "customer_id"},
                    {"name": "email"},
                    {"name": "phone_number"},
                    {"name": "account_number"},
                    {"name": "dob"},
                    {"name": "created_date"},
                    {"name": "account_type"},
                    {"name": "balance"},
                ],
            }
        ]
    }
    context_text = (
        "Domain: Data Quality Observability for customer_data.\n\n"
        "Table in scope:\n- customer_data: customer master records.\n\n"
        "Validation rules to apply on customer_data:\n\n"
        "1. customer_data.customer_id must be present and not null.\n"
        "2. customer_data.email must be present and not null.\n"
        "3. customer_data.phone_number must be present and not null.\n"
        "4. customer_data.customer_id must be unique.\n"
        "5. Each customer_data.account_number must map to only one customer_data.customer_id.\n"
        "6. customer_data.email must match a basic email pattern.\n"
        "7. Customer age must be between 18 and 80, calculated using customer_data.dob and customer_data.created_date.\n"
        "8. customer_data.account_type must be one of Savings, Current, or Business.\n"
        "9. customer_data.balance must not be negative.\n"
    )

    monkeypatch.setattr(
        dq_rules,
        "business_context_validation_planner_tool",
        lambda **kwargs: {
            "planner_mode": "llm",
            "validation_controls": [
                {"control_key": "ctrl_1", "source_text": "customer_data.customer_id must be present and not null."},
                {"control_key": "ctrl_2", "source_text": "customer_data.email must be present and not null."},
                {"control_key": "ctrl_3", "source_text": "customer_data.phone_number must be present and not null."},
                {"control_key": "ctrl_4", "source_text": "customer_data.customer_id must be unique."},
                {"control_key": "ctrl_5", "source_text": "Each customer_data.account_number must map to only one customer_data.customer_id."},
                {"control_key": "ctrl_6", "source_text": "customer_data.email must match a basic email pattern."},
                {"control_key": "ctrl_7", "source_text": "Customer age must be between 18 and 80, calculated using customer_data.dob and customer_data.created_date."},
                {"control_key": "ctrl_8", "source_text": "customer_data.account_type must be one of Savings, Current, or Business."},
                {"control_key": "ctrl_9", "source_text": "customer_data.balance must not be negative."},
            ],
        },
    )
    monkeypatch.setattr(
        dq_rules,
        "_extract_quality_rules_with_llm",
        lambda settings, text, schema_graph, validation_controls=None: [
            {
                "rule_type": "not_null",
                "table_name": "customer_data",
                "column_name": "customer_id",
                "severity": "critical",
                "condition_json": {"source_text": "customer_data.customer_id must be present and not null."},
                "source": "llm_context_text",
                "confidence": 0.75,
                "status": "active",
            },
            {
                "rule_type": "not_null",
                "table_name": "customer_data",
                "column_name": "email",
                "severity": "warning",
                "condition_json": {"source_text": "customer_data.email must be present and not null."},
                "source": "llm_context_text",
                "confidence": 0.75,
                "status": "active",
            },
            {
                "rule_type": "not_null",
                "table_name": "customer_data",
                "column_name": "phone_number",
                "severity": "warning",
                "condition_json": {"source_text": "customer_data.phone_number must be present and not null."},
                "source": "llm_context_text",
                "confidence": 0.75,
                "status": "active",
            },
            {
                "rule_type": "unique",
                "table_name": "customer_data",
                "column_name": "customer_id",
                "severity": "critical",
                "condition_json": {"source_text": "customer_data.customer_id must be unique."},
                "source": "llm_context_text",
                "confidence": 0.75,
                "status": "active",
            },
            {
                "rule_type": "custom_sql",
                "table_name": "customer_data",
                "column_name": "dob",
                "severity": "warning",
                "condition_json": {
                    "source_text": context_text,
                    "validation_sql": "SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE EXTRACT(YEAR FROM AGE(CURRENT_DATE, customer_data.dob)) < 18 OR EXTRACT(YEAR FROM AGE(CURRENT_DATE, customer_data.dob)) > 80) AS violation_count FROM customer_data",
                },
                "source": "llm_context_text",
                "confidence": 0.75,
                "status": "active",
            },
        ],
    )

    plan = dq_rules.plan_quality_rules_from_context(
        context_text=context_text,
        schema_graph=schema_graph,
        settings=SimpleNamespace(openai_api_key="test-key", openai_model="gpt-4o-mini"),
    )

    labels = [dq_rules.derive_quality_rule_label(rule) for rule in plan["rules"]]

    assert len(plan["rules"]) == 9
    assert "Table in scope:" not in labels
    assert "customer_data.account_number must map to a single target" in labels
    assert "Validate customer_data.email email format" in labels
    assert "customer_data.account_type allowed values check" in labels
    assert "customer_data.balance minimum value check" in labels


def test_plan_quality_rules_compiles_missing_rules_from_validation_controls(monkeypatch) -> None:
    schema_graph = {
        "tables": [
            {
                "name": "customer_data",
                "columns": [
                    {"name": "customer_id"},
                    {"name": "email"},
                    {"name": "phone_number"},
                    {"name": "account_number"},
                    {"name": "dob"},
                    {"name": "created_date"},
                    {"name": "account_type"},
                    {"name": "balance"},
                ],
            }
        ]
    }
    context_text = Path("debug-logs/customer_data_dq_context.txt").read_text(encoding="utf-8")
    controls = [
        {"control_key": "ctrl_1", "source_text": "customer_data.customer_id must be present and not null."},
        {"control_key": "ctrl_2", "source_text": "customer_data.email must be present and not null."},
        {"control_key": "ctrl_3", "source_text": "customer_data.phone_number must be present and not null."},
        {"control_key": "ctrl_4", "source_text": "customer_data.customer_id must be unique."},
        {"control_key": "ctrl_5", "source_text": "Each customer_data.account_number must map to only one customer_data.customer_id."},
        {"control_key": "ctrl_6", "source_text": "customer_data.email must match a basic email pattern."},
        {"control_key": "ctrl_7", "source_text": "Customer age must be between 18 and 80, calculated using customer_data.dob and customer_data.created_date."},
        {"control_key": "ctrl_8", "source_text": "customer_data.account_type must be one of Savings, Current, or Business."},
        {"control_key": "ctrl_9", "source_text": "customer_data.balance must not be negative."},
    ]

    monkeypatch.setattr(
        dq_rules,
        "business_context_validation_planner_tool",
        lambda **kwargs: {"planner_mode": "llm", "validation_controls": controls},
    )
    monkeypatch.setattr(
        dq_rules,
        "_extract_quality_rules_with_llm",
        lambda settings, text, schema_graph, validation_controls=None: [
            {
                "rule_type": "custom_sql",
                "table_name": "customer_data",
                "column_name": "customer_id",
                "severity": "warning",
                "condition_json": {"source_text": context_text, "validation_sql": "SELECT 1"},
                "source": "llm_context_text",
                "confidence": 0.4,
                "status": "active",
            }
        ],
    )
    original = dq_rules._extract_quality_rules_deterministic

    def fake_extract(text: str | None, schema: dict[str, Any]) -> list[dict[str, Any]]:
        source = str(text or "").strip()
        if source == context_text.strip():
            return original(
                "\n".join(
                    [
                        "customer_data.customer_id must be present and not null.",
                        "customer_data.email must be present and not null.",
                        "customer_data.phone_number must be present and not null.",
                        "customer_data.customer_id must be unique.",
                    ]
                ),
                schema,
            )
        return original(text, schema)

    monkeypatch.setattr(dq_rules, "_extract_quality_rules_deterministic", fake_extract)

    plan = dq_rules.plan_quality_rules_from_context(
        context_text=context_text,
        schema_graph=schema_graph,
        settings=SimpleNamespace(openai_api_key="test-key", openai_model="gpt-4o-mini"),
    )

    labels = [dq_rules.derive_quality_rule_label(rule) for rule in plan["rules"]]

    assert len(plan["rules"]) == 9
    assert "Table in scope:" not in labels
    assert "customer_data.account_number must map to a single target" in labels
    assert "Validate customer_data.email email format" in labels
    assert "customer_data.account_type allowed values check" in labels
    assert "customer_data.balance minimum value check" in labels


def test_derive_quality_rule_label_for_custom_sql_patterns() -> None:
    assert dq_rules.derive_quality_rule_label(
        {
            "rule_type": "custom_sql",
            "table_name": "roaming_settlement_data",
            "condition_json": {
                "validation_sql": "SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE charged_amount < 0) AS violation_count FROM roaming_settlement_data"
            },
        }
    ) == "Negative charged amount in roaming_settlement_data"
    assert dq_rules.derive_quality_rule_label(
        {
            "rule_type": "custom_sql",
            "table_name": "billing_cdr_data",
            "condition_json": {
                "validation_sql": "SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE billing_status NOT IN ('BILLED', 'PENDING')) AS violation_count FROM billing_cdr_data"
            },
        }
    ) == "Unexpected billing status in billing_cdr_data"


def test_business_context_validation_planner_tool_extracts_atomic_controls() -> None:
    schema_graph = {
        "tables": [
            {"name": "network_cdr_data", "columns": [{"name": "call_id"}, {"name": "msisdn"}]},
            {"name": "mediation_data", "columns": [{"name": "cdr_id"}, {"name": "rating_flag"}]},
            {"name": "billing_cdr_data", "columns": [{"name": "billing_status"}, {"name": "cdr_id"}]},
        ]
    }
    result = dq_rules.business_context_validation_planner_tool(
        context_text=(
            "1. Network CDR to Mediation reconciliation\n"
            "- Reconcile network_cdr_data to mediation_data.\n"
            "- Key controls to evaluate:\n"
            "  - records present in network_cdr_data but missing in mediation_data\n"
            "  - duplicate records in either layer\n"
            "2. Mediation to Billing reconciliation\n"
            "- Reconcile mediation_data to billing_cdr_data.\n"
            "- Key controls to evaluate:\n"
            "  - unrated usage where mediation event should be billable but no billing row exists\n"
        ),
        schema_graph=schema_graph,
    )
    controls = result["validation_controls"]
    assert result["control_count"] >= 3
    assert any("missing in mediation_data" in str(item.get("source_text")) for item in controls)
    assert any("duplicate records in either layer" in str(item.get("source_text")) for item in controls)
    assert any("billable but no billing row exists" in str(item.get("source_text")) for item in controls)


def test_plan_quality_rules_from_context_returns_coverage() -> None:
    schema_graph = {
        "tables": [
            {"name": "billing_cdr_data", "columns": [{"name": "billing_status"}]},
        ]
    }
    plan = dq_rules.plan_quality_rules_from_context(
        context_text=(
            "Mediation to Billing reconciliation\n"
            "- Key controls to evaluate:\n"
            "  - rows not flagged for rating when business logic suggests they should be\n"
            "  - invalid billing status values\n"
        ),
        schema_graph=schema_graph,
    )
    assert "validation_controls" in plan
    assert "rules" in plan
    assert "rule_coverage" in plan
    assert plan["rule_coverage"]["validation_control_count"] >= 2


def test_infer_stage_plan_tool_builds_sources_joins_filters_and_final_stage() -> None:
    plan = dq_stages.infer_stage_plan_tool(
        schema_graph={
            "tables": [
                {"name": "orders", "columns": [{"name": "customer_id"}, {"name": "status"}]},
                {"name": "customer", "columns": [{"name": "customer_id"}, {"name": "status"}]},
            ]
        },
        context_text=(
            "orders.customer_id must exist in customer.customer_id. "
            "Only customer.status = active. "
            "Filter to recent orders."
        ),
    )

    assert plan["source_table_count"] == 2
    assert plan["workflow_type"] in {"multi_table_quality", "reconciliation"}
    assert isinstance(plan["shared_key_inferences"], list)
    assert isinstance(plan["join_strategies"], list)
    assert plan["join_stage_count"] >= 1
    assert plan["filter_stage_count"] >= 1
    assert plan["joins"][0]["join_artifact_id"].startswith("dqjoin_")
    assert plan["stages"][0]["stage_id"].startswith("dqstage_")
    assert plan["stages"][0]["stage_type"] == "source_profile"
    assert plan["stages"][-1]["stage_type"] == "final_projection"


def test_domain_context_interpreter_and_join_strategy_tools_return_structured_contracts() -> None:
    schema_graph = {
        "tables": [
            {"name": "billing_cdr_data", "columns": [{"name": "rating_timestamp"}, {"name": "msisdn"}]},
            {"name": "roaming_settlement_data", "columns": [{"name": "event_time"}, {"name": "msisdn"}]},
        ]
    }
    interpreted = dq_stages.domain_context_interpreter_tool(
        schema_graph=schema_graph,
        context_text=(
            "Billing to Roaming Settlement reconciliation\n"
            "- Reconcile billing_cdr_data to roaming_settlement_data.\n"
            "- Core match intent: billing rating_timestamp to roaming_settlement_data event_time inside the reconciliation window.\n"
            "- Match window: 900 seconds.\n"
        ),
    )
    shared_keys = dq_stages.shared_key_inference_tool(
        schema_graph=schema_graph,
        interpreted_context=interpreted,
    )
    asymmetries = dq_stages.asymmetry_detection_tool(
        interpreted_context=interpreted,
        shared_key_inferences=shared_keys,
    )
    strategies = dq_stages.join_strategy_builder_tool(
        shared_key_inferences=shared_keys,
        asymmetry_detections=asymmetries,
    )

    assert interpreted["workflow_type"] == "reconciliation"
    assert interpreted["join_intents"][0]["left_table"] == "billing_cdr_data"
    assert ("billing_cdr_data", "roaming_settlement_data") == (
        shared_keys[0]["left_table"],
        shared_keys[0]["right_table"],
    )
    assert any(item["left_key"] == "rating_timestamp" and item["right_key"] == "event_time" for item in shared_keys[0]["match_keys"])
    assert any(item["asymmetry_type"] == "temporal_window" and item["tolerance_seconds"] == 900 for item in asymmetries[0]["asymmetries"])
    assert strategies[0]["strategy_type"] == "windowed_temporal_join"


def test_infer_stage_plan_tool_builds_cdr_reconciliation_joins() -> None:
    plan = dq_stages.infer_stage_plan_tool(
        schema_graph={
            "tables": [
                {"name": "network_cdr_data", "columns": [{"name": "call_id"}, {"name": "msisdn"}, {"name": "event_time"}]},
                {"name": "mediation_data", "columns": [{"name": "call_id"}, {"name": "msisdn"}, {"name": "cdr_id"}]},
                {"name": "billing_cdr_data", "columns": [{"name": "cdr_id"}, {"name": "rating_timestamp"}, {"name": "msisdn"}]},
                {"name": "roaming_settlement_data", "columns": [{"name": "event_time"}, {"name": "msisdn"}, {"name": "partner_id"}]},
            ]
        },
        context_text=(
            "Network CDR to Mediation reconciliation\n"
            "- Reconcile network_cdr_data to mediation_data.\n"
            "- Core match intent: same call/session identity using call_id, msisdn, and time logic.\n"
            "Mediation to Billing reconciliation\n"
            "- Reconcile mediation_data to billing_cdr_data.\n"
            "- Core match intent: mediation usage event to billing row by cdr_id and billing eligibility.\n"
            "Billing to Roaming Settlement reconciliation\n"
            "- Reconcile billing_cdr_data to roaming_settlement_data.\n"
            "- Core match intent: billing rating_timestamp to roaming_settlement_data event_time inside the reconciliation window, with subscriber correlation and partner context.\n"
        ),
    )

    join_pairs = {
        (join["left_table"], join["left_key"], join["right_table"], join["right_key"])
        for join in (plan.get("joins") or [])
    }
    assert ("network_cdr_data", "call_id", "mediation_data", "call_id") in join_pairs
    assert ("network_cdr_data", "msisdn", "mediation_data", "msisdn") in join_pairs
    assert ("mediation_data", "cdr_id", "billing_cdr_data", "cdr_id") in join_pairs
    assert ("billing_cdr_data", "rating_timestamp", "roaming_settlement_data", "event_time") in join_pairs
    assert any(strategy["strategy_type"] == "windowed_temporal_join" for strategy in (plan.get("join_strategies") or []))
    assert plan["join_stage_count"] >= 4
    assert plan["stage_count"] >= 9
    assert plan["stages"][-1]["stage_type"] == "final_projection"


def test_compute_stage_plan_metrics_tool_measures_source_and_join_counts(monkeypatch) -> None:
    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        if 'COUNT(*) AS row_count FROM "public"."orders"' in sql:
            return [{"row_count": 12}]
        if 'COUNT(*) AS row_count FROM "public"."customer" WHERE "status"::text = %s' in sql:
            return [{"row_count": 3}]
        if 'COUNT(*) AS row_count FROM "public"."customer"' in sql:
            return [{"row_count": 5}]
        if "AS matched_row_count" in sql:
            return [{"matched_row_count": 10}]
        if 'FROM "public"."orders" l' in sql and "AS unmatched_row_count" in sql:
            return [{"unmatched_row_count": 2}]
        if 'FROM "public"."customer" r' in sql and "AS unmatched_row_count" in sql:
            return [{"unmatched_row_count": 1}]
        if "AS duplicate_match_count" in sql:
            return [{"duplicate_match_count": 3}]
        if "__right_row_ref" in sql:
            return [{"__left_row_ref": "(0,1)", "__right_row_ref": "(0,9)", "left_key_value": "C001", "right_key_value": "C001"}]
        if "__left_row_ref" in sql and "*" in sql:
            return [{"__left_row_ref": "(0,2)", "left_key_value": "C404"}]
        if "__right_row_ref" in sql and "*" in sql:
            return [{"__right_row_ref": "(0,4)", "right_key_value": "C999"}]
        if 'FROM "public"."customer" WHERE NOT ("status"::text = %s)' in sql:
            return [{"__row_ref": "(0,5)", "status": "inactive"}]
        return [{"__row_ref": "(0,1)", "customer_id": "C001"}]

    monkeypatch.setattr(dq_stages, "run_query", fake_run_query)

    plan = dq_stages.compute_stage_plan_metrics_tool(
        object(),
        scoped_conn=object(),
        schema_name="public",
        tenant_id="tenant",
        domain_id="data_quality_observability",
        stage_plan={
            "stages": [
                {
                    "stage_id": "dqstage_1",
                    "stage_seq": 1,
                    "stage_name": "source_profile_orders",
                    "stage_type": "source_profile",
                    "output_dataset": "orders",
                },
                {
                    "stage_id": "dqstage_2",
                    "stage_seq": 2,
                    "stage_name": "orders_to_customer_customer_id",
                    "stage_type": "join_validation",
                    "join": {
                        "join_artifact_id": "dqjoin_1",
                        "join_name": "orders_to_customer_customer_id",
                        "left_table": "orders",
                        "right_table": "customer",
                        "left_key": "customer_id",
                        "right_key": "customer_id",
                    },
                },
                {
                    "stage_id": "dqstage_3",
                    "stage_seq": 3,
                    "stage_name": "filter_1",
                    "stage_type": "filter",
                    "output_dataset": "customer",
                    "expression": {
                        "expression_text": "customer.status = active",
                        "parsed_filter": {"table_name": "customer", "column_name": "status", "operator": "=", "value": "active"},
                    },
                },
                {
                    "stage_id": "dqstage_4",
                    "stage_seq": 4,
                    "stage_name": "final_dataset_projection",
                    "stage_type": "final_projection",
                },
            ],
            "joins": [
                {
                    "join_artifact_id": "dqjoin_1",
                    "join_name": "orders_to_customer_customer_id",
                    "left_table": "orders",
                    "right_table": "customer",
                    "left_key": "customer_id",
                    "right_key": "customer_id",
                }
            ],
        },
    )

    assert plan["stages"][0]["output_row_count"] == 12
    assert plan["joins"][0]["matched_row_count"] == 10
    assert plan["joins"][0]["unmatched_left_row_count"] == 2
    assert plan["stages"][1]["rejected_row_count"] == 2
    assert plan["stages"][2]["output_row_count"] == 3
    assert plan["stages"][2]["rejected_row_count"] == 2
    assert plan["row_outcomes"][0]["row_lineage_id"].startswith("dqlin_")
    assert plan["lineage_edges"][0]["row_lineage_id"].startswith("dqlin_")
    assert any(item["reason_code"] == "filter_rejected" for item in plan["row_outcomes"])
    assert plan["stages"][3]["output_row_count"] == 3
    assert plan["final_dataset"]["final_row_count"] == 3
    assert plan["final_dataset"]["summary_json"]["lineage_enabled"] is True
    assert plan["final_dataset"]["summary_json"]["basis_stage"]["stage_name"] == "filter_1"
    assert plan["final_dataset"]["summary_json"]["sample_rows"][0]["customer_id"] == "C001"
    assert plan["final_dataset"]["summary_json"]["row_source"] == "live_stage_snapshot"


def test_list_agent_run_events_stage_aware_requests_latest_events(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(agentic_store, "_table_columns", lambda settings, table_name: {"stage_name", "stage_seq", "logical_event_id", "payload_compacted"})

    def _fake_run_query(settings, sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(agentic_store, "run_query", _fake_run_query)

    agentic_store.list_agent_run_events_stage_aware(object(), "run_1", limit=25)

    sql = str(captured["sql"])
    assert "ORDER BY created_at DESC" in sql
    assert "ORDER BY created_at ASC" in sql
    assert captured["params"] == ["run_1", 25]


def test_extract_quality_rules_uses_llm_first_when_available(monkeypatch) -> None:
    class Settings:
        openai_api_key = "key"
        openai_model = "model"

    monkeypatch.setenv("DATA_QUALITY_RULE_LLM_MODE", "auto")
    monkeypatch.setattr(
        dq_rules,
        "_extract_quality_rules_with_llm",
        lambda settings, text, schema, validation_controls=None: [
            {
                "rule_type": "not_null",
                "severity": "critical",
                "table_name": "customer",
                "column_name": "email",
                "condition_json": {"source": "llm"},
                "source": "llm_context_text",
                "confidence": 0.91,
                "status": "active",
            }
        ],
    )
    schema_graph = {"tables": [{"name": "customer", "columns": [{"name": "email"}]}]}

    rules = dq_rules.extract_quality_rules_from_context(
        "Customer email must be present.",
        schema_graph,
        settings=Settings(),
    )

    assert len(rules) == 1
    assert rules[0]["source"] == "llm_context_text"
    assert rules[0]["condition_json"] == {"source": "llm"}


def test_extract_quality_rules_merges_partial_llm_and_deterministic_results(monkeypatch) -> None:
    class Settings:
        openai_api_key = "key"
        openai_model = "model"

    monkeypatch.setenv("DATA_QUALITY_RULE_LLM_MODE", "auto")
    monkeypatch.setattr(
        dq_rules,
        "_extract_quality_rules_with_llm",
        lambda settings, text, schema_graph, validation_controls=None: [
            {
                "rule_type": "not_null",
                "severity": "critical",
                "table_name": "customer_data",
                "column_name": "customer_id",
                "condition_json": {"source_text": "customer_data.customer_id must be present"},
                "source": "llm_context_text",
                "confidence": 0.95,
                "status": "active",
            }
        ],
    )
    schema_graph = {"tables": [{"name": "customer_data", "columns": [{"name": "customer_id"}, {"name": "balance"}]}]}

    rules = dq_rules.extract_quality_rules_from_context(
        "customer_data.customer_id must be present. customer_data.balance must not be negative.",
        schema_graph,
        settings=Settings(),
    )

    assert [rule["rule_type"] for rule in rules] == ["not_null", "numeric_min"]


def test_build_quality_rule_execution_plan_for_referential_integrity() -> None:
    plan = dq_rules.build_quality_rule_execution_plan(
        {
            "rule_type": "referential_integrity",
            "table_name": "orders",
            "column_name": "customer_id",
            "reference_table": "customer",
            "reference_column": "customer_id",
        },
        schema_name="public",
    )

    assert plan["executor_kind"] == "deterministic_sql"
    assert "LEFT JOIN" in plan["validation_sql"]
    assert "violating_value" in plan["sample_sql"]
    assert plan["sql_preview"]["status"] == "available"
    assert plan["sql_preview"]["source"] == "deterministic_fallback"
    assert "LEFT JOIN" in str(plan["sql_preview"]["validation_sql"])


def test_build_quality_rule_execution_plan_prefers_llm_sql_preview(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_rules,
        "_build_quality_rule_sql_preview_with_llm",
        lambda settings, rule, schema_name: {
            "status": "available",
            "source": "llm",
            "validation_sql": 'SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE "email" IS NULL) AS violation_count FROM "public"."customer"',
            "sample_sql": 'SELECT * FROM "public"."customer" WHERE "email" IS NULL LIMIT 25',
            "notes": ["LLM preview"],
            "error": None,
        },
    )

    plan = dq_rules.build_quality_rule_execution_plan(
        {
            "rule_type": "not_null",
            "table_name": "customer",
            "column_name": "email",
        },
        schema_name="public",
        settings=type("Settings", (), {"openai_api_key": "key", "openai_model": "model"})(),
    )

    assert plan["sql_preview"]["source"] == "llm"
    assert "customer" in str(plan["sql_preview"]["validation_sql"])


def test_build_quality_rule_execution_plan_builds_deterministic_preview_for_date_range(monkeypatch) -> None:
    monkeypatch.setattr(dq_rules, "_build_quality_rule_sql_preview_with_llm", lambda settings, rule, schema_name: None)

    plan = dq_rules.build_quality_rule_execution_plan(
        {
            "rule_type": "date_range",
            "table_name": "customer",
            "column_name": "updated_at",
            "condition_json": {"not_future": True},
        },
        schema_name="public",
    )

    assert plan["sql_preview"]["status"] == "available"
    assert plan["sql_preview_source"] == "deterministic_fallback"
    assert "CURRENT_DATE" in str(plan["validation_sql"])


def test_build_quality_rule_execution_plan_compiles_relative_date_expression(monkeypatch) -> None:
    monkeypatch.setattr(dq_rules, "_build_quality_rule_sql_preview_with_llm", lambda settings, rule, schema_name: None)

    plan = dq_rules.build_quality_rule_execution_plan(
        {
            "rule_type": "date_range",
            "table_name": "customer",
            "column_name": "dob",
            "condition_json": {"max_date": "today - 1 day"},
        },
        schema_name="public",
    )

    assert plan["sql_preview"]["status"] == "available"
    assert "CURRENT_DATE - INTERVAL '1 day'" in str(plan["validation_sql"])


def test_classify_quality_rule_review_status_marks_low_confidence_rule_for_review() -> None:
    status = dq_rules.classify_quality_rule_review_status(
        {
            "confidence": 0.61,
            "executor_kind": "deterministic_sql",
            "execution_plan_json": {"sql_preview_status": "available"},
        },
        confidence_threshold=0.85,
    )

    assert status == "needs_review"


def test_classify_quality_rule_review_status_marks_unimplemented_rule_unsupported() -> None:
    status = dq_rules.classify_quality_rule_review_status(
        {
            "confidence": 0.99,
            "executor_kind": "unimplemented",
            "execution_plan_json": {"sql_preview_status": "preview_unavailable"},
        },
        confidence_threshold=0.85,
    )

    assert status == "unsupported"


def test_execute_date_range_supports_relative_date_expression(monkeypatch) -> None:
    calls: list[tuple[str, list[object]]] = []

    def _fake_run_query(settings, sql, params, scoped_conn=None):
        calls.append((sql, params))
        if "COUNT(*) AS checked_row_count" in sql:
            return [{"checked_row_count": 10, "violation_count": 2}]
        return [{"violating_value": "2036-11-28"}]

    monkeypatch.setattr(dq_rules, "run_query", _fake_run_query)

    result = dq_rules._execute_date_range(
        object(),
        rule={
            "table_name": "customers_dq_data",
            "column_name": "dob",
            "condition_json": {"max_date": "today - 1 day"},
        },
        schema_name="public",
        scoped_conn=None,
    )

    assert result[0] == "failed"
    assert result[1] == 10
    assert result[2] == 2
    assert all(not params for _, params in calls)
    assert "CURRENT_DATE - INTERVAL '1 day'" in calls[0][0]


def test_replace_quality_rules_persists_source_text_and_execution_plan(monkeypatch) -> None:
    calls: list[tuple[str, list[object]]] = []
    monkeypatch.setattr(dq_store, "execute_non_query", lambda settings, sql, params: calls.append((sql, params)))

    inserted = dq_store.replace_quality_rules(
        object(),
        quality_run_id="dqrun_1",
        run_id="run_1",
        tenant_id="tenant",
        domain_id="data_quality_observability",
        connection_id="conn_1",
        database_name="db_1",
        schema_name="public",
        rules=[
            {
                "rule_id": "dqr_1",
                "rule_type": "not_null",
                "severity": "critical",
                "table_name": "customer",
                "column_name": "email",
                "source_text": "Customer email must be present.",
                "executor_kind": "deterministic_sql",
                "execution_plan_json": {
                    "validation_sql": "SELECT ...",
                    "sample_sql": "SELECT ...",
                    "sql_preview": {"status": "available", "source": "deterministic_fallback", "validation_sql": "SELECT ..."},
                    "sql_preview_status": "available",
                    "sql_preview_source": "deterministic_fallback",
                },
                "condition_json": {"source_text": "Customer email must be present."},
                "source": "context_text",
                "confidence": 0.91,
                "status": "active",
            }
        ],
    )

    assert inserted == 1
    assert len(calls) == 2
    insert_params = calls[1][1]
    assert insert_params[14] == "Customer email must be present."
    assert insert_params[15] == "deterministic_sql"


def test_update_quality_rule_review_persists_review_fields(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_execute_returning_query(settings, sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return [{"rule_id": "dqr_1", "status": "active", "reviewed_by": "reviewer"}]

    monkeypatch.setattr(dq_store, "execute_returning_query", fake_execute_returning_query)

    row = dq_store.update_quality_rule_review(
        object(),
        rule_id="dqr_1",
        tenant_id="tenant",
        status="active",
        reviewed_by="reviewer",
        review_notes="approved after review",
        execution_plan_json={"sql_preview_status": "available"},
    )

    assert row["status"] == "active"
    assert captured["params"][0] == "active"
    assert captured["params"][1] == "reviewer"
    assert captured["params"][2] == "approved after review"


def test_get_quality_rule_review_queue_counts_reviewable_rules(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_rule_review,
        "list_quality_rules",
        lambda settings, tenant_id, domain_id, run_id, limit=500: [
            {"rule_id": "r1", "status": "active"},
            {"rule_id": "r2", "status": "needs_review"},
            {"rule_id": "r3", "status": "unsupported"},
        ],
    )

    result = dq_rule_review.get_quality_rule_review_queue(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
    )

    assert result["summary"]["accepted_auto_count"] == 1
    assert result["summary"]["needs_review_count"] == 1
    assert result["summary"]["unsupported_count"] == 1
    assert len(result["rules"]) == 2


def test_apply_quality_rule_review_action_approves_and_executes(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_rule_review,
        "build_quality_rule_execution_plan",
        lambda rule, schema_name, settings=None: {
            "executor_kind": "deterministic_sql",
            "validation_sql": "SELECT 1",
            "sample_sql": "SELECT 1 LIMIT 25",
            "sql_preview": {"status": "available", "source": "deterministic_fallback", "validation_sql": "SELECT 1"},
            "sql_preview_status": "available",
            "sql_preview_source": "deterministic_fallback",
        },
    )
    monkeypatch.setattr(
        dq_rule_review,
        "update_quality_rule_review",
        lambda *args, **kwargs: {"rule_id": "dqr_1", "status": kwargs["status"]},
    )
    monkeypatch.setattr(dq_rule_review, "resolve_database_credentials_cached", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        dq_rule_review,
        "execute_quality_rules",
        lambda settings, rules, schema_name, scoped_conn: {"rules_executed": 1, "results": [{"rule_id": rules[0]["rule_id"], "status": "passed"}]},
    )

    result = dq_rule_review.apply_quality_rule_review_action(
        object(),
        rule_row={
            "rule_id": "dqr_1",
            "tenant_id": "tenant",
            "connection_id": "conn_1",
            "schema_name": "public",
            "rule_type": "not_null",
            "table_name": "customer",
            "column_name": "email",
            "condition_json": {"source_text": "Customer email must be present."},
            "confidence": 0.61,
        },
        action="approve",
        reviewed_by="reviewer",
        execute_after_approval=True,
    )

    assert result["status"] == "active"
    assert result["execution"]["rules_executed"] == 1


def test_apply_quality_rule_review_action_rejects_without_execution(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_rule_review,
        "update_quality_rule_review",
        lambda *args, **kwargs: {"rule_id": "dqr_2", "status": kwargs["status"]},
    )

    result = dq_rule_review.apply_quality_rule_review_action(
        object(),
        rule_row={"rule_id": "dqr_2", "tenant_id": "tenant"},
        action="reject",
        reviewed_by="reviewer",
    )

    assert result["status"] == "rejected"
    assert result["execution"] is None


def test_fetch_missingness_evidence_uses_scoped_query(monkeypatch) -> None:
    captured: list[tuple[str, list[object]]] = []

    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        captured.append((sql, params))
        if "affected_row_count" in sql:
            return [{"affected_row_count": 2}]
        return [{"__row_ref": "(1,1)", "email": None}, {"__row_ref": "(1,2)", "email": ""}]

    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())
    monkeypatch.setattr(dq_evidence, "run_query", fake_run_query)

    result = dq_evidence.fetch_missingness_evidence(
        object(),
        run_row={"schema_name": "public"},
        table_name="customer",
        column_name="pincode",
        include_blank=True,
        limit=100,
        offset=0,
    )

    assert result["affected_row_count"] == 2
    assert result["column_alias"] == "postal_code"
    assert len(result["rows"]) == 2
    assert "btrim" in captured[0][0]


def test_fetch_duplicate_evidence_rehydrates_exact_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "_get_duplicate_row",
        lambda settings, tenant_id, domain_id, candidate_id: {
            "candidate_id": candidate_id,
            "run_id": "run_1",
            "table_name": "customer",
            "duplicate_type": "exact_key_duplicate",
            "match_columns_json": ["customer_id"],
            "sample_rows_json": [{"duplicate_value": "C001"}],
        },
    )
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {"schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())
    monkeypatch.setattr(
        dq_evidence,
        "run_query",
        lambda settings, sql, params, scoped_conn=None, statement_timeout_ms=None: [{"__row_ref": "(1,1)", "customer_id": "C001"}],
    )

    result = dq_evidence.fetch_duplicate_evidence(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        candidate_id="dqdup_1",
        limit=100,
    )

    assert result["candidate"]["duplicate_type"] == "exact_key_duplicate"
    assert result["match_column_aliases"] == ["customer_id"]
    assert result["evidence_rows"][0]["customer_id"] == "C001"


def test_fetch_freshness_evidence_returns_persisted_monitoring(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_tables",
        lambda *args, **kwargs: [
            {
                "table_name": "customer",
                "summary_json": {
                    "freshness_analysis": {"freshness_status": "stale", "freshness_lag_days": 9.0},
                    "stability_analysis": {"stability_status": "changed", "row_count_change_pct": 25.0},
                    "trust_components": {"freshness": 55.0},
                },
            }
        ],
    )

    result = dq_evidence.fetch_freshness_evidence(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        table_name="customer",
    )

    assert result["freshness_analysis"]["freshness_status"] == "stale"
    assert result["stability_analysis"]["stability_status"] == "changed"


def test_fetch_enrichment_evidence_returns_proposed_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "get_quality_enrichment_proposal",
        lambda settings, proposal_id, tenant_id=None: {
            "proposal_id": proposal_id,
            "target_column": "state",
            "source_columns_json": ["pincode", "country"],
            "matched_count": 10,
            "unmatched_count": 2,
            "source_references_json": [{"provider": "llm_context_inference"}],
            "proposed_values_json": [{"row_ref": "(1,1)", "proposed_value": "Karnataka"}],
        },
    )

    result = dq_evidence.fetch_enrichment_evidence(
        object(),
        proposal_id="dqep_1",
        tenant_id="tenant",
        limit=100,
    )

    assert result["summary"]["matched_count"] == 10
    assert result["target_column_alias"] == "state"
    assert result["source_column_aliases"] == ["postal_code", "country"]
    assert result["proposed_rows"][0]["proposed_value"] == "Karnataka"


def test_fetch_stage_evidence_returns_join_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "get_quality_dataset_stage",
        lambda settings, stage_id, tenant_id=None: {
            "stage_id": stage_id,
            "run_id": "run_1",
            "tenant_id": tenant_id,
            "domain_id": "data_quality_observability",
            "stage_type": "join_validation",
            "summary_json": {
                "join": {
                    "join_name": "orders_to_customer_customer_id",
                    "left_table": "orders",
                    "right_table": "customer",
                    "left_key": "customer_id",
                    "right_key": "customer_id",
                }
            },
        },
    )
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {"schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())

    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        if "JOIN" in sql:
            return [{"__left_row_ref": "(0,1)", "__right_row_ref": "(0,9)", "left_key_value": "C001", "right_key_value": "C001"}]
        if 'FROM "public"."orders" l' in sql:
            return [{"__left_row_ref": "(0,2)", "left_key_value": "C404"}]
        return [{"__right_row_ref": "(0,4)", "right_key_value": "C999"}]

    monkeypatch.setattr(dq_evidence, "run_query", fake_run_query)

    result = dq_evidence.fetch_stage_evidence(
        object(),
        stage_id="dqstage_2",
        tenant_id="tenant",
        domain_id="data_quality_observability",
        limit=100,
        offset=0,
    )

    assert result["evidence_type"] == "join_validation"
    assert result["match_key_aliases"]["left_key_alias"] == "customer_id"
    assert result["matched_rows"][0]["left_key_value"] == "C001"
    assert result["matched_rows"][0]["row_lineage_id"].startswith("dqlin_")
    assert result["unmatched_left_rows"][0]["left_key_value"] == "C404"


def test_fetch_stage_evidence_returns_filter_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "get_quality_dataset_stage",
        lambda settings, stage_id, tenant_id=None: {
            "stage_id": stage_id,
            "run_id": "run_1",
            "tenant_id": tenant_id,
            "domain_id": "data_quality_observability",
            "stage_type": "filter",
            "summary_json": {
                "parsed_filter": {"table_name": "customer", "column_name": "status", "operator": "=", "value": "active"},
                "output_dataset": "customer",
            },
        },
    )
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {"schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_stage_row_outcomes",
        lambda *args, **kwargs: [{"row_ref": "(0,2)", "reason_code": "filter_rejected"}],
    )

    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        return [{"__row_ref": "(0,1)", "status": "active"}]

    monkeypatch.setattr(dq_evidence, "run_query", fake_run_query)

    result = dq_evidence.fetch_stage_evidence(
        object(),
        stage_id="dqstage_filter_1",
        tenant_id="tenant",
        domain_id="data_quality_observability",
        limit=100,
        offset=0,
    )

    assert result["evidence_type"] == "filter"
    assert result["passed_rows"][0]["status"] == "active"
    assert result["passed_rows"][0]["row_lineage_id"].startswith("dqlin_")
    assert result["rejected_rows"][0]["reason_code"] == "filter_rejected"


def test_fetch_join_evidence_returns_join_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "get_quality_join_artifact",
        lambda settings, join_artifact_id, tenant_id=None: {
            "join_artifact_id": join_artifact_id,
            "run_id": "run_1",
            "tenant_id": tenant_id,
            "domain_id": "data_quality_observability",
            "left_table": "orders",
            "right_table": "customer",
            "join_keys_json": [{"left_key": "customer_id", "right_key": "customer_id"}],
            "summary_json": {"join_name": "orders_to_customer_customer_id", "measurement_status": "measured"},
        },
    )
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {"schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())

    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        if "JOIN" in sql:
            return [{"__left_row_ref": "(0,1)", "__right_row_ref": "(0,9)", "left_key_value": "C001", "right_key_value": "C001"}]
        if 'FROM "public"."orders" l' in sql:
            return [{"__left_row_ref": "(0,2)", "left_key_value": "C404"}]
        return [{"__right_row_ref": "(0,4)", "right_key_value": "C999"}]

    monkeypatch.setattr(dq_evidence, "run_query", fake_run_query)

    result = dq_evidence.fetch_join_evidence(
        object(),
        join_artifact_id="dqjoin_1",
        tenant_id="tenant",
        domain_id="data_quality_observability",
        limit=100,
        offset=0,
    )

    assert result["match_key_aliases"]["right_key_alias"] == "customer_id"
    assert result["matched_rows"][0]["right_key_value"] == "C001"
    assert result["matched_rows"][0]["row_lineage_id"].startswith("dqlin_")
    assert result["summary"]["join_name"] == "orders_to_customer_customer_id"


def test_fetch_final_dataset_rows_returns_rows_and_basis_stage(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {"schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_dataset_stages",
        lambda *args, **kwargs: [{"stage_id": "dqstage_2", "stage_name": "customer_join_region", "stage_type": "join_validation"}],
    )
    monkeypatch.setattr(
        dq_evidence,
        "get_quality_final_dataset_artifact",
        lambda *args, **kwargs: {"artifact_id": "dqfinal_1", "final_stage_name": "final_dataset_projection", "final_row_count": 8},
    )
    monkeypatch.setattr(
        dq_evidence,
        "fetch_final_dataset_rows_tool",
        lambda *args, **kwargs: (
            [{"__left_row_ref": "(0,1)", "__right_row_ref": "(0,9)", "left_key_value": "C001", "right_key_value": "C001"}],
            {"stage_id": "dqstage_2", "stage_name": "customer_join_region", "stage_type": "join_validation"},
        ),
    )

    result = dq_evidence.fetch_final_dataset_rows(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        limit=100,
        offset=0,
    )

    assert result["final_dataset"]["artifact_id"] == "dqfinal_1"
    assert result["basis_stage"]["stage_name"] == "customer_join_region"
    assert result["rows"][0]["left_key_value"] == "C001"
    assert result["row_source"] == "live_query"


def test_fetch_final_dataset_rows_falls_back_to_persisted_sample(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {"schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: None)
    monkeypatch.setattr(dq_evidence, "list_quality_dataset_stages", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dq_evidence,
        "get_quality_final_dataset_artifact",
        lambda *args, **kwargs: {
            "artifact_id": "dqfinal_1",
            "final_stage_name": "final_dataset_projection",
            "final_row_count": 2,
            "summary_json": {
                "basis_stage": {"stage_id": "dqstage_2", "stage_name": "filter_1", "stage_type": "filter"},
                "sample_rows": [{"__row_ref": "(0,1)", "customer_id": "C001"}, {"__row_ref": "(0,2)", "customer_id": "C002"}],
            },
        },
    )
    monkeypatch.setattr(dq_evidence, "fetch_final_dataset_rows_tool", lambda *args, **kwargs: ([], None))

    result = dq_evidence.fetch_final_dataset_rows(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        limit=1,
        offset=1,
    )

    assert result["rows"] == [{"__row_ref": "(0,2)", "customer_id": "C002"}]
    assert result["basis_stage"]["stage_name"] == "filter_1"
    assert result["row_source"] == "persisted_sample"


def test_fetch_rule_records_accepts_rule_logical_key(monkeypatch) -> None:
    rule = {
        "rule_id": "dqr_1",
        "run_id": "run_1",
        "tenant_id": "tenant",
        "domain_id": "data_quality_observability",
        "rule_type": "not_null",
        "table_name": "customer_data",
        "column_name": "email",
        "rule_label": "customer_data.email is required",
    }
    monkeypatch.setattr(dq_evidence, "list_quality_rules", lambda *args, **kwargs: [rule])
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {"schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())
    monkeypatch.setattr(
        dq_evidence,
        "run_query",
        lambda *args, **kwargs: [{"__row_ref": "(0,1)", "email": None}],
    )

    result = dq_evidence.fetch_rule_records(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        rule_id=dq_trends.rule_logical_key(rule),
        outcome="failed",
        limit=100,
        offset=0,
    )

    assert result["rule"]["rule_id"] == "dqr_1"
    assert result["rows"][0]["__row_ref"] == "(0,1)"


def test_fetch_lineage_trace_returns_edges_and_membership(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {"schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_dataset_stages",
        lambda *args, **kwargs: [
            {"stage_id": "dqstage_1", "stage_seq": 1, "stage_name": "source_profile_orders", "stage_type": "source_profile"},
            {"stage_id": "dqstage_2", "stage_seq": 2, "stage_name": "orders_to_customer_customer_id", "stage_type": "join_validation"},
        ],
    )
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_lineage_edges",
        lambda *args, **kwargs: [
            {
                "edge_id": "dqedge_1",
                "row_lineage_id": "dqlin_b3JkZXJzfCgwLDE1KQ_hash",
                "from_stage_id": "dqstage_1",
                "from_stage_name": "source_profile_orders",
                "to_stage_id": "dqstage_2",
                "to_stage_name": "orders_to_customer_customer_id",
                "edge_type": "join_unmatched_left",
            }
        ],
    )
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_stage_row_outcomes",
        lambda *args, **kwargs: [
            {
                "outcome_id": "dqout_1",
                "stage_id": "dqstage_2",
                "stage_name": "orders_to_customer_customer_id",
                "row_lineage_id": "dqlin_b3JkZXJzfCgwLDE1KQ_hash",
                "reason_code": "join_unmatched_left",
            }
        ],
    )
    monkeypatch.setattr(
        dq_evidence,
        "get_quality_final_dataset_artifact",
        lambda *args, **kwargs: {"artifact_id": "dqfinal_1", "final_stage_name": "final_dataset_projection"},
    )
    monkeypatch.setattr(
        dq_evidence,
        "fetch_final_dataset_rows_tool",
        lambda *args, **kwargs: ([], {}),
    )
    monkeypatch.setattr(
        dq_evidence,
        "run_query",
        lambda *args, **kwargs: [{"__row_ref": "(0,15)", "customer_id": "CUST-404"}],
    )

    result = dq_evidence.fetch_lineage_trace(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        row_lineage_id="dqlin_b3JkZXJzfCgwLDE1KQ_hash",
    )

    assert result["decoded_lineage"]["parts"] == ["orders", "(0,15)"]
    assert result["source_snapshot"]["__row_ref"] == "(0,15)"
    assert result["edges"][0]["edge_type"] == "join_unmatched_left"
    assert result["stage_trace"][0]["stage_name"] == "source_profile_orders"
    assert result["final_dataset_membership"]["is_member"] is False


def test_fetch_lineage_overview_summarizes_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda *args, **kwargs: {"run_id": "run_1", "schema_name": "public", "connection_id": "conn_1"},
    )
    monkeypatch.setattr(
        dq_evidence,
        "resolve_quality_run_scoped_conn",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_dataset_stages",
        lambda *args, **kwargs: [
            {"stage_id": "dqstage_1", "stage_seq": 1, "stage_name": "source_profile_orders", "stage_type": "source_profile"},
            {"stage_id": "dqstage_2", "stage_seq": 2, "stage_name": "orders_to_customer_customer_id", "stage_type": "join_validation"},
        ],
    )
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_lineage_edges",
        lambda *args, **kwargs: [
            {
                "row_lineage_id": "dqlin_b3JkZXJzfCgwLDE1KQ_hash",
                "from_stage_id": "dqstage_1",
                "from_stage_name": "source_profile_orders",
                "to_stage_id": "dqstage_2",
                "to_stage_name": "orders_to_customer_customer_id",
                "edge_type": "join_unmatched_left",
            }
        ],
    )
    monkeypatch.setattr(
        dq_evidence,
        "list_quality_stage_row_outcomes",
        lambda *args, **kwargs: [
            {
                "row_lineage_id": "dqlin_b3JkZXJzfCgwLDE1KQ_hash",
                "stage_id": "dqstage_2",
                "stage_name": "orders_to_customer_customer_id",
                "outcome_type": "rejected",
                "reason_code": "join_unmatched_left",
            }
        ],
    )
    monkeypatch.setattr(
        dq_evidence,
        "get_quality_final_dataset_artifact",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        dq_evidence,
        "fetch_final_dataset_rows_tool",
        lambda *args, **kwargs: ([], {}),
    )

    result = dq_evidence.fetch_lineage_overview(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        limit=10,
    )

    assert result["summary"]["lineage_row_count"] == 1
    assert result["summary"]["rejected_row_count"] == 1
    assert result["rows"][0]["source_table"] == "orders"
    assert result["rows"][0]["final_state"] == "join_unmatched_left"
    assert "/data-quality/lineage/dqlin_" in result["rows"][0]["evidence_path"]
    assert "/journey?" in result["rows"][0]["evidence_path"]


def test_fetch_lineage_journey_returns_display_steps(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "fetch_lineage_trace",
        lambda *args, **kwargs: {
            "run_id": "run_1",
            "row_lineage_id": "dqlin_b3JkZXJzfCgwLDE1KQ_hash",
            "decoded_lineage": {"raw": "orders|(0,15)", "parts": ["orders", "(0,15)"]},
            "source_snapshot": {"__row_ref": "(0,15)", "customer_id": "C404"},
            "edges": [{"edge_type": "join_unmatched_left"}],
            "outcomes": [{"reason_code": "join_unmatched_left"}],
            "stage_trace": [
                {
                    "stage_id": "dqstage_1",
                    "stage_seq": 1,
                    "stage_name": "source_profile_orders",
                    "stage_type": "source_profile",
                    "state": "entered",
                },
                {
                    "stage_id": "dqstage_2",
                    "stage_seq": 2,
                    "stage_name": "orders_to_customer_customer_id",
                    "stage_type": "join_validation",
                    "state": "join_unmatched_left",
                },
            ],
            "final_dataset_membership": {"is_member": False, "basis_stage": {}, "row": None},
        },
    )

    result = dq_evidence.fetch_lineage_journey(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        row_lineage_id="dqlin_b3JkZXJzfCgwLDE1KQ_hash",
    )

    assert result["summary"]["step_count"] == 2
    assert result["summary"]["final_state"] == "join_unmatched_left"
    assert result["source"]["source_table"] == "orders"
    assert result["journey"][0]["status_category"] == "progressed"
    assert result["journey"][1]["status_category"] == "rejected"
    assert "Rejected by left-side join mismatch" in result["journey"][1]["display_label"]
    assert "/data-quality/lineage/dqlin_b3JkZXJzfCgwLDE1KQ_hash?" in result["trace_path"]


def test_extract_quality_rules_falls_back_when_llm_returns_empty(monkeypatch) -> None:
    class Settings:
        openai_api_key = "key"
        openai_model = "model"

    monkeypatch.setenv("DATA_QUALITY_RULE_LLM_MODE", "auto")
    monkeypatch.setattr(dq_rules, "_extract_quality_rules_with_llm", lambda settings, text, schema: [])
    schema_graph = {"tables": [{"name": "customer", "columns": [{"name": "email"}]}]}

    rules = dq_rules.extract_quality_rules_from_context(
        "Customer email must be present.",
        schema_graph,
        settings=Settings(),
    )

    assert len(rules) == 1
    assert rules[0]["rule_type"] == "not_null"
    assert rules[0]["source"] == "context_text"


def test_validate_llm_rule_rejects_unknown_columns() -> None:
    schema_graph = {"tables": [{"name": "customer", "columns": [{"name": "email"}]}]}

    assert dq_rules._validate_llm_rule(
        {
            "rule_type": "not_null",
            "table_name": "customer",
            "column_name": "missing_column",
        },
        schema_graph,
    ) is None


def test_execute_quality_rules_persists_referential_integrity_result(monkeypatch) -> None:
    queries: list[tuple[str, list[object]]] = []
    inserted: list[dict] = []

    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        queries.append((sql, params))
        if "COUNT(*) AS checked_row_count" in sql:
            return [{"checked_row_count": 10, "violation_count": 2}]
        return [{"violating_value": "missing_customer"}]

    monkeypatch.setattr(dq_rules, "run_query", fake_run_query)
    monkeypatch.setattr(
        dq_rules,
        "insert_quality_rule_result",
        lambda settings, **kwargs: inserted.append(kwargs) or "dqrr_1",
    )

    summary = dq_rules.execute_quality_rules(
        object(),
        rules=[
            {
                "rule_id": "rule_1",
                "quality_run_id": "dqrun_1",
                "run_id": "run_1",
                "tenant_id": "tenant",
                "domain_id": "data_quality_observability",
                "rule_type": "referential_integrity",
                "table_name": "orders",
                "column_name": "customer_id",
                "reference_table": "customer",
                "reference_column": "customer_id",
            }
        ],
        schema_name="public",
        scoped_conn=None,
    )

    assert summary["rules_executed"] == 1
    assert summary["failed_rules"] == 1
    assert inserted[0]["status"] == "failed"
    assert inserted[0]["checked_row_count"] == 10
    assert inserted[0]["violation_count"] == 2
    assert inserted[0]["violation_pct"] == 20.0
    assert "LEFT JOIN" in queries[0][0]


def test_execute_quality_rules_supports_all_standard_llm_rule_types(monkeypatch) -> None:
    inserted: list[dict] = []

    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        if "COUNT(*) AS checked_row_count" in sql:
            return [{"checked_row_count": 10, "violation_count": 1}]
        return [{"violating_value": "bad"}]

    monkeypatch.setattr(dq_rules, "run_query", fake_run_query)
    monkeypatch.setattr(
        dq_rules,
        "insert_quality_rule_result",
        lambda settings, **kwargs: inserted.append(kwargs) or "dqrr_1",
    )

    base = {
        "quality_run_id": "dqrun_1",
        "run_id": "run_1",
        "tenant_id": "tenant",
        "domain_id": "data_quality_observability",
        "table_name": "customer",
        "column_name": "status",
    }
    rules = [
        {**base, "rule_id": "not_blank", "rule_type": "not_blank"},
        {**base, "rule_id": "numeric_max", "rule_type": "numeric_max", "condition_json": {"max_value": 100}},
        {**base, "rule_id": "allowed_values", "rule_type": "allowed_values", "condition_json": {"allowed_values": ["A", "B"]}},
        {**base, "rule_id": "regex_pattern", "rule_type": "regex_pattern", "condition_json": {"pattern": "^[A-Z]+$"}},
    ]

    summary = dq_rules.execute_quality_rules(object(), rules=rules, schema_name="public", scoped_conn=None)

    assert summary["rules_executed"] == 4
    assert summary["failed_rules"] == 4
    assert summary["not_executed_rules"] == 0
    assert [item["status"] for item in inserted] == ["failed", "failed", "failed", "failed"]


def test_custom_sql_executor_runs_safe_select_and_rejects_mutation(monkeypatch) -> None:
    inserted: list[dict] = []

    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        if "COUNT(*)" in sql:
            return [{"checked_row_count": 5, "violation_count": 2}]
        return [{"id": 1}]

    monkeypatch.setattr(dq_rules, "run_query", fake_run_query)
    monkeypatch.setattr(
        dq_rules,
        "insert_quality_rule_result",
        lambda settings, **kwargs: inserted.append(kwargs) or "dqrr_1",
    )

    safe_rule = {
        "rule_id": "custom_safe",
        "quality_run_id": "dqrun_1",
        "run_id": "run_1",
        "tenant_id": "tenant",
        "domain_id": "data_quality_observability",
        "rule_type": "custom_sql",
        "table_name": "orders",
        "condition_json": {
            "validation_sql": "SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE status = 'BAD') AS violation_count FROM public.orders",
            "sample_sql": "SELECT order_id, status FROM public.orders WHERE status = 'BAD'",
        },
    }
    unsafe_rule = {
        **safe_rule,
        "rule_id": "custom_unsafe",
        "condition_json": {"validation_sql": "DELETE FROM public.orders"},
    }

    summary = dq_rules.execute_quality_rules(object(), rules=[safe_rule, unsafe_rule], schema_name="public", scoped_conn=None)

    assert summary["rules_executed"] == 2
    assert summary["failed_rules"] == 1
    assert summary["error_rules"] == 1
    assert inserted[0]["status"] == "failed"
    assert inserted[0]["violation_count"] == 2
    assert inserted[1]["status"] == "error"
    assert "Unsafe custom validation SQL rejected" in inserted[1]["error_message"]


def test_validate_llm_rule_accepts_safe_custom_sql() -> None:
    schema_graph = {"tables": [{"name": "orders", "columns": [{"name": "status"}]}]}

    rule = dq_rules._validate_llm_rule(
        {
            "rule_type": "custom_sql",
            "table_name": "orders",
            "condition_json": {
                "validation_sql": "SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE status = 'BAD') AS violation_count FROM public.orders",
            },
        },
        schema_graph,
    )

    assert rule is not None
    assert rule["rule_type"] == "custom_sql"


def test_validate_llm_rule_rewrites_date_text_custom_sql_safely() -> None:
    schema_graph = {"tables": [{"name": "customers_dq_data", "columns": [{"name": "dob"}]}]}

    rule = dq_rules._validate_llm_rule(
        {
            "rule_type": "custom_sql",
            "table_name": "customers_dq_data",
            "column_name": "dob",
            "source_text": "dob must parse as YYYY-MM-DD and be strictly before today.",
            "condition_json": {
                "validation_sql": "SELECT COUNT(*) AS checked_row_count, COUNT(*) FILTER (WHERE dob >= CURRENT_DATE OR dob IS NULL OR dob !~ '^\\d{4}-\\d{2}-\\d{2}$') AS violation_count FROM public.customers_dq_data",
                "sample_sql": "SELECT dob FROM public.customers_dq_data WHERE dob >= CURRENT_DATE OR dob IS NULL OR dob !~ '^\\d{4}-\\d{2}-\\d{2}$' LIMIT 25",
            },
        },
        schema_graph,
    )

    assert rule is not None
    assert rule["rule_type"] == "custom_sql"
    assert "CASE WHEN \"dob\"::text ~ '^\\d{4}-\\d{2}-\\d{2}$'" in rule["condition_json"]["validation_sql"]
    assert "FROM \"customers_dq_data\"" in rule["condition_json"]["validation_sql"]


def test_validate_llm_rule_rejects_half_formed_rules() -> None:
    schema_graph = {"tables": [{"name": "customer", "columns": [{"name": "status"}]}]}

    assert dq_rules._validate_llm_rule(
        {"rule_type": "allowed_values", "table_name": "customer", "column_name": "status", "condition_json": {}},
        schema_graph,
    ) is None
    assert dq_rules._validate_llm_rule(
        {"rule_type": "custom_sql", "table_name": "customer", "condition_json": {"validation_sql": "UPDATE customer SET status='X'"}},
        schema_graph,
    ) is None


def test_validate_llm_rule_accepts_new_rule_families() -> None:
    schema_graph = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "order_id"},
                    {"name": "line_number"},
                    {"name": "order_date"},
                    {"name": "ship_date"},
                    {"name": "status"},
                    {"name": "amount"},
                    {"name": "pincode"},
                ],
            }
        ]
    }

    cases = [
        {"rule_type": "unique", "table_name": "orders", "column_name": "order_id"},
        {"rule_type": "composite_unique", "table_name": "orders", "condition_json": {"columns": ["order_id", "line_number"]}},
        {"rule_type": "date_range", "table_name": "orders", "column_name": "order_date", "condition_json": {"not_future": True}},
        {"rule_type": "freshness_sla", "table_name": "orders", "column_name": "order_date", "condition_json": {"max_lag_hours": 24}},
        {
            "rule_type": "conditional_required",
            "table_name": "orders",
            "condition_json": {"when_column": "status", "when_value": "SHIPPED", "required_column": "ship_date"},
        },
        {
            "rule_type": "cross_column_consistency",
            "table_name": "orders",
            "condition_json": {"left_column": "ship_date", "operator": ">=", "right_column": "order_date"},
        },
        {"rule_type": "numeric_range", "table_name": "orders", "column_name": "amount", "condition_json": {"min_value": 0, "max_value": 100}},
        {"rule_type": "length", "table_name": "orders", "column_name": "pincode", "condition_json": {"exact_length": 6}},
        {"rule_type": "null_pct_threshold", "table_name": "orders", "column_name": "ship_date", "condition_json": {"max_null_pct": 5}},
        {"rule_type": "row_count_change_pct", "table_name": "orders", "condition_json": {"baseline_row_count": 100, "max_change_pct": 20}},
    ]

    validated = [dq_rules._validate_llm_rule(case, schema_graph) for case in cases]

    assert all(item is not None for item in validated)
    assert validated[1]["condition_json"]["columns"] == ["order_id", "line_number"]
    assert validated[4]["condition_json"]["required_column"] == "ship_date"


def test_execute_quality_rules_supports_next_rule_families(monkeypatch) -> None:
    inserted: list[dict] = []

    def fake_run_query(settings, sql, params, scoped_conn=None, statement_timeout_ms=None):
        if "lag_hours" in sql:
            return [{"lag_hours": 48}]
        if "current_row_count" in sql:
            return [{"current_row_count": 150}]
        if "COUNT(*) AS checked_row_count" in sql or "checked_row_count" in sql:
            return [{"checked_row_count": 10, "violation_count": 1}]
        return [{"violating_value": "bad"}]

    monkeypatch.setattr(dq_rules, "run_query", fake_run_query)
    monkeypatch.setattr(
        dq_rules,
        "insert_quality_rule_result",
        lambda settings, **kwargs: inserted.append(kwargs) or "dqrr_1",
    )
    base = {
        "quality_run_id": "dqrun_1",
        "run_id": "run_1",
        "tenant_id": "tenant",
        "domain_id": "data_quality_observability",
        "table_name": "orders",
        "column_name": "amount",
    }
    rules = [
        {**base, "rule_id": "unique", "rule_type": "unique", "column_name": "order_id"},
        {**base, "rule_id": "composite_unique", "rule_type": "composite_unique", "condition_json": {"columns": ["order_id", "line_number"]}},
        {**base, "rule_id": "date_range", "rule_type": "date_range", "column_name": "order_date", "condition_json": {"not_future": True}},
        {**base, "rule_id": "freshness_sla", "rule_type": "freshness_sla", "column_name": "order_date", "condition_json": {"max_lag_hours": 24}},
        {
            **base,
            "rule_id": "conditional_required",
            "rule_type": "conditional_required",
            "condition_json": {"when_column": "status", "when_values": ["SHIPPED"], "required_column": "ship_date"},
        },
        {
            **base,
            "rule_id": "cross_column_consistency",
            "rule_type": "cross_column_consistency",
            "condition_json": {"left_column": "ship_date", "operator": ">=", "right_column": "order_date"},
        },
        {**base, "rule_id": "numeric_range", "rule_type": "numeric_range", "condition_json": {"min_value": 0, "max_value": 100}},
        {**base, "rule_id": "length", "rule_type": "length", "column_name": "pincode", "condition_json": {"exact_length": 6}},
        {**base, "rule_id": "null_pct_threshold", "rule_type": "null_pct_threshold", "column_name": "ship_date", "condition_json": {"max_null_pct": 5}},
        {**base, "rule_id": "row_count_change_pct", "rule_type": "row_count_change_pct", "condition_json": {"baseline_row_count": 100, "max_change_pct": 20}},
    ]

    summary = dq_rules.execute_quality_rules(object(), rules=rules, schema_name="public", scoped_conn=None)

    assert summary["rules_executed"] == len(rules)
    assert summary["not_executed_rules"] == 0
    assert len(inserted) == len(rules)


def test_build_xlsx_workbook_creates_open_xml_package() -> None:
    workbook = dq_report.build_xlsx_workbook(
        [
            ("Executive Summary", [[{"value": "Metric", "style": 1}, {"value": "Value", "style": 1}], ["Run ID", "run_1"]]),
            ("Validation Rules", [["Rule ID", "Status"], ["rule_1", "failed"]]),
        ]
    )

    with zipfile.ZipFile(BytesIO(workbook)) as archive:
        names = set(archive.namelist())
        assert "[Content_Types].xml" in names
        assert "xl/workbook.xml" in names
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "run_1" in archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert 's="1"' in archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "FFD9E2F3" in archive.read("xl/styles.xml").decode("utf-8")


def test_build_data_quality_excel_report_reads_persisted_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_report,
        "get_quality_run_by_run_id",
        lambda settings, run_id: {
            "quality_run_id": "dqrun_1",
            "run_id": run_id,
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "connection_id": "conn_1",
            "schema_name": "public",
            "status": "completed",
            "overall_trust_score": 82.5,
            "summary_json": {"profiled_tables": 1},
        },
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_tables",
        lambda *args, **kwargs: [
            {
                "quality_run_id": "dqrun_1",
                "run_id": "run_1",
                "table_name": "customer",
                "row_count": 10,
                "trust_score": 80,
                "severity": "good",
                "summary_json": {
                    "freshness_analysis": {
                        "freshness_column": "updated_at",
                        "latest_timestamp": "2026-04-18T10:00:00Z",
                        "freshness_lag_days": 2.0,
                        "freshness_status": "fresh",
                    },
                    "stability_analysis": {
                        "row_count_change_pct": 12.0,
                        "completeness_score_change": -4.0,
                        "stability_status": "stable",
                        "stability_issues": [],
                    },
                },
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "get_quality_table_detail",
        lambda *args, **kwargs: {
            "table_name": "customer",
            "columns": [
                {
                    "table_name": "customer",
                    "column_name": "email",
                    "data_type": "text",
                    "null_pct": 10,
                    "completeness_score": 90,
                }
            ],
        },
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_rules",
        lambda *args, **kwargs: [
            {
                "rule_id": "rule_1",
                "rule_label": "Invalid customer email",
                "rule_type": "email_pattern",
                "source": "context_text",
                "severity": "warning",
                "table_name": "customer",
                "column_name": "email",
                "result_status": "failed",
                "checked_row_count": 10,
                "violation_count": 1,
                "violation_pct": 10,
                "sample_rows_json": [{"email": "bad"}],
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_duplicate_candidates",
        lambda *args, **kwargs: [
            {
                "candidate_id": "dqdup_1",
                "table_name": "customer",
                "duplicate_type": "exact_key_duplicate",
                "match_columns_json": ["customer_id"],
                "confidence": 0.99,
                "candidate_record_count": 2,
                "review_status": "needs_review",
                "sample_rows_json": [{"duplicate_value": "C001", "duplicate_count": 2}],
                "cluster_json": {"duplicate_group_count": 1},
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_dataset_stages",
        lambda *args, **kwargs: [
            {
                "stage_id": "dqstage_1",
                "stage_seq": 1,
                "stage_name": "source_profile_customer",
                "stage_type": "source_profile",
                "input_row_count": 10,
                "output_row_count": 10,
                "rejected_row_count": 0,
                "summary_json": {"measurement_status": "measured"},
            },
            {
                "stage_id": "dqstage_2",
                "stage_seq": 2,
                "stage_name": "customer_join_region",
                "stage_type": "join_validation",
                "input_row_count": 10,
                "output_row_count": 8,
                "rejected_row_count": 2,
                "summary_json": {"measurement_status": "measured"},
            },
            {
                "stage_id": "dqstage_3",
                "stage_seq": 3,
                "stage_name": "filter_1",
                "stage_type": "filter",
                "output_dataset": "customer",
                "input_row_count": 8,
                "output_row_count": 6,
                "rejected_row_count": 2,
                "expression": {"expression_text": "customer.status = active"},
                "summary_json": {"measurement_status": "measured", "evidence_path": "/data-quality/evidence/stages/dqstage_3"},
            },
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_join_artifacts",
        lambda *args, **kwargs: [
            {
                "join_artifact_id": "dqjoin_1",
                "join_name": "customer_join_region",
                "left_table": "customer",
                "right_table": "region",
                "join_type": "reference_lookup",
                "matched_row_count": 8,
                "unmatched_left_row_count": 2,
                "unmatched_right_row_count": 0,
                "duplicate_match_count": 0,
                "summary_json": {"measurement_status": "measured"},
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_lineage_edges",
        lambda *args, **kwargs: [
            {
                "row_lineage_id": "dqlin_Y3VzdG9tZXJ8KDAsMSk_hash",
                "from_stage_id": "dqstage_1",
                "from_stage_name": "source_profile_customer",
                "to_stage_id": "dqstage_2",
                "to_stage_name": "customer_join_region",
                "edge_type": "join_matched",
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_stage_row_outcomes",
        lambda *args, **kwargs: [
            {
                "outcome_id": "dqout_1",
                "stage_id": "dqstage_2",
                "stage_name": "customer_join_region",
                "outcome_type": "rejected",
                "row_lineage_id": "dqlin_left_c404",
                "row_ref": "(0,2)",
                "source_table": "customer",
                "source_key_json": {"customer_id": "C404"},
                "reason_code": "join_unmatched_left",
                "reason_detail": "No region match",
                "row_data_json": {"left_key_value": "C404"},
            },
            {
                "outcome_id": "dqout_2",
                "stage_id": "dqstage_2",
                "stage_name": "customer_join_region",
                "outcome_type": "join_exception",
                "row_lineage_id": "dqlin_right_r404",
                "row_ref": "(0,4)",
                "source_table": "region",
                "source_key_json": {"region_id": "R404"},
                "reason_code": "join_unmatched_right",
                "reason_detail": "Unreferenced region row",
                "row_data_json": {"right_key_value": "R404"},
            },
            {
                "outcome_id": "dqout_3",
                "stage_id": "dqstage_3",
                "stage_name": "filter_1",
                "outcome_type": "rejected",
                "row_lineage_id": "dqlin_filter_inactive",
                "row_ref": "(0,5)",
                "source_table": "customer",
                "source_key_json": {"status": "inactive"},
                "reason_code": "filter_rejected",
                "reason_detail": "Row did not satisfy filter",
                "row_data_json": {"status": "inactive"},
            },
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "get_quality_final_dataset_artifact",
        lambda *args, **kwargs: {
            "artifact_id": "dqfinal_1",
            "final_stage_name": "final_dataset_projection",
            "final_row_count": 8,
            "total_rejected_row_count": 2,
            "readiness_status": "ready",
            "summary_json": {"measurement_status": "derived"},
        },
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_enrichment_opportunities",
        lambda *args, **kwargs: [
            {
                "opportunity_id": "dqopp_1",
                "table_name": "customer",
                "target_column": "state",
                "source_columns": ["pincode", "country"],
                "missing_count": 4,
                "confidence": 0.9,
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_trends",
        lambda *args, **kwargs: [
            {
                "object_type": "table",
                "object_key": "customer",
                "object_name": "customer",
                "metric_name": "trust_score",
                "previous_value_num": 78.0,
                "current_value_num": 80.0,
                "delta_value": 2.0,
                "delta_pct": 2.56,
                "trend_status": "improved",
                "directionality": "higher_is_better",
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_anomalies",
        lambda *args, **kwargs: [
            {
                "anomaly_id": "dqanom_1",
                "anomaly_key": "tenant|data_quality_observability|scope|run|__run__|trust_score_drop",
                "tenant_id": "tenant",
                "domain_id": "data_quality_observability",
                "run_id": "run_1",
                "quality_run_id": "dqrun_1",
                "trend_scope_key": "scope",
                "baseline_run_id": "run_prev",
                "object_type": "run",
                "object_key": "__run__",
                "object_name": "Run Summary",
                "anomaly_type": "trust_score_drop",
                "title": "Overall trust score dropped materially",
                "severity": "critical",
                "current_value_num": 82.5,
                "previous_value_num": 91.0,
                "delta_value": -8.5,
                "delta_pct": -9.34,
                "evidence_path": "/data-quality/trends?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1&object_type=run&object_key=__run__",
                "summary_json": {},
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_issues",
        lambda *args, **kwargs: [
            {
                "issue_id": "dqissue_1",
                "issue_key": "dqissuekey_1",
                "tenant_id": "tenant",
                "domain_id": "data_quality_observability",
                "run_id": "run_1",
                "quality_run_id": "dqrun_1",
                "issue_type": "join_exception",
                "title": "Join exceptions detected in customer_join_region",
                "severity": "critical",
                "owner_id": "domain_owner",
                "status": "open",
                "first_seen_at": "2026-04-20T10:00:00+00:00",
                "last_seen_at": "2026-04-25T10:00:00+00:00",
                "due_at": "2026-04-22T10:00:00+00:00",
                "evidence_path": "/data-quality/evidence/joins/dqjoin_1?tenant_id=tenant&domain_id=data_quality_observability",
                "recommendation_json": {"text": "Investigate missing join keys."},
                "summary_json": {"unmatched_left_row_count": 2},
                "related_run_ids_json": ["run_1"],
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "_list_staged_overlay_artifacts",
        lambda settings, run_id: [
            {
                "artifact_id": "artifact_stage_1",
                "raw_json": {
                    "proposal_id": "dqep_1",
                    "table_name": "customer",
                    "target_column": "state",
                    "target_column_alias": "state",
                    "source_column_aliases": ["postal_code", "country"],
                    "approval_scope": "high_confidence",
                    "approved_rows": [
                        {
                            "row_ref": "(1,1)",
                            "proposed_value": "Karnataka",
                            "confidence": 0.91,
                            "method": "llm_context_inference",
                            "target_column_alias": "state",
                            "source_column_aliases": ["postal_code", "country"],
                            "source_values": {"pincode": "560001", "country": "India"},
                        }
                    ],
                    "deferred_rows": [
                        {
                            "row_ref": "(1,2)",
                            "proposed_value": "Unknown",
                            "confidence": 0.61,
                            "method": "llm_context_inference",
                            "target_column_alias": "state",
                            "source_column_aliases": ["postal_code", "country"],
                            "source_values": {"pincode": "000000", "country": "India"},
                        }
                    ],
                },
            }
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "_fetch_overlay_source_rows",
        lambda *args, **kwargs: {
            "(1,1)": {"__row_ref": "(1,1)", "pincode": "560001", "country": "India", "state": None},
        },
    )
    monkeypatch.setattr(dq_report, "resolve_database_credentials_cached", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        dq_report,
        "run_query",
        lambda *args, **kwargs: [{"__row_ref": "(0,1)"}] if "__row_ref" in str(args[1]) else [],
    )
    monkeypatch.setattr(
        dq_report,
        "fetch_stage_snapshot_rows_tool",
        lambda *args, **kwargs: [{"__row_ref": "(0,1)", "customer_id": "C001", "row_lineage_id": "dqlin_source_c001"}],
    )
    monkeypatch.setattr(
        dq_report,
        "fetch_final_dataset_rows_tool",
        lambda *args, **kwargs: ([{"__left_row_ref": "(0,1)", "__right_row_ref": "(0,9)", "left_key_value": "C001", "right_key_value": "C001", "row_lineage_id": "dqlin_final_c001"}], {"stage_name": "customer_join_region"}),
    )
    monkeypatch.setattr(
        dq_report,
        "_fetch_table_rows",
        lambda *args, **kwargs: [
            {"__row_ref": "(0,1)", "email": "bad@example"},
            {"__row_ref": "(0,2)", "email": "good@example.com"},
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "_build_validation_failure_map",
        lambda *args, **kwargs: {"customer": {"(0,1)": {"email"}}},
    )
    monkeypatch.setattr(
        dq_report,
        "fetch_rule_records",
        lambda settings, *, tenant_id, domain_id, run_id, rule_id, outcome, limit, offset: {
            "supported": True,
            "unsupported_reason": None,
            "rows": (
                [{"__row_ref": "(0,1)", "email": "bad@example"}]
                if outcome == "failed"
                else [{"__row_ref": "(0,2)", "email": "good@example.com"}]
            ),
            "affected_row_count": 1,
            "rule": {"rule_id": rule_id},
        },
    )
    monkeypatch.setattr(dq_report, "create_quality_report_metadata", lambda *args, **kwargs: "dqreport_1")

    workbook, file_name, summary = dq_report.build_data_quality_excel_report(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
    )
    csv_archive, csv_file_name, csv_summary = dq_report.build_data_quality_csv_report(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
    )

    assert file_name == "data_quality_run_1.xlsx"
    assert summary["report_id"] == "dqreport_1"
    assert csv_file_name == "data_quality_run_1_csv_sheets.zip"
    assert csv_summary["report_id"] == "dqreport_1"
    assert summary["table_count"] == 1
    assert summary["column_count"] == 1
    assert summary["failed_rule_count"] == 1
    assert summary["duplicate_candidate_count"] == 1
    assert summary["dataset_stage_count"] == 3
    assert summary["join_artifact_count"] == 1
    assert summary["lineage_edge_count"] == 1
    assert summary["rejected_record_count"] == 2
    assert summary["filter_rejection_count"] == 1
    assert summary["join_exception_count"] == 1
    assert summary["final_dataset_row_count"] == 8
    assert summary["approved_enrichment_row_count"] == 1
    assert summary["deferred_enrichment_row_count"] == 1
    assert summary["anomaly_count"] == 1
    assert summary["critical_anomaly_count"] == 1
    assert summary["published_enrichment_sheet_count"] == 1
    assert summary["stage_snapshot_sheet_count"] == 3
    assert summary["all_data_sheet_count"] == 1
    assert summary["rule_detail_sheet_count"] == 1
    assert summary["failed_rule_detail_sheet_count"] == 1
    assert summary["issue_count"] == 1
    assert summary["open_issue_count"] == 1
    assert summary["overdue_issue_count"] == 1
    assert summary["remediation_action_count"] >= 2
    with zipfile.ZipFile(BytesIO(workbook)) as archive:
        sheet_texts = [
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet")
        ]
        assert any("email_pattern" in text for text in sheet_texts)
        sheet_names = archive.read("xl/workbook.xml").decode("utf-8")
        assert "Legend" in sheet_names
        assert "Freshness" in sheet_names
        assert "Duplicates" in sheet_names
        assert "Stage Waterfall" in sheet_names
        assert "Join Health" in sheet_names
        assert "Filter Impact" in sheet_names
        assert "Validation Rules" in sheet_names
        assert "Validation by Severity" in sheet_names
        assert "Validation by Area" in sheet_names
        assert "Rule Summary" in sheet_names
        assert "Top Risks" in sheet_names
        assert "Quality Trends" in sheet_names
        assert "Anomaly Summary" in sheet_names
        assert "Anomalies" in sheet_names
        assert "Issue Register" in sheet_names
        assert "SLA Breaches" in sheet_names
        assert "Rule Trends" in sheet_names
        assert "Stage Trends" in sheet_names
        assert "Final Dataset Trends" in sheet_names
        assert "Rejected Records" in sheet_names
        assert "Final Dataset" in sheet_names
        assert "Join Exceptions" in sheet_names
        assert "Validation 01 Invalid customer" in sheet_names
        assert "Stage 1 source_profile_customer" in sheet_names
        assert "Stage 2 customer_join_region" in sheet_names
        assert "Stage 3 filter_1" in sheet_names
        assert "Enrichment Summary" in sheet_names
        assert "Recommended Actions" in sheet_names
        assert "Staged Enrichment" in sheet_names
        assert "All Data customer" in sheet_names
        assert "Published customer" in sheet_names
        assert any("Validation Failure" in text and "light orange" in text for text in sheet_texts)
        assert any("Karnataka" in text and ('s=\"3\"' in text or 's=\"4\"' in text) for text in sheet_texts)
        assert any("560001" in text and "India" in text and "Karnataka" in text for text in sheet_texts)
        assert any("bad@example" in text and 's=\"6\"' in text for text in sheet_texts)
        assert any("Invalid customer email" in text and "bad@example" in text and "Pass / Fail" in text for text in sheet_texts)
        assert any("good@example.com" in text and "Pass" in text for text in sheet_texts)
        assert any("Join exceptions detected in customer_join_region" in text for text in sheet_texts)
        assert any("Invalid customer email" in text for text in sheet_texts)
        assert any("postal_code" in text for text in sheet_texts)
        assert any("customer_join_region" in text and "C001" in text for text in sheet_texts)
        assert any("dqlin_final_c001" in text for text in sheet_texts)
        assert all("Failed Records API" not in text for text in sheet_texts)
        assert all("Passed Records API" not in text for text in sheet_texts)
        assert all("Review Detail API" not in text for text in sheet_texts)
        assert any("Rule" in text and "Rows Passed" in text for text in sheet_texts)
    with zipfile.ZipFile(BytesIO(csv_archive)) as archive:
        names = set(archive.namelist())
        assert "01_Report_Highlights.csv" in names
        assert "02_Legend.csv" in names
        assert "03_Executive_Summary.csv" in names
        assert any(name.endswith("Quality_Trends.csv") for name in names)
        assert any(name.endswith("Published_customer.csv") for name in names)
        legend_csv = archive.read("02_Legend.csv").decode("utf-8")
        assert "Validation Failure" in legend_csv
        assert "light orange" in legend_csv
        assert any("Invalid customer email" in archive.read(name).decode("utf-8") for name in names)
        assert any("560001" in archive.read(name).decode("utf-8") for name in names)
        assert all("Failed Records API" not in archive.read(name).decode("utf-8") for name in names)


def test_build_data_quality_excel_report_flattens_source_json_values(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_report,
        "get_quality_run_by_run_id",
        lambda settings, run_id: {
            "quality_run_id": "dqrun_1",
            "run_id": run_id,
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "connection_id": "conn_1",
            "schema_name": "public",
            "status": "completed",
            "overall_trust_score": 82.5,
            "summary_json": {"profiled_tables": 1},
        },
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_tables",
        lambda *args, **kwargs: [
            {"quality_run_id": "dqrun_1", "run_id": "run_1", "table_name": "customer", "row_count": 1, "trust_score": 80, "summary_json": {}}
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "get_quality_table_detail",
        lambda *args, **kwargs: {
            "table_name": "customer",
            "columns": [
                {"table_name": "customer", "column_name": "payload", "data_type": "jsonb", "null_pct": 0, "completeness_score": 100}
            ],
        },
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_trends",
        lambda *args, **kwargs: [
            {
                "object_type": "table",
                "object_key": "customer",
                "object_name": "customer",
                "metric_name": "trust_score",
                "previous_value_num": 78.0,
                "current_value_num": 80.0,
                "delta_value": 2.0,
                "delta_pct": 2.56,
                "trend_status": "improved",
                "directionality": "higher_is_better",
            }
        ],
    )
    monkeypatch.setattr(dq_report, "list_quality_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_duplicate_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_trends", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_dataset_stages", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_join_artifacts", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_lineage_edges", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_stage_row_outcomes", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "get_quality_final_dataset_artifact", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_report, "list_quality_enrichment_opportunities", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_anomalies", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_issues", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "_list_staged_overlay_artifacts", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "resolve_database_credentials_cached", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        dq_report,
        "_fetch_table_rows",
        lambda *args, **kwargs: [{"__row_ref": "(0,1)", "payload": {"city": "Dublin", "codes": ["IE", "DUB"]}}],
    )
    monkeypatch.setattr(dq_report, "_build_validation_failure_map", lambda *args, **kwargs: {})
    monkeypatch.setattr(dq_report, "create_quality_report_metadata", lambda *args, **kwargs: "dqreport_1")

    workbook, _, _ = dq_report.build_data_quality_excel_report(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
    )

    with zipfile.ZipFile(BytesIO(workbook)) as archive:
        sheet_texts = [
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet")
        ]
        assert any("city=Dublin; codes=IE, DUB" in text for text in sheet_texts)
        assert all('{"city"' not in text for text in sheet_texts)


def test_build_data_quality_excel_report_adds_rule_sheets_from_validation_controls_when_rules_missing(monkeypatch) -> None:
    controls = [
        {"control_key": "ctrl_1", "source_text": "customer_data.customer_id must be present and not null."},
        {"control_key": "ctrl_2", "source_text": "customer_data.email must be present and not null."},
        {"control_key": "ctrl_3", "source_text": "customer_data.phone_number must be present and not null."},
    ]
    monkeypatch.setattr(
        dq_report,
        "get_quality_run_by_run_id",
        lambda settings, run_id: {
            "quality_run_id": "dqrun_1",
            "run_id": run_id,
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "connection_id": "conn_1",
            "schema_name": "public",
            "status": "completed",
            "overall_trust_score": 82.5,
            "summary_json": {"profiled_tables": 1, "validation_controls": controls},
        },
    )
    monkeypatch.setattr(
        dq_report,
        "list_quality_tables",
        lambda *args, **kwargs: [
            {"quality_run_id": "dqrun_1", "run_id": "run_1", "table_name": "customer_data", "row_count": 1, "trust_score": 80, "summary_json": {}}
        ],
    )
    monkeypatch.setattr(
        dq_report,
        "get_quality_table_detail",
        lambda *args, **kwargs: {
            "table_name": "customer_data",
            "columns": [
                {"table_name": "customer_data", "column_name": "customer_id", "data_type": "text", "null_pct": 0, "completeness_score": 100},
                {"table_name": "customer_data", "column_name": "email", "data_type": "text", "null_pct": 0, "completeness_score": 100},
                {"table_name": "customer_data", "column_name": "phone_number", "data_type": "text", "null_pct": 0, "completeness_score": 100},
            ],
        },
    )
    monkeypatch.setattr(dq_report, "list_quality_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_duplicate_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_trends", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_dataset_stages", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_join_artifacts", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_lineage_edges", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_stage_row_outcomes", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "get_quality_final_dataset_artifact", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_report, "list_quality_enrichment_opportunities", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_anomalies", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "list_quality_issues", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "_list_staged_overlay_artifacts", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "resolve_database_credentials_cached", lambda *args, **kwargs: object())
    monkeypatch.setattr(dq_report, "_fetch_table_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_report, "_build_validation_failure_map", lambda *args, **kwargs: {})
    monkeypatch.setattr(dq_report, "create_quality_report_metadata", lambda *args, **kwargs: "dqreport_1")

    workbook, _, summary = dq_report.build_data_quality_excel_report(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
    )

    assert summary["rule_count"] == 3
    assert summary["rule_detail_sheet_count"] == 3

    with zipfile.ZipFile(BytesIO(workbook)) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        assert "Report Highlights" in workbook_xml
        assert "Rule Summary" in workbook_xml
        assert "Validation 01 Customer id req" in workbook_xml
        assert "Validation 02 Email required" in workbook_xml
        assert "Validation 03 Phone number re" in workbook_xml


def test_build_data_quality_dashboard_spec_shapes_quality_views() -> None:
    spec = dq_dashboard.build_data_quality_dashboard_spec(
        run_id="run_1",
        domain_id="data_quality_observability",
        profiling={
            "tables": [
                {
                    "name": "customer",
                    "row_count": 10,
                    "quality_summary": {
                        "table_trust_score": 72.5,
                        "table_completeness_score": 80,
                        "freshness_lag_days": 2,
                        "duplicate_risk_columns_count": 1,
                    },
                    "column_profiles": [
                        {"name": "email", "null_pct": 20, "blank_pct": 5, "completeness_score": 75},
                    ],
                }
            ]
        },
        quality_tables=[
            {
                "table_name": "customer",
                "trust_score": 68.0,
                "completeness_score": 80.0,
                "validity_score": 90.0,
                "referential_integrity_score": 80.0,
                "freshness_score": 90.0,
                "duplicate_risk_score": 70.0,
            }
        ],
        quality_summary={
            "average_table_trust_score": 72.5,
            "critical_issue_count": 0,
            "warning_issue_count": 1,
            "failed_rule_count": 1,
        },
        quality_rules=[
            {
                "rule_id": "rule_1",
                "rule_type": "referential_integrity",
                "severity": "critical",
                "table_name": "orders",
                "column_name": "customer_id",
                "reference_table": "customer",
                "reference_column": "customer_id",
            }
        ],
        quality_rule_results=[
            {
                "status": "failed",
                "violation_count": 2,
                "violation_pct": 20.0,
            }
        ],
        duplicate_candidates=[
            {
                "candidate_id": "dqdup_1",
                "table_name": "customer",
                "duplicate_type": "exact_key_duplicate",
                "candidate_record_count": 4,
                "confidence": 0.99,
            }
        ],
        enrichment_opportunities=[
            {
                "opportunity_id": "dqopp_1",
                "table_name": "customer",
                "target_column": "state",
                "missing_count": 20,
                "confidence": 0.91,
            }
        ],
        dataset_stages=[
            {
                "stage_id": "dqstage_1",
                "stage_seq": 1,
                "stage_name": "source_profile_customer",
                "stage_type": "source_profile",
                "input_row_count": 10,
                "output_row_count": 10,
                "rejected_row_count": 0,
            },
            {
                "stage_id": "dqstage_2",
                "stage_seq": 2,
                "stage_name": "customer_join_region",
                "stage_type": "join_validation",
                "input_row_count": 10,
                "output_row_count": 8,
                "rejected_row_count": 2,
            },
            {
                "stage_id": "dqstage_3",
                "stage_seq": 3,
                "stage_name": "filter_1",
                "stage_type": "filter",
                "output_dataset": "customer",
                "input_row_count": 8,
                "output_row_count": 6,
                "rejected_row_count": 2,
                "expression": {"expression_text": "customer.status = active"},
            },
        ],
        join_artifacts=[
            {
                "join_artifact_id": "dqjoin_1",
                "join_name": "customer_join_region",
                "left_table": "customer",
                "right_table": "region",
                "matched_row_count": 8,
                "unmatched_left_row_count": 2,
                "unmatched_right_row_count": 0,
                "duplicate_match_count": 0,
            }
        ],
        lineage_edges=[
            {
                "row_lineage_id": "dqlin_Y3VzdG9tZXJ8KDAsMSk_hash",
                "from_stage_id": "dqstage_1",
                "from_stage_name": "source_profile_customer",
                "to_stage_id": "dqstage_2",
                "to_stage_name": "customer_join_region",
                "edge_type": "join_matched",
            }
        ],
        row_outcomes=[
            {"outcome_type": "rejected"},
            {"outcome_type": "join_exception"},
            {"outcome_type": "rejected", "reason_code": "filter_rejected"},
        ],
        final_dataset={
            "final_row_count": 8,
            "total_rejected_row_count": 2,
            "readiness_status": "ready",
            "final_stage_name": "final_dataset_projection",
            "summary_json": {"measurement_status": "derived"},
        },
    )

    assert spec["title"] == "Data Quality Observability Data Quality Dashboard"
    assert len(spec["chart_plan"]) == 12
    assert spec["summary_view"]["title"] == "Executive Summary"
    assert spec["summary_view"]["rows"][0]["metric_key"] == "quality_score"
    chart_by_key = {item["chart_key"]: item for item in spec["chart_plan"]}
    assert chart_by_key["executive_summary"]["rows"][0]["metric_key"] == "quality_score"
    assert chart_by_key["filter_impact"]["rows"][0]["rejected_row_count"] == 2
    assert chart_by_key["missingness_heatmap"]["display_columns"][1] == {"field": "column_name", "label": "Physical Column"}
    assert chart_by_key["missingness_heatmap"]["display_columns"][2] == {"field": "column_alias", "label": "Semantic Alias"}
    assert chart_by_key["missingness_heatmap"]["rows"][0]["column_alias"] == "email"
    assert "/data-quality/evidence/missingness" in str(chart_by_key["missingness_heatmap"]["rows"][0]["evidence_path"])
    assert chart_by_key["referential_integrity"]["rows"][0]["reference_table"] == "customer"
    assert chart_by_key["referential_integrity"]["rows"][0]["column_alias"] == "customer_id"
    assert "/data-quality/runs/run_1/rules/rule_1/failed-records" in str(chart_by_key["referential_integrity"]["rows"][0]["evidence_path"])
    assert "/data-quality/evidence/rules/rule_1" in str(chart_by_key["referential_integrity"]["rows"][0]["detail_evidence_path"])
    assert chart_by_key["duplicate_risk"]["rows"][0]["duplicate_candidate_count"] == 1
    assert "/data-quality/evidence/duplicates/" in str(chart_by_key["duplicate_risk"]["rows"][0]["evidence_path"])
    assert "recommended_actions" in chart_by_key
    assert "business_term_trends" not in chart_by_key
    assert "lineage_overview" not in chart_by_key
    assert "owner_workload" not in chart_by_key
    assert "data_trust_scorecard" not in chart_by_key
    final_dataset_quality = chart_by_key["final_dataset_quality"]
    assert "/data-quality/final-dataset/rows" in str(final_dataset_quality["rows"][0]["evidence_path"])
    assert "/data-quality/final-dataset?tenant_id=tenant" in str(final_dataset_quality["rows"][0]["detail_evidence_path"])


def test_build_data_quality_dashboard_spec_skips_empty_sections() -> None:
    spec = dq_dashboard.build_data_quality_dashboard_spec(
        run_id="run_1",
        domain_id="data_quality_observability",
        profiling={
            "tables": [
                {
                    "name": "customer",
                    "row_count": 10,
                    "quality_summary": {
                        "table_trust_score": 72.5,
                        "table_completeness_score": 80,
                    },
                    "column_profiles": [
                        {"name": "email", "null_pct": 0, "blank_pct": 0, "completeness_score": 100},
                    ],
                }
            ]
        },
        quality_tables=[
            {
                "table_name": "customer",
                "trust_score": 68.0,
                "completeness_score": 80.0,
            }
        ],
        quality_summary={
            "average_table_trust_score": 72.5,
            "critical_issue_count": 0,
            "warning_issue_count": 0,
            "failed_rule_count": 0,
        },
        quality_rules=[],
        quality_rule_results=[],
        duplicate_candidates=[],
        freshness_results=[],
        enrichment_opportunities=[],
    )

    chart_keys = [item["chart_key"] for item in spec["chart_plan"]]
    assert chart_keys == ["executive_summary", "publish_readiness"]


def test_build_data_quality_dashboard_spec_includes_quality_trends_when_present() -> None:
    spec = dq_dashboard.build_data_quality_dashboard_spec(
        run_id="run_1",
        domain_id="data_quality_observability",
        profiling={"tables": []},
        quality_summary={"average_table_trust_score": 72.5, "critical_issue_count": 0, "failed_rule_count": 0},
        trends=[
            {
                "object_type": "rule",
                "object_key": "rule_1",
                "object_name": "customer.email is required",
                "metric_name": "violation_count",
                "current_value_num": 12.0,
                "trend_status": "worsened",
                "directionality": "lower_better",
            },
            {
                "object_type": "table",
                "object_key": "customer",
                "object_name": "customer",
                "metric_name": "trust_score",
                "previous_value_num": 81.0,
                "current_value_num": 76.0,
                "delta_value": -5.0,
                "delta_pct": -6.17,
                "trend_status": "worsened",
                "directionality": "higher_is_better",
            }
        ],
    )

    quality_trends = next(item for item in spec["chart_plan"] if item["chart_key"] == "quality_trends")
    rule_row = next(row for row in quality_trends["rows"] if row["object_type"] == "Rule")
    table_row = next(row for row in quality_trends["rows"] if row["object_type"] == "Table")
    assert table_row["object_key"] == "customer"
    assert quality_trends["summary"]["worsened_metric_count"] == 2
    assert rule_row["metric_name"] == "Failed Records"
    assert "/data-quality/runs/run_1/rules/rule_1/failed-records" in str(rule_row["evidence_path"])
    assert "/data-quality/trends/rules/rule_1" in str(rule_row["detail_evidence_path"])


def test_build_business_term_trend_payload_groups_rows_by_glossary_term() -> None:
    result = dq_trends.build_business_term_trend_payload(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        trends=[
            {
                "object_type": "table",
                "object_key": "customer",
                "object_name": "Customer",
                "metric_name": "trust_score",
                "trend_status": "worsened",
            },
            {
                "object_type": "rule",
                "object_key": "rule_1",
                "object_name": "Invalid customer email",
                "metric_name": "violation_count",
                "trend_status": "improved",
            },
        ],
        glossary_terms=[
            {
                "term": "Customer",
                "normalized_term": "customer",
                "definition": "Customer master and subscriber identity domain.",
                "synonyms": ["subscriber"],
                "abbreviations": [],
            }
        ],
    )

    assert result["summary"]["business_term_group_count"] == 1
    assert result["summary"]["worsened_business_term_count"] == 1
    assert result["rows"][0]["business_term"] == "Customer"
    assert result["rows"][0]["trend_row_count"] == 2
    assert "/data-quality/trends/business-terms/records" in str(result["rows"][0]["evidence_path"])
    assert "/data-quality/trends/business-terms?" in str(result["rows"][0]["detail_evidence_path"])


def test_build_business_term_trend_payload_uses_llm_fallback_when_glossary_coverage_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_trends,
        "_infer_business_terms_for_run",
        lambda *args, **kwargs: [
            {
                "term": "Customer",
                "normalized_term": "customer",
                "definition": "Customer identity and account ownership domain.",
                "synonyms": ["customer_id", "email", "phone_number"],
                "abbreviations": [],
            }
        ],
    )

    result = dq_trends.build_business_term_trend_payload(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        trends=[
            {
                "object_type": "rule",
                "object_key": "rule_1",
                "object_name": "Customer email is required",
                "metric_name": "violation_count",
                "trend_status": "worsened",
            }
        ],
        glossary_terms=[],
        settings=SimpleNamespace(openai_api_key="key", openai_model="model"),
    )

    assert result["summary"]["business_term_group_count"] == 1
    assert result["summary"]["unmatched_trend_row_count"] == 0
    assert result["rows"][0]["business_term"] == "Customer"


def test_build_business_term_record_payload_maps_term_to_rule_and_stage_records(monkeypatch) -> None:
    rule = {
        "rule_id": "dqr_1",
        "run_id": "run_1",
        "rule_label": "customer_id is required",
        "rule_type": "not_null",
        "severity": "high",
        "table_name": "customer_data",
        "column_name": "customer_id",
        "condition_json": {},
        "source_text": "customer_id should not be null",
    }
    stage = {
        "stage_id": "dqstage_1",
        "run_id": "run_1",
        "stage_name": "customer_id presence",
        "stage_type": "filter",
        "stage_seq": 2,
        "summary_json": {"rejected_row_count": 3},
    }
    monkeypatch.setattr(dq_trends, "list_quality_rules", lambda *args, **kwargs: [rule])
    monkeypatch.setattr(dq_trends, "list_quality_dataset_stages", lambda *args, **kwargs: [stage])
    monkeypatch.setattr(
        dq_trends,
        "fetch_rule_records",
        lambda *args, **kwargs: {
            "supported": True,
            "affected_row_count": 2,
            "rows": [{"__row_ref": "(0,1)", "customer_id": None}],
        },
    )
    monkeypatch.setattr(
        dq_trends,
        "fetch_stage_evidence",
        lambda *args, **kwargs: {
            "summary": {"rejected_row_count": 3},
            "rows": [{"__row_ref": "(0,2)", "customer_id": None}],
        },
    )
    monkeypatch.setattr(
        dq_trends,
        "fetch_final_dataset_rows",
        lambda *args, **kwargs: {
            "final_dataset": {"final_row_count": 10},
            "basis_stage": {"stage_id": "dqstage_final"},
            "rows": [{"__row_ref": "(0,3)", "customer_id": "C1"}],
        },
    )

    result = dq_trends.build_business_term_record_payload(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        term="customer id",
        trends=[
            {
                "object_type": "rule",
                "object_key": dq_trends.rule_logical_key(rule),
                "object_name": "customer_id is required",
                "metric_name": "violation_count",
                "trend_status": "worsened",
                "current_value_num": 2,
            },
            {
                "object_type": "stage",
                "object_key": dq_trends.stage_logical_key(stage),
                "object_name": "customer_id presence",
                "metric_name": "rejected_row_count",
                "trend_status": "worsened",
            },
        ],
        glossary_terms=[
            {
                "term": "Customer ID",
                "normalized_term": "customer id",
                "definition": "Customer identifier.",
                "synonyms": ["customer_id"],
                "abbreviations": [],
            }
        ],
        settings=SimpleNamespace(openai_api_key=None),
    )

    assert result["business_term"] == "Customer ID"
    assert result["summary"]["record_group_count"] == 2
    assert "/data-quality/runs/run_1/rules/dqr_1/failed-records" in str(result["record_groups"][0]["evidence_path"])
    assert any(group["source_type"] == "stage_evidence" for group in result["record_groups"])


def test_upsert_glossary_terms_normalizes_and_persists_entries(monkeypatch) -> None:
    calls: list[list[object]] = []
    monkeypatch.setattr(dq_glossary, "execute_non_query", lambda settings, sql, params: calls.append(params))

    updated = dq_glossary.upsert_glossary_terms(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        terms=[
            {
                "term": "Customer Identifier",
                "definition": "Primary customer key",
                "synonyms": ["customer_id", "customer id"],
                "abbreviations": ["CID"],
            }
        ],
        lifecycle_status="suggested",
        source_context_id="ctx_1",
    )

    assert updated == 1
    assert calls
    assert calls[0][0] == "tenant__data_quality_observability__customer_identifier"
    assert calls[0][4] == "customer identifier"
    assert calls[0][8] == "suggested"
    assert calls[0][9] == "ctx_1"


def test_build_data_quality_dashboard_spec_includes_business_term_trends_when_present() -> None:
    spec = dq_dashboard.build_data_quality_dashboard_spec(
        run_id="run_1",
        domain_id="data_quality_observability",
        profiling={"tables": []},
        quality_summary={"average_table_trust_score": 72.5, "critical_issue_count": 0, "failed_rule_count": 0},
        trends=[],
        business_term_trends={
            "summary": {
                "business_term_group_count": 1,
                "worsened_business_term_count": 1,
                "improved_business_term_count": 0,
                "unmatched_trend_row_count": 0,
            },
            "rows": [
                {
                    "business_term": "Customer",
                    "trend_row_count": 2,
                    "worsened_metric_count": 1,
                    "improved_metric_count": 0,
                    "affected_object_count": 2,
                    "top_metrics": "trust_score, violation_count",
                    "evidence_path": "/data-quality/trends/business-terms/records?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1&term=customer",
                    "detail_evidence_path": "/data-quality/trends/business-terms?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1&term=customer",
                }
            ],
        },
    )

    chart_keys = [item["chart_key"] for item in spec["chart_plan"]]
    assert "business_term_trends" not in chart_keys


def test_build_data_quality_dashboard_spec_uses_persisted_rule_id_for_trend_record_links() -> None:
    spec = dq_dashboard.build_data_quality_dashboard_spec(
        run_id="run_1",
        domain_id="data_quality_observability",
        profiling={"tables": []},
        quality_summary={"average_table_trust_score": 72.5, "critical_issue_count": 0, "failed_rule_count": 1},
        quality_rules=[
            {
                "rule_id": "dqr_123",
                "rule_type": "not_null",
                "severity": "warning",
                "table_name": "customer_data",
                "column_name": "email",
                "rule_label": "customer_data.email is required",
            }
        ],
        trends=[
            {
                "object_type": "rule",
                "object_key": dq_trends.rule_logical_key(
                    {
                        "rule_id": "dqr_123",
                        "rule_type": "not_null",
                        "table_name": "customer_data",
                        "column_name": "email",
                        "rule_label": "customer_data.email is required",
                    }
                ),
                "object_name": "customer_data.email is required",
                "metric_name": "violation_count",
                "current_value_num": 10,
                "previous_value_num": 0,
                "current_value_text": None,
                "trend_status": "worsened",
            }
        ],
    )

    quality_trends = next(item for item in spec["chart_plan"] if item["chart_key"] == "quality_trends")
    row = quality_trends["rows"][0]
    assert "/data-quality/runs/run_1/rules/dqr_123/failed-records" in str(row["evidence_path"])
    assert "/data-quality/runs/run_1/rules/dqr_123/passed-records" in str(row["passed_records_path"])


def test_derive_data_quality_anomalies_detects_core_regressions() -> None:
    anomalies = dq_anomalies.derive_data_quality_anomalies(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        quality_run_id="dqrun_1",
        trend_scope_key="scope_1",
        baseline_run_id="run_prev",
        trends=[
            {
                "object_type": "run",
                "object_key": "__run__",
                "metric_name": "overall_trust_score",
                "trend_status": "worsened",
                "current_value_num": 70.0,
                "previous_value_num": 82.0,
                "delta_value": -12.0,
                "delta_pct": -14.6,
            },
            {
                "object_type": "table",
                "object_key": "customer",
                "object_name": "customer",
                "metric_name": "row_count",
                "trend_status": "worsened",
                "current_value_num": 800.0,
                "previous_value_num": 2000.0,
                "delta_value": -400.0,
                "delta_pct": -33.33,
            },
            {
                "object_type": "rule",
                "object_key": "rulekey_1",
                "object_name": "Invalid customer email",
                "metric_name": "violation_count",
                "trend_status": "worsened",
                "current_value_num": 40.0,
                "previous_value_num": 20.0,
                "delta_value": 20.0,
                "delta_pct": 100.0,
            },
        ],
    )

    anomaly_types = {row["anomaly_type"] for row in anomalies}
    assert "trust_score_drop" in anomaly_types
    assert "row_count_drift" in anomaly_types
    assert "rule_violation_spike" in anomaly_types


def test_build_data_quality_dashboard_spec_includes_anomaly_summary_when_present() -> None:
    spec = dq_dashboard.build_data_quality_dashboard_spec(
        run_id="run_1",
        domain_id="data_quality_observability",
        profiling={"tables": []},
        quality_summary={"average_table_trust_score": 72.5, "critical_issue_count": 0, "failed_rule_count": 0},
        anomalies=[
            {
                "anomaly_id": "dqanom_1",
                "anomaly_type": "trust_score_drop",
                "title": "Overall trust score dropped materially",
                "severity": "critical",
                "object_type": "run",
                "object_key": "__run__",
                "baseline_run_id": "run_prev",
                "current_value_num": 82.5,
                "previous_value_num": 91.0,
                "delta_value": -8.5,
                "delta_pct": -9.34,
                "evidence_path": "/data-quality/trends?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1&object_type=run&object_key=__run__",
            }
        ],
    )

    anomaly_chart = next(item for item in spec["chart_plan"] if item["chart_key"] == "anomaly_summary")
    assert anomaly_chart["summary"]["anomaly_count"] == 1
    assert anomaly_chart["rows"][0]["anomaly_type"] == "trust_score_drop"


def test_build_readiness_trend_payload_summarizes_publish_readiness() -> None:
    payload = dq_trends.build_readiness_trend_payload(
        run_id="run_1",
        baseline_run_id="run_prev",
        final_dataset={"readiness_status": "warning", "final_row_count": 120},
        trends=[
            {
                "object_type": "final_dataset",
                "object_key": "final_dataset",
                "metric_name": "readiness_status",
                "previous_value_text": "blocked",
                "current_value_text": "warning",
                "trend_status": "improved",
            },
            {
                "object_type": "final_dataset",
                "object_key": "final_dataset",
                "metric_name": "final_row_count",
                "previous_value_num": 100.0,
                "current_value_num": 120.0,
                "delta_value": 20.0,
                "delta_pct": 20.0,
                "trend_status": "improved",
            },
        ],
        issues=[
            {
                "issue_type": "publish_readiness_blocker",
                "title": "Final dataset readiness is warning",
                "severity": "high",
                "status": "open",
            }
        ],
        anomalies=[{"severity": "critical"}],
    )

    assert payload["current_readiness_status"] == "warning"
    assert payload["previous_readiness_status"] == "blocked"
    assert payload["readiness_trend_status"] == "improved"
    assert payload["certification_blocker_count"] == 1
    assert payload["residual_anomaly_count"] == 1


def test_build_data_quality_dashboard_spec_includes_publish_readiness_when_present() -> None:
    spec = dq_dashboard.build_data_quality_dashboard_spec(
        run_id="run_1",
        domain_id="data_quality_observability",
        profiling={"tables": []},
        quality_summary={"average_table_trust_score": 72.5, "critical_issue_count": 0, "failed_rule_count": 0, "baseline_run_id": "run_prev"},
        final_dataset={"readiness_status": "warning", "final_row_count": 120, "total_rejected_row_count": 12},
        trends=[
            {
                "object_type": "final_dataset",
                "object_key": "final_dataset",
                "metric_name": "readiness_status",
                "previous_value_text": "blocked",
                "current_value_text": "warning",
                "trend_status": "improved",
            }
        ],
        issues=[
            {
                "issue_id": "dqissue_1",
                "issue_key": "dqissuekey_1",
                "issue_type": "publish_readiness_blocker",
                "title": "Final dataset readiness is warning",
                "severity": "high",
                "status": "open",
            }
        ],
        anomalies=[{"severity": "critical"}],
    )

    chart = next(item for item in spec["chart_plan"] if item["chart_key"] == "publish_readiness")
    assert chart["summary"]["current_readiness_status"] == "warning"
    assert chart["summary"]["certification_blocker_count"] == 1


def test_derive_data_quality_issues_covers_core_issue_types() -> None:
    issues = dq_issues.derive_data_quality_issues(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        trend_scope_key="cdr_primary_reconciliation",
        quality_summary={},
        rules=[
            {
                "rule_id": "rule_1",
                "rule_label": "Invalid customer email",
                "rule_type": "email_pattern",
                "severity": "error",
                "table_name": "customer",
                "column_name": "email",
                "result_status": "failed",
                "violation_count": 12,
                "violation_pct": 10.0,
            }
        ],
        duplicate_candidates=[
            {"candidate_id": "dup_1", "table_name": "customer"},
            {"candidate_id": "dup_2", "table_name": "customer"},
        ],
        freshness_results=[
            {"table_name": "customer", "freshness_status": "stale", "freshness_lag_days": 6},
            {"table_name": "customer", "stability_status": "changed", "row_count_change_pct": 25.0},
        ],
        dataset_stages=[
            {
                "stage_id": "stage_1",
                "stage_type": "filter",
                "stage_name": "filter_billable",
                "output_dataset": "mediation_data",
                "input_row_count": 1000,
                "rejected_row_count": 300,
                "expression": {"expression_text": "billable_flag = true"},
            }
        ],
        join_artifacts=[
            {
                "join_artifact_id": "join_1",
                "join_name": "network_to_mediation",
                "left_table": "network_cdr_data",
                "right_table": "mediation_data",
                "unmatched_left_row_count": 40,
                "unmatched_right_row_count": 0,
                "duplicate_match_count": 0,
            }
        ],
        final_dataset={"readiness_status": "blocked", "final_row_count": 600},
        trends=[
            {
                "object_type": "run",
                "object_key": "__run__",
                "metric_name": "overall_trust_score",
                "trend_status": "worsened",
                "delta_value": -5.0,
                "delta_pct": -6.0,
                "baseline_run_id": "run_0",
            }
        ],
    )

    issue_types = {row["issue_type"] for row in issues}
    assert "failed_rule" in issue_types
    assert "duplicate_risk" in issue_types
    assert "stale_dataset" in issue_types
    assert "stability_change" in issue_types
    assert "filter_loss_concentration" in issue_types
    assert "join_exception" in issue_types
    assert "publish_readiness_blocker" in issue_types
    assert "trend_regression" in issue_types


def test_build_data_quality_dashboard_spec_includes_issue_sections_when_present() -> None:
    spec = dq_dashboard.build_data_quality_dashboard_spec(
        run_id="run_1",
        domain_id="data_quality_observability",
        profiling={"tables": []},
        quality_summary={"average_table_trust_score": 72.5, "critical_issue_count": 1, "failed_rule_count": 1},
        issues=[
            {
                "issue_id": "dqissue_1",
                "issue_key": "dqissuekey_1",
                "issue_type": "join_exception",
                "title": "Join exceptions detected",
                "severity": "critical",
                "owner_id": "domain_owner",
                "status": "open",
                "first_seen_at": "2026-04-20T10:00:00+00:00",
                "due_at": "2026-04-22T10:00:00+00:00",
                "evidence_path": "/data-quality/evidence/joins/join_1?tenant_id=tenant&domain_id=data_quality_observability",
            }
        ],
    )

    chart_keys = [item["chart_key"] for item in spec["chart_plan"]]
    assert "issue_register" in chart_keys
    assert "issue_aging" in chart_keys
    assert "sla_breaches" in chart_keys


def test_build_data_quality_run_hydration_payload_includes_issue_card() -> None:
    response = dq_api_payloads.build_data_quality_run_hydration_payload(
        row={
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "status": "completed",
            "summary_json": {"workflow_status": "completed"},
        },
        remediation_plan={"summary": {}, "actions": []},
        issue_overview={
            "summary": {"issue_count": 2, "open_issue_count": 1, "overdue_issue_count": 1},
            "issues": [{"issue_id": "dqissue_1", "title": "Blocked publish", "severity": "critical"}],
        },
    )

    assert response["pending_tasks"]["issues"]["issue_count"] == 2
    assert response["pending_tasks"]["issues"]["top_items"][0]["issue_id"] == "dqissue_1"


def test_build_data_quality_run_hydration_payload_includes_anomaly_card() -> None:
    response = dq_api_payloads.build_data_quality_run_hydration_payload(
        row={
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "status": "completed",
            "summary_json": {"workflow_status": "completed"},
        },
        remediation_plan={"summary": {}, "actions": []},
        anomaly_overview={
            "summary": {"anomaly_count": 2, "critical_anomaly_count": 1, "high_anomaly_count": 1},
            "anomalies": [{"anomaly_id": "dqanom_1", "title": "Trust score drop", "severity": "critical"}],
        },
    )

    assert response["pending_tasks"]["anomalies"]["anomaly_count"] == 2
    assert response["pending_tasks"]["anomalies"]["top_items"][0]["anomaly_id"] == "dqanom_1"


def test_build_data_quality_run_hydration_payload_includes_readiness_card() -> None:
    response = dq_api_payloads.build_data_quality_run_hydration_payload(
        row={
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "status": "completed",
            "summary_json": {"workflow_status": "completed"},
        },
        remediation_plan={"summary": {}, "actions": []},
        readiness_overview={
            "current_readiness_status": "warning",
            "previous_readiness_status": "blocked",
            "readiness_trend_status": "improved",
            "certification_blocker_count": 1,
            "residual_anomaly_count": 2,
        },
    )

    assert response["pending_tasks"]["readiness"]["current_readiness_status"] == "warning"
    assert response["pending_tasks"]["readiness"]["certification_blocker_count"] == 1


def test_derive_data_quality_remediation_plan_prioritizes_explainable_actions() -> None:
    plan = dq_remediation.derive_data_quality_remediation_plan(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        tables=[
            {
                "table_name": "customer",
                "trust_score": 62.0,
                "summary_json": {
                    "freshness_analysis": {"freshness_status": "stale", "freshness_lag_days": 8.0, "freshness_column": "updated_at"},
                    "stability_analysis": {"stability_status": "changed", "row_count_change_pct": 25.0, "completeness_score_change": -12.0},
                    "trust_components": {"freshness": 40.0, "completeness": 70.0},
                    "trust_component_explanations": {"freshness": "Freshness lag exceeds the expected SLA."},
                },
            }
        ],
        table_details=[
            {
                "table_name": "customer",
                "trust_score": 62.0,
                "columns": [
                    {"column_name": "email", "null_pct": 35.0, "blank_pct": 0.0},
                ],
            }
        ],
        rules=[
            {
                "rule_id": "rule_1",
                "rule_type": "referential_integrity",
                "table_name": "orders",
                "column_name": "customer_id",
                "severity": "critical",
                "result_status": "failed",
                "violation_count": 12,
                "violation_pct": 24.0,
            }
        ],
        duplicates=[
            {
                "candidate_id": "dqdup_1",
                "table_name": "customer",
                "duplicate_type": "exact_key_duplicate",
                "candidate_record_count": 30,
                "confidence": 0.99,
            }
        ],
        dataset_stages=[
            {
                "stage_id": "dqstage_filter_1",
                "stage_name": "filter_1",
                "stage_type": "filter",
                "output_dataset": "customer",
                "input_row_count": 100,
                "rejected_row_count": 40,
                "expression": {"expression_text": "customer.status = active"},
            }
        ],
        row_outcomes=[
            {"stage_id": "dqstage_filter_1", "reason_code": "filter_rejected"},
        ],
        opportunities=[
            {
                "opportunity_id": "dqopp_1",
                "table_name": "customer",
                "target_column": "state",
                "source_columns": ["pincode", "country"],
                "missing_count": 80,
                "confidence": 0.88,
            }
        ],
        limit=20,
    )

    assert plan["summary"]["action_count"] >= 5
    assert plan["summary"]["critical_action_count"] >= 1
    assert any(row["evidence_type"] == "missingness" for row in plan["actions"])
    assert any(row["evidence_type"] == "rule_failure" for row in plan["actions"])
    assert any(row["evidence_type"] == "freshness" for row in plan["actions"])
    assert any(row["action_type"] == "filter_review" for row in plan["actions"])
    assert any("/data-quality/evidence/missingness" in str(row["evidence_path"]) for row in plan["actions"])


def test_create_data_quality_dashboard_uses_dashboard_store(monkeypatch) -> None:
    created: dict = {}

    def fake_create_dashboard(settings, **kwargs):
        created.update(kwargs)
        return {"dashboard_id": "db_dq_1"}

    monkeypatch.setattr(dq_dashboard, "create_dashboard", fake_create_dashboard)

    result = dq_dashboard.create_data_quality_dashboard(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        profiling={"tables": []},
        quality_summary={"average_table_trust_score": 88.0, "critical_issue_count": 0},
        quality_rules=[],
        quality_rule_results=[],
        duplicate_candidates=[],
    )

    assert result["dashboard_id"] == "db_dq_1"
    assert created["dashboard_type"] == "data_quality"
    assert created["run_id"] == "run_1"
    assert isinstance(created["chart_plan"], list)
    assert result["summary_view"]["title"] == "Executive Summary"


def test_detect_duplicate_candidates_collects_exact_and_fuzzy(monkeypatch) -> None:
    def fake_run_query(settings, sql, params, scoped_conn=None):
        assert "duplicate_value::text" not in sql
        if "COUNT(*) AS duplicate_group_count" in sql:
            return [{"duplicate_group_count": 1, "candidate_record_count": 2, "max_group_size": 2}]
        if "duplicate_value" in sql:
            return [{"duplicate_value": "C001", "duplicate_count": 2}]
        if '"customer_name", "pincode"' in sql and "GROUP BY" in sql:
            return [{"customer_name": "Acme", "pincode": "560001", "duplicate_count": 2}]
        return [{"duplicate_group_count": 1, "candidate_record_count": 2, "max_group_size": 2}]

    monkeypatch.setattr(dq_duplicates, "run_query", fake_run_query)

    candidates = dq_duplicates.detect_duplicate_candidates(
        object(),
        profiling={
            "tables": [
                {
                    "name": "customer",
                    "candidate_keys": [{"column": "customer_id", "duplicate_count": 2, "uniqueness_ratio": 0.8}],
                    "column_profiles": [{"name": "customer_name"}, {"name": "pincode"}],
                    "sample_values": {"customer_name": ["Acme Ltd", "Acme  Ltd", "Beta Co", "Beta-Co"]},
                    "fuzzy_duplicate_signals": [
                        {
                            "column": "customer_name",
                            "raw_unique_sample_count": 4,
                            "normalized_unique_sample_count": 2,
                            "duplicate_pressure": 0.5,
                            "risk_level": "high",
                        }
                    ],
                }
            ]
        },
        schema_name="public",
        scoped_conn=None,
        quality_run_id="dqrun_1",
        run_id="run_1",
        tenant_id="tenant",
        domain_id="data_quality_observability",
    )

    assert any(item["duplicate_type"] == "exact_key_duplicate" for item in candidates)
    assert any(item["duplicate_type"] == "exact_composite_duplicate" for item in candidates)
    assert any(item["duplicate_type"] == "fuzzy_duplicate_signal" for item in candidates)


def test_analyze_freshness_and_stability_compares_previous_snapshot() -> None:
    result = dq_freshness.analyze_freshness_and_stability(
        profiling={
            "tables": [
                {
                    "name": "customer",
                    "row_count": 120,
                    "quality_summary": {
                        "row_count": 120,
                        "table_completeness_score": 80.0,
                        "primary_time_column": "updated_at",
                        "latest_timestamp": "2026-04-18T10:00:00Z",
                        "freshness_lag_days": 9.0,
                    },
                }
            ]
        },
        previous_tables_by_name={
            "customer": {
                "quality_run_id": "dqrun_prev",
                "row_count": 90,
                "completeness_score": 95.0,
                "summary_json": {"quality_summary": {"row_count": 90, "table_completeness_score": 95.0}},
            }
        },
    )

    row = result["results"][0]
    assert row["freshness_status"] == "stale"
    assert row["stability_status"] == "changed"
    assert row["row_count_change_pct"] == 33.33
    assert row["completeness_score_change"] == -15.0
    assert result["summary"]["stale_table_count"] == 1
    assert result["summary"]["stability_issue_count"] == 1


def test_compute_data_quality_trust_scores_uses_all_major_components() -> None:
    result = dq_trust.compute_data_quality_trust_scores(
        quality_tables=[
            {
                "table_name": "customer",
                "row_count": 100.0,
                "completeness_score": 80.0,
                "freshness_score": 70.0,
                "duplicate_risk_score": 85.0,
            }
        ],
        quality_rules=[
            {"table_name": "customer", "rule_type": "not_null", "result_status": "failed", "checked_row_count": 100, "violation_count": 10},
            {"table_name": "customer", "rule_type": "referential_integrity", "result_status": "failed", "checked_row_count": 100, "violation_count": 5},
        ],
        duplicate_candidates=[
            {"table_name": "customer", "duplicate_type": "exact_key_duplicate", "candidate_record_count": 8},
            {"table_name": "customer", "duplicate_type": "fuzzy_duplicate_signal", "candidate_record_count": 2},
        ],
        freshness_results=[
            {
                "table_name": "customer",
                "freshness_score": 70.0,
                "freshness_status": "stale",
                "stability_status": "changed",
                "row_count_change_pct": 25.0,
                "completeness_score_change": -12.0,
            }
        ],
        enrichment_opportunities=[
            {"table_name": "customer"},
            {"table_name": "customer"},
        ],
    )

    table = result["tables"][0]
    assert table["validity_score"] == 90.0
    assert table["referential_integrity_score"] == 95.0
    assert table["uniqueness_score"] == 92.0
    assert table["freshness_score"] == 70.0
    assert table["trust_components"]["enrichment_readiness"] == 80.0
    assert table["trust_score"] is not None
    assert result["summary"]["average_table_trust_score"] == table["trust_score"]


def test_discover_enrichment_opportunities_from_location_columns() -> None:
    opportunities = dq_enrichment.discover_enrichment_opportunities(
        {
            "tables": [
                {
                    "name": "customer",
                    "column_profiles": [
                        {"name": "state", "null_count": 3, "blank_count": 1},
                        {"name": "country", "null_count": 2, "blank_count": 0},
                        {"name": "pincode", "null_count": 0, "blank_count": 0},
                        {"name": "country_code", "null_count": 0, "blank_count": 0},
                    ],
                }
            ]
        },
        quality_run_id="dqrun_1",
        run_id="run_1",
        tenant_id="tenant",
        domain_id="data_quality_observability",
    )

    by_target = {item["target_column"]: item for item in opportunities}
    assert "state" in by_target
    assert by_target["state"]["candidate_method"] == "postal_context_inference"
    assert by_target["state"]["target_column_alias"] == "state"
    assert by_target["state"]["source_column_aliases_json"] == ["postal_code", "country"]
    assert by_target["state"]["requires_external_lookup"] is False
    assert by_target["country"]["candidate_method"] == "country_code_normalization"


def test_discover_enrichment_opportunities_for_new_generic_types() -> None:
    opportunities = dq_enrichment.discover_enrichment_opportunities(
        {
            "tables": [
                {
                    "name": "customer",
                    "column_profiles": [
                        {"name": "status", "null_count": 4, "blank_count": 0},
                        {"name": "status_code", "null_count": 0, "blank_count": 0},
                        {"name": "full_name", "null_count": 3, "blank_count": 0},
                        {"name": "first_name", "null_count": 0, "blank_count": 0},
                        {"name": "last_name", "null_count": 0, "blank_count": 0},
                        {"name": "order_year", "null_count": 5, "blank_count": 0, "data_type": "integer"},
                        {"name": "order_date", "null_count": 0, "blank_count": 0, "data_type": "date"},
                    ],
                },
                {
                    "name": "reference_data",
                    "column_profiles": [
                        {"name": "status", "null_count": 2, "blank_count": 0},
                        {"name": "status_label", "null_count": 0, "blank_count": 0},
                    ],
                },
            ]
        },
        quality_run_id="dqrun_1",
        run_id="run_1",
        tenant_id="tenant",
        domain_id="data_quality_observability",
    )

    by_table_target = {(item["table_name"], item["target_column"]): item for item in opportunities}
    assert by_table_target[("customer", "status")]["candidate_method"] == "code_to_label_derivation"
    assert by_table_target[("customer", "full_name")]["candidate_method"] == "cross_column_derivation"
    assert by_table_target[("customer", "order_year")]["candidate_method"] == "temporal_derivation"
    assert by_table_target[("reference_data", "status")]["candidate_method"] == "canonical_label_normalization"


def test_replace_quality_enrichment_opportunities_persists_rows(monkeypatch) -> None:
    calls: list[tuple[str, list[object]]] = []
    monkeypatch.setattr(dq_store, "execute_non_query", lambda settings, sql, params: calls.append((sql, params)))

    inserted = dq_store.replace_quality_enrichment_opportunities(
        object(),
        quality_run_id="dqrun_1",
        run_id="run_1",
        tenant_id="tenant",
        domain_id="data_quality_observability",
        opportunities=[
            {
                "opportunity_id": "dqeo_1",
                "table_name": "customer",
                "target_column": "state",
                "source_columns_json": ["pincode", "country"],
                "missing_count": 10,
                "candidate_method": "postal_context_inference",
                "requires_external_lookup": False,
                "requires_user_approval": True,
                "confidence": 0.82,
                "question": "Can we use existing row context to propose missing state values from pincode, country?",
                "status": "needs_user_approval",
            }
        ],
    )

    assert inserted == 1
    assert len(calls) == 2
    assert calls[1][1][5] == "customer"
    assert calls[1][1][6] == "state"


def test_build_enrichment_proposal_uses_preview_for_internal_normalization() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(dq_enrichment, "_fetch_candidate_rows", lambda *args, **kwargs: [{"__row_ref": "(1,1)", "country": "India", "country_code": None}])
    monkeypatch.setattr(dq_enrichment, "_fetch_example_rows", lambda *args, **kwargs: [{"country": "India", "country_code": "IN"}])
    proposal = dq_enrichment.build_enrichment_proposal(
        object(),
        {
            "opportunity_id": "dqeo_1",
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "table_name": "customer",
            "target_column": "country_code",
            "source_columns_json": ["country"],
            "missing_count": 12,
            "candidate_method": "country_code_normalization",
            "requires_external_lookup": False,
        },
        scoped_conn=object(),
        schema_name="public",
    )
    monkeypatch.undo()

    assert proposal["matched_count"] == 1
    assert proposal["unmatched_count"] == 0
    assert proposal["proposed_values_json"][0]["method"] == "deterministic_exact_match"
    assert proposal["proposed_values_json"][0]["proposed_value"] == "IN"


def test_build_enrichment_proposal_uses_canonical_label_normalization() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        dq_enrichment,
        "_fetch_candidate_rows",
        lambda *args, **kwargs: [{"__row_ref": "(1,1)", "status_label": "active", "status": None}],
    )
    monkeypatch.setattr(dq_enrichment, "_fetch_example_rows", lambda *args, **kwargs: [])
    proposal = dq_enrichment.build_enrichment_proposal(
        object(),
        {
            "opportunity_id": "dqeo_1",
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "table_name": "customer",
            "target_column": "status",
            "source_columns_json": ["status_label"],
            "missing_count": 1,
            "candidate_method": "canonical_label_normalization",
            "requires_external_lookup": False,
        },
        scoped_conn=object(),
        schema_name="public",
    )
    monkeypatch.undo()

    assert proposal["matched_count"] == 1
    assert proposal["target_column"] == "status"
    assert proposal["target_column_alias"] == "status"
    assert proposal["source_column_aliases_json"] == ["status"]
    assert proposal["proposed_values_json"][0]["method"] == "deterministic_canonical_normalization"
    assert proposal["proposed_values_json"][0]["proposed_value"] == "Active"
    assert proposal["proposed_values_json"][0]["target_column_alias"] == "status"


def test_build_enrichment_proposal_requires_sources_for_external_lookup() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        dq_enrichment,
        "_fetch_candidate_rows",
        lambda *args, **kwargs: [{"__row_ref": "(1,1)", "pincode": "560001", "country": "India", "state": None}],
    )
    monkeypatch.setattr(
        dq_enrichment,
        "_fetch_example_rows",
        lambda *args, **kwargs: [{"pincode": "999999", "country": "India", "state": "Known"}],
    )
    monkeypatch.setattr(
        dq_enrichment,
        "_llm_enrichment_proposals",
        lambda *args, **kwargs: [{"row_ref": "(1,1)", "proposed_value": "Karnataka", "confidence": 0.84, "rationale": "Learned from examples", "method": "llm_context_inference"}],
    )
    proposal = dq_enrichment.build_enrichment_proposal(
        object(),
        {
            "opportunity_id": "dqeo_1",
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "table_name": "customer",
            "target_column": "state",
            "source_columns_json": ["pincode", "country"],
            "missing_count": 20,
            "candidate_method": "postal_context_inference",
            "requires_external_lookup": False,
        },
        scoped_conn=object(),
        schema_name="public",
        max_records=5,
    )
    monkeypatch.undo()

    assert proposal["matched_count"] == 1
    assert proposal["unmatched_count"] == 0
    assert proposal["source_references_json"][1]["provider"] == "llm_context_inference"
    assert proposal["proposed_values_json"][0]["proposed_value"] == "Karnataka"


def test_build_enrichment_proposal_uses_cross_column_derivation() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        dq_enrichment,
        "_fetch_candidate_rows",
        lambda *args, **kwargs: [{"__row_ref": "(1,1)", "first_name": "Ada", "last_name": "Lovelace", "full_name": None}],
    )
    monkeypatch.setattr(dq_enrichment, "_fetch_example_rows", lambda *args, **kwargs: [])
    proposal = dq_enrichment.build_enrichment_proposal(
        object(),
        {
            "opportunity_id": "dqeo_1",
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "table_name": "customer",
            "target_column": "full_name",
            "source_columns_json": ["first_name", "last_name"],
            "missing_count": 1,
            "candidate_method": "cross_column_derivation",
            "requires_external_lookup": False,
        },
        scoped_conn=object(),
        schema_name="public",
    )
    monkeypatch.undo()

    assert proposal["matched_count"] == 1
    assert proposal["proposed_values_json"][0]["method"] == "deterministic_cross_column_derivation"
    assert proposal["proposed_values_json"][0]["proposed_value"] == "Ada Lovelace"


def test_canonical_column_aliases_preserve_physical_name_and_expose_semantic_aliases() -> None:
    assert dq_enrichment.canonical_column_alias("pincode") == "postal_code"
    assert dq_enrichment.canonical_column_alias("province") == "state"
    assert dq_enrichment.canonical_column_alias("status_label") == "status"
    assert dq_enrichment.canonical_column_aliases(["pincode", "country_code"]) == ["postal_code", "country_code"]


def test_build_enrichment_question_queue_shapes_pending_and_ready_questions(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_enrichment_questions,
        "list_quality_enrichment_opportunities",
        lambda *args, **kwargs: [
            {
                "opportunity_id": "dqeo_1",
                "run_id": "run_1",
                "quality_run_id": "dqrun_1",
                "table_name": "customer",
                "target_column": "state",
                "source_columns_json": ["pincode", "country"],
                "missing_count": 25,
                "candidate_method": "postal_context_inference",
                "confidence": 0.88,
                "question": "Can we use existing row context to propose missing state values from pincode, country?",
                "status": "needs_user_approval",
            },
            {
                "opportunity_id": "dqeo_2",
                "run_id": "run_1",
                "quality_run_id": "dqrun_1",
                "table_name": "customer",
                "target_column": "status",
                "source_columns_json": ["status_code"],
                "missing_count": 5,
                "candidate_method": "code_to_label_derivation",
                "confidence": 0.95,
                "question": "Can we derive status labels from existing code values in status_code?",
                "status": "proposal_generated",
            },
        ],
    )
    monkeypatch.setattr(
        dq_enrichment_questions,
        "get_latest_quality_enrichment_proposal_for_opportunity",
        lambda settings, opportunity_id, tenant_id=None: (
            {
                "proposal_id": "dqep_2",
                "status": "proposed",
                "matched_count": 4,
                "unmatched_count": 1,
            }
            if opportunity_id == "dqeo_2"
            else None
        ),
    )

    queue = dq_enrichment_questions.build_enrichment_question_queue(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
    )

    assert queue["summary"]["question_count"] == 2
    assert queue["summary"]["pending_answer_count"] == 1
    assert queue["summary"]["proposal_ready_count"] == 1
    assert queue["questions"][0]["opportunity_id"] == "dqeo_1"
    assert queue["questions"][0]["status"] == "pending_answer"
    assert queue["questions"][0]["target_column_alias"] == "state"
    assert queue["questions"][0]["source_column_aliases_json"] == ["postal_code", "country"]
    assert queue["questions"][0]["available_actions"] == ["approve", "defer", "reject"]
    ready = next(item for item in queue["questions"] if item["opportunity_id"] == "dqeo_2")
    assert ready["status"] == "proposal_ready"
    assert ready["proposal_id"] == "dqep_2"
    assert ready["available_actions"] == ["review_proposal", "defer", "reject"]


def test_build_enrichment_proposal_uses_temporal_derivation() -> None:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        dq_enrichment,
        "_fetch_candidate_rows",
        lambda *args, **kwargs: [{"__row_ref": "(1,1)", "order_date": "2026-04-18", "order_year": None}],
    )
    monkeypatch.setattr(dq_enrichment, "_fetch_example_rows", lambda *args, **kwargs: [])
    proposal = dq_enrichment.build_enrichment_proposal(
        object(),
        {
            "opportunity_id": "dqeo_1",
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "table_name": "orders",
            "target_column": "order_year",
            "source_columns_json": ["order_date"],
            "missing_count": 1,
            "candidate_method": "temporal_derivation",
            "requires_external_lookup": False,
        },
        scoped_conn=object(),
        schema_name="public",
    )
    monkeypatch.undo()

    assert proposal["matched_count"] == 1
    assert proposal["proposed_values_json"][0]["method"] == "deterministic_temporal_derivation"
    assert proposal["proposed_values_json"][0]["proposed_value"] == "2026"


def test_create_quality_enrichment_proposal_persists_row(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_store,
        "execute_returning_query",
        lambda settings, sql, params: [{"proposal_id": params[0], "status": params[6], "matched_count": params[7]}],
    )

    row = dq_store.create_quality_enrichment_proposal(
        object(),
        proposal={
            "proposal_id": "dqep_1",
            "opportunity_id": "dqeo_1",
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "status": "proposed",
            "matched_count": 1,
            "unmatched_count": 2,
            "source_references_json": [],
            "proposed_values_json": [],
        },
    )

    assert row["proposal_id"] == "dqep_1"
    assert row["status"] == "proposed"
    assert row["matched_count"] == 1


def test_summarize_enrichment_proposal_groups_and_buckets() -> None:
    summary = dq_enrichment.summarize_enrichment_proposal(
        {
            "matched_count": 4,
            "unmatched_count": 2,
            "proposed_values_json": [
                {"row_ref": "(1,1)", "proposed_value": "Karnataka", "confidence": 0.99, "method": "deterministic_exact_match", "source_values": {"pincode": "560001"}},
                {"row_ref": "(1,2)", "proposed_value": "Karnataka", "confidence": 0.91, "method": "llm_context_inference", "source_values": {"pincode": "560001"}},
                {"row_ref": "(1,3)", "proposed_value": "Maharashtra", "confidence": 0.88, "method": "llm_context_inference", "source_values": {"pincode": "400001"}},
                {"row_ref": "(1,4)", "proposed_value": "Unknown", "confidence": 0.62, "method": "llm_context_inference", "source_values": {"pincode": "000000"}},
            ],
        }
    )

    assert summary["total_candidate_rows"] == 6
    assert summary["confidence_buckets"] == {
        "auto_approve": 1,
        "high_confidence": 2,
        "needs_review": 1,
    }
    assert summary["grouped_values"][0]["proposed_value"] == "Karnataka"
    assert summary["grouped_values"][0]["row_count"] == 2


def test_select_enrichment_rows_for_application_filters_by_scope_and_threshold() -> None:
    proposal = {
        "proposed_values_json": [
            {"row_ref": "(1,1)", "proposed_value": "Karnataka", "confidence": 0.99, "method": "deterministic_exact_match"},
            {"row_ref": "(1,2)", "proposed_value": "Karnataka", "confidence": 0.91, "method": "llm_context_inference"},
            {"row_ref": "(1,3)", "proposed_value": "Unknown", "confidence": 0.62, "method": "llm_context_inference"},
        ]
    }

    deterministic = dq_enrichment.select_enrichment_rows_for_application(proposal, approval_scope="deterministic_only")
    assert len(deterministic["approved_rows"]) == 1
    assert len(deterministic["deferred_rows"]) == 2

    thresholded = dq_enrichment.select_enrichment_rows_for_application(proposal, approval_scope="high_confidence", min_confidence=0.9)
    assert len(thresholded["approved_rows"]) == 2
    assert len(thresholded["deferred_rows"]) == 1


def test_build_staged_enrichment_overlay_artifact_contains_rows_and_policy() -> None:
    artifact = dq_enrichment.build_staged_enrichment_overlay_artifact(
        {
            "proposal_id": "dqep_1",
            "opportunity_id": "dqeo_1",
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "table_name": "customer",
            "target_column": "state",
            "source_references_json": [{"provider": "llm_context_inference"}],
        },
        selection={
            "approval_scope": "high_confidence",
            "confidence_threshold": 0.85,
            "approved_rows": [
                {"row_ref": "(1,1)", "proposed_value": "Karnataka", "confidence": 0.91, "table_name": "customer", "target_column": "state"},
            ],
            "deferred_rows": [
                {"row_ref": "(1,2)", "proposed_value": "Unknown", "confidence": 0.61, "table_name": "customer", "target_column": "state"},
            ],
        },
        approved_by="user_1",
        application_mode="staged_overlay",
        reason="Reviewed confidence buckets",
    )

    assert artifact["artifact_type"] == "data_quality_staged_overlay"
    assert artifact["approved_row_count"] == 1
    assert artifact["deferred_row_count"] == 1
    assert artifact["approval_scope"] == "high_confidence"
    assert artifact["summary"]["source_references"][0]["provider"] == "llm_context_inference"


def test_get_agent_event_artifact_by_logical_event_id_filters_stage(monkeypatch) -> None:
    captured: dict = {}

    def fake_run_query(settings, sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return [{"artifact_id": "artifact_1", "logical_event_id": params[1], "stage_name": params[2]}]

    monkeypatch.setattr(agentic_store, "run_query", fake_run_query)
    row = agentic_store.get_agent_event_artifact_by_logical_event_id(
        object(),
        "run_1",
        "dq_stage::dqep_1",
        stage_name="staged_overlay",
    )

    assert row["artifact_id"] == "artifact_1"
    assert captured["params"] == ["run_1", "dq_stage::dqep_1", "staged_overlay"]
    assert "logical_event_id = %s" in captured["sql"]


def test_run_data_quality_agentic_workflow_minimal(monkeypatch) -> None:
    if dq_orchestrator.StateGraph is None:
        pytest.skip("LangGraph is not installed")

    events: list[dict] = []
    monkeypatch.setattr(dq_orchestrator, "append_agent_run_event", lambda settings, run_id, agent, status, msg, artifacts=None: f"event_{agent}")
    monkeypatch.setattr(dq_orchestrator, "append_agent_chat_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "create_or_update_quality_run", lambda *args, **kwargs: "dqrun_1")
    monkeypatch.setattr(dq_orchestrator, "persist_schema_graph_artifact", lambda *args, **kwargs: "sg_1")
    monkeypatch.setattr(dq_orchestrator, "persist_table_profile_artifact", lambda *args, **kwargs: "tp_1")
    monkeypatch.setattr(
        dq_orchestrator,
        "detect_duplicate_candidates",
        lambda *args, **kwargs: [{"table_name": "customer", "duplicate_type": "exact_key_duplicate"}],
    )
    monkeypatch.setattr(dq_orchestrator, "replace_quality_duplicate_candidates", lambda *args, **kwargs: 1)
    monkeypatch.setattr(dq_orchestrator, "get_previous_quality_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "list_quality_tables_by_quality_run", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dq_orchestrator,
        "list_quality_tables",
        lambda *args, **kwargs: [
            {"table_name": "customer", "row_count": 10, "completeness_score": 100.0, "freshness_score": 90.0, "duplicate_risk_score": 100.0, "summary_json": {}}
        ],
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "analyze_freshness_and_stability",
        lambda **kwargs: {
            "results": [{"table_name": "customer", "freshness_score": 90.0}],
            "summary": {"stale_table_count": 0, "tables_without_freshness_column_count": 0, "stability_issue_count": 0},
        },
    )
    monkeypatch.setattr(dq_orchestrator, "update_quality_table_monitoring", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        dq_orchestrator,
        "compute_data_quality_trust_scores",
        lambda **kwargs: {
            "tables": [{"table_name": "customer", "trust_score": 88.0, "severity": "good"}],
            "summary": {"average_table_trust_score": 88.0, "low_trust_tables_count": 0, "critical_issue_count": 0, "warning_issue_count": 0},
        },
    )
    monkeypatch.setattr(dq_orchestrator, "update_quality_table_trust_scores", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "replace_quality_dataset_stages", lambda *args, **kwargs: len(kwargs.get("stages") or []))
    monkeypatch.setattr(dq_orchestrator, "replace_quality_join_artifacts", lambda *args, **kwargs: len(kwargs.get("joins") or []))
    monkeypatch.setattr(dq_orchestrator, "replace_quality_stage_row_outcomes", lambda *args, **kwargs: len(kwargs.get("row_outcomes") or []))
    monkeypatch.setattr(dq_orchestrator, "upsert_quality_final_dataset_artifact", lambda *args, **kwargs: "dqfinal_1")
    monkeypatch.setattr(dq_orchestrator, "list_quality_trends", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_issues", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dq_orchestrator,
        "_persist_trend_artifacts",
        lambda *args, **kwargs: {"baseline_run_id": None, "trends": [], "summary": {"trend_row_count": 0, "improved_metric_count": 0, "worsened_metric_count": 0}},
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "_persist_issue_artifacts",
        lambda *args, **kwargs: {"issues": [], "summary": {"issue_count": 0, "open_issue_count": 0, "overdue_issue_count": 0}},
    )
    monkeypatch.setattr(dq_orchestrator, "replace_quality_rules", lambda *args, **kwargs: 0)
    monkeypatch.setattr(dq_orchestrator, "execute_quality_rules", lambda *args, **kwargs: {"rules_executed": 0, "failed_rules": 0, "passed_rules": 0, "error_rules": 0, "results": []})
    monkeypatch.setattr(
        dq_orchestrator,
        "create_data_quality_dashboard",
        lambda *args, **kwargs: {"dashboard_id": "db_dq_1", "dashboard_title": "DQ Dashboard", "chart_plan": [{"chart_key": "data_trust_scorecard"}]},
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "discover_enrichment_opportunities",
        lambda *args, **kwargs: [
            {
                "opportunity_id": "dqeo_1",
                "table_name": "customer",
                "target_column": "state",
                "requires_external_lookup": False,
            }
        ],
    )
    monkeypatch.setattr(dq_orchestrator, "replace_quality_enrichment_opportunities", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        dq_orchestrator,
        "build_schema_graph",
        lambda payload: {"tables": [{"name": "customer", "columns": [{"name": "email", "data_type": "text"}]}]},
    )
    monkeypatch.setattr(dq_orchestrator, "enrich_schema_graph_columns", lambda *args, **kwargs: args[1])
    monkeypatch.setattr(
        dq_orchestrator,
        "profile_tables",
        lambda *args, **kwargs: {
            "quality_overview": {"average_table_trust_score": 80.0, "low_trust_tables_count": 0},
            "tables": [
                {
                    "name": "customer",
                    "quality_summary": {"table_trust_score": 80.0},
                    "column_profiles": [{"name": "email", "completeness_score": 100.0}],
                }
            ],
        },
    )
    monkeypatch.setattr(dq_orchestrator, "upsert_quality_artifacts_from_profiling", lambda *args, **kwargs: {"tables": 1, "columns": 1})

    result = dq_orchestrator.run_data_quality_agentic_workflow(
        object(),
        "run_1",
        {
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "schema_payload": {},
            "schema_name": "public",
        },
        event_callback=lambda event: events.append(event),
    )

    assert result["workflow_kind"] == "data_quality"
    assert result["quality_summary"]["profiled_tables"] == 1
    assert result["quality_summary"]["duplicate_candidate_count"] == 1
    assert result["quality_summary"]["average_table_trust_score"] == 88.0
    assert result["quality_summary"]["stale_table_count"] == 0
    assert result["quality_summary"]["dashboard_id"] == "db_dq_1"
    assert result["quality_summary"]["enrichment_opportunity_count"] == 1
    assert result["quality_summary"]["dataset_stage_count"] >= 2
    assert [event["agent_name"] for event in events] == [
        "DataQualityWorkflowRouter",
        "DataQualitySchemaAgent",
        "DataQualitySchemaAgent",
        "DatasetStagePlannerAgent",
        "DatasetStagePlannerAgent",
        "DataQualityProfilingAgent",
        "DataQualityProfilingAgent",
        "DuplicateDetectionAgent",
        "DuplicateDetectionAgent",
        "FreshnessAndStabilityAgent",
        "FreshnessAndStabilityAgent",
        "DataQualityRuleAgent",
        "DataQualityRuleAgent",
        "DataEnrichmentOpportunityAgent",
        "DataEnrichmentOpportunityAgent",
        "DataTrustScoringAgent",
        "TrendAnalysisAgent",
        "TrendAnalysisAgent",
        "DataQualityDashboardAgent",
        "DataQualityDashboardAgent",
    ]


def test_run_data_quality_agentic_workflow_pauses_for_rule_review(monkeypatch) -> None:
    if dq_orchestrator.StateGraph is None:
        pytest.skip("LangGraph is not installed")

    events: list[dict] = []
    statuses: list[str] = []
    monkeypatch.setattr(dq_orchestrator, "append_agent_run_event", lambda settings, run_id, agent, status, msg, artifacts=None: f"event_{agent}")
    monkeypatch.setattr(dq_orchestrator, "append_agent_chat_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        dq_orchestrator,
        "create_or_update_quality_run",
        lambda *args, **kwargs: statuses.append(kwargs.get("status")) or "dqrun_1",
    )
    monkeypatch.setattr(dq_orchestrator, "persist_schema_graph_artifact", lambda *args, **kwargs: "sg_1")
    monkeypatch.setattr(dq_orchestrator, "persist_table_profile_artifact", lambda *args, **kwargs: "tp_1")
    monkeypatch.setattr(dq_orchestrator, "replace_quality_dataset_stages", lambda *args, **kwargs: len(kwargs.get("stages") or []))
    monkeypatch.setattr(dq_orchestrator, "replace_quality_join_artifacts", lambda *args, **kwargs: len(kwargs.get("joins") or []))
    monkeypatch.setattr(dq_orchestrator, "replace_quality_stage_row_outcomes", lambda *args, **kwargs: len(kwargs.get("row_outcomes") or []))
    monkeypatch.setattr(dq_orchestrator, "upsert_quality_final_dataset_artifact", lambda *args, **kwargs: "dqfinal_1")
    monkeypatch.setattr(dq_orchestrator, "detect_duplicate_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "replace_quality_duplicate_candidates", lambda *args, **kwargs: 0)
    monkeypatch.setattr(dq_orchestrator, "get_previous_quality_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "list_quality_tables_by_quality_run", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_tables", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dq_orchestrator,
        "analyze_freshness_and_stability",
        lambda **kwargs: {"results": [], "summary": {"stale_table_count": 0, "tables_without_freshness_column_count": 0, "stability_issue_count": 0}},
    )
    monkeypatch.setattr(dq_orchestrator, "update_quality_table_monitoring", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "update_quality_table_trust_scores", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "replace_quality_rules", lambda *args, **kwargs: len(kwargs.get("rules") or []))
    monkeypatch.setattr(
        dq_orchestrator,
        "execute_quality_rules",
        lambda *args, **kwargs: pytest.fail("rules should not execute before review"),
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "build_schema_graph",
        lambda payload: {"tables": [{"name": "customer", "columns": [{"name": "status", "data_type": "text"}]}]},
    )
    monkeypatch.setattr(dq_orchestrator, "enrich_schema_graph_columns", lambda *args, **kwargs: args[1])
    monkeypatch.setattr(
        dq_orchestrator,
        "profile_tables",
        lambda *args, **kwargs: {
            "quality_overview": {"average_table_trust_score": 80.0, "low_trust_tables_count": 0},
            "tables": [
                {
                    "name": "customer",
                    "quality_summary": {"table_trust_score": 80.0},
                    "column_profiles": [{"name": "status", "completeness_score": 100.0}],
                }
            ],
        },
    )
    monkeypatch.setattr(dq_orchestrator, "upsert_quality_artifacts_from_profiling", lambda *args, **kwargs: {"tables": 1, "columns": 1})
    monkeypatch.setattr(
        dq_orchestrator,
        "extract_quality_rules_from_context",
        lambda *args, **kwargs: [
            {
                "rule_id": "rule_1",
                "rule_type": "allowed_values",
                "table_name": "customer",
                "column_name": "status",
                "condition_json": {},
                "confidence": 0.41,
            }
        ],
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "build_quality_rule_execution_plan",
        lambda rule, schema_name, settings=None: {"executor_kind": "deterministic_sql", "sql_preview_status": "available"},
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "classify_quality_rule_review_status",
        lambda rule: "needs_review",
    )

    result = dq_orchestrator.run_data_quality_agentic_workflow(
        object(),
        "run_pause_1",
        {
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "schema_payload": {},
            "schema_name": "public",
            "context_text": "customer.status should be valid",
            "pause_for_rule_review": True,
        },
        event_callback=lambda event: events.append(event),
    )

    assert result["run_status"] == "awaiting_rule_review"
    assert result["quality_summary"]["rule_review_required"] is True
    assert result["quality_summary"]["review_queue_pending_count"] == 1
    assert "awaiting_rule_review" in statuses
    assert [event["agent_name"] for event in events][-2:] == ["DataQualityRuleAgent", "DataQualityReviewGate"]


def test_resume_data_quality_agentic_workflow_after_rule_review_completes(monkeypatch) -> None:
    events: list[dict] = []
    statuses: list[str] = []
    monkeypatch.setattr(dq_orchestrator, "append_agent_run_event", lambda settings, run_id, agent, status, msg, artifacts=None: f"event_{agent}")
    monkeypatch.setattr(dq_orchestrator, "append_agent_chat_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        dq_orchestrator,
        "create_or_update_quality_run",
        lambda *args, **kwargs: statuses.append(kwargs.get("status")) or "dqrun_resume_1",
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "get_quality_run_by_run_id",
        lambda settings, run_id: {
            "quality_run_id": "dqrun_resume_1",
            "run_id": run_id,
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "connection_id": "conn_1",
            "database_name": "db_1",
            "schema_name": "public",
            "status": "awaiting_rule_review",
            "summary_json": {"persisted": {"tables": 1, "columns": 1}},
        },
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "get_table_profile_artifact",
        lambda *args, **kwargs: {
            "profiling_json": {
                "quality_overview": {"average_table_trust_score": 80.0, "low_trust_tables_count": 0},
                "tables": [
                    {
                        "name": "customer",
                        "quality_summary": {"table_trust_score": 80.0},
                        "column_profiles": [{"name": "status", "completeness_score": 100.0}],
                    }
                ],
            }
        },
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "list_quality_rules",
        lambda *args, **kwargs: [
            {
                "rule_id": "rule_1",
                "rule_type": "allowed_values",
                "table_name": "customer",
                "column_name": "status",
                "status": "active",
                "schema_name": "public",
                "condition_json": {"allowed_values": ["ACTIVE", "INACTIVE"]},
            }
        ],
    )
    monkeypatch.setattr(dq_orchestrator, "_resolve_scoped_conn_from_scope", lambda settings, scope: None)
    monkeypatch.setattr(
        dq_orchestrator,
        "execute_quality_rules",
        lambda *args, **kwargs: {
            "rules_executed": 1,
            "failed_rules": 0,
            "passed_rules": 1,
            "error_rules": 0,
            "results": [{"rule_id": "rule_1", "status": "passed", "checked_row_count": 10, "violation_count": 0, "violation_pct": 0.0}],
        },
    )
    monkeypatch.setattr(dq_orchestrator, "list_quality_duplicate_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dq_orchestrator,
        "list_quality_tables",
        lambda *args, **kwargs: [
            {
                "table_name": "customer",
                "row_count": 10,
                "completeness_score": 100.0,
                "freshness_score": 90.0,
                "duplicate_risk_score": 100.0,
                "summary_json": {
                    "freshness_analysis": {"freshness_status": "fresh", "freshness_score": 90.0},
                    "stability_analysis": {"stability_status": "stable", "row_count_change_pct": 0.0, "completeness_score_change": 0.0},
                },
            }
        ],
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "discover_enrichment_opportunities",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(dq_orchestrator, "replace_quality_enrichment_opportunities", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        dq_orchestrator,
        "compute_data_quality_trust_scores",
        lambda **kwargs: {
            "tables": [{"table_name": "customer", "trust_score": 92.0, "severity": "good"}],
            "summary": {"average_table_trust_score": 92.0, "low_trust_tables_count": 0, "critical_issue_count": 0, "warning_issue_count": 0},
        },
    )
    monkeypatch.setattr(dq_orchestrator, "update_quality_table_trust_scores", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "list_quality_dataset_stages", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_join_artifacts", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_lineage_edges", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_stage_row_outcomes", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_trends", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_issues", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "get_quality_final_dataset_artifact", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        dq_orchestrator,
        "_persist_trend_artifacts",
        lambda *args, **kwargs: {"baseline_run_id": None, "trends": [], "summary": {"trend_row_count": 0, "improved_metric_count": 0, "worsened_metric_count": 0}},
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "_persist_issue_artifacts",
        lambda *args, **kwargs: {"issues": [], "summary": {"issue_count": 0, "open_issue_count": 0, "overdue_issue_count": 0}},
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "create_data_quality_dashboard",
        lambda *args, **kwargs: {
            "dashboard_id": "db_dq_1",
            "dashboard_title": "DQ Dashboard",
            "chart_plan": [{"chart_key": "data_trust_scorecard"}],
            "open_issue_count": 0,
            "overdue_issue_count": 0,
        },
    )

    result = dq_orchestrator.resume_data_quality_agentic_workflow_after_rule_review(
        object(),
        "run_resume_1",
        event_callback=lambda event: events.append(event),
    )

    assert result["run_status"] == "completed"
    assert result["quality_summary"]["average_table_trust_score"] == 92.0
    assert result["quality_summary"]["rule_review_required"] is False
    assert result["quality_summary"]["workflow_status"] == "completed"
    assert statuses[0] == "running"
    assert statuses[-1] == "completed"
    assert [event["agent_name"] for event in events] == [
        "DataQualityRuleAgent",
        "DataQualityRuleAgent",
        "DataEnrichmentOpportunityAgent",
        "DataEnrichmentOpportunityAgent",
        "DataTrustScoringAgent",
        "DataTrustScoringAgent",
        "TrendAnalysisAgent",
        "TrendAnalysisAgent",
        "IssueRegisterAgent",
        "IssueRegisterAgent",
        "DataQualityDashboardAgent",
        "DataQualityDashboardAgent",
    ]


def test_build_data_quality_workspace_response_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_workspace,
        "get_quality_run_by_run_id",
        lambda settings, run_id: {
            "quality_run_id": "dqrun_1",
            "run_id": run_id,
            "overall_trust_score": 74.2,
            "summary_json": {
                "critical_issue_count": 2,
                "warning_issue_count": 4,
                "enrichment_opportunity_count": 1,
            },
        },
    )
    monkeypatch.setattr(
        dq_workspace,
        "list_quality_tables",
        lambda *args, **kwargs: [
            {"table_name": "customer", "trust_score": 61.0, "severity": "critical"},
            {"table_name": "orders", "trust_score": 82.0, "severity": "warning"},
        ],
    )
    monkeypatch.setattr(
        dq_workspace,
        "list_quality_rules",
        lambda *args, **kwargs: [
            {
                "rule_id": "rule_1",
                "rule_type": "referential_integrity",
                "severity": "critical",
                "table_name": "orders",
                "column_name": "customer_id",
                "result_status": "failed",
                "violation_count": 12,
                "violation_pct": 6.0,
            }
        ],
    )
    monkeypatch.setattr(dq_workspace, "list_quality_duplicate_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_workspace, "list_quality_enrichment_opportunities", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dq_workspace,
        "build_data_quality_remediation_plan",
        lambda *args, **kwargs: {
            "summary": {"action_count": 2, "critical_action_count": 1},
            "actions": [
                {
                    "priority": "critical",
                    "action_type": "missingness_backfill",
                    "title": "Backfill customer.email",
                    "evidence_path": "/data-quality/evidence/missingness?tenant_id=tenant&run_id=run_1&table_name=customer&column_name=email",
                }
            ],
        },
    )

    response = dq_workspace.build_data_quality_workspace_response(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        question="what are the top data quality issues?",
    )

    assert response is not None
    payload, assistant_text, summary_json, inference_json = response
    assert payload["conversation_plan"]["sql_mode"] == "data_quality_artifacts"
    assert payload["conversation_plan"]["remediation_action_count"] == 2
    assert payload["chart_title"] == "Top Data Quality Issues"
    assert payload["data_quality"]["artifacts"]["dashboard"] == "/data-quality/runs/run_1/dashboard"
    assert payload["data_quality"]["artifacts"]["remediation"].startswith("/data-quality/remediation")
    assert payload["data_quality"]["remediation_summary"]["critical_action_count"] == 1
    assert payload["data_quality"]["recommended_actions"][0]["action_type"] == "missingness_backfill"
    assert payload["rows"][0]["issue_type"] in {"table_trust", "rule_failure"}
    assert "Overall trust score is 74.2" in assistant_text
    assert summary_json["data_quality"]["quality_run_id"] == "dqrun_1"
    assert payload["artifact_lineage"]["remediation"].startswith("/data-quality/remediation")
    assert inference_json["artifact_lineage"]["excel_report"].startswith("/data-quality/reports/run_1/excel")
    assert inference_json["artifact_lineage"]["csv_report"].startswith("/data-quality/reports/run_1/csv")


def test_build_data_quality_run_summary_payload_includes_artifacts_and_recommended_actions() -> None:
    response = dq_api_payloads.build_data_quality_run_summary_payload(
        row={
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
                "domain_id": "data_quality_observability",
                "connection_id": "conn_1",
                "database_name": "db_1",
                "schema_name": "public",
                "status": "awaiting_rule_review",
                "overall_trust_score": 78.4,
                "summary_json": {
                "critical_issue_count": 2,
                "warning_issue_count": 4,
                "active_rule_count": 3,
                "needs_review_rule_count": 1,
                "rule_review_required": True,
                "review_queue_pending_count": 1,
                "workflow_status": "awaiting_rule_review",
                "dataset_stage_count": 5,
                "join_stage_count": 1,
                "filter_stage_count": 1,
                "lineage_edge_count": 2,
                "rule_validation_planner_mode": "llm",
                "validation_control_count": 9,
                "compiled_validation_control_count": 6,
                "uncovered_validation_control_count": 3,
                "total_rejected_row_count": 2,
                "final_dataset_row_count": 10,
                "final_dataset_readiness_status": "ready",
                "remediation_action_count": 6,
                "critical_remediation_action_count": 2,
            },
        },
        remediation_plan={
            "summary": {"action_count": 6, "critical_action_count": 2},
            "actions": [
                {
                    "priority": "critical",
                    "action_type": "freshness_recovery",
                    "title": "Restore freshness for customer",
                }
            ],
        },
    )

    assert response["artifacts"]["dashboard"] == "/data-quality/runs/run_1/dashboard"
    assert response["artifacts"]["csv_report"].startswith("/data-quality/reports/run_1/csv")
    assert response["artifacts"]["stages"].endswith("run_id=run_1")
    assert response["artifacts"]["joins"].endswith("run_id=run_1")
    assert response["artifacts"]["rejected_records"].endswith("run_id=run_1")
    assert response["artifacts"]["final_dataset"].endswith("run_id=run_1")
    assert response["artifacts"]["lineage_base"].endswith("run_id=run_1")
    assert response["artifacts"]["rule_review_queue"].endswith("run_id=run_1")
    assert response["artifacts"]["rule_coverage"].endswith("run_id=run_1")
    assert response["artifacts"]["resume_after_rule_review"] == "/data-quality/runs/run_1/resume-after-rule-review"
    assert response["artifacts"]["enrichment_questions"].endswith("run_id=run_1")
    assert response["active_rule_count"] == 3
    assert response["needs_review_rule_count"] == 1
    assert response["rule_review_required"] is True
    assert response["workflow_status"] == "awaiting_rule_review"
    assert response["dataset_stage_count"] == 5
    assert response["join_stage_count"] == 1
    assert response["filter_stage_count"] == 1
    assert response["lineage_edge_count"] == 2
    assert response["rule_validation_planner_mode"] == "llm"
    assert response["validation_control_count"] == 9
    assert response["compiled_validation_control_count"] == 6
    assert response["uncovered_validation_control_count"] == 3
    assert response["total_rejected_row_count"] == 2
    assert response["final_dataset_row_count"] == 10
    assert response["final_dataset_readiness_status"] == "ready"
    assert response["artifacts"]["remediation"].startswith("/data-quality/remediation?tenant_id=tenant")
    assert response["remediation_summary"]["action_count"] == 6
    assert response["recommended_actions"][0]["action_type"] == "freshness_recovery"


def test_build_data_quality_run_summary_payload_overrides_terminal_workflow_status() -> None:
    response = dq_api_payloads.build_data_quality_run_summary_payload(
        row={
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "status": "completed",
            "summary_json": {"workflow_status": "running"},
        },
        remediation_plan={"summary": {}, "actions": []},
    )

    assert response["workflow_status"] == "completed"
    assert response["summary"]["workflow_status"] == "completed"


def test_build_data_quality_rule_outcome_payload_adds_passed_counts_and_evidence() -> None:
    payload = dq_api_payloads.build_data_quality_rule_outcome_payload(
        row={
            "rule_id": "rule_1",
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "rule_type": "not_null",
            "rule_label": "customer.email is required",
            "severity": "critical",
            "table_name": "customer",
            "column_name": "email",
            "status": "active",
            "result_id": "res_1",
            "result_status": "failed",
            "checked_row_count": 10,
            "violation_count": 2,
            "violation_pct": 20.0,
            "sample_rows_json": [{"email": None}],
        },
        tenant_id="tenant",
        domain_id="data_quality_observability",
    )

    assert payload["dimension"] == "completeness"
    assert payload["result"]["passed_row_count"] == 8
    assert payload["result"]["pass_pct"] == 80.0
    assert payload["result"]["result_status"] == "failed"
    assert payload["evidence"]["failed_records"].startswith("/data-quality/runs/run_1/rules/rule_1/failed-records")
    assert payload["result"]["evidence"]["passed_records"].startswith("/data-quality/runs/run_1/rules/rule_1/passed-records")


def test_build_filter_predicate_supports_in_like_and_age_between() -> None:
    predicate, params = dq_stages._build_filter_predicate(
        {
            "table_name": "customer_data",
            "column_name": "account_type",
            "operator": "IN",
            "value": ["Savings", "Current", "Business"],
        }
    )
    assert predicate == '"account_type"::text IN (%s, %s, %s)'
    assert params == ["Savings", "Current", "Business"]

    predicate, params = dq_stages._build_filter_predicate(
        {
            "table_name": "customer_data",
            "column_name": "email",
            "operator": "LIKE",
            "value": "%@%.%",
        }
    )
    assert predicate == '"email"::text LIKE %s'
    assert params == ["%@%.%"]

    predicate, params = dq_stages._build_filter_predicate(
        {
            "table_name": "customer_data",
            "column_name": "dob",
            "reference_column": "created_date",
            "operator": "AGE BETWEEN",
            "value": [18, 80],
        }
    )
    assert "DATE_PART('year', AGE(\"created_date\"::date, \"dob\"::date)) BETWEEN %s AND %s" == predicate
    assert params == [18, 80]


def test_fetch_rule_records_supports_not_null_failed_and_passed(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_evidence,
        "_get_rule_row",
        lambda settings, tenant_id, domain_id, rule_id: {
            "rule_id": rule_id,
            "run_id": "run_1",
            "rule_type": "not_null",
            "table_name": "customer",
            "column_name": "email",
            "condition_json": {"source_text": "customer.email is required"},
        },
    )
    monkeypatch.setattr(
        dq_evidence,
        "load_quality_run",
        lambda settings, run_id, tenant_id, domain_id: {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "domain_id": domain_id,
            "schema_name": "public",
            "connection_id": "conn_1",
        },
    )
    monkeypatch.setattr(dq_evidence, "resolve_quality_run_scoped_conn", lambda settings, run_row: object())

    calls: list[tuple[str, list[object]]] = []

    def _fake_run_query(settings, sql, params, scoped_conn=None):
        calls.append((sql, params))
        if "COUNT(*) AS affected_row_count" in sql:
            return [{"affected_row_count": 2}]
        return [{"__row_ref": "(0,1)", "email": None}]

    monkeypatch.setattr(dq_evidence, "run_query", _fake_run_query)

    failed = dq_evidence.fetch_rule_records(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        rule_id="rule_1",
        outcome="failed",
        limit=25,
        offset=0,
    )
    passed = dq_evidence.fetch_rule_records(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        rule_id="rule_1",
        outcome="passed",
        limit=25,
        offset=0,
    )

    assert failed["supported"] is True
    assert failed["affected_row_count"] == 2
    assert passed["supported"] is True
    assert any('WHERE "email" IS NULL' in sql for sql, _ in calls)
    assert any('WHERE "email" IS NOT NULL' in sql for sql, _ in calls)


def test_build_data_quality_run_hydration_payload_includes_pending_cards() -> None:
    response = dq_api_payloads.build_data_quality_run_hydration_payload(
        row={
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "status": "awaiting_rule_review",
            "summary_json": {
                "rule_review_required": True,
                "review_queue_pending_count": 2,
                "workflow_status": "awaiting_rule_review",
            },
        },
        remediation_plan={
            "summary": {"action_count": 2, "critical_action_count": 1},
            "actions": [{"action_type": "missingness_backfill", "title": "Backfill customer state"}],
        },
        rule_review_queue={
            "summary": {"needs_review_count": 2, "unsupported_count": 0},
            "rules": [
                {
                    "rule_id": "rule_1",
                    "table_name": "orders",
                    "column_name": "status",
                    "rule_type": "allowed_values",
                    "severity": "warning",
                    "confidence": 0.61,
                    "status": "needs_review",
                    "source_text": "Order status should be valid",
                    "execution_plan_json": {"sql_preview_status": "available", "sql_preview_source": "llm"},
                }
            ],
        },
        enrichment_question_queue={
            "summary": {"question_count": 1, "pending_answer_count": 1, "proposal_ready_count": 0},
            "questions": [
                {
                    "question_id": "dqeo_1",
                    "question": "Can we derive missing state values?",
                    "target_column_alias": "state",
                    "available_actions": ["approve", "defer", "reject"],
                }
            ],
        },
        lineage_overview={
            "summary": {
                "lineage_row_count": 3,
                "final_dataset_member_count": 2,
                "rejected_row_count": 1,
                "join_exception_row_count": 0,
            },
            "rows": [
                {
                    "row_lineage_id": "dqlin_1",
                    "source_table": "orders",
                    "final_state": "final_dataset_member",
                    "evidence_path": "/data-quality/lineage/dqlin_1/journey?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1",
                }
            ],
        },
        trend_overview={
            "summary": {
                "trend_row_count": 4,
                "improved_metric_count": 1,
                "worsened_metric_count": 2,
            },
            "trends": [
                {
                    "object_type": "table",
                    "object_key": "orders",
                    "object_name": "orders",
                    "metric_name": "trust_score",
                    "trend_status": "worsened",
                    "evidence_path": "/data-quality/trends/tables/orders?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1",
                }
            ],
        },
    )

    assert response["run"]["workflow_status"] == "awaiting_rule_review"
    assert response["pending_tasks"]["requires_attention"] is True
    assert response["pending_tasks"]["rule_review"]["needs_review_count"] == 2
    assert response["pending_tasks"]["rule_review"]["top_items"][0]["rule_id"] == "rule_1"
    assert response["pending_tasks"]["enrichment_questions"]["pending_answer_count"] == 1
    assert response["pending_tasks"]["enrichment_questions"]["top_items"][0]["question_id"] == "dqeo_1"
    assert response["pending_tasks"]["lineage"]["lineage_row_count"] == 3
    assert response["pending_tasks"]["lineage"]["top_items"][0]["row_lineage_id"] == "dqlin_1"
    assert response["pending_tasks"]["trends"]["trend_row_count"] == 4
    assert response["pending_tasks"]["trends"]["top_items"][0]["object_key"] == "orders"
    assert response["pending_tasks"]["business_terms"]["business_term_group_count"] == 0
    assert response["artifact_links"]["enrichment_questions"].endswith("run_id=run_1")


def test_build_data_quality_run_hydration_payload_includes_business_term_card() -> None:
    response = dq_api_payloads.build_data_quality_run_hydration_payload(
        row={
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "status": "completed",
            "summary_json": {},
        },
        business_term_overview={
            "summary": {
                "business_term_group_count": 2,
                "worsened_business_term_count": 1,
                "improved_business_term_count": 1,
                "unmatched_trend_row_count": 0,
            },
            "rows": [
                {
                    "business_term": "Customer",
                    "trend_row_count": 2,
                    "worsened_metric_count": 1,
                    "improved_metric_count": 1,
                    "evidence_path": "/data-quality/trends/business-terms?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1&term=customer",
                }
            ],
        },
    )

    assert response["pending_tasks"]["business_terms"]["business_term_group_count"] == 2
    assert response["pending_tasks"]["business_terms"]["top_items"][0]["business_term"] == "Customer"


def test_build_data_quality_workspace_response_missingness(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_workspace,
        "get_quality_run_by_run_id",
        lambda settings, run_id: {
            "quality_run_id": "dqrun_1",
            "run_id": run_id,
            "overall_trust_score": 80.0,
            "summary_json": {},
        },
    )
    monkeypatch.setattr(
        dq_workspace,
        "list_quality_tables",
        lambda *args, **kwargs: [{"table_name": "customer", "trust_score": 71.0, "severity": "warning"}],
    )
    monkeypatch.setattr(dq_workspace, "list_quality_duplicate_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_workspace, "list_quality_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_workspace, "list_quality_enrichment_opportunities", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dq_workspace,
        "get_quality_table_detail",
        lambda *args, **kwargs: {
            "table_name": "customer",
            "columns": [
                {"column_name": "state", "null_count": 35, "null_pct": 35.0, "blank_count": 0, "blank_pct": 0.0, "completeness_score": 65.0},
                {"column_name": "email", "null_count": 10, "null_pct": 10.0, "blank_count": 2, "blank_pct": 2.0, "completeness_score": 88.0},
            ],
        },
    )

    response = dq_workspace.build_data_quality_workspace_response(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        question="show missing columns for customer",
    )

    assert response is not None
    payload, assistant_text, _, _ = response
    assert payload["chart_title"] == "Missingness - customer"
    assert payload["rows"][0]["column_name"] == "state"
    assert "state at 35.0% null" in assistant_text


def test_build_data_quality_workspace_response_enrichment(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_workspace,
        "get_quality_run_by_run_id",
        lambda settings, run_id: {
            "quality_run_id": "dqrun_1",
            "run_id": run_id,
            "overall_trust_score": 80.0,
            "summary_json": {},
        },
    )
    monkeypatch.setattr(
        dq_workspace,
        "list_quality_tables",
        lambda *args, **kwargs: [{"table_name": "customer", "trust_score": 71.0, "severity": "warning"}],
    )
    monkeypatch.setattr(dq_workspace, "list_quality_duplicate_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_workspace, "list_quality_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dq_workspace,
        "list_quality_enrichment_opportunities",
        lambda *args, **kwargs: [
            {
                "opportunity_id": "dqeo_1",
                "table_name": "customer",
                "target_column": "state",
                "source_columns": ["pincode", "country"],
                "missing_count": 35000,
                "candidate_method": "postal_context_inference",
                "confidence": 0.91,
                "status": "open",
                "question": "Can we infer missing state values?",
            }
        ],
    )

    response = dq_workspace.build_data_quality_workspace_response(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        question="what enrichment opportunities need approval?",
    )

    assert response is not None
    payload, assistant_text, _, _ = response
    assert payload["chart_title"] == "Enrichment Opportunities"
    assert payload["rows"][0]["missing_count"] == 35000
    assert "1 enrichment opportunities" in assistant_text


def test_build_data_quality_workspace_response_freshness(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_workspace,
        "get_quality_run_by_run_id",
        lambda settings, run_id: {
            "quality_run_id": "dqrun_1",
            "run_id": run_id,
            "overall_trust_score": 80.0,
            "summary_json": {},
        },
    )
    monkeypatch.setattr(
        dq_workspace,
        "list_quality_tables",
        lambda *args, **kwargs: [
            {
                "table_name": "customer",
                "trust_score": 71.0,
                "severity": "warning",
                "summary_json": {
                    "freshness_analysis": {"freshness_column": "updated_at", "freshness_lag_days": 9.0, "freshness_status": "stale"},
                    "stability_analysis": {"row_count_change_pct": 25.0, "completeness_score_change": -12.0, "stability_status": "changed", "stability_issues": ["row_count_change_pct>20"]},
                },
            }
        ],
    )
    monkeypatch.setattr(dq_workspace, "list_quality_duplicate_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_workspace, "list_quality_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_workspace, "list_quality_enrichment_opportunities", lambda *args, **kwargs: [])

    response = dq_workspace.build_data_quality_workspace_response(
        object(),
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        question="which tables are stale or unstable?",
    )

    assert response is not None
    payload, assistant_text, _, _ = response
    assert payload["chart_title"] == "Freshness and Stability"
    assert payload["rows"][0]["freshness_status"] == "stale"
    assert "1 stale tables and 1 tables with stability changes" in assistant_text


def test_infer_trend_scope_key_reuses_source_run_scope() -> None:
    key, label = dq_trends.infer_trend_scope_key(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        connection_id="1",
        database_name="analytics",
        schema_name="public",
        table_names=["network_cdr_data", "mediation_data"],
        context_text="reconcile network and mediation records",
        trend_mode="monitor",
        source_run={
            "trend_scope_key": "cdr_primary_reconciliation",
            "trend_scope_label": "Primary CDR Reconciliation",
        },
    )

    assert key == "cdr_primary_reconciliation"
    assert label == "Primary CDR Reconciliation"


def test_infer_trend_scope_key_reuses_existing_monitor_scope_from_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_trends,
        "_trend_scope_llm_json",
        lambda *args, **kwargs: {
            "decision": "reuse_existing",
            "selected_existing_scope_key": "cdr_primary_reconciliation",
            "selected_existing_scope_label": "Primary CDR Reconciliation",
        },
    )

    key, label = dq_trends.infer_trend_scope_key(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        connection_id="1",
        database_name="analytics",
        schema_name="public",
        table_names=["network_cdr_data", "mediation_data", "billing_cdr_data"],
        context_text="Daily reconciliation across network, mediation, and billing CDR datasets.",
        trend_mode="monitor",
        settings=SimpleNamespace(openai_api_key="test-key", openai_model="gpt-4o-mini"),
        previous_runs=[
            {
                "run_id": "run_prev",
                "trend_scope_key": "cdr_primary_reconciliation",
                "trend_scope_label": "Primary CDR Reconciliation",
                "trend_mode": "monitor",
                "deployment_payload_json": {
                    "connection_id": "1",
                    "database": "analytics",
                    "schema_name": "public",
                    "context_text": "Prior primary reconciliation run",
                },
            }
        ],
    )

    assert key == "cdr_primary_reconciliation"
    assert label == "Primary CDR Reconciliation"


def test_infer_trend_scope_key_accepts_llm_proposed_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        dq_trends,
        "_trend_scope_llm_json",
        lambda *args, **kwargs: {
            "decision": "create_new",
            "proposed_scope_key": "Billing Readiness Daily",
            "proposed_scope_label": "Billing Readiness Daily",
        },
    )

    key, label = dq_trends.infer_trend_scope_key(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        connection_id="1",
        database_name="analytics",
        schema_name="public",
        table_names=["billing_cdr_data"],
        context_text="Monitor final billing publish readiness every day.",
        trend_mode="monitor",
        settings=SimpleNamespace(openai_api_key="test-key", openai_model="gpt-4o-mini"),
        previous_runs=[],
    )

    assert key == "billing_readiness_daily"
    assert label == "Billing Readiness Daily"


def test_build_trend_rows_compares_previous_snapshots() -> None:
    trends = dq_trends.build_trend_rows(
        current_run_id="run_new",
        baseline_run_id="run_old",
        current_snapshots=[
            {
                "object_type": "table",
                "object_key": "billing_cdr_data",
                "object_name": "billing_cdr_data",
                "metric_name": "trust_score",
                "metric_value_num": 82.0,
                "metric_unit": "score",
            }
        ],
        previous_snapshots=[
            {
                "object_type": "table",
                "object_key": "billing_cdr_data",
                "object_name": "billing_cdr_data",
                "metric_name": "trust_score",
                "metric_value_num": 74.0,
                "metric_unit": "score",
            }
        ],
    )

    assert len(trends) == 1
    assert trends[0]["baseline_run_id"] == "run_old"
    assert trends[0]["trend_status"] == "improved"
    assert trends[0]["delta_value"] == 8.0


def test_build_object_metric_snapshots_uses_business_rule_label() -> None:
    snapshots = dq_trends.build_object_metric_snapshots(
        tables=[],
        rules=[
            {
                "rule_type": "custom_sql",
                "table_name": "billing_cdr_data",
                "condition_json": {
                    "validation_sql": "SELECT COUNT(*) FILTER (WHERE charged_amount < 0) AS violation_count FROM billing_cdr_data"
                },
            }
        ],
        stages=[],
        final_dataset=None,
    )

    rule_rows = [row for row in snapshots if row.get("object_type") == "rule"]
    assert rule_rows
    assert all(row["object_name"] == "Negative charged amount in billing_cdr_data" for row in rule_rows)


def test_list_quality_trends_supports_presentation_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_query(settings, sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(dq_store, "run_query", fake_run_query)

    dq_store.list_quality_trends(
        None,
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        object_type="table",
        object_key="billing_cdr_data",
        trend_status="improved",
        metric_name="trust_score",
        limit=1200,
    )

    assert "AND object_type = %s" in str(captured["sql"])
    assert "AND object_key = %s" in str(captured["sql"])
    assert "AND trend_status = %s" in str(captured["sql"])
    assert "AND metric_name = %s" in str(captured["sql"])
    assert captured["params"] == [
        "tenant",
        "data_quality_observability",
        "run_1",
        "table",
        "billing_cdr_data",
        "improved",
        "trust_score",
        1200,
    ]


def test_build_trend_api_payload_adds_evidence_paths() -> None:
    payload = dq_trends.build_trend_api_payload(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        trend_scope_key="scope_1",
        baseline_run_id="run_0",
        readiness_overview={
            "current_readiness_status": "ready",
            "previous_readiness_status": "warning",
            "readiness_trend_status": "improved",
            "certification_blocker_count": 0,
            "residual_anomaly_count": 0,
            "critical_anomaly_count": 0,
            "evidence_path_template": "/data-quality/final-dataset?tenant_id={tenant_id}&domain_id={domain_id}&run_id=run_1",
        },
        business_term_overview={
            "summary": {
                "business_term_group_count": 1,
                "worsened_business_term_count": 0,
                "improved_business_term_count": 1,
                "unmatched_trend_row_count": 0,
            },
            "rows": [
                {
                    "business_term": "Orders",
                    "trend_row_count": 1,
                    "improved_metric_count": 1,
                    "worsened_metric_count": 0,
                    "baseline_metric_count": 0,
                    "affected_object_count": 1,
                    "evidence_path": "/data-quality/trends/business-terms?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1&term=orders",
                }
            ],
        },
        trends=[
            {
                "object_type": "table",
                "object_key": "orders",
                "object_name": "orders",
                "metric_name": "trust_score",
                "previous_value_num": 70.0,
                "current_value_num": 75.0,
                "delta_value": 5.0,
                "delta_pct": 7.14,
                "trend_status": "improved",
                "directionality": "higher_better",
            },
            {
                "object_type": "rule",
                "object_key": "rule_123",
                "object_name": "Invalid customer email",
                "metric_name": "violation_count",
                "previous_value_num": 12.0,
                "current_value_num": 3.0,
                "delta_value": -9.0,
                "delta_pct": -75.0,
                "trend_status": "improved",
                "directionality": "lower_better",
            },
            {
                "object_type": "run",
                "object_key": "__run__",
                "object_name": "Run Summary",
                "metric_name": "overall_trust_score",
                "previous_value_num": 70.0,
                "current_value_num": 75.0,
                "delta_value": 5.0,
                "delta_pct": 7.14,
                "trend_status": "improved",
                "directionality": "higher_better",
            },
            {
                "object_type": "final_dataset",
                "object_key": "final_dataset",
                "object_name": "Final Dataset",
                "metric_name": "final_row_count",
                "previous_value_num": 10.0,
                "current_value_num": 12.0,
                "delta_value": 2.0,
                "delta_pct": 20.0,
                "trend_status": "improved",
                "directionality": "higher_better",
            },
            {
                "object_type": "stage",
                "object_key": "stage_123",
                "object_name": "Source Profile Orders",
                "metric_name": "output_row_count",
                "previous_value_num": 10.0,
                "current_value_num": 12.0,
                "delta_value": 2.0,
                "delta_pct": 20.0,
                "trend_status": "improved",
                "directionality": "higher_better",
            },
        ],
    )

    assert payload["trends"][0]["evidence_path"] == "/data-quality/trends/tables/orders?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1"
    assert payload["trends"][1]["evidence_path"] == "/data-quality/trends/rules/rule_123?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1"
    assert payload["trends"][2]["evidence_path"] == "/data-quality/trends/run-summary?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1"
    assert payload["trends"][3]["evidence_path"] == "/data-quality/trends/final-dataset?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1"
    assert payload["trends"][4]["evidence_path"] == "/data-quality/trends/stages/stage_123?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1"
    assert payload["summary"]["unchanged_metric_count"] == 0
    assert payload["summary"]["changed_metric_count"] == 0
    assert payload["cards"][0]["card_key"] == "trend_scope"
    assert payload["cards"][1]["card_key"] == "overall_trust_score"
    assert payload["cards"][4]["card_key"] == "publish_readiness"
    assert payload["cards"][5]["card_key"] == "business_term_groups"
    assert payload["chart_plan"][0]["chart_key"] == "trend_status_distribution"
    assert payload["chart_plan"][1]["chart_key"] == "object_type_distribution"
    assert payload["chart_plan"][0]["x_field"] == "category"
    assert payload["chart_plan"][0]["y_field"] == "value"
    assert payload["chart_plan"][0]["series_fields"] == ["value"]
    assert payload["chart_plan"][4]["chart_key"] == "publish_readiness"
    assert payload["chart_plan"][5]["chart_key"] == "business_term_trends"
    assert payload["groups"]["tables"]["count"] == 1
    assert payload["groups"]["rules"]["count"] == 1
    assert payload["groups"]["run_final_dataset"]["count"] == 2
    assert payload["groups"]["tables"]["summary"]["trend_row_count"] == 1
    assert payload["trends"][0]["previous_display_value"] == 70.0
    assert payload["trends"][0]["current_display_value"] == 75.0


def test_build_trend_table_payload_returns_chart_ready_sections() -> None:
    payload = dq_trends.build_trend_table_payload(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        trend_scope_key="scope_1",
        table_name="orders",
        trends=[
            {
                "baseline_run_id": "run_0",
                "object_type": "table",
                "object_key": "orders",
                "object_name": "orders",
                "metric_name": "trust_score",
                "previous_value_num": 70.0,
                "current_value_num": 75.0,
                "delta_value": 5.0,
                "delta_pct": 7.14,
                "trend_status": "improved",
                "directionality": "higher_better",
            }
        ],
    )

    assert payload["focus"] == {
        "focus_type": "table",
        "focus_key": "orders",
        "focus_label": "orders",
    }
    assert payload["chart_plan"][2]["chart_key"] == "top_improved_deltas"
    assert payload["groups"]["tables"]["count"] == 1


def test_build_stage_and_run_final_trend_payloads_return_focus_blocks() -> None:
    stage_payload = dq_trends.build_trend_stage_payload(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        trend_scope_key="scope_1",
        stage_key="stage_abc",
        trends=[
            {
                "baseline_run_id": "run_0",
                "object_type": "stage",
                "object_key": "stage_abc",
                "object_name": "Stage ABC",
                "metric_name": "output_row_count",
                "previous_value_num": 10.0,
                "current_value_num": 12.0,
                "delta_value": 2.0,
                "delta_pct": 20.0,
                "trend_status": "improved",
                "directionality": "higher_better",
            }
        ],
    )
    run_payload = dq_trends.build_trend_run_summary_payload(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        trend_scope_key="scope_1",
        trends=[
            {
                "baseline_run_id": "run_0",
                "object_type": "run",
                "object_key": "__run__",
                "object_name": "Run Summary",
                "metric_name": "overall_trust_score",
                "previous_value_num": 70.0,
                "current_value_num": 75.0,
                "delta_value": 5.0,
                "delta_pct": 7.14,
                "trend_status": "improved",
                "directionality": "higher_better",
            }
        ],
    )
    final_payload = dq_trends.build_trend_final_dataset_payload(
        tenant_id="tenant",
        domain_id="data_quality_observability",
        run_id="run_1",
        trend_scope_key="scope_1",
        trends=[
            {
                "baseline_run_id": "run_0",
                "object_type": "final_dataset",
                "object_key": "final_dataset",
                "object_name": "Final Dataset",
                "metric_name": "final_row_count",
                "previous_value_num": 10.0,
                "current_value_num": 12.0,
                "delta_value": 2.0,
                "delta_pct": 20.0,
                "trend_status": "improved",
                "directionality": "higher_better",
            }
        ],
    )

    assert stage_payload["focus"]["focus_type"] == "stage"
    assert stage_payload["stage_logical_key"] == "stage_abc"
    assert run_payload["focus"]["focus_type"] == "run"
    assert final_payload["focus"]["focus_type"] == "final_dataset"


def test_persist_trend_artifacts_reads_baseline_object_snapshots_with_scope_key(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        dq_orchestrator,
        "_resolved_trend_metadata",
        lambda *args, **kwargs: {
            "trend_mode": "monitor",
            "trend_scope_key": "scope_1",
            "trend_scope_label": "Scope 1",
            "baseline_run_id": None,
        },
    )
    monkeypatch.setattr(dq_orchestrator, "replace_quality_run_metric_snapshots", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "replace_quality_object_metric_snapshots", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "list_quality_tables", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_rules", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "list_quality_dataset_stages", lambda *args, **kwargs: [])
    monkeypatch.setattr(dq_orchestrator, "get_quality_final_dataset_artifact", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        dq_orchestrator,
        "list_runs_by_trend_scope",
        lambda *args, **kwargs: [{"run_id": "run_old", "trend_mode": "monitor"}],
    )
    monkeypatch.setattr(
        dq_orchestrator,
        "select_trend_baseline_run",
        lambda *args, **kwargs: {"run_id": "run_old", "trend_mode": "monitor"},
    )
    monkeypatch.setattr(dq_orchestrator, "list_quality_run_metric_snapshots", lambda *args, **kwargs: [])

    def fake_list_quality_object_metric_snapshots(*args, **kwargs):
        captured["trend_scope_key"] = kwargs.get("trend_scope_key")
        captured["run_id"] = kwargs.get("run_id")
        return []

    monkeypatch.setattr(dq_orchestrator, "list_quality_object_metric_snapshots", fake_list_quality_object_metric_snapshots)
    monkeypatch.setattr(dq_orchestrator, "replace_quality_trends", lambda *args, **kwargs: None)
    monkeypatch.setattr(dq_orchestrator, "build_business_term_trend_payload", lambda *args, **kwargs: {"summary": {}, "rows": []})
    monkeypatch.setattr(dq_orchestrator, "fetch_glossary_terms", lambda *args, **kwargs: [])

    state = {
        "tenant_id": "tenant",
        "domain_id": "data_quality_observability",
        "quality_run_id": "dqrun_1",
        "quality_summary": {},
        "quality_tables": [],
        "quality_rule_rows": [],
        "dataset_stages": [],
        "final_dataset": {},
    }

    dq_orchestrator._persist_trend_artifacts(None, "run_1", state)

    assert captured["trend_scope_key"] == "scope_1"
    assert captured["run_id"] == "run_old"


def test_select_trend_baseline_run_ignores_runs_before_latest_reset() -> None:
    baseline = dq_trends.select_trend_baseline_run(
        trend_mode="monitor",
        previous_runs=[
            {"run_id": "run_post_reset_2", "trend_mode": "monitor"},
            {"run_id": "run_post_reset_1", "trend_mode": "monitor"},
            {"run_id": "run_reset", "trend_mode": "baseline_reset"},
            {"run_id": "run_old", "trend_mode": "monitor"},
        ],
    )

    assert baseline["run_id"] == "run_post_reset_2"


def test_select_trend_baseline_run_returns_none_for_baseline_reset_mode() -> None:
    baseline = dq_trends.select_trend_baseline_run(
        trend_mode="baseline_reset",
        previous_runs=[{"run_id": "run_old", "trend_mode": "monitor"}],
    )

    assert baseline is None


def test_build_data_quality_run_summary_payload_includes_trend_fields() -> None:
    response = dq_api_payloads.build_data_quality_run_summary_payload(
        row={
            "quality_run_id": "dqrun_1",
            "run_id": "run_1",
            "tenant_id": "tenant",
            "domain_id": "data_quality_observability",
            "status": "completed",
            "trend_mode": "monitor",
            "trend_scope_key": "cdr_primary_reconciliation",
            "trend_scope_label": "Primary CDR Reconciliation",
            "baseline_run_id": "run_0",
            "summary_json": {
                "workflow_status": "completed",
                "trend_row_count": 9,
                "improved_metric_count": 4,
                "worsened_metric_count": 1,
            },
        },
        remediation_plan={"summary": {}, "actions": []},
    )

    assert response["trend_mode"] == "monitor"
    assert response["trend_scope_key"] == "cdr_primary_reconciliation"
    assert response["baseline_run_id"] == "run_0"
    assert response["trend_row_count"] == 9
    assert response["artifacts"]["trends"].endswith("/data-quality/trends?tenant_id=tenant&domain_id=data_quality_observability&run_id=run_1")
    assert response["artifacts"]["run_lineage"] == "/agentic/runs/run_1/lineage"


def test_build_run_lineage_graph_payload_shapes_nodes_and_edges() -> None:
    from services.ai import agentic_lineage

    def _fake_get_deployment_run(_settings, run_id: str) -> dict:
        rows = {
            "run_1": {
                "run_id": "run_1",
                "display_name": "Data Quality Observability Deployment v3",
                "status": "completed",
                "version_no": 3,
                "trend_mode": "monitor",
                "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2",
                "trend_scope_label": "Primary CDR Reconciliation",
                "parent_run_id": None,
                "rerun_root_run_id": "run_1",
                "created_at": "2026-04-24T12:00:00Z",
                "updated_at": "2026-04-24T12:30:00Z",
            },
            "run_2": {
                "run_id": "run_2",
                "display_name": "Data Quality Observability Deployment v4",
                "status": "completed",
                "version_no": 4,
                "trend_mode": "monitor",
                "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2",
                "trend_scope_label": "Primary CDR Reconciliation",
                "parent_run_id": "run_1",
                "rerun_root_run_id": "run_1",
                "created_at": "2026-04-25T12:00:00Z",
                "updated_at": "2026-04-25T12:30:00Z",
            },
        }
        return rows[run_id]

    response = agentic_lineage.build_run_lineage_graph_payload(
        run_id="run_2",
        edges=[
            {
                "lineage_edge_id": "runedge_001",
                "parent_run_id": "run_1",
                "child_run_id": "run_2",
                "edge_type": "rerun_monitor",
                "trend_scope_key": "cdr_primary_reconciliation_f8a1c3b0d2",
            }
        ],
        fetch_run=lambda node_run_id: _fake_get_deployment_run(None, node_run_id),
    )

    assert response["graph"]["root_run_id"] == "run_1"
    assert response["graph"]["focus_run_id"] == "run_2"
    assert response["graph"]["node_count"] == 2
    assert response["graph"]["edge_count"] == 1
    assert response["graph"]["trend_scope_keys"] == ["cdr_primary_reconciliation_f8a1c3b0d2"]
    assert response["edges"][0]["edge_type"] == "rerun_monitor"
    assert response["nodes"][0]["is_root_run"] is True
    assert response["nodes"][1]["is_focus_run"] is True
    assert response["nodes"][1]["trend_scope_label"] == "Primary CDR Reconciliation"
