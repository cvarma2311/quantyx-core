from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class QueryFilter(BaseModel):
    field: str = Field(..., description="Dimension name (e.g., product_name)")
    operator: str = Field(..., description="One of =, !=, >, >=, <, <=, IN, ILIKE")
    value: Any = Field(..., description="Filter value or list of values for IN")
    model_config = {
        "json_schema_extra": {
            "example": {"field": "product_name", "operator": "=", "value": "MS"}
        }
    }


class QueryRequest(BaseModel):
    question: Optional[str] = Field(
        None,
        description="Natural language question",
        examples=["Top 5 sales areas by sales volume for MS in Q2 FY 2024-2025."],
    )
    tenant_id: Optional[str] = Field(
        None,
        description="Tenant identifier for glossary/context enrichment",
        examples=["tenant_a"],
    )
    domain_id: Optional[str] = Field(
        None,
        description="Domain identifier for glossary/context enrichment",
        examples=["manufacturing"],
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
    model_config = {
        "json_schema_extra": {
            "example": {
                "question": "Top 5 sales areas by sales volume for MS in Q2 FY 2024-2025.",
                "tenant_id": "tenant_a",
                "domain_id": "manufacturing",
                "limit": 100,
                "explain": True,
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "metrics": ["total_sales_volume_tmt"],
                "dimensions": ["sales_area_name", "fiscal_year"],
                "sql": "SELECT sales_area_name, SUM(sales_tmt) AS total_sales_volume_tmt FROM ...",
                "rows": [{"sales_area_name": "Tenali", "total_sales_volume_tmt": 123.4}],
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "metrics": [
                    {
                        "name": "total_sales_volume_tmt",
                        "type": "sum",
                        "grain": "day",
                        "status": "certified",
                        "owner": "analytics@company.com",
                        "version": "v1",
                    }
                ],
                "limit": 200,
                "cursor": None,
                "next_cursor": None,
            }
        }
    }


class SchemaResponse(BaseModel):
    models: List[dict] = Field(
        examples=[[{"name": "fact_hpcl_sales_daily", "schema": "public"}]]
    )
    limit: int = Field(200, examples=[200])
    cursor: str | None = Field(None, examples=["ZmFjdF9ocGNsX3NhbGVzX2RhaWx5"])
    next_cursor: str | None = Field(None, examples=["ZmFjdF9ocGNsX3NhbGVzX21vbnRobHlfdGFyZ2V0cw=="])
    model_config = {
        "json_schema_extra": {
            "example": {
                "models": [{"name": "fact_hpcl_sales_daily", "schema": "public"}],
                "limit": 200,
                "cursor": None,
                "next_cursor": None,
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "datasets": [
                    {
                        "name": "sales_area_performance",
                        "source_model": "fact_hpcl_sales_daily",
                        "description": "Sales performance by sales area and product",
                    }
                ],
                "limit": 200,
                "cursor": None,
                "next_cursor": None,
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "dimensions": [
                    {
                        "name": "sales_area_name",
                        "description": "Sales area",
                        "data_type": "string",
                        "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_area_name",
                    }
                ]
            }
        }
    }


class DimensionValuesResponse(BaseModel):
    dimension: str = Field(..., examples=["sales_area_name"])
    values: List[dict] = Field(
        examples=[[{"value": "Tenali"}]]
    )
    limit: int = Field(100, examples=[100])
    cursor: str | None = Field(None, examples=["VmlqYXlhd2FkYQ=="])
    next_cursor: str | None = Field(None, examples=["VGVuYWxp"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "dimension": "sales_area_name",
                "values": [{"value": "Tenali"}],
                "limit": 100,
                "cursor": None,
                "next_cursor": None,
            }
        }
    }


class EntityOverrideRequest(BaseModel):
    description: str | None = Field(
        None, examples=["Organizational hierarchy for sales operations"]
    )
    join_key: str | None = Field(None, examples=["sales_area_name"])
    examples: List[str] | None = Field(default=None, examples=[["zone", "region", "sales_area"]])
    model_config = {
        "json_schema_extra": {
            "example": {
                "description": "Organizational hierarchy for sales operations",
                "join_key": "sales_area_name",
                "examples": ["zone", "region", "sales_area"],
            }
        }
    }


