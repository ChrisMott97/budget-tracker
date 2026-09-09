"""Endpoint tests. The Gemini client is replaced with a fake so nothing leaves the machine."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import budget_buddy.main as api


class FakeClient:
    """Stands in for genai.Client. Each create() call pops the next canned JSON output."""

    def __init__(self, outputs: list[dict]):
        self.calls: list[str] = []
        self._outputs = [json.dumps(o) for o in outputs]
        self.interactions = self

    def create(self, *, model: str, input: str, response_format: dict):
        self.calls.append(input)
        return SimpleNamespace(output_text=self._outputs.pop(0))


def exact(column: str) -> dict:
    return {"column": column, "purity": "exact"}


# An `exact` payee keeps these tests to a single model call; the embedded-payee
# path that triggers layer B has its own tests below with their own canned answers.
MAPPING = {
    "fields": {
        "date": exact("Date"),
        "amount": exact("Amount"),
        "payee": exact("Description"),
    }
}


# The trailing `{"links": []}` answers the payee-categorisation pass, which every
# completed request now makes because `MAPPING` carries no bank category column.
@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient([MAPPING, {"links": []}])
    monkeypatch.setattr(api, "get_client", lambda: client)
    return client


@pytest.fixture(autouse=True)
def _clear_caches():
    api._CATEGORY_MAP_CACHE.clear()
    api._PAYEE_CATEGORY_CACHE.clear()
    yield
    api._CATEGORY_MAP_CACHE.clear()
    api._PAYEE_CATEGORY_CACHE.clear()


def post_csv(csv_text: str):
    with TestClient(api.app) as http:
        return http.post(
            "/transactions", files={"file": ("bank.csv", csv_text, "text/csv")}
        )


def test_transactions_endpoint_returns_parsed_rows(fake_client):
    csv_text = "Date,Description,Amount\n" + "\n".join(
        f'2025-03-{day:02d},"{desc}",-1.00'
        for day, desc in enumerate(
            [
                "TESCO STORES 1234",
                "AMAZON.CO.UK, 12MAR25",
                "MARKS & SPENCER",
                "DD 987654 REF A1B2",
                "PAYPAL *STEAM 12/03/25",
                "TFL TRAVEL CH, 12MAR25, GB",
            ],
            start=1,
        )
    )

    response = post_csv(csv_text)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 6
    assert body[0] == {
        "date": "2025-03-01",
        "description": "TESCO STORES 1234",
        "amount": -1.0,
        "balance": None,
        "category": None,
        "reference": None,
        "txn_type": None,
        "currency": None,
    }


def test_column_mapping_prompt_sends_profile_stats_not_raw_rows(fake_client):
    """The prompt carries the anonymised profile, never a transaction row."""
    rows = [
        ("2025-03-01", "TESCO STORES 4021 LONDON", "-14.30"),
        ("2025-03-02", "KOFFEEWERK ROASTERY BERLIN", "-3.80"),
        ("2025-03-03", "ALEX HOLLOWAY RENT JULY", "-780.00"),
    ]
    csv_text = "Date,Description,Amount\n" + "\n".join(",".join(row) for row in rows)

    post_csv(csv_text)
    prompt = fake_client.calls[0]

    assert "cardinality_ratio" in prompt
    assert "case_profile" in prompt
    for date, description, amount in rows:
        assert f"{date},{description},{amount}" not in prompt


def test_column_mapping_prompt_decorrelates_sampled_values(fake_client):
    """Sample values are sorted per column, so no aligned pair is a real row's pair."""
    csv_text = "Date,Description,Amount,Reference\n" + "\n".join(
        f"2025-03-0{n},PAYEE{n},-{n}.00,REF{9 - n}" for n in range(1, 5)
    )

    post_csv(csv_text)
    prompt = fake_client.calls[0]

    for n in range(1, 5):
        assert f"2025-03-0{n},PAYEE{n},-{n}.00,REF{9 - n}" not in prompt

    profile = json.loads(prompt[prompt.index("{") :])
    samples = {column["label"]: column["samples"] for column in profile["columns"]}
    for payee, reference in zip(samples["Description"], samples["Reference"]):
        n = int(payee.removeprefix("PAYEE"))
        assert reference != f"REF{9 - n}"


def test_transactions_endpoint_handles_fewer_than_six_shapes(fake_client):
    csv_text = "Date,Description,Amount\n2025-03-12,TESCO STORES,-12.50\n"

    response = post_csv(csv_text)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_transactions_endpoint_parses_a_headerless_csv(monkeypatch):
    """A headerless file used to lose its first row silently; all rows must survive.

    The canned answer says nothing about the header row -- `detect_dialect` supplies
    that -- so this also covers the model addressing columns by index.
    """
    client = FakeClient(
        [
            {
                "date_format": "%d/%m/%Y",
                "fields": {
                    "date": exact("0"),
                    "amount": exact("2"),
                    "payee": {"column": "1", "purity": "embedded"},
                },
            },
            # payee is embedded, so layer B runs; a null slot leaves the
            # descriptor whole, which is what this test asserts on.
            {"assignments": [{"payee": None}]},
            # the payee-categorisation pass; no category is asserted here.
            {"links": []},
        ]
    )
    monkeypatch.setattr(api, "get_client", lambda: client)
    csv_text = (
        '30/07/2026,"CR BRIGHTFORD LTD SALARY          ",3980.44\n'
        '30/07/2026,"DD VODAFONE LTD                   ",-24.50\n'
    )

    response = post_csv(csv_text)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0] == {
        "date": "2026-07-30",
        "description": "CR BRIGHTFORD LTD SALARY",
        "amount": 3980.44,
        "balance": None,
        "category": None,
        "reference": None,
        "txn_type": None,
        "currency": None,
    }


