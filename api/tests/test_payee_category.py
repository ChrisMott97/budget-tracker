"""Payee-based categorisation: the fallback when a bank ships no category column.

`infer_payee_categories` is given a stub client, so nothing leaves the machine.
The per-payee cache is cleared around every test so ordering cannot leak.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import budget_buddy.main as api
from budget_buddy.main import (
    CATEGORY_PRESETS,
    infer_payee_categories,
    resolve_payee_categories,
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
    api._PAYEE_CATEGORY_CACHE.clear()
    yield
    api._PAYEE_CATEGORY_CACHE.clear()


def test_infer_payee_categories_maps_payees_to_presets():
    client = StubModel(link_map(("TESCO", "Groceries"), ("TFL", "Transport")))

    result = infer_payee_categories(["TESCO", "TFL"], client)

    assert result == {"TESCO": "Groceries", "TFL": "Transport"}


def test_infer_payee_categories_drops_a_target_outside_the_preset_list():
    """A hallucinated preset is a mislabel, not a row corruption, so it degrades to null."""
    client = StubModel(link_map(("TESCO", "Supermarket")))

    assert infer_payee_categories(["TESCO"], client) == {"TESCO": None}


def test_infer_payee_categories_passes_a_null_target_through():
    client = StubModel(link_map(("SOME LTD", None)))

    assert infer_payee_categories(["SOME LTD"], client) == {"SOME LTD": None}


def test_infer_payee_categories_raises_502_on_empty_output():
    with pytest.raises(HTTPException) as raised:
        infer_payee_categories(["TESCO"], StubModel(""))

    assert raised.value.status_code == 502


def test_infer_payee_categories_prompt_carries_only_payees_and_presets():
    client = StubModel(link_map(("TESCO", "Groceries")))

    infer_payee_categories(["TESCO", "GREGGS"], client)
    prompt = client.inputs[0]

    assert "TESCO" in prompt and "GREGGS" in prompt
    for preset in CATEGORY_PRESETS:
        assert preset in prompt


def test_resolve_payee_categories_caches_each_payee_so_a_reimport_makes_no_call():
    client = StubModel(link_map(("TESCO", "Groceries")))

    resolve_payee_categories({"TESCO"}, client)
    resolve_payee_categories({"TESCO"}, client)

    assert len(client.inputs) == 1


def test_resolve_payee_categories_only_queries_payees_not_already_cached():
    """The cross-user warmth guarantee: a merchant seen before is not re-sent."""
    api._PAYEE_CATEGORY_CACHE[("TESCO", api.CATEGORY_LIST_VERSION)] = "Groceries"
    client = StubModel(link_map(("GREGGS", "Eating out")))

    result = resolve_payee_categories({"TESCO", "GREGGS"}, client)

    assert result == {"TESCO": "Groceries", "GREGGS": "Eating out"}
    assert "GREGGS" in client.inputs[0] and "TESCO" not in client.inputs[0]


def test_resolve_payee_categories_caches_a_payee_the_model_omitted_as_none():
    """An omitted payee is cached as None, so the next import does not re-query it."""
    client = StubModel(link_map(("TESCO", "Groceries")))

    resolve_payee_categories({"TESCO", "MYSTERY"}, client)
    resolve_payee_categories({"MYSTERY"}, client)

    assert len(client.inputs) == 1


def test_resolve_payee_categories_recomputes_when_the_list_version_changes(monkeypatch):
    client = StubModel(link_map(("TESCO", "Groceries")))

    resolve_payee_categories({"TESCO"}, client)
    monkeypatch.setattr(api, "CATEGORY_LIST_VERSION", "2")
    resolve_payee_categories({"TESCO"}, client)

    assert len(client.inputs) == 2