class HierarchyOverrideRequest(BaseModel):
    levels: List[str] = Field(default_factory=list, examples=[["zone", "region", "sales_area"]])
    description: str | None = Field(None, examples=["Sales organization rollup"])
    model_config = {
        "json_schema_extra": {
            "example": {"levels": ["zone", "region", "sales_area"], "description": "Sales rollup"}
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "entities": [{"entity_id": "organizational_unit", "join_key": "sales_area_name"}],
                "hierarchies": [
                    {"name": "sales_org", "levels": ["sbu", "zone", "region", "sales_area"]}
                ],
                "entity_limit": 200,
                "entity_cursor": None,
                "entity_next_cursor": None,
                "hierarchy_limit": 200,
                "hierarchy_cursor": None,
                "hierarchy_next_cursor": None,
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "policies": [
                    {"policy_id": "sbu_exclusion", "description": "Exclude SBU values"}
                ]
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "lineage": [
                    {
                        "metric_name": "total_sales_volume_tmt",
                        "dataset": "fact_hpcl_sales_daily",
                        "dbt_model": "fact_hpcl_sales_daily",
                    }
                ]
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "insights": [
                    {
                        "insight_id": "ins_123",
                        "insight_type": "variance",
                        "headline": "Sales volume decreased 4.2% vs last month",
                        "severity": "medium",
                        "confidence": 0.8,
                    }
                ],
                "limit": 200,
                "cursor": None,
                "next_cursor": None,
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "insight": {
                    "insight_id": "ins_123",
                    "insight_type": "variance",
                    "headline": "Sales volume decreased 4.2% vs last month",
                    "severity": "medium",
                    "confidence": 0.8,
                    "entity_scope": {"sales_area_name": "Tenali"},
                }
            }
        }
    }


class ActionCreateRequest(BaseModel):
    domain_id: str = Field(..., examples=["energy_distribution"])
    headline: str = Field(..., examples=["Investigate sales drop in Tenali"])
    severity: str | None = Field(None, examples=["medium"])
    status: str | None = Field("open", examples=["open"])
    assigned_to: str | None = Field(None, examples=["ops_manager@company.com"])
    source_insight_id: str | None = Field(None, examples=["ins_123"])
    scenario_id: str | None = Field(None, examples=["baseline"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "domain_id": "energy_distribution",
                "headline": "Investigate sales drop in Tenali",
                "severity": "medium",
                "status": "open",
                "assigned_to": "ops_manager@company.com",
                "source_insight_id": "ins_123",
            }
        }
    }


class ActionUpdateRequest(BaseModel):
    headline: str | None = Field(None, examples=["Re-check distributor plan"])
    severity: str | None = Field(None, examples=["high"])
    status: str | None = Field(None, examples=["in_progress"])
    assigned_to: str | None = Field(None, examples=["ops_manager@company.com"])
    model_config = {
        "json_schema_extra": {
            "example": {"headline": "Re-check distributor plan", "status": "in_progress"}
        }
    }


class ActionFeedbackRequest(BaseModel):
    status: str | None = Field(None, examples=["resolved"])
    outcome: str | None = Field(None, examples=["Distributor restocked"])
    notes: str | None = Field(None, examples=["Root cause was delayed shipment"])
    impact_window: dict | None = Field(None, examples=[{"start": "2025-02-01", "end": "2025-02-28"}])
    assigned_to: str | None = Field(None, examples=["ops_manager@company.com"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "resolved",
                "outcome": "Distributor restocked",
                "notes": "Root cause was delayed shipment",
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "actions": [
                    {
                        "action_id": "act_123",
                        "headline": "Investigate sales drop in Tenali",
                        "status": "open",
                        "severity": "medium",
                    }
                ],
                "limit": 200,
                "cursor": None,
                "next_cursor": None,
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "action": {
                    "action_id": "act_123",
                    "headline": "Investigate sales drop in Tenali",
                    "status": "open",
                    "severity": "medium",
                }
            }
        }
    }


class ActionCreateResponse(BaseModel):
    action_id: str = Field(..., examples=["act_123"])
    status: str = Field(..., examples=["open"])
    model_config = {"json_schema_extra": {"example": {"action_id": "act_123", "status": "open"}}}


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "scenarios": [
                    {
                        "scenario_id": "baseline",
                        "domain_id": "energy_distribution",
                        "name": "Baseline",
                        "status": "ready",
                        "is_baseline": True,
                    }
                ],
                "limit": 200,
                "cursor": None,
                "next_cursor": None,
            }
        }
    }


