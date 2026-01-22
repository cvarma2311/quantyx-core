from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class QueryFilter(BaseModel):
    field: str = Field(..., description="Dimension name (e.g., product_name)")
    operator: str = Field(..., description="One of =, !=, >, >=, <, <=, IN, ILIKE")
    value: Any = Field(..., description="Filter value or list of values for IN")


class QueryRequest(BaseModel):
    question: Optional[str] = Field(None, description="Natural language question")
    metric: Optional[str] = Field(None, description="Metric name to query directly")
    metrics: Optional[List[str]] = Field(None, description="Metric names to query")
    dimensions: List[str] = Field(default_factory=list, description="Dimensions to group by")
    filters: List[QueryFilter] = Field(default_factory=list, description="Filters to apply")
    limit: int = Field(200, ge=1, le=1000, description="Row limit")
    explain: bool = Field(False, description="Return SQL and resolution info")


class QueryResult(BaseModel):
    metrics: List[str]
    dimensions: List[str]
    sql: Optional[str]
    rows: List[dict]
    by_company_sql: Optional[str] = None
    by_company_rows: Optional[List[dict]] = None


class MetricsResponse(BaseModel):
    metrics: List[dict]


class SchemaResponse(BaseModel):
    models: List[dict]
