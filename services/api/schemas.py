from __future__ import annotations

from enum import Enum
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
                "limit": 100,
                "explain": True,
            }
        }
    }


class ChatRequest(BaseModel):
    question: str = Field(..., description="Natural language question")
    tenant_id: str = Field(..., description="Tenant identifier")
    domain_id: Optional[str] = Field(None, description="Domain identifier")
    metrics: Optional[List[str]] = Field(None, description="Metric names to query")
    dimensions: List[str] = Field(default_factory=list, description="Dimensions to group by")
    filters: List[QueryFilter] = Field(default_factory=list, description="Filters to apply")
    limit: int = Field(200, ge=1, le=1000, description="Row limit")
    explain: bool = Field(False, description="Include SQL details")
    mode: str = Field("sync", description="sync or async", examples=["sync", "async"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "question": "What is total LPG production by plant last week?",
                "tenant_id": "VC_101",
                "domain_id": "lpg_production_distribution",
                "mode": "sync",
            }
        }
    }


class ChatResponse(BaseModel):
    chat_id: Optional[str] = None
    status: str
    response: Optional[dict] = None
    error_message: Optional[str] = None

class QueryResult(BaseModel):
    metrics: List[str] = Field(examples=[["total_sales_volume_tmt"]])
    dimensions: List[str] = Field(examples=[["sales_area_name", "fiscal_year"]])
    chart_id: Optional[str] = Field(
        None,
        description="Chart request id for async chart rendering",
        examples=["chart_2f7a9c4d"],
    )
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
    semantic_validation: Optional[dict] = Field(
        None,
        examples=[
            {
                "definitions": ["total_sales_volume_tmt"],
                "assumptions": ["default grain=day"],
                "policy_applied": [],
            }
        ],
    )
    lineage: Optional[dict] = Field(
        None,
        examples=[{"models": ["fact_sales"], "tables": ["public.fact_sales"]}],
    )
    model_config = {
        "json_schema_extra": {
            "example": {
                "metrics": ["total_sales_volume_tmt"],
                "dimensions": ["sales_area_name", "fiscal_year"],
                "sql": "SELECT sales_area_name, SUM(sales_tmt) AS total_sales_volume_tmt FROM ...",
                "rows": [{"sales_area_name": "Tenali", "total_sales_volume_tmt": 123.4}],
                "semantic_validation": {
                    "definitions": ["total_sales_volume_tmt"],
                    "assumptions": ["default grain=day"],
                    "policy_applied": [],
                },
                "lineage": {"models": ["fact_sales"], "tables": ["public.fact_sales"]},
            }
        }
    }


class ChartRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    domain_id: Optional[str] = Field(None, description="Domain identifier")
    question: Optional[str] = Field(None, description="Natural language question")
    metrics: Optional[List[str]] = Field(None, description="Metric names to query")
    dimensions: Optional[List[str]] = Field(None, description="Dimensions to group by")
    filters: Optional[List[QueryFilter]] = Field(None, description="Filters to apply")
    limit: int = Field(200, ge=1, le=1000, description="Row limit")


class ChartStatusResponse(BaseModel):
    chart_id: str
    status: str
    chart_type: Optional[str] = None
    chart_payload: Optional[dict] = None
    data: Optional[List[dict]] = None
    sql: Optional[str] = None
    params: Optional[List[Any]] = None
    rows_json: Optional[List[dict]] = None
    error_message: Optional[str] = None


class RollupCreateRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    domain_id: Optional[str] = Field(None, description="Domain identifier")
    metric_name: str = Field(..., description="Metric name to roll up")
    dimensions: List[str] = Field(default_factory=list, description="Dimensions to group by")
    time_grain: str = Field(
        "none",
        description="Rollup time grain. Use 'none' if no time dimension.",
        examples=["none", "day", "week", "month"],
    )
    filters: Optional[List[dict]] = Field(None, description="Optional filters for the rollup")
    build_now: bool = Field(True, description="Build rollup table immediately")


class RollupResponse(BaseModel):
    rollup_id: str
    tenant_id: str
    domain_id: str
    base_model: str
    metric_name: str
    dimensions: List[str]
    time_grain: str
    filters: Optional[List[dict]] = None
    rollup_table: str
    status: str


class RollupRefreshResponse(BaseModel):
    rollup_id: str
    status: str


class SemanticFeedbackRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier")
    domain_id: Optional[str] = Field(None, description="Domain identifier")
    edge_id: str = Field(..., description="Semantic edge identifier")
    action: str = Field(..., description="confirm|reject|correct")
    delta_confidence: Optional[float] = Field(
        None,
        description="Confidence delta to apply to edge",
        examples=[0.1, -0.2],
    )
    notes: Optional[str] = Field(None, description="Optional feedback notes")


