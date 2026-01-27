from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class QueryFilter(BaseModel):
    field: str = Field(..., description="Dimension name (e.g., product_name)")
    operator: str = Field(..., description="One of =, !=, >, >=, <, <=, IN, ILIKE")
    value: Any = Field(..., description="Filter value or list of values for IN")


class QueryRequest(BaseModel):
    question: Optional[str] = Field(
        None,
        description="Natural language question",
        examples=["Top 5 sales areas by sales volume for MS in Q2 FY 2024-2025."],
    )
    metric: Optional[str] = Field(
        None,
        description="Metric name to query directly",
        examples=["industry_sales_tmt"],
    )
    metrics: Optional[List[str]] = Field(
        None,
        description="Metric names to query",
        examples=[["industry_sales_tmt", "hpcl_vs_company_sales_ratio"]],
    )
    dimensions: List[str] = Field(
        default_factory=list,
        description="Dimensions to group by",
        examples=[["sales_area_name", "calendar_quarter_sales", "fiscal_year"]],
    )
    filters: List[QueryFilter] = Field(
        default_factory=list,
        description="Filters to apply",
        examples=[[{"field": "product_name", "operator": "=", "value": "MS"}]],
    )
    limit: int = Field(200, ge=1, le=1000, description="Row limit", examples=[100])
    explain: bool = Field(False, description="Return SQL and resolution info", examples=[True])


class QueryResult(BaseModel):
    metrics: List[str] = Field(examples=[["total_sales_volume_tmt"]])
    dimensions: List[str] = Field(examples=[["sales_area_name", "fiscal_year"]])
    sql: Optional[str] = Field(
        None,
        examples=[
            "SELECT sales_area_name, SUM(sales_tmt) AS total_sales_volume_tmt FROM ...",
        ],
    )
    rows: List[dict] = Field(
        examples=[[{"sales_area_name": "Tenali", "total_sales_volume_tmt": 123.4}]]
    )
    by_company_sql: Optional[str] = Field(
        None,
        examples=[
            "SELECT company_name, SUM(industry_sales_tmt) AS industry_sales_by_company_tmt FROM ...",
        ],
    )
    by_company_rows: Optional[List[dict]] = Field(
        None,
        examples=[[{"company_name": "HPCL", "industry_sales_by_company_tmt": 1000.0}]],
    )


class MetricsResponse(BaseModel):
    metrics: List[dict] = Field(
        examples=[
            [
                {
                    "name": "total_sales_volume_tmt",
                    "type": "sum",
                    "grain": "day",
                    "status": "certified",
                    "owner": "analytics@company.com",
                    "version": "v1",
                }
            ]
        ]
    )
    limit: int = Field(200, examples=[200])
    cursor: str | None = Field(None, examples=["dG90YWxfc2FsZXNfdm9sdW1lX3RtdA=="])
    next_cursor: str | None = Field(None, examples=["c2FsZXNfdnNfdGFyZ2V0X2FjaGlldmVtZW50X3BjdA=="])


class SchemaResponse(BaseModel):
    models: List[dict] = Field(
        examples=[[{"name": "fact_hpcl_sales_daily", "schema": "public"}]]
    )
    limit: int = Field(200, examples=[200])
    cursor: str | None = Field(None, examples=["ZmFjdF9ocGNsX3NhbGVzX2RhaWx5"])
    next_cursor: str | None = Field(None, examples=["ZmFjdF9ocGNsX3NhbGVzX21vbnRobHlfdGFyZ2V0cw=="])


class DatasetsResponse(BaseModel):
    datasets: List[dict] = Field(
        examples=[
            [
                {
                    "name": "sales_area_performance",
                    "source_model": "fact_hpcl_sales_daily",
                    "description": "Sales performance by sales area and product",
                }
            ]
        ]
    )
    limit: int = Field(200, examples=[200])
    cursor: str | None = Field(None, examples=["c2FsZXNfYXJlYV9wZXJmb3JtYW5jZQ=="])
    next_cursor: str | None = Field(None, examples=["aW5kdXN0cnlfcGVyZm9ybWFuY2U="])


class DimensionsResponse(BaseModel):
    dimensions: List[dict] = Field(
        examples=[
            [
                {
                    "name": "sales_area_name",
                    "description": "Sales area",
                    "data_type": "string",
                    "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_area_name",
                }
            ]
        ]
    )


