from services.ai import semantic_extraction


def test_build_prompt_preserves_literal_json_braces() -> None:
    instructions = """Return JSON only:
{
  "terms": [
    {
      "term": "string"
    }
  ]
}
"""
    rendered = semantic_extraction._build_prompt(
        instructions,
        [("Input", "production means output")],
    )

    assert '"terms"' in rendered
    assert "Input:\nproduction means output" in rendered
    assert "production means output" in rendered


def test_extract_semantic_contract_handles_glossary_prompt_with_json_schema(monkeypatch) -> None:
    def fake_call_llm(settings, system_prompt: str, user_prompt: str) -> dict:
        assert '"terms"' in user_prompt
        assert "Use process_date as the canonical operational date." in user_prompt
        return {"terms": [{"term": "process date", "definition": "Operational date"}]}

    monkeypatch.setattr(semantic_extraction, "_call_llm", fake_call_llm)

    contract = semantic_extraction.extract_semantic_contract(
        settings=type("SettingsStub", (), {"openai_api_key": "test", "openai_model": "test-model"})(),
        raw_text="Use process_date as the canonical operational date.",
    )

    assert contract["business_terms"] == [{"term": "process date", "definition": "Operational date"}]
    assert contract["entity_mappings"] == []
    assert contract["metric_definitions"] == []