class ScenarioCreateRequest(BaseModel):
    scenario_id: str | None = Field(None, examples=["scenario_001"])
    domain_id: str = Field(..., examples=["energy_distribution"])
    name: str = Field(..., examples=["Distribution Disruption"])
    description: str | None = Field(None, examples=["Simulate loss of supply in Zone A"])
    status: str | None = Field("draft", examples=["draft"])
    is_baseline: bool | None = Field(False, examples=[False])
    created_by: str | None = Field(None, examples=["planner@company.com"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "scenario_id": "scenario_001",
                "domain_id": "energy_distribution",
                "name": "Distribution Disruption",
                "description": "Simulate loss of supply in Zone A",
                "status": "draft",
            }
        }
    }


class ScenarioUpdateRequest(BaseModel):
    name: str | None = Field(None, examples=["Distribution Disruption"])
    description: str | None = Field(None, examples=["Updated description"])
    status: str | None = Field(None, examples=["ready"])
    is_baseline: bool | None = Field(None, examples=[False])
    model_config = {
        "json_schema_extra": {
            "example": {"name": "Distribution Disruption", "status": "ready"}
        }
    }


class ScenarioRunRequest(BaseModel):
    parameters: dict = Field(default_factory=dict, examples=[{"uplift_pct": 3}])
    model_config = {"json_schema_extra": {"example": {"parameters": {"uplift_pct": 3}}}}


class ScenarioCompareRequest(BaseModel):
    base_scenario_id: str = Field(..., examples=["baseline"])
    compare_scenario_id: str = Field(..., examples=["scenario_001"])
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "base_scenario_id": "baseline",
                "compare_scenario_id": "scenario_001",
                "metric_name": "total_sales_volume_tmt",
            }
        }
    }


class ScenarioRunResponse(BaseModel):
    scenario_id: str = Field(..., examples=["scenario_001"])
    status: str = Field(..., examples=["completed"])
    model_config = {"json_schema_extra": {"example": {"scenario_id": "scenario_001", "status": "completed"}}}


class ScenarioCompareResponse(BaseModel):
    base_scenario_id: str = Field(..., examples=["baseline"])
    compare_scenario_id: str = Field(..., examples=["scenario_001"])
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    delta: float | None = Field(None, examples=[12.3])
    model_config = {
        "json_schema_extra": {
            "example": {
                "base_scenario_id": "baseline",
                "compare_scenario_id": "scenario_001",
                "metric_name": "total_sales_volume_tmt",
                "delta": 12.3,
            }
        }
    }


class TimeSeriesRequest(BaseModel):
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    grain: str = Field("month", examples=["month"])
    filters: List[QueryFilter] = Field(default_factory=list)
    limit: int = Field(24, ge=1, le=1000)
    window: int = Field(6, ge=2, le=52)
    threshold: float = Field(2.5, ge=0.1, le=10)
    model_config = {
        "json_schema_extra": {
            "example": {
                "metric_name": "total_sales_volume_tmt",
                "grain": "month",
                "filters": [{"field": "product_name", "operator": "=", "value": "MS"}],
                "limit": 24,
                "window": 6,
                "threshold": 2.5,
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "metric_name": "total_sales_volume_tmt",
                "grain": "month",
                "series": [
                    {
                        "period": "2024-01-01",
                        "actual": 1200.5,
                        "baseline": 1150.0,
                        "deviation": 50.5,
                        "z_score": 1.2,
                        "is_anomaly": False,
                    }
                ],
            }
        }
    }


class InsightDetailWithContextResponse(BaseModel):
    insight: dict
    drivers: List[dict] = Field(default_factory=list)
    correlations: List[dict] = Field(default_factory=list)
    model_config = {
        "json_schema_extra": {
            "example": {
                "insight": {
                    "insight_id": "ins_123",
                    "insight_type": "variance",
                    "headline": "Sales volume decreased 4.2% vs last month",
                },
                "drivers": [{"dimension": "product_name", "value": "MS", "delta": -120.3}],
                "correlations": [{"metric": "inventory_days", "correlation": -0.62}],
            }
        }
    }