class DimensionValuesResponse(BaseModel):
    dimension: str = Field(..., examples=["sales_area_name"])
    values: List[dict] = Field(
        examples=[[{"value": "Tenali"}]]
    )
    limit: int = Field(100, examples=[100])
    cursor: str | None = Field(None, examples=["VmlqYXlhd2FkYQ=="])
    next_cursor: str | None = Field(None, examples=["VGVuYWxp"])


class EntityOverrideRequest(BaseModel):
    description: str | None = Field(
        None, examples=["Organizational hierarchy for sales operations"]
    )
    join_key: str | None = Field(None, examples=["sales_area_name"])
    examples: List[str] | None = Field(default=None, examples=[["zone", "region", "sales_area"]])


class HierarchyOverrideRequest(BaseModel):
    levels: List[str] = Field(default_factory=list, examples=[["zone", "region", "sales_area"]])
    description: str | None = Field(None, examples=["Sales organization rollup"])


class EntitiesResponse(BaseModel):
    entities: List[dict] = Field(
        examples=[[{"entity_id": "organizational_unit", "join_key": "sales_area_name"}]]
    )
    hierarchies: List[dict] = Field(
        examples=[[{"name": "sales_org", "levels": ["sbu", "zone", "region", "sales_area"]}]]
    )
    entity_limit: int = Field(200, examples=[200])
    entity_cursor: str | None = Field(None, examples=["b3JnYW5pemF0aW9uYWxfdW5pdA=="])
    entity_next_cursor: str | None = Field(None, examples=["cHJvZHVjdA=="])
    hierarchy_limit: int = Field(200, examples=[200])
    hierarchy_cursor: str | None = Field(None, examples=["c2FsZXNfb3Jn"])
    hierarchy_next_cursor: str | None = Field(None, examples=["cmVnaW9uX29yZw=="])


class PoliciesResponse(BaseModel):
    policies: List[dict] = Field(
        examples=[
            [
                {
                    "policy_id": "sbu_exclusion",
                    "description": "Exclude SBU values not relevant for this tenant",
                }
            ]
        ]
    )


class LineageResponse(BaseModel):
    lineage: List[dict] = Field(
        examples=[
            [
                {
                    "metric_name": "total_sales_volume_tmt",
                    "dataset": "fact_hpcl_sales_daily",
                    "dbt_model": "fact_hpcl_sales_daily",
                }
            ]
        ]
    )


class InsightsResponse(BaseModel):
    insights: List[dict] = Field(
        examples=[
            [
                {
                    "insight_id": "ins_123",
                    "insight_type": "variance",
                    "headline": "Sales volume decreased 4.2% vs last month",
                    "severity": "medium",
                    "confidence": 0.8,
                }
            ]
        ]
    )
    limit: int = Field(200, examples=[200])
    cursor: str | None = Field(None, examples=["aW5zXzEyMw=="])
    next_cursor: str | None = Field(None, examples=["aW5zXzEyNA=="])


class InsightDetailResponse(BaseModel):
    insight: dict = Field(
        examples=[
            {
                "insight_id": "ins_123",
                "insight_type": "variance",
                "headline": "Sales volume decreased 4.2% vs last month",
                "severity": "medium",
                "confidence": 0.8,
                "entity_scope": {"sales_area_name": "Tenali"},
            }
        ]
    )


class ActionCreateRequest(BaseModel):
    domain_id: str = Field(..., examples=["energy_distribution"])
    headline: str = Field(..., examples=["Investigate sales drop in Tenali"])
    severity: str | None = Field(None, examples=["medium"])
    status: str | None = Field("open", examples=["open"])
    assigned_to: str | None = Field(None, examples=["ops_manager@company.com"])
    source_insight_id: str | None = Field(None, examples=["ins_123"])
    scenario_id: str | None = Field(None, examples=["baseline"])


class ActionUpdateRequest(BaseModel):
    headline: str | None = Field(None, examples=["Re-check distributor plan"])
    severity: str | None = Field(None, examples=["high"])
    status: str | None = Field(None, examples=["in_progress"])
    assigned_to: str | None = Field(None, examples=["ops_manager@company.com"])


class ActionFeedbackRequest(BaseModel):
    status: str | None = Field(None, examples=["resolved"])
    outcome: str | None = Field(None, examples=["Distributor restocked"])
    notes: str | None = Field(None, examples=["Root cause was delayed shipment"])
    impact_window: dict | None = Field(None, examples=[{"start": "2025-02-01", "end": "2025-02-28"}])
    assigned_to: str | None = Field(None, examples=["ops_manager@company.com"])