def test_transactions_endpoint_rejects_a_field_map_missing_a_required_fact(monkeypatch):
    """A model answer that names no amount column is a validation failure, not a crash."""
    client = FakeClient([{"fields": {"date": exact("Date"), "payee": exact("Desc")}}])
    monkeypatch.setattr(api, "get_client", lambda: client)

    response = post_csv("Date,Desc,Amount\n2025-03-12,TESCO,-12.50\n")

    assert response.status_code == 422
    assert "amount" in response.json()["detail"]


def test_exact_payee_skips_layer_b(fake_client):
    """An `exact` payee needs no slot inference: layer A, then the payee pass, no layer B."""
    post_csv("Date,Description,Amount\n2025-03-12,TESCO STORES,-12.50\n")

    assert len(fake_client.calls) == 2


def test_exact_category_is_remapped_to_a_preset(monkeypatch):
    """A bank category column is mapped set-to-set; a null target leaves the row None."""
    layer_a = {
        "fields": {
            "date": exact("Date"),
            "amount": exact("Amount"),
            "payee": exact("Name"),
            "category": exact("Category"),
        }
    }
    category_map = {
        "links": [
            {"source": "Groceries", "target": "Groceries"},
            {"source": "Transfers", "target": None},
        ]
    }
    # Alice's bank label maps to null, so her row reaches the payee pass, which
    # also finds nothing -- she stays uncategorised.
    client = FakeClient([layer_a, category_map, {"links": []}])
    monkeypatch.setattr(api, "get_client", lambda: client)

    csv_text = (
        "Date,Name,Amount,Category\n"
        "2026-08-01,Tesco,-12.50,Groceries\n"
        "2026-08-02,Alice,-5.00,Transfers\n"
    )

    body = post_csv(csv_text).json()

    assert len(client.calls) == 3
    assert [(row["description"], row["category"]) for row in body] == [
        ("Tesco", "Groceries"),
        ("Alice", None),
    ]


def test_embedded_payee_endpoint_narrows_descriptions_to_the_payee_slot(monkeypatch):
    """The whole point of layer B: an embedded descriptor comes back as the payee."""
    layer_a = {
        "fields": {
            "date": exact("Date"),
            "amount": exact("Amount"),
            "payee": {"column": "Description", "purity": "embedded"},
        }
    }
    # The three rows share the refined shape `PFX W+` (scheme prefix, then payee),
    # so layer B answers with one assignment: the payee is slot 1.
    client = FakeClient([layer_a, {"assignments": [{"payee": 1}]}, {"links": []}])
    monkeypatch.setattr(api, "get_client", lambda: client)

    csv_text = (
        "Date,Description,Amount\n"
        "2026-08-01,CR BRIGHTFORD LTD SALARY,3980.44\n"
        "2026-08-02,DD VODAFONE LTD,-24.50\n"
        "2026-08-03,VIS BOKKA CAFE LISBOA,-8.10\n"
    )

    body = post_csv(csv_text).json()

    assert len(client.calls) == 3
    assert [row["description"] for row in body] == [
        "BRIGHTFORD LTD SALARY",
        "VODAFONE LTD",
        "BOKKA CAFE LISBOA",
    ]


def test_payee_categorises_rows_with_no_bank_category(monkeypatch):
    """No bank category column: rows are categorised from their distinct payees."""
    payee_map = {"links": [{"source": "TESCO STORES", "target": "Groceries"}]}
    client = FakeClient([MAPPING, payee_map])
    monkeypatch.setattr(api, "get_client", lambda: client)
    csv_text = (
        "Date,Description,Amount\n"
        "2025-03-01,TESCO STORES,-12.50\n"
        "2025-03-02,TESCO STORES,-4.00\n"
    )

    body = post_csv(csv_text).json()

    assert len(client.calls) == 2
    assert [row["category"] for row in body] == ["Groceries", "Groceries"]


def test_payee_fallback_fills_a_row_left_null_by_the_bank_mapping(monkeypatch):
    """A bank label that fit no preset is retried against the payee."""
    layer_a = {
        "fields": {
            "date": exact("Date"),
            "amount": exact("Amount"),
            "payee": exact("Name"),
            "category": exact("Category"),
        }
    }
    category_map = {"links": [{"source": "Misc", "target": None}]}
    payee_map = {"links": [{"source": "TFL TRAVEL", "target": "Transport"}]}
    client = FakeClient([layer_a, category_map, payee_map])
    monkeypatch.setattr(api, "get_client", lambda: client)

    csv_text = "Date,Name,Amount,Category\n2026-08-01,TFL TRAVEL,-2.80,Misc\n"

    body = post_csv(csv_text).json()

    assert len(client.calls) == 3
    assert body[0]["category"] == "Transport"
