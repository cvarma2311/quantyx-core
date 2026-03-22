import unittest
from dataclasses import dataclass
from datetime import date, timedelta

from services.ai.workspace_query_planner import (
    build_workspace_chart,
    bind_dimensions,
    bind_metric,
    compile_workspace_query_plan,
    conversation_plan_diagnostics,
    detect_detail_intent,
    parse_exact_date_filters,
    parse_relative_date_filters,
    validate_workspace_query_plan,
)


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    metric_type: str
    sql: str
    grain: str
    dimensions: list[str]


@dataclass(frozen=True)
class Dimension:
    name: str
    description: str
    data_type: str
    sql: str


@dataclass(frozen=True)
class MetricCatalog:
    metrics: dict[str, Metric]
    dimensions: dict[str, Dimension]


def _catalog() -> MetricCatalog:
    return MetricCatalog(
        metrics={
            "sum_total_productivity": Metric(
                name="sum_total_productivity",
                description="",
                metric_type="aggregate",
                sql="select 1",
                grain="day",
                dimensions=["zone", "filling_head", "process_date"],
            ),
            "productivity_avg": Metric(
                name="productivity_avg",
                description="",
                metric_type="aggregate",
                sql="select 1",
                grain="day",
                dimensions=["zone", "filling_head", "process_date"],
            ),
            "total_productivity": Metric(
                name="total_productivity",
                description="",
                metric_type="aggregate",
                sql="select 1",
                grain="day",
                dimensions=["zone", "filling_head", "process_date"],
            ),
        },
        dimensions={
            "zone": Dimension(name="zone", description="", data_type="text", sql="zone"),
            "filling_head": Dimension(name="filling_head", description="", data_type="text", sql="filling_head"),
            "process_date": Dimension(name="process_date", description="", data_type="date", sql="process_date"),
            "id": Dimension(name="id", description="", data_type="int", sql="id"),
        },
    )