class ActionsResponse(BaseModel):
    actions: List[dict] = Field(
        examples=[
            [
                {
                    "action_id": "act_123",
                    "headline": "Investigate sales drop in Tenali",
                    "status": "open",
                    "severity": "medium",
                }
            ]
        ]
    )
    limit: int = Field(200, examples=[200])
    cursor: str | None = Field(None, examples=["YWN0XzEyMw=="])
    next_cursor: str | None = Field(None, examples=["YWN0XzEyNA=="])


class ActionDetailResponse(BaseModel):
    action: dict = Field(
        examples=[
            {
                "action_id": "act_123",
                "headline": "Investigate sales drop in Tenali",
                "status": "open",
                "severity": "medium",
            }
        ]
    )


class ActionCreateResponse(BaseModel):
    action_id: str = Field(..., examples=["act_123"])
    status: str = Field(..., examples=["open"])


class ScenariosResponse(BaseModel):
    scenarios: List[dict] = Field(
        examples=[
            [
                {
                    "scenario_id": "baseline",
                    "domain_id": "energy_distribution",
                    "name": "Baseline",
                    "status": "ready",
                    "is_baseline": True,
                }
            ]
        ]
    )
    limit: int = Field(200, examples=[200])
    cursor: str | None = Field(None, examples=["YmFzZWxpbmU="])
    next_cursor: str | None = Field(None, examples=["c2Nlbl8wMDE="])


class ScenarioCreateRequest(BaseModel):
    scenario_id: str | None = Field(None, examples=["scenario_001"])
    domain_id: str = Field(..., examples=["energy_distribution"])
    name: str = Field(..., examples=["Distribution Disruption"])
    description: str | None = Field(None, examples=["Simulate loss of supply in Zone A"])
    status: str | None = Field("draft", examples=["draft"])
    is_baseline: bool | None = Field(False, examples=[False])
    created_by: str | None = Field(None, examples=["planner@company.com"])


class ScenarioUpdateRequest(BaseModel):
    name: str | None = Field(None, examples=["Distribution Disruption"])
    description: str | None = Field(None, examples=["Updated description"])
    status: str | None = Field(None, examples=["ready"])
    is_baseline: bool | None = Field(None, examples=[False])


class ScenarioRunRequest(BaseModel):
    parameters: dict = Field(default_factory=dict, examples=[{"uplift_pct": 3}])


class ScenarioCompareRequest(BaseModel):
    base_scenario_id: str = Field(..., examples=["baseline"])
    compare_scenario_id: str = Field(..., examples=["scenario_001"])
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])


class ScenarioRunResponse(BaseModel):
    scenario_id: str = Field(..., examples=["scenario_001"])
    status: str = Field(..., examples=["completed"])


class ScenarioCompareResponse(BaseModel):
    base_scenario_id: str = Field(..., examples=["baseline"])
    compare_scenario_id: str = Field(..., examples=["scenario_001"])
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    delta: float | None = Field(None, examples=[12.3])


class TimeSeriesRequest(BaseModel):
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    grain: str = Field("month", examples=["month"])
    filters: List[QueryFilter] = Field(default_factory=list)
    limit: int = Field(24, ge=1, le=1000)
    window: int = Field(6, ge=2, le=52)
    threshold: float = Field(2.5, ge=0.1, le=10)


class TimeSeriesResponse(BaseModel):
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    grain: str = Field(..., examples=["month"])
    series: List[dict] = Field(
        examples=[
            [
                {
                    "period": "2024-01-01",
                    "actual": 1200.5,
                    "baseline": 1150.0,
                    "deviation": 50.5,
                    "z_score": 1.2,
                    "is_anomaly": False,
                }
            ]
        ]
    )


class InsightDetailWithContextResponse(BaseModel):
    insight: dict
    drivers: List[dict] = Field(default_factory=list)
    correlations: List[dict] = Field(default_factory=list)


class OnboardScanRequest(BaseModel):
    schema: str | None = Field(None, examples=["public"])


class OnboardScanResponse(BaseModel):
    tables: List[dict]


class OnboardMapResponse(BaseModel):
    candidates: List[dict]
    low_confidence_candidates: List[dict]
    low_confidence_threshold: float = Field(
        0.7, description="Confidence threshold used to classify low-confidence candidates"
    )


