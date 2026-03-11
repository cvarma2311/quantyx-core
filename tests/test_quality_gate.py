from services.ai.quality_gate import evaluate_quality_report, has_blocked_metric_pattern


def test_has_blocked_metric_pattern_detects_sum_id_and_code() -> None:
    assert has_blocked_metric_pattern("sum_distributor_code")
    assert has_blocked_metric_pattern("sum_event_id")
    assert not has_blocked_metric_pattern("utilization_pct")


def test_evaluate_quality_report_passes_for_kpi_mix() -> None:
    state = {
        "metric_defs": [
            {"metric_name": "production_mt", "metric_source": "template", "eligible_measure": True},
            {"metric_name": "rejection_rate_pct", "metric_source": "template", "eligible_measure": True},
        ],
        "chart_plan": [
            {"intent": "trend", "metric_intent": "volume"},
            {"intent": "breakdown", "metric_intent": "volume"},
            {"intent": "trend", "metric_intent": "quality"},
        ],
        "join_edges": [{"confidence": 0.9}],
        "ontology": {"hierarchy_edges": [{"confidence": 0.8}]},
        "chart_candidate_rejections": [],
    }
    report = evaluate_quality_report(state)
    assert report["gate_passed"] is True
    assert report["kpi_mix"]["trend"] >= 1
    assert report["kpi_mix"]["breakdown_or_share"] >= 1
    assert report["kpi_mix"]["quality_or_rate"] >= 1
    assert "blocked_metric_name_pattern" not in report["warnings"]


def test_evaluate_quality_report_blocks_code_sum_pattern() -> None:
    state = {
        "metric_defs": [
            {"metric_name": "sum_payment_error_code", "metric_source": "fallback", "eligible_measure": False},
        ],
        "chart_plan": [
            {"intent": "trend", "metric_intent": "volume"},
            {"intent": "breakdown", "metric_intent": "volume"},
            {"intent": "trend", "metric_intent": "quality"},
        ],
        "join_edges": [],
        "ontology": {"hierarchy_edges": []},
        "chart_candidate_rejections": [],
    }
    report = evaluate_quality_report(state)
    assert report["gate_passed"] is False
    assert "blocked_metric_name_pattern" in report["warnings"]
    assert any(item.startswith("metric:sum_payment_error_code") for item in report["blocked_patterns"])