class SemanticFeedbackResponse(BaseModel):
    feedback_id: str
    tenant_id: str
    domain_id: str
    edge_id: str
    action: str
    delta_confidence: Optional[float] = None
    notes: Optional[str] = None


class ViewListResponse(BaseModel):
    views: List[dict]


class ViewSchemaResponse(BaseModel):
    view_name: str
    schema_name: str = Field(..., alias="schema")
    columns: List[dict]
    model_config = {"populate_by_name": True}


class ViewQueryRequest(BaseModel):
    tenant_id: str
    sql: str
    limit: int = Field(200, ge=1, le=1000, description="Row limit")


class ViewQueryResponse(BaseModel):
    rows: List[dict]
    columns: List[str]
    row_count: int
    chart: Optional[dict] = None


class DashboardListResponse(BaseModel):
    dashboards: List[dict]


class DashboardResponse(BaseModel):
    dashboard_id: str
    tenant_id: str
    domain_id: str
    title: str
    spec: dict
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DashboardUpdateRequest(BaseModel):
    action: str = Field(..., description="Currently supported: delete_chart")
    chart_id: Optional[str] = Field(None, description="Chart id to delete from dashboard spec")
    chart_index: Optional[int] = Field(
        None,
        ge=0,
        description="Fallback chart index to delete when chart_id is unavailable",
    )
    chart_title: Optional[str] = Field(None, description="Fallback chart title to delete")


class TenantCreateRequest(BaseModel):
    tenant_id: str = Field(..., description="Tenant identifier", examples=["VC_101"])
    display_name: Optional[str] = Field(None, description="Tenant display name", examples=["HPCL LPG"])
    domain_id: str = Field(..., description="Default domain for the tenant", examples=["lpg_production_distribution"])
    status: str = Field("active", description="Tenant status", examples=["active"])
    metadata: dict | None = Field(None, description="Optional tenant metadata")
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "VC_101",
                "display_name": "HPCL LPG",
                "domain_id": "lpg_production_distribution",
                "status": "active",
                "metadata": {"region": "IN"},
            }
        }
    }


class TenantUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, description="Tenant display name", examples=["HPCL LPG"])
    domain_id: Optional[str] = Field(None, description="Default domain for the tenant", examples=["lpg_production_distribution"])
    status: Optional[str] = Field(None, description="Tenant status", examples=["active"])
    metadata: dict | None = Field(None, description="Optional tenant metadata")


class TenantResponse(BaseModel):
    tenant_id: str
    display_name: Optional[str] = None
    status: str
    domain_id: Optional[str] = None
    metadata: dict | None = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TenantsResponse(BaseModel):
    tenants: List[dict] = Field(
        examples=[
            [
                {
                    "tenant_id": "VC_101",
                    "display_name": "HPCL LPG",
                    "status": "active",
                    "domain_id": "lpg_production_distribution",
                }
            ]
        ]
    )
    limit: int = Field(200, examples=[200])