class OnboardScanConnectionRequest(BaseModel):
    db_type: str = Field(..., examples=["postgres"])
    host: str = Field(..., examples=["db.company.com"])
    port: int = Field(5432, examples=[5432])
    database: str = Field(..., examples=["prod_warehouse"])
    user: str = Field(..., examples=["readonly_user"])
    password: str = Field(..., examples=["******"])
    schema: str = Field("public", examples=["public"])
    tables: List[str] | None = Field(None, examples=[["fact_production_daily", "dim_plant"]])
    sample_rows: int = Field(100, ge=10, le=100, examples=[100])
    limit: int = Field(20, ge=1, le=500, examples=[20])
    cursor: str | None = Field(None, examples=["ZmFjdF9wcm9kdWN0aW9uX2RhaWx5"])


class OnboardScanConnectionResponse(BaseModel):
    tables: List[dict]
    limit: int = Field(20, examples=[20])
    cursor: str | None = Field(None, examples=["ZmFjdF9wcm9kdWN0aW9uX2RhaWx5"])
    next_cursor: str | None = Field(None, examples=["ZGltX3BsYW50"])


class InferModelsRequest(BaseModel):
    schema: str = Field("public", examples=["public"])
    tables: List[str] | None = Field(None, examples=[["fact_production_daily", "dim_plant"]])
    time_column: str | None = Field(None, examples=["production_date"])
    grain: str | None = Field(None, examples=["day"])
    use_llm: bool = Field(False, examples=[True])


class InferModelsResponse(BaseModel):
    facts: List[dict]
    dimensions: List[dict]


class SuggestedMetricsResponse(BaseModel):
    measures: List[dict]
    low_confidence_measures: List[dict]
    low_confidence_threshold: float = Field(
        0.7, description="Confidence threshold used to classify low-confidence measures"
    )
    time_columns: List[dict]
    entity_candidates: List[dict]


class MetricUpsertRequest(BaseModel):
    domain_id: str = Field(..., examples=["energy_distribution"])
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    display_name: str | None = Field(None, examples=["Total Sales Volume (TMT)"])
    description: str | None = Field(None, examples=["Total sales volume in TMT"])
    type: str = Field(..., examples=["sum"])
    sql: str = Field(..., examples=["{{ ref('fact_hpcl_sales_daily') }}.sales_tmt"])
    grain: str = Field(..., examples=["day"])
    dimensions: List[str] = Field(default_factory=list, examples=[["sales_area_name", "fiscal_year"]])
    unit: str | None = Field(None, examples=["tmt"])
    status: str | None = Field("suggested", examples=["certified"])
    dataset_id: str | None = Field(None, examples=["fact_hpcl_sales_daily"])
    source_model: str | None = Field(None, examples=["fact_hpcl_sales_daily"])
    source_schema: str | None = Field(None, examples=["public"])
    owner: str | None = Field(None, examples=["analytics@company.com"])
    version: str | None = Field(None, examples=["v1"])


class MetricPatchRequest(BaseModel):
    metric_name: str | None = Field(None, examples=["total_sales_volume_tmt"])
    display_name: str | None = Field(None, examples=["Total Sales Volume (TMT)"])
    description: str | None = Field(None, examples=["Updated description"])
    type: str | None = Field(None, examples=["sum"])
    sql: str | None = Field(None, examples=["{{ ref('fact_hpcl_sales_daily') }}.sales_tmt"])
    grain: str | None = Field(None, examples=["day"])
    dimensions: List[str] | None = Field(None, examples=[["sales_area_name", "fiscal_year"]])
    unit: str | None = Field(None, examples=["tmt"])
    status: str | None = Field(None, examples=["certified"])
    dataset_id: str | None = Field(None, examples=["fact_hpcl_sales_daily"])
    source_model: str | None = Field(None, examples=["fact_hpcl_sales_daily"])
    source_schema: str | None = Field(None, examples=["public"])
    owner: str | None = Field(None, examples=["analytics@company.com"])
    version: str | None = Field(None, examples=["v1"])


class MetricUpsertResponse(BaseModel):
    metric_id: str = Field(..., examples=["energy_distribution__total_sales_volume_tmt"])
    status: str = Field(..., examples=["suggested"])


class ContractMetric(BaseModel):
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    type: str = Field(..., examples=["sum"])
    sql: str = Field(..., examples=["{{ ref('fact_hpcl_sales_daily') }}.sales_tmt"])
    grain: str = Field(..., examples=["day"])
    dimensions: List[str] = Field(default_factory=list, examples=[["sales_area_name", "fiscal_year"]])


class ContractValidateRequest(BaseModel):
    metrics: List[ContractMetric] = Field(default_factory=list)


class ContractValidateResponse(BaseModel):
    valid: bool = Field(..., examples=[True])
    errors: List[dict] = Field(default_factory=list)
    warnings: List[dict] = Field(default_factory=list)