class TestWorkspaceQueryPlanner(unittest.TestCase):
    def test_parse_exact_date_filters_handles_day_month_year(self) -> None:
        filters = parse_exact_date_filters(
            "Provide productivity by zone for 19-Mar-2026",
            ["zone", "process_date"],
        )
        self.assertEqual(
            filters,
            [{"field": "process_date", "operator": "=", "value": "2026-03-19", "value_type": "date"}],
        )

    def test_bind_dimensions_rejects_identifier_fields(self) -> None:
        bound, rejected, warnings = bind_dimensions(
            ["zone", "filling head", "id"],
            ["zone", "filling_head", "process_date", "id"],
        )
        self.assertEqual(bound, ["zone", "filling_head"])
        self.assertEqual(rejected, ["id"])
        self.assertIn("dimension_bound:filling head->filling_head", warnings)

    def test_parse_relative_date_filters_handles_yesterday(self) -> None:
        filters = parse_relative_date_filters(
            "Top 10 plants by productivity yesterday",
            ["zone", "process_date"],
        )
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["field"], "process_date")
        self.assertEqual(filters[0]["operator"], "=")
        self.assertEqual(filters[0]["value_type"], "date")

    def test_parse_relative_date_filters_handles_last_week(self) -> None:
        filters = parse_relative_date_filters(
            "Show total production by zone last week",
            ["zone", "process_date"],
        )
        self.assertEqual(len(filters), 2)
        self.assertEqual(filters[0]["field"], "process_date")
        self.assertEqual(filters[0]["operator"], ">=")
        self.assertEqual(filters[1]["operator"], "<=")

    def test_parse_relative_date_filters_handles_named_month(self) -> None:
        filters = parse_relative_date_filters(
            "Show productivity trend for March 2026",
            ["zone", "process_date"],
        )
        self.assertEqual(
            filters,
            [
                {"field": "process_date", "operator": ">=", "value": "2026-03-01", "value_type": "date"},
                {"field": "process_date", "operator": "<=", "value": "2026-03-31", "value_type": "date"},
            ],
        )

    def test_parse_relative_date_filters_handles_last_three_months(self) -> None:
        filters = parse_relative_date_filters(
            "Show productivity trend for last three months",
            ["zone", "process_date"],
        )
        self.assertEqual(len(filters), 1)
        self.assertEqual(filters[0]["field"], "process_date")
        self.assertEqual(filters[0]["operator"], ">=")

    def test_parse_relative_date_filters_handles_q1_calendar_year(self) -> None:
        filters = parse_relative_date_filters(
            "Show productivity trend for Q1 2026",
            ["zone", "process_date"],
        )
        self.assertEqual(
            filters,
            [
                {"field": "process_date", "operator": ">=", "value": "2026-01-01", "value_type": "date"},
                {"field": "process_date", "operator": "<=", "value": "2026-03-31", "value_type": "date"},
            ],
        )

    def test_parse_relative_date_filters_handles_fiscal_quarter(self) -> None:
        filters = parse_relative_date_filters(
            "Show productivity trend for Q2 FY 2026-2027",
            ["zone", "process_date"],
        )
        self.assertEqual(
            filters,
            [
                {"field": "process_date", "operator": ">=", "value": "2026-07-01", "value_type": "date"},
                {"field": "process_date", "operator": "<=", "value": "2026-09-30", "value_type": "date"},
            ],
        )

    def test_parse_relative_date_filters_handles_this_quarter(self) -> None:
        filters = parse_relative_date_filters(
            "Show productivity trend this quarter",
            ["zone", "process_date"],
        )
        today = date.today()
        current_quarter = ((today.month - 1) // 3) + 1
        start_month = ((current_quarter - 1) * 3) + 1
        quarter_start = date(today.year, start_month, 1)
        if current_quarter == 4:
            quarter_end = date(today.year + 1, 1, 1) - timedelta(days=1)
        else:
            quarter_end = date(today.year, start_month + 3, 1) - timedelta(days=1)
        self.assertEqual(
            filters,
            [
                {"field": "process_date", "operator": ">=", "value": quarter_start.isoformat(), "value_type": "date"},
                {"field": "process_date", "operator": "<=", "value": quarter_end.isoformat(), "value_type": "date"},
            ],
        )

    def test_parse_relative_date_filters_handles_last_quarter(self) -> None:
        filters = parse_relative_date_filters(
            "Show productivity trend for past quarter",
            ["zone", "process_date"],
        )
        today = date.today()
        current_quarter = ((today.month - 1) // 3) + 1
        quarter_no = current_quarter - 1
        year_no = today.year
        if quarter_no == 0:
            quarter_no = 4
            year_no -= 1
        start_month = ((quarter_no - 1) * 3) + 1
        quarter_start = date(year_no, start_month, 1)
        if quarter_no == 4:
            quarter_end = date(year_no + 1, 1, 1) - timedelta(days=1)
        else:
            quarter_end = date(year_no, start_month + 3, 1) - timedelta(days=1)
        self.assertEqual(
            filters,
            [
                {"field": "process_date", "operator": ">=", "value": quarter_start.isoformat(), "value_type": "date"},
                {"field": "process_date", "operator": "<=", "value": quarter_end.isoformat(), "value_type": "date"},
            ],
        )

    def test_bind_metric_prefers_productivity_match(self) -> None:
        metric_name, warnings = bind_metric(
            ["productivity", "total productivity"],
            ["sum_total_productivity", "productivity_avg", "total_productivity"],
        )
        self.assertIn(metric_name, {"productivity_avg", "total_productivity", "sum_total_productivity"})
        self.assertIsNotNone(warnings)

    def test_validate_workspace_query_plan_preserves_breakdowns_and_rejects_id(self) -> None:
        validated = validate_workspace_query_plan(
            question="Provide productivity (in cylinders per hour) by zone and filling head for 19-Mar-2026",
            raw_plan={
                "intent": "analytic_query",
                "metric_candidates": ["productivity"],
                "dimensions": ["zone", "filling head", "id"],
                "filters": [],
                "chart_intent": "grouped_bar",
                "response_mode": "chart_plus_table",
                "sort": [{"field": "productivity", "direction": "desc"}],
            },
            metric_catalog=_catalog(),
            allowed_dimensions=["zone", "filling_head", "process_date", "id"],
        )
        self.assertIsNotNone(validated["metric_name"])
        self.assertEqual(validated["dimensions"], ["zone", "filling_head"])
        self.assertEqual(validated["chart_type"], "grouped_bar")
        self.assertEqual(
            validated["filters"],
            [{"field": "process_date", "operator": "=", "value": "2026-03-19", "value_type": "date"}],
        )
        self.assertIn("id", validated["rejected_candidates"]["dimensions"])
        self.assertIn("identifier_dimension_rejected:id", validated["validation_warnings"])
        self.assertEqual(validated["time_grain"], "day")
        self.assertEqual(validated["filter_objects"][0]["column"], "process_date")

    def test_validate_workspace_query_plan_binds_month_wise_to_process_month(self) -> None:
        validated = validate_workspace_query_plan(
            question="what is the total productivity month wise",
            raw_plan={
                "intent": "analytic_query",
                "metric_candidates": ["Total Productivity"],
                "dimensions": ["process_date"],
                "filters": [],
                "chart_intent": "line",
                "response_mode": "chart_plus_table",
                "sort": [],
            },
            metric_catalog=_catalog(),
            allowed_dimensions=["zone", "filling_head", "process_date", "id"],
        )
        self.assertEqual(validated["time_grain"], "month")
        self.assertEqual(validated["dimensions"], ["process_month"])
        self.assertIn("time_grain_bound_to_month_dimension:process_month", validated["validation_warnings"])

    def test_validate_workspace_query_plan_rejects_measure_dimension_conflict(self) -> None:
        validated = validate_workspace_query_plan(
            question="Show total productivity by total productivity and zone for 19-Mar-2026",
            raw_plan={
                "intent": "analytic_query",
                "metric_candidates": ["total productivity"],
                "dimensions": ["total_productivity", "zone"],
                "filters": [],
                "chart_intent": "grouped_bar",
                "response_mode": "chart_plus_table",
                "sort": [],
            },
            metric_catalog=_catalog(),
            allowed_dimensions=["zone", "filling_head", "process_date", "total_productivity", "id"],
        )
        self.assertEqual(validated["dimensions"], ["zone"])
        self.assertIn("candidate_measure_dimension_conflict:total_productivity", validated["validation_warnings"])
        self.assertIn("total_productivity", validated["disallowed_dimensions_removed"])

    def test_validate_workspace_query_plan_allows_id_for_detail_intent(self) -> None:
        self.assertTrue(detect_detail_intent("Show top 20 records for plant EZ on 19-Mar-2026"))
        validated = validate_workspace_query_plan(
            question="Show top 20 records for plant EZ on 19-Mar-2026",
            raw_plan={
                "intent": "detail_query",
                "metric_candidates": ["total productivity"],
                "dimensions": ["id", "zone"],
                "filters": [],
                "chart_intent": "table",
                "response_mode": "table_only",
                "sort": [],
            },
            metric_catalog=_catalog(),
            allowed_dimensions=["zone", "filling_head", "process_date", "id"],
        )
        self.assertEqual(validated["intent"], "detail_query")
        self.assertEqual(validated["chart_type"], "table")
        self.assertIn("id", validated["dimensions"])

    def test_compile_workspace_query_plan_builds_explicit_request(self) -> None:
        compiled = compile_workspace_query_plan(
            tenant_id="tenant_1",
            domain_id="lpg_production_distribution",
            run_id="run_123",
            validated_plan={
                "metric_name": "total_productivity",
                "dimensions": ["zone", "filling_head"],
                "filters": [{"field": "process_date", "operator": "=", "value": "2026-03-19"}],
            },
            limit=200,
        )
        self.assertIsNone(compiled["question"])
        self.assertEqual(compiled["metrics"], ["total_productivity"])
        self.assertEqual(compiled["dimensions"], ["zone", "filling_head"])
        self.assertEqual(compiled["filters"][0]["field"], "process_date")

    def test_build_workspace_chart_falls_back_to_table_for_three_breakdowns(self) -> None:
        chart_type, chart_payload, warnings = build_workspace_chart(
            rows=[{"zone": "EZ", "filling_head": "24H", "plant": "A", "value": 10}],
            metric_name="value",
            dimensions=["zone", "filling_head", "plant"],
            response_mode="chart_plus_table",
        )
        self.assertEqual(chart_type, "table")
        self.assertIsNone(chart_payload)
        self.assertIn("chart_intent_fallback:multi_breakdown_gt_2->table", warnings)

    def test_conversation_plan_diagnostics_exposes_expected_shape(self) -> None:
        diagnostics = conversation_plan_diagnostics(
            raw_llm_plan={"metric_candidates": ["productivity"]},
            validated_plan={
                "metric_name": "total_productivity",
                "dimensions": ["zone", "filling_head"],
                "filters": [{"field": "process_date", "operator": "=", "value": "2026-03-19"}],
                "rejected_candidates": {"dimensions": ["id"], "filters": [], "metrics": []},
                "validation_warnings": ["identifier_dimension_rejected:id"],
            },
            compiled_sql_preview="SELECT ...",
        )
        self.assertEqual(diagnostics["raw_llm_plan"]["metric_candidates"], ["productivity"])
        self.assertEqual(diagnostics["validated_plan"]["metric_name"], "total_productivity")
        self.assertEqual(diagnostics["rejected_candidates"]["dimensions"], ["id"])
        self.assertEqual(diagnostics["compiled_sql_preview"], "SELECT ...")


if __name__ == "__main__":
    unittest.main()