class OnboardScanRequest(BaseModel):
    schema: str | None = Field(None, examples=["public"])
    schemas: List[str] | None = Field(None, examples=[["public", "staging"]])
    tables: List[str] | None = Field(None, examples=[["fact_production_daily", "dim_plant"]])
    connection_id: str | None = Field(None, examples=["conn_prod"])
    database: str | None = Field(None, examples=["prod_warehouse"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "schema": "public",
                "tables": ["fact_production_daily", "dim_plant"],
                "connection_id": "conn_prod",
                "database": "prod_warehouse",
            }
        }
    }


class OnboardScanResponse(BaseModel):
    tables: List[dict]
    model_config = {
        "json_schema_extra": {
            "example": {
                "tables": [
                    {
                        "table": "fact_production_daily",
                        "columns": [
                            {"name": "production_date", "type": "date", "profile": "100% non-null"}
                        ],
                    }
                ]
            }
        }
    }


class OnboardMapResponse(BaseModel):
    candidates: List[dict]
    low_confidence_candidates: List[dict]
    low_confidence_threshold: float = Field(
        0.7, description="Confidence threshold used to classify low-confidence candidates"
    )
    model_config = {
        "json_schema_extra": {
            "example": {
                "candidates": [
                    {
                        "column": "sales_area_name",
                        "entity_id": "organizational_unit",
                        "confidence": 0.85,
                    }
                ],
                "low_confidence_candidates": [],
                "low_confidence_threshold": 0.7,
            }
        }
    }


class ContextIngestRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str = Field(..., examples=["manufacturing"])
    source_type: str = Field(..., examples=["business_context"])
    source_title: str | None = Field(None, examples=["Operations glossary and hierarchy notes"])
    raw_text: str = Field(..., examples=["SBU = Strategic Business Unit. Sales org is Zone > Region > Sales Area."])
    metadata: dict | None = Field(
        default=None,
        examples=[
            {
                "connection_id": "conn_prod",
                "database": "prod_warehouse",
                "schema": "public",
                "tables": ["fact_production_daily", "dim_plant"],
                "columns": ["plant_name", "region_name"],
            }
        ],
    )
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "domain_id": "manufacturing",
                "source_type": "business_context",
                "source_title": "Operations glossary and hierarchy notes",
                "raw_text": "SBU = Strategic Business Unit. Sales org is Zone > Region > Sales Area.",
                "metadata": {
                    "connection_id": "conn_prod",
                    "database": "prod_warehouse",
                    "schema": "public",
                    "tables": ["fact_production_daily", "dim_plant"],
                    "columns": ["plant_name", "region_name"],
                },
            }
        }
    }


class ContextIngestResponse(BaseModel):
    context_id: str = Field(..., examples=["ctx_123"])
    status: str = Field(..., examples=["submitted"])
    model_config = {
        "json_schema_extra": {"example": {"context_id": "ctx_123", "status": "submitted"}}
    }


class ContextListResponse(BaseModel):
    entries: List[dict]
    limit: int = Field(200, examples=[200])
    cursor: str | None = Field(None, examples=["MjAyNS0wMS0wMVQwMDowMDowMFo="])
    next_cursor: str | None = Field(None, examples=["MjAyNS0wMS0wMVQwMDowMDowMFo="])
    model_config = {
        "json_schema_extra": {
            "example": {
                "entries": [
                    {
                        "context_id": "ctx_123",
                        "source_type": "business_context",
                        "source_title": "Operations glossary",
                        "status": "submitted",
                        "created_at": "2025-02-14T10:00:00Z",
                    }
                ],
                "limit": 200,
                "cursor": None,
                "next_cursor": None,
            }
        }
    }


class ContextExtractRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str = Field(..., examples=["manufacturing"])
    context_id: str = Field(..., examples=["ctx_123"])
    extraction_types: List[str] = Field(
        default_factory=list,
        examples=[["abbreviations", "synonyms", "hierarchies", "metric_candidates", "question_intents"]],
    )
    model: str | None = Field(None, examples=["gpt-4o-mini"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "domain_id": "manufacturing",
                "context_id": "ctx_123",
                "extraction_types": [
                    "abbreviations",
                    "synonyms",
                    "hierarchies",
                    "metric_candidates",
                    "question_intents",
                ],
                "model": "gpt-4o-mini",
            }
        }
    }


