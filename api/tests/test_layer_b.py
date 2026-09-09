"""Layer B: slot inference and application.

The pure functions run with no network; `infer_slot_map` is given a stub client
so nothing leaves the machine.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from budget_buddy.main import (
    FieldMap,
    FieldSource,
    SlotAssignment,
    Transaction,
    apply_payee_slots,
    embedded_facts_in,
    infer_slot_map,
)


class StubModel:
    """Stands in for genai.Client: returns one canned JSON output, records inputs."""

    def __init__(self, output: dict):
        self._output = json.dumps(output)
        self.inputs: list[str] = []
        self.interactions = self

    def create(self, *, model: str, input: str, response_format: dict):
        self.inputs.append(input)
        return SimpleNamespace(output_text=self._output)


def txn(description: str) -> Transaction:
    return Transaction(date="2026-08-27", description=description, amount=-1.0)


def test_embedded_facts_in_lists_only_facts_embedded_in_that_column():
    fields = FieldMap(
        payee=FieldSource(column="Description", purity="embedded"),
        reference=FieldSource(column="Description", purity="embedded"),
        date=FieldSource(column="Date", purity="exact"),
        txn_type=FieldSource(column="Type", purity="embedded"),
    )

    assert embedded_facts_in(fields, "Description") == ["payee", "reference"]


def test_apply_payee_slots_narrows_description_to_the_payee_slot():
    descriptions = [
        "CR BRIGHTFORD LTD SALARY",
        "DD VODAFONE LTD",
        "VIS BOKKA CAFE LISBOA",
    ]
    rows = [txn(d) for d in descriptions]

    apply_payee_slots(rows, descriptions, {"PFX W+": SlotAssignment(payee=1)})

    assert [row.description for row in rows] == [
        "BRIGHTFORD LTD SALARY",
        "VODAFONE LTD",
        "BOKKA CAFE LISBOA",
    ]


def test_apply_payee_slots_leaves_a_bucket_with_no_payee_assignment_untouched():
    descriptions = [
        "CR BRIGHTFORD LTD SALARY",
        "DD VODAFONE LTD",
        "VIS BOKKA CAFE LISBOA",
    ]
    rows = [txn(d) for d in descriptions]

    apply_payee_slots(rows, descriptions, {"PFX W+": SlotAssignment(payee=None)})

    assert [row.description for row in rows] == descriptions


def test_infer_slot_map_rejects_a_length_mismatch():
    """One assignment for two shapes means the whole answer is untrustworthy."""
    client = StubModel({"assignments": [{"payee": 1}]})
    descriptions = [
        "CR BRIGHTFORD LTD SALARY",
        "DD VODAFONE LTD",
        "VIS BOKKA CAFE LISBOA",
        "7712 26AUG26 C , WAITROSE 742 , LONDON GB",
    ]

    with pytest.raises(HTTPException) as raised:
        infer_slot_map(descriptions, ["payee"], client)

    assert raised.value.status_code == 502


def test_infer_slot_map_nulls_an_out_of_range_index():
    """`PFX W+` has two slots; slot 5 does not exist, so it is dropped to null."""
    client = StubModel({"assignments": [{"payee": 5}]})
    descriptions = [
        "CR BRIGHTFORD LTD SALARY",
        "DD VODAFONE LTD",
        "VIS BOKKA CAFE LISBOA",
    ]

    slot_map = infer_slot_map(descriptions, ["payee"], client)

    assert slot_map["PFX W+"].payee is None


def test_infer_slot_map_prompt_carries_shapes_and_masked_samples_only():
    client = StubModel({"assignments": [{"payee": 1}]})
    descriptions = [
        "CR BRIGHTFORD LTD SALARY",
        "DD VODAFONE LTD",
        "VIS BOKKA CAFE LISBOA",
    ]

    infer_slot_map(descriptions, ["payee"], client)
    prompt = client.inputs[0]

    assert "PFX W+" in prompt
    assert '"X X X X"' in prompt  # CR BRIGHTFORD LTD SALARY, every word masked
    for token in ["BRIGHTFORD", "VODAFONE", "BOKKA", "LISBOA", "SALARY"]:
        assert token not in prompt
