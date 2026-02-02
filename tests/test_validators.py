import unittest

from services.api.validators import (
    extract_scope_from_metadata,
    generate_source_title,
    scopes_match,
    validate_scope_fields,
)


class TestValidators(unittest.TestCase):
    def test_validate_scope_fields_missing(self) -> None:
        missing = validate_scope_fields({})
        self.assertIn("connection_id", missing)
        self.assertIn("database", missing)
        self.assertIn("schema", missing)
        self.assertIn("tables", missing)

    def test_validate_scope_fields_tables_empty(self) -> None:
        missing = validate_scope_fields(
            {"connection_id": "conn", "database": "db", "schema": "public", "tables": []}
        )
        self.assertIn("tables", missing)

    def test_generate_source_title_from_text(self) -> None:
        title = generate_source_title(
            "SBU = Strategic Business Unit for sales operations and reporting", {}
        )
        self.assertTrue(title)
        self.assertLessEqual(len(title), 80)

    def test_scopes_match(self) -> None:
        existing = {
            "connection_id": "conn",
            "database": "db",
            "schema": "public",
            "tables": ["fact_sales"],
        }
        updated = {
            "connection_id": "conn",
            "database": "db",
            "schema": "public",
            "tables": ["fact_sales"],
        }
        self.assertTrue(scopes_match(existing, updated))
        self.assertEqual(extract_scope_from_metadata(existing), extract_scope_from_metadata(updated))


if __name__ == "__main__":
    unittest.main()
