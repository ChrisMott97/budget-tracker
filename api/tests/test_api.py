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


MAPPING = {
    "date_column": "Date",
    "description_column": "Description",
    "amount_column": "Amount",
}


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient([MAPPING])
    monkeypatch.setattr(api, "get_client", lambda: client)
    return client


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
    }


def test_column_mapping_prompt_only_sees_the_csv_head(fake_client):
    csv_text = "Date,Description,Amount\n" + "\n".join(
        f"2025-03-01,ROW{i} SHAPE{i} {'X' * i} {i:0{i}d},-1.00" for i in range(1, 15)
    )

    post_csv(csv_text)

    head_prompt = fake_client.calls[0]
    assert "ROW1" in head_prompt
    assert "ROW14" not in head_prompt


def test_transactions_endpoint_handles_fewer_than_six_shapes(fake_client):
    csv_text = "Date,Description,Amount\n2025-03-12,TESCO STORES,-12.50\n"

    response = post_csv(csv_text)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_transactions_endpoint_parses_a_headerless_csv(monkeypatch):
    """A headerless file used to lose its first row silently; all rows must survive."""
    client = FakeClient(
        [
            {
                "has_header": False,
                "date_column": "0",
                "date_format": "%d/%m/%Y",
                "description_column": "1",
                "amount_column": "2",
            }
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
    }
