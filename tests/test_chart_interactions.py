import unittest

from services.ai.chart_interactions import _inject_where_into_sql, compile_chart_query


class ChartInteractionFilterTests(unittest.TestCase):
    def test_filter_injection_resolves_select_alias_to_physical_column(self) -> None:
        sql = (
            'SELECT t."plant_name" AS category, SUM(t."qty") AS value '
            'FROM "public"."fact_lpg_plant_operations" t '
            'GROUP BY t."plant_name" ORDER BY value DESC LIMIT 10'
        )

        filtered_sql, params = _inject_where_into_sql(
            sql,
            [{"field": "category", "operator": "=", "value": "A"}],
        )

        self.assertIn('t."plant_name" = %s', filtered_sql)
        self.assertNotIn('t."category" = %s', filtered_sql)
        self.assertEqual(params, ["A"])

    def test_compile_chart_query_resolves_context_filter_alias_to_physical_column(self) -> None:
        sql = (
            'SELECT t."plant_name" AS category, SUM(t."qty") AS value '
            'FROM "public"."fact_lpg_plant_operations" t '
            'GROUP BY t."plant_name" ORDER BY value DESC LIMIT 10'
        )
        chart_row = {"sql": sql}
        interaction_context = {
            "source_scope": {"schema_name": "public", "base_table": "fact_lpg_plant_operations"},
            "query_shape": {
                "metric_expressions": [{"metric_id": "value", "expression": 'SUM(t."qty")'}],
                "group_dimensions": ["plant_name"],
            },
            "filters": [{"field": "category", "operator": "=", "value": "A"}],
        }

        compiled_sql, params, _, _ = compile_chart_query(
            chart_row=chart_row,
            interaction_context=interaction_context,
        )

        self.assertIn('t."plant_name" = %s', compiled_sql)
        self.assertNotIn('t."category" = %s', compiled_sql)
        self.assertEqual(params, ["A"])


if __name__ == "__main__":
    unittest.main()