class MetricsResponse(BaseModel):
    metrics: List[dict] = Field(
        examples=[
            [
                {
                    "metric_name": "total_sales",
                    "type": "sum",
                    "grain": "day",
                    "sql": "{{ ref('fact_sales') }}.sales_amount",
                    "dimensions": ["sales_area_name"],
                    "tables": ["fact_sales"],
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
                        "metric_name": "total_sales",
                        "type": "sum",
                        "grain": "day",
                        "sql": "{{ ref('fact_sales') }}.sales_amount",
                        "dimensions": ["sales_area_name"],
                        "tables": ["fact_sales"],
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


class ContextAppliedEntity(BaseModel):
    entity_id: str
    description: Optional[str] = None
    join_key: Optional[str] = None
    examples: Optional[List[str]] = None
    lifecycle_status: Optional[str] = None


class ContextAppliedHierarchy(BaseModel):
    name: str
    levels: Optional[List[str]] = None
    description: Optional[str] = None
    hierarchy_group: Optional[str] = None
    lifecycle_status: Optional[str] = None


class ContextAppliedGlossary(BaseModel):
    term_id: Optional[str] = None
    term: str
    definition: Optional[str] = None
    synonyms: Optional[List[str]] = None
    abbreviations: Optional[List[str]] = None
    lifecycle_status: Optional[str] = None


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
    status: str | None = Field(None, examples=["suggested", "certified"])
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
    context_id: str | None = Field(None, examples=["ctx_123"])
    hierarchy_group: str | None = Field(None, examples=["geography"])
    levels: List[str] = Field(default_factory=list, examples=[["zone", "region", "sales_area"]])
    description: str | None = Field(None, examples=["Sales organization rollup"])
    status: str | None = Field(None, examples=["suggested", "certified"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "context_id": "ctx_123",
                "hierarchy_group": "geography",
                "levels": ["zone", "region", "sales_area"],
                "description": "Sales rollup",
            }
        }
    }


class HierarchyUpdateRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    hierarchy_name: str = Field(..., examples=["Geographic Hierarchy"])
    context_id: str | None = Field(None, examples=["ctx_123"])
    hierarchy_group: str | None = Field(None, examples=["geography"])
    levels: List[str] = Field(default_factory=list, examples=[["zone", "region", "sales_area"]])
    description: str | None = Field(None, examples=["Sales organization rollup"])
    status: str | None = Field(None, examples=["suggested", "certified"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "hierarchy_name": "Geographic Hierarchy",
                "context_id": "ctx_123",
                "hierarchy_group": "geography",
                "levels": ["zone", "region", "sales_area"],
                "description": "Sales rollup",
                "status": "certified",
            }
        }
    }

class EntitiesResponse(BaseModel):
    entities: List[dict] = Field(
        examples=[[{"entity_id": "organizational_unit", "join_key": "sales_area_name"}]]
    )
    hierarchies: List[dict] = Field(
        examples=[[{"name": "sales_org", "levels": ["sbu", "zone", "region", "sales_area"]}]]
    )
    entity_limit: int | None = Field(None, examples=[200])
    entity_cursor: str | None = Field(None, examples=["b3JnYW5pemF0aW9uYWxfdW5pdA=="])
    entity_next_cursor: str | None = Field(None, examples=["cHJvZHVjdA=="])
    hierarchy_limit: int | None = Field(None, examples=[200])
    hierarchy_cursor: str | None = Field(None, examples=["c2FsZXNfb3Jn"])
    hierarchy_next_cursor: str | None = Field(None, examples=["cmVnaW9uX29yZw=="])
    model_config = {
        "json_schema_extra": {
            "example": {
                "entities": [{"entity_id": "organizational_unit", "join_key": "sales_area_name"}],
                "hierarchies": [
                    {"name": "sales_org", "levels": ["sbu", "zone", "region", "sales_area"]}
                ],
            }
        }
    }


class EntitiesAllResponse(BaseModel):
    connections: List[dict] = Field(
        examples=[
            [
                {
                    "entities": [{"entity_id": "organizational_unit"}],
                    "hierarchies": [{"name": "sales_org", "levels": ["zone", "region"]}],
                }
            ]
        ]
    )


class FactsUpsertRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    table_name: str = Field(..., examples=["fact_sales"])
    grain: str | None = Field(None, examples=["day"])
    time_column: str | None = Field(None, examples=["sales_date"])
    measures: List[str] = Field(default_factory=list, examples=[["sales_amount", "sales_tmt"]])
    dimensions: List[str] = Field(default_factory=list, examples=[["sales_area_name"]])
    description: str | None = Field(None, examples=["Daily sales fact"])
    status: str | None = Field("live", examples=["reviewed"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "table_name": "fact_sales",
                "grain": "day",
                "time_column": "sales_date",
                "measures": ["sales_amount", "sales_tmt"],
                "dimensions": ["sales_area_name"],
                "status": "live",
            }
        }
    }


class FactsPatchRequest(BaseModel):
    table_name: str | None = Field(None, examples=["fact_sales"])
    grain: str | None = Field(None, examples=["day"])
    time_column: str | None = Field(None, examples=["sales_date"])
    measures: List[str] | None = Field(None, examples=[["sales_amount"]])
    dimensions: List[str] | None = Field(None, examples=[["sales_area_name"]])
    description: str | None = Field(None, examples=["Updated description"])
    status: str | None = Field(None, examples=["reviewed"])


class FactsResponse(BaseModel):
    facts: List[dict] = Field(
        examples=[
            [
                {
                    "fact_id": "fact_123",
                    "table_name": "fact_sales",
                    "grain": "day",
                    "time_column": "sales_date",
                    "measures": ["sales_amount"],
                    "dimensions": ["sales_area_name"],
                    "status": "live",
                }
            ]
        ]
    )


class FactsAllResponse(BaseModel):
    connections: List[dict] = Field(
        examples=[
            [
                {
                    "facts": [{"fact_id": "fact_123", "table_name": "fact_sales"}],
                }
            ]
        ]
    )


class DimensionsUpsertRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    name: str = Field(..., examples=["dim_customer"])
    keys: List[str] = Field(default_factory=list, examples=[["customer_id"]])
    attributes: List[str] = Field(default_factory=list, examples=[["customer_name", "region_name"]])
    description: str | None = Field(None, examples=["Customer dimension"])
    status: str | None = Field("live", examples=["reviewed"])


class DimensionsPatchRequest(BaseModel):
    name: str | None = Field(None, examples=["dim_customer"])
    keys: List[str] | None = Field(None, examples=[["customer_id"]])
    attributes: List[str] | None = Field(None, examples=[["customer_name"]])
    description: str | None = Field(None, examples=["Updated description"])
    status: str | None = Field(None, examples=["reviewed"])


class DimensionsResponse(BaseModel):
    dimensions: List[dict] = Field(
        examples=[
            [
                {
                    "dimension_id": "dim_123",
                    "name": "dim_customer",
                    "keys": ["customer_id"],
                    "attributes": ["customer_name"],
                    "status": "live",
                }
            ]
        ]
    )


class DimensionsAllResponse(BaseModel):
    connections: List[dict] = Field(
        examples=[
            [
                {
                    "dimensions": [{"dimension_id": "dim_123", "name": "dim_customer"}],
                }
            ]
        ]
    )


class ReviewCreateRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    artifact_type: str = Field(..., examples=["entities"])
    artifact_id: str = Field(..., examples=["map_123"])
    status: str = Field(..., examples=["reviewed"], description="Enum: draft, reviewed, applied, rejected")
    notes: str | None = Field(None, examples=["Looks good"])
    payload: dict | None = Field(default=None, examples=[{"entities": 4}])


class ReviewPatchRequest(BaseModel):
    status: str | None = Field(
        None, examples=["applied"], description="Enum: draft, reviewed, applied, rejected"
    )
    notes: str | None = Field(None, examples=["Applied to registry"])


class ReviewResponse(BaseModel):
    review_id: str = Field(..., examples=["review_abc123"])
    status: str = Field(..., examples=["reviewed"])


class ReviewListResponse(BaseModel):
    reviews: List[dict] = Field(
        examples=[
            [
                {
                    "review_id": "review_abc123",
                    "artifact_type": "entities",
                    "artifact_id": "map_123",
                    "status": "reviewed",
                }
            ]
        ]
    )


class ReviewSummaryResponse(BaseModel):
    scan: dict | None = Field(default=None, examples=[{"tables": 12}])
    glossary: List[dict] = Field(default_factory=list)
    entities: List[dict] = Field(default_factory=list)
    hierarchies: List[dict] = Field(default_factory=list)
    facts: List[dict] = Field(default_factory=list)
    dimensions: List[dict] = Field(default_factory=list)
    metrics: List[dict] = Field(default_factory=list)
    ontology: dict | None = Field(default=None)


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
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["energy_distribution"])
    headline: str = Field(..., examples=["Investigate sales drop in Tenali"])
    severity: str | None = Field(None, examples=["medium"])
    status: str | None = Field("open", examples=["open"])
    assigned_to: str | None = Field(None, examples=["ops_manager@company.com"])
    source_insight_id: str | None = Field(None, examples=["ins_123"])
    scenario_id: str | None = Field(None, examples=["baseline"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
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
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["energy_distribution"])
    name: str = Field(..., examples=["Distribution Disruption"])
    description: str | None = Field(None, examples=["Simulate loss of supply in Zone A"])
    status: str | None = Field("live", examples=["live"])
    is_baseline: bool | None = Field(False, examples=[False])
    created_by: str | None = Field(None, examples=["planner@company.com"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "scenario_id": "scenario_001",
                "tenant_id": "tenant_a",
                "name": "Distribution Disruption",
                "description": "Simulate loss of supply in Zone A",
                "status": "live",
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
    tenant_id: str | None = Field(None, examples=["tenant_a"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
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
    mapping_id: str | None = Field(None, examples=["map_ab12cd34"])
    tenant_id: str | None = Field(None, examples=["tenant_a"])
    candidates: List[dict]
    low_confidence_candidates: List[dict]
    low_confidence_threshold: float = Field(
        0.7, description="Confidence threshold used to classify low-confidence candidates"
    )
    model_config = {
        "json_schema_extra": {
            "example": {
                "mapping_id": "map_ab12cd34",
                "tenant_id": "tenant_a",
                "candidates": [
                    {
                        "table": "fact_sales",
                        "column": "sales_area_name",
                        "entity_id": "organizational_unit",
                        "mapped_entity_type": "organizational_unit",
                        "confidence": 0.85,
                    }
                ],
                "low_confidence_candidates": [],
                "low_confidence_threshold": 0.7,
            }
        }
    }


class MappingApplySelectionMode(str, Enum):
    all = "all"
    selected = "selected"


class MappingCandidateSelection(BaseModel):
    table: str = Field(..., examples=["fact_sales"])
    column: str = Field(..., examples=["sales_area_name"])
    mapped_entity_type: str = Field(..., examples=["organizational_unit"])


class OnboardMapApplyRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    selection_mode: MappingApplySelectionMode = Field(MappingApplySelectionMode.all)
    candidates: List[MappingCandidateSelection] = Field(default_factory=list)
    status: str = Field("live", examples=["live"])
    notes: str | None = Field(None, examples=["Initial apply from mapping run"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "selection_mode": "all",
                "candidates": [],
                "status": "live",
                "notes": "Initial apply from mapping run",
            }
        }
    }


class OnboardMapApplyResponse(BaseModel):
    ok: bool = Field(..., examples=[True])
    mapping_id: str = Field(..., examples=["map_ab12cd34"])
    applied_count: int = Field(..., examples=[8])
    skipped_count: int = Field(..., examples=[2])
    status: str = Field(..., examples=["live"])
    review_id: str | None = Field(None, examples=["review_123"])
    mapping_status: str = Field(..., examples=["applied"])


class OnboardMapRunResponse(BaseModel):
    mapping_id: str = Field(..., examples=["map_ab12cd34"])
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str = Field(..., examples=["manufacturing"])
    connection_id: str = Field(..., examples=["conn_prod"])
    database_name: str = Field(..., examples=["prod_warehouse"])
    schema_name: str = Field(..., examples=["public"])
    tables: List[str] = Field(default_factory=list)
    candidates: List[dict] = Field(default_factory=list)
    low_confidence_candidates: List[dict] = Field(default_factory=list)
    low_confidence_threshold: float = Field(0.7, examples=[0.7])
    status: str = Field("live", examples=["live"])
    created_at: str | None = Field(None, examples=["2026-02-18T10:00:00Z"])
    updated_at: str | None = Field(None, examples=["2026-02-18T10:05:00Z"])


class ContextIngestRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    source_type: str = Field(..., examples=["business_context"])
    source_title: str | None = Field(None, examples=["Operations glossary and hierarchy notes"])
    raw_text: str | None = Field(
        None,
        examples=["SBU = Strategic Business Unit. Sales org is Zone > Region > Sales Area."],
    )
    file_ids: List[str] | None = Field(None, examples=[["file_123", "file_456"]])
    metadata: dict | None = Field(
        default=None,
        examples=[
            {
                "columns": ["plant_name", "region_name"],
            }
        ],
    )
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "source_type": "business_context",
                "source_title": "Operations glossary and hierarchy notes",
                "raw_text": "SBU = Strategic Business Unit. Sales org is Zone > Region > Sales Area.",
                "file_ids": ["file_123", "file_456"],
                "metadata": {
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


class ContextFileIngestResponse(BaseModel):
    file_id: str = Field(..., examples=["file_123"])
    status: str = Field(..., examples=["stored"])
    model_config = {
        "json_schema_extra": {"example": {"file_id": "file_123", "status": "stored"}}
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
                        "is_active": True,
                        "extraction_types": ["combined"],
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
    domain_id: str | None = Field(None, examples=["manufacturing"])
    context_id: str = Field(..., examples=["ctx_123"])
    extraction_types: List[str] = Field(
        default_factory=list,
        examples=[["abbreviations", "synonyms", "hierarchies", "metric_candidates", "question_intents"]],
    )
    mode: str | None = Field(None, examples=["parallel"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "context_id": "ctx_123",
                "extraction_types": [
                    "abbreviations",
                    "synonyms",
                    "hierarchies",
                    "metric_candidates",
                    "question_intents",
                ],
                "mode": "parallel",
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


class ContextExtractionResponse(BaseModel):
    extraction_id: str = Field(..., examples=["ext_123"])
    context_id: str = Field(..., examples=["ctx_123"])
    extraction_type: str | None = Field(None, examples=["combined"])
    payload: dict
    raw_text: Optional[str] = Field(None, examples=["Raw context text"])
    files: Optional[List[dict]] = Field(None, examples=[[{"file_id": "file_1", "filename": "notes.txt"}]])
    applied_glossary: Optional[List[ContextAppliedGlossary]] = None
    applied_entities: Optional[List[ContextAppliedEntity]] = None
    applied_hierarchies: Optional[List[ContextAppliedHierarchy]] = None
    status: str | None = Field(None, examples=["reviewed"])
    notes: str | None = Field(None, examples=["Reviewed by analyst"])
    created_at: str | None = Field(None, examples=["2025-02-14T10:00:00Z"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "extraction_id": "ext_123",
                "context_id": "ctx_123",
                "extraction_type": "combined",
                "payload": {"hierarchies": [{"name": "sales_org", "levels": ["zone", "region"]}]},
                "applied_glossary": [
                    {"term": "plant", "definition": "LPG filling facility", "synonyms": ["sap_id"]}
                ],
                "applied_entities": [
                    {"entity_id": "plant", "join_key": "sap_id", "lifecycle_status": "certified"}
                ],
                "applied_hierarchies": [
                    {"name": "sales_org", "levels": ["zone", "region", "sales_area"]}
                ],
                "status": "reviewed",
                "notes": "Reviewed by analyst",
                "created_at": "2025-02-14T10:00:00Z",
            }
        }
    }


class ContextExtractionListResponse(BaseModel):
    extractions: List[ContextExtractionResponse]


class ContextApplyRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    extraction_id: str = Field(..., examples=["ext_123"])
    apply: dict = Field(
        default_factory=dict,
        examples=[{"entities": True, "hierarchies": True, "glossary": True, "metrics": True}],
    )
    hierarchy_selection: dict | None = Field(
        None,
        examples=[{"names": ["geography", "supply_chain"], "apply_all": False}],
    )
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "extraction_id": "ext_123",
                "apply": {"entities": True, "hierarchies": True, "glossary": True, "metrics": True},
                "hierarchy_selection": {"names": ["geography"], "apply_all": False},
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


class ContextPatchRequest(BaseModel):
    source_title: str | None = Field(None, examples=["Operations glossary v2"])
    raw_text: str | None = Field(None, examples=["Updated glossary content..."])
    metadata: dict | None = Field(None, examples=[{"columns": ["sales_area_name"]}])
    status: str | None = Field(None, examples=["processed", "active", "inactive"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "source_title": "Operations glossary v2",
                "status": "processed",
                "metadata": {"columns": ["sales_area_name"]},
            }
        }
    }


class ContextFilePatchRequest(BaseModel):
    metadata: dict | None = Field(None, examples=[{"columns": ["sales_area_name"]}])
    model_config = {
        "json_schema_extra": {
            "example": {
                "metadata": {
                    "columns": ["sales_area_name"],
                }
            }
        }
    }


class ContextExtractionPatchRequest(BaseModel):
    status: str | None = Field(None, examples=["reviewed"])
    notes: str | None = Field(None, examples=["Reviewed by analytics lead"])
    model_config = {"json_schema_extra": {"example": {"status": "reviewed", "notes": "Looks good"}}}


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
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    connections: List[OnboardScanConnectionSpec] = Field(default_factory=list)
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "connections": [
                    {
                        "connection_id": "conn_prod",
                        "db_type": "postgres",
                        "host": "db.company.com",
                        "port": 5432,
                        "user": "readonly_user",
                        "password": "******",
                        "sample_rows": 100,
                        "databases": [
                            {"name": "prod_warehouse", "schemas": [{"name": "public"}]}
                        ],
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
    tenant_id: str | None = Field(None, examples=["tenant_a"])
    time_column: str | None = Field(None, examples=["production_date"])
    grain: str | None = Field(None, examples=["day"])
    use_llm: bool = Field(True, examples=[True])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "grain": "day",
                "use_llm": True,
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


class JobStatusEnum(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"


class JobCreateRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    job_type: str = Field(..., examples=["scan_connection"])
    payload: dict = Field(..., examples=[{"connections": []}])
    idempotency_key: str | None = Field(None, examples=["client-key-123"])


class JobCreateResponse(BaseModel):
    job_id: str = Field(..., examples=["job_123"])
    status: JobStatusEnum = Field(..., examples=["queued"])


class JobStatusResponse(BaseModel):
    job_id: str
    job_type: str
    status: JobStatusEnum
    progress_pct: float | None = None
    progress_stage: str | None = None
    error_message: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class JobResultResponse(BaseModel):
    job_id: str
    status: JobStatusEnum
    result: dict | None = None
    error_message: str | None = None


class JobListItem(BaseModel):
    job_id: str
    job_type: str
    status: JobStatusEnum
    created_at: str | None = None
    updated_at: str | None = None


class JobListResponse(BaseModel):
    jobs: List[JobListItem]
    limit: int
    cursor: str | None = None
    next_cursor: str | None = None


class JobCancelResponse(BaseModel):
    job_id: str
    status: JobStatusEnum


class PackApplyRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    industry: str = Field(..., examples=["petroleum_refinery"])
    version: str = Field(..., examples=["1.0.0"])


class PackApplyResponse(BaseModel):
    ok: bool = True
    contract_id: str | None = None


class PackListResponse(BaseModel):
    packs: List[dict] = Field(
        examples=[[{"industry": "manufacturing", "version": "1.0.0", "release_date": "2025-02-14"}]]
    )


class SemanticContractResponse(BaseModel):
    contract_id: str
    tenant_id: str
    industry: str
    version: str
    payload: dict
    hash: str
    status: str
    created_at: str | None = None


class SemanticContractListResponse(BaseModel):
    contracts: List[dict]


class SemanticContractValidateResponse(BaseModel):
    ok: bool = True
    errors: List[dict] = Field(default_factory=list)


class SemanticExtractRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    industry: str = Field(..., examples=["petroleum_refinery"])
    inputs: dict = Field(..., examples=[{"raw_text": "MFM = mass flow meter", "tables": ["fact_dispatch"]}])
    model: str | None = Field(None, examples=["gpt-4o-mini"])


class SemanticExtractResponse(BaseModel):
    contract_id: str
    status: str


class SemanticApplyRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    contract_id: str = Field(..., examples=["contract_123"])


class SemanticApplyResponse(BaseModel):
    ok: bool = True


class SemanticSuggestInputs(BaseModel):
    schema_summary: str | None = Field(None, examples=["fact_dispatch: [dispatch_date, plant_id, product_id, volume_tmt]"])
    questions: List[str] = Field(default_factory=list, examples=[["Top 5 plants by dispatch volume this month"]])
    glossary: str | None = Field(None, examples=["MFM=Mass Flow Meter, bay=loading bay"])
    tables: List[dict] | None = Field(
        None,
        examples=[[{"table": "fact_dispatch", "columns": [{"name": "dispatch_date", "data_type": "date"}]}]],
    )


class SemanticSuggestRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["petroleum_refinery"])
    inputs: SemanticSuggestInputs
    model: str | None = Field(None, examples=["gpt-4o-mini"])


class SemanticSuggestResponse(BaseModel):
    facts: List[dict] = Field(default_factory=list)
    dimensions: List[dict] = Field(default_factory=list)
    metrics: List[dict] = Field(default_factory=list)
    lineage: dict = Field(default_factory=dict)
    question_types: List[str] = Field(default_factory=list)


class SemanticSuggestApplyRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["petroleum_refinery"])
    canvas_id: str | None = Field(None, examples=["canvas_123"])
    facts: List[dict] = Field(default_factory=list)
    dimensions: List[dict] = Field(default_factory=list)
    metrics: List[dict] = Field(default_factory=list)
    lineage: dict = Field(default_factory=dict)
    idempotency_key: str | None = Field(None, examples=["semantic-apply-001"])


class SemanticSuggestApplyResponse(BaseModel):
    ok: bool = True
    canvas_id: str | None = None
    facts: int = 0
    dimensions: int = 0
    metrics: int = 0


class TenantScopeUpsertRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str = Field(..., examples=["manufacturing"])
    connection_id: str = Field(..., examples=["conn_prod"])
    database: str = Field(..., examples=["prod_warehouse"])
    schema_name: str = Field(..., alias="schema", examples=["public"])
    tables: List[str] | None = Field(None, examples=[["fact_sales", "dim_customer"]])
    model_config = {"populate_by_name": True}


class TenantScopeResponse(BaseModel):
    tenant_id: str
    domain_id: str
    connection_id: str
    database: str
    schema_name: str = Field(..., alias="schema")
    tables: List[str] | None = None
    status: str
    model_config = {"populate_by_name": True}


class MetricUpsertRequest(BaseModel):
    tenant_id: str | None = Field(None, examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["energy_distribution"])
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
                "tenant_id": "tenant_a",
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
    tenant_id: str | None = Field(None, examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["energy_distribution"])
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


class DbtManifestGenerateRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    dbt_project_path: str | None = Field(None, examples=["dbt"])
    profile_name: str = Field(..., examples=["default"])
    target_name: str = Field(..., examples=["dev"])
    profiles_dir: str | None = Field(None, examples=["~/.dbt"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "dbt_project_path": "dbt",
                "profile_name": "default",
                "target_name": "dev",
                "profiles_dir": "~/.dbt",
            }
        }
    }


class DbtManifestGenerateResponse(BaseModel):
    manifest_id: str = Field(..., examples=["manifest_123"])
    status: str = Field(..., examples=["stored"])
    tenant_id: str = Field(..., examples=["tenant_a"])
    dbt_project_path: str = Field(..., examples=["dbt_projects/dbt_tenant_a"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "manifest_id": "manifest_123",
                "status": "stored",
                "tenant_id": "tenant_a",
                "dbt_project_path": "dbt_projects/dbt_tenant_a",
            }
        }
    }


class DbtConfigUpsertRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    dbt_project_path: str | None = Field(None, examples=["dbt_projects/dbt_tenant_a"])
    target_name: str | None = Field(None, examples=["dev"])
    profiles_dir: str | None = Field(None, examples=["~/.dbt"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "dbt_project_path": "dbt_projects/dbt_tenant_a",
                "target_name": "dev",
                "profiles_dir": "~/.dbt",
            }
        }
    }


class DbtConfigResponse(BaseModel):
    config_id: str | None = Field(None, examples=["dbt_cfg_123"])
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str = Field(..., examples=["manufacturing"])
    dbt_project_path: str = Field(..., examples=["dbt_projects/dbt_tenant_a"])
    profile_name: str = Field(..., examples=["tenant_a"])
    target_name: str = Field(..., examples=["dev"])
    profiles_dir: str | None = Field(None, examples=["~/.dbt"])
    created_at: str | None = Field(None, examples=["2025-02-14T10:00:00Z"])
    updated_at: str | None = Field(None, examples=["2025-02-14T10:00:00Z"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "config_id": "dbt_cfg_123",
                "tenant_id": "tenant_a",
                "domain_id": "manufacturing",
                "dbt_project_path": "dbt_projects/dbt_tenant_a",
                "profile_name": "default",
                "target_name": "dev",
                "profiles_dir": "~/.dbt",
                "created_at": "2025-02-14T10:00:00Z",
                "updated_at": "2025-02-14T10:00:00Z",
            }
        }
    }


class DbtScaffoldRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["manufacturing"])
    context_id: str | None = Field(None, examples=["ctx_123"])
    model: str | None = Field(None, examples=["gpt-4o-mini"])
    host: str | None = Field(None, examples=["db.company.com"])
    port: int | None = Field(None, examples=[5432])
    user: str | None = Field(None, examples=["readonly_user"])
    password: str | None = Field(None, examples=["******"])
    model_config = {
        "json_schema_extra": {
            "example": {
                "tenant_id": "tenant_a",
                "context_id": "ctx_123",
                "host": "db.company.com",
                "port": 5432,
                "user": "readonly_user",
                "password": "******",
            }
        }
    }


class DbtScaffoldResponse(BaseModel):
    status: str = Field(..., examples=["generated"])
    scaffold_id: str = Field(..., examples=["scaffold_123"])
    models: List[dict] = Field(
        examples=[
            [
                {"name": "fact_sales", "path": "models/auto/fact_sales.sql", "status": "live"},
                {"name": "dim_customer", "path": "models/auto/dim_customer.sql", "status": "live"},
            ]
        ]
    )
    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "generated",
                "scaffold_id": "scaffold_123",
                "models": [
                    {"name": "fact_sales", "path": "models/auto/fact_sales.sql", "status": "live"},
                    {"name": "dim_customer", "path": "models/auto/dim_customer.sql", "status": "live"},
                ],
            }
        }
    }