class ContextExtractResponse(BaseModel):
    extraction_id: str = Field(..., examples=["ext_123"])
    context_id: str = Field(..., examples=["ctx_123"])
    extractions: dict
    model_config = {
        "json_schema_extra": {
            "example": {
                "extraction_id": "ext_123",
                "context_id": "ctx_123",
                "extractions": {
                    "abbreviations": [{"abbr": "SBU", "definition": "Strategic Business Unit"}],
                    "synonyms": [{"term": "sales area", "synonyms": ["territory"]}],
                    "hierarchies": [{"name": "sales_org", "levels": ["zone", "region", "sales_area"]}],
                    "metric_candidates": [{"metric_name": "output_tmt", "table": "fact_production_daily"}],
                    "question_intents": [
                        {"question": "Which plants are underperforming?", "metrics": ["output_tmt"]}
                    ],
                },
            }
        }
    }


class ContextApplyRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str = Field(..., examples=["manufacturing"])
    extraction_id: str = Field(..., examples=["ext_123"])
    apply: dict = Field(
        default_factory=dict,
        examples=[{"entities": True, "hierarchies": True, "glossary": True, "metrics": True}],
    )
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "domain_id": "manufacturing",
                "extraction_id": "ext_123",
                "apply": {"entities": True, "hierarchies": True, "glossary": True, "metrics": True},
            }
        }
    }


class ContextApplyResponse(BaseModel):
    status: str = Field(..., examples=["applied"])
    updated: dict = Field(default_factory=dict)
    model_config = {
        "json_schema_extra": {
            "example": {"status": "applied", "updated": {"entities": 4, "hierarchies": 1, "metrics": 8}}
        }
    }


class OnboardScanSchemaSpec(BaseModel):
    name: str = Field(..., examples=["public"])
    tables: List[str] | None = Field(None, examples=[["fact_production_daily", "dim_plant"]])
    limit: int = Field(20, ge=1, le=500, examples=[20])
    cursor: str | None = Field(None, examples=["ZmFjdF9wcm9kdWN0aW9uX2RhaWx5"])


class OnboardScanDatabaseSpec(BaseModel):
    name: str = Field(..., examples=["prod_warehouse"])
    schemas: List[OnboardScanSchemaSpec] = Field(default_factory=list)


class OnboardScanConnectionSpec(BaseModel):
    connection_id: str = Field(..., examples=["conn_prod"])
    db_type: str = Field(..., examples=["postgres"])
    host: str = Field(..., examples=["db.company.com"])
    port: int = Field(5432, examples=[5432])
    user: str = Field(..., examples=["readonly_user"])
    password: str = Field(..., examples=["******"])
    sample_rows: int = Field(100, ge=10, le=100, examples=[100])
    databases: List[OnboardScanDatabaseSpec] = Field(default_factory=list)


class OnboardScanMultiConnectionRequest(BaseModel):
    connections: List[OnboardScanConnectionSpec] = Field(default_factory=list)
    model_config = {
        "json_schema_extra": {
            "example": {
                "connections": [
                    {
                        "connection_id": "conn_prod",
                        "db_type": "postgres",
                        "host": "db.company.com",
                        "port": 5432,
                        "user": "readonly_user",
                        "password": "******",
                        "sample_rows": 100,
                        "databases": [{"name": "prod_warehouse", "schemas": [{"name": "public"}]}],
                    }
                ]
            }
        }
    }


class OnboardScanSchemaResult(BaseModel):
    name: str = Field(..., examples=["public"])
    tables: List[dict]
    limit: int = Field(20, examples=[20])
    cursor: str | None = Field(None, examples=["ZmFjdF9wcm9kdWN0aW9uX2RhaWx5"])
    next_cursor: str | None = Field(None, examples=["ZGltX3BsYW50"])


class OnboardScanDatabaseResult(BaseModel):
    name: str = Field(..., examples=["prod_warehouse"])
    schemas: List[OnboardScanSchemaResult] = Field(default_factory=list)


class OnboardScanConnectionResult(BaseModel):
    connection_id: str = Field(..., examples=["conn_prod"])
    databases: List[OnboardScanDatabaseResult] = Field(default_factory=list)


