"""Set-to-set category mapping: a bank's own labels onto the preset list.

`infer_category_map` is given a stub client, so nothing leaves the machine. The
cache is cleared around every test so ordering between tests cannot leak.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import budget_buddy.main as api
from budget_buddy.main import (
    CATEGORY_PRESETS,
    infer_category_map,
    resolve_category_map,
)


class StubModel:
    """Stands in for genai.Client: returns one canned output, records every input."""

    def __init__(self, output: dict | str):
        self._output = output if isinstance(output, str) else json.dumps(output)
        self.inputs: list[str] = []
        self.interactions = self

    def create(self, *, model: str, input: str, response_format: dict):
        self.inputs.append(input)
        return SimpleNamespace(output_text=self._output)


def link_map(*pairs: tuple[str, str | None]) -> dict:
    return {"links": [{"source": source, "target": target} for source, target in pairs]}


@pytest.fixture(autouse=True)
def _clear_cache():
    api._CATEGORY_MAP_CACHE.clear()
    yield
    api._CATEGORY_MAP_CACHE.clear()


def test_infer_category_map_maps_bank_labels_to_presets():
    client = StubModel(link_map(("GROCERIES", "Groceries"), ("INCOME", "Income")))

    result = infer_category_map(["GROCERIES", "INCOME"], client)

    assert result == {"GROCERIES": "Groceries", "INCOME": "Income"}


def test_infer_category_map_drops_a_target_outside_the_preset_list():
    """A hallucinated preset is a mislabel, not a row corruption, so it degrades to null."""
    client = StubModel(link_map(("GENERAL", "Miscellaneous")))

    assert infer_category_map(["GENERAL"], client) == {"GENERAL": None}


def test_infer_category_map_passes_a_null_target_through():
    client = StubModel(link_map(("PAYMENTS", None)))

    assert infer_category_map(["PAYMENTS"], client) == {"PAYMENTS": None}


def test_infer_category_map_raises_502_on_empty_output():
    with pytest.raises(HTTPException) as raised:
        infer_category_map(["GROCERIES"], StubModel(""))

    assert raised.value.status_code == 502


def test_infer_category_map_prompt_carries_only_labels_and_presets():
    client = StubModel(link_map(("EATING OUT", "Eating out")))

    infer_category_map(["EATING OUT", "GROCERIES"], client)
    prompt = client.inputs[0]

    assert "EATING OUT" in prompt and "GROCERIES" in prompt
    for preset in CATEGORY_PRESETS:
        assert preset in prompt


def test_resolve_category_map_caches_so_a_reimport_makes_no_second_call():
    client = StubModel(link_map(("GROCERIES", "Groceries")))

    resolve_category_map({"GROCERIES"}, client)
    resolve_category_map({"GROCERIES"}, client)

    assert len(client.inputs) == 1


def test_resolve_category_map_cache_key_ignores_category_order():
    client = StubModel(link_map(("A", None), ("B", None)))

    resolve_category_map({"A", "B"}, client)
    resolve_category_map({"B", "A"}, client)

    assert len(client.inputs) == 1


def test_resolve_category_map_recomputes_when_the_list_version_changes(monkeypatch):
    client = StubModel(link_map(("GROCERIES", "Groceries")))

    resolve_category_map({"GROCERIES"}, client)
    monkeypatch.setattr(api, "CATEGORY_LIST_VERSION", "2")
    resolve_category_map({"GROCERIES"}, client)

    assert len(client.inputs) == 2