class DbtScaffoldListResponse(BaseModel):
    scaffolds: List[dict]
    model_config = {
        "json_schema_extra": {
            "example": {
                "scaffolds": [
                    {
                        "scaffold_id": "scaffold_123",
                        "tables": ["fact_sales", "dim_customer"],
                        "status": "live",
                        "created_at": "2025-02-14T10:00:00Z",
                    }
                ]
            }
        }
    }


class DbtScaffoldPatchRequest(BaseModel):
    status: str | None = Field(None, examples=["reviewed"])
    notes: str | None = Field(None, examples=["Reviewed by analyst"])
    payload: dict | None = Field(None, examples=[{"schema_yaml": "version: 2"}])
    model_config = {"json_schema_extra": {"example": {"status": "reviewed", "notes": "Looks good"}}}




class CanvasNodePayload(BaseModel):
    type: str = Field(..., examples=["dimension"])
    payload: dict = Field(default_factory=dict)


class CanvasEdgePayload(BaseModel):
    from_id: str = Field(..., examples=["dim_plant"])
    to_id: str = Field(..., examples=["fact_production_daily"])
    edge_type: str = Field(..., examples=["dimension_to_fact"])
    source: str | None = Field("manual", examples=["manual"])
    confidence: float | None = Field(None, examples=[0.9])