class OnboardScanConnectionResponse(BaseModel):
    connections: List[OnboardScanConnectionResult] = Field(default_factory=list)
    model_config = {
        "json_schema_extra": {
            "example": {
                "connections": [
                    {
                        "connection_id": "conn_prod",
                        "databases": [
                            {
                                "name": "prod_warehouse",
                                "schemas": [
                                    {
                                        "name": "public",
                                        "tables": [{"table": "fact_production_daily"}],
                                        "limit": 20,
                                        "cursor": None,
                                        "next_cursor": None,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }
    }


class InferModelsRequest(BaseModel):
    schema: str = Field("public", examples=["public"])
    schemas: List[str] | None = Field(None, examples=[["public", "staging"]])
    tables: List[str] | None = Field(None, examples=[["fact_production_daily", "dim_plant"]])
    time_column: str | None = Field(None, examples=["production_date"])
    grain: str | None = Field(None, examples=["day"])
    use_llm: bool = Field(False, examples=[True])
    connection_id: str | None = Field(None, examples=["conn_prod"])
    database: str | None = Field(None, examples=["prod_warehouse"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "schema": "public",
                "tables": ["fact_production_daily", "dim_plant"],
                "grain": "day",
                "use_llm": False,
                "connection_id": "conn_prod",
                "database": "prod_warehouse",
            }
        }
    }


class InferModelsResponse(BaseModel):
    facts: List[dict]
    dimensions: List[dict]
    model_config = {
        "json_schema_extra": {
            "example": {
                "facts": [{"table": "fact_production_daily", "time_column": "production_date"}],
                "dimensions": [{"table": "dim_plant", "primary_key": "plant_id"}],
            }
        }
    }


class SuggestedMetricsResponse(BaseModel):
    measures: List[dict]
    low_confidence_measures: List[dict]
    low_confidence_threshold: float = Field(
        0.7, description="Confidence threshold used to classify low-confidence measures"
    )
    time_columns: List[dict]
    entity_candidates: List[dict]
    model_config = {
        "json_schema_extra": {
            "example": {
                "measures": [{"table": "fact_production_daily", "column": "output_tmt"}],
                "low_confidence_measures": [],
                "low_confidence_threshold": 0.7,
                "time_columns": [{"table": "fact_production_daily", "column": "production_date"}],
                "entity_candidates": [{"column": "plant_name", "entity_id": "plant"}],
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {
                "domain_id": "energy_distribution",
                "metric_name": "total_sales_volume_tmt",
                "type": "sum",
                "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_tmt",
                "grain": "day",
                "dimensions": ["sales_area_name", "fiscal_year"],
                "status": "suggested",
            }
        }
    }


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
    model_config = {
        "json_schema_extra": {
            "example": {"display_name": "Total Sales Volume (TMT)", "status": "certified"}
        }
    }


class MetricUpsertResponse(BaseModel):
    metric_id: str = Field(..., examples=["energy_distribution__total_sales_volume_tmt"])
    status: str = Field(..., examples=["suggested"])
    model_config = {
        "json_schema_extra": {
            "example": {"metric_id": "energy_distribution__total_sales_volume_tmt", "status": "suggested"}
        }
    }


class ContractMetric(BaseModel):
    metric_name: str = Field(..., examples=["total_sales_volume_tmt"])
    type: str = Field(..., examples=["sum"])
    sql: str = Field(..., examples=["{{ ref('fact_hpcl_sales_daily') }}.sales_tmt"])
    grain: str = Field(..., examples=["day"])
    dimensions: List[str] = Field(default_factory=list, examples=[["sales_area_name", "fiscal_year"]])


class ContractValidateRequest(BaseModel):
    metrics: List[ContractMetric] = Field(default_factory=list)
    model_config = {
        "json_schema_extra": {
            "example": {
                "metrics": [
                    {
                        "metric_name": "total_sales_volume_tmt",
                        "type": "sum",
                        "sql": "{{ ref('fact_hpcl_sales_daily') }}.sales_tmt",
                        "grain": "day",
                        "dimensions": ["sales_area_name", "fiscal_year"],
                    }
                ]
            }
        }
    }


class ContractValidateResponse(BaseModel):
    valid: bool = Field(..., examples=[True])
    errors: List[dict] = Field(default_factory=list)
    warnings: List[dict] = Field(default_factory=list)
    model_config = {
        "json_schema_extra": {"example": {"valid": True, "errors": [], "warnings": []}}
    }