class CanvasSaveRequest(BaseModel):
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str | None = Field(None, examples=["petroleum_refinery"])
    name: str = Field(..., examples=["Default Semantic Canvas"])
    description: str | None = Field(None, examples=["Main tenant canvas"])
    nodes: List[CanvasNodePayload] = Field(default_factory=list)
    edges: List[CanvasEdgePayload] = Field(default_factory=list)
    root_node_id: str | None = Field(None, examples=["tenant_root"])
    status: str | None = Field("live", examples=["reviewed"])
    idempotency_key: str | None = Field(None, examples=["canvas-001"])


class CanvasSaveResponse(BaseModel):
    canvas_id: str = Field(..., examples=["canvas_123"])
    status: str = Field(..., examples=["saved"])


class CanvasListResponse(BaseModel):
    canvases: List[dict]


class CanvasDetailResponse(BaseModel):
    canvas_id: str
    tenant_id: str
    domain_id: str
    name: str
    description: str | None = None
    graph_json: dict
    root_node_id: str | None = None
    status: str
    created_at: str | None = None
    updated_at: str | None = None


class CanvasTreeResponse(BaseModel):
    nodes: List[dict]
    edges: List[dict]


class DbtManifestLatestResponse(BaseModel):
    manifest_id: str = Field(..., examples=["manifest_123"])
    tenant_id: str = Field(..., examples=["tenant_a"])
    domain_id: str = Field(..., examples=["manufacturing"])
    dbt_project_path: str = Field(..., examples=["dbt"])
    profile_name: str = Field(..., examples=["default"])
    target_name: str = Field(..., examples=["dev"])
    created_at: str = Field(..., examples=["2025-02-14T10:00:00Z"])
    manifest_json: dict
    model_config = {
        "json_schema_extra": {
            "example": {
                "manifest_id": "manifest_123",
                "tenant_id": "tenant_a",
                "domain_id": "manufacturing",
                "dbt_project_path": "dbt",
                "profile_name": "default",
                "target_name": "dev",
                "created_at": "2025-02-14T10:00:00Z",
                "manifest_json": {"metadata": {"dbt_version": "1.7.0"}},
            }
        }
    }
