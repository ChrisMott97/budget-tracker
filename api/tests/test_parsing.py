"""Tests for the pure parsing and anonymisation functions in budget_buddy.main.

These run with no network and no API key.
"""

import datetime

import pytest
from fastapi import HTTPException

from budget_buddy.main import (
    ColumnMapping,
    FieldMap,
    FieldSource,
    Purity,
    decode_csv,
    parse_transactions,
    response_schema,
    shape,
)


def test_decode_csv_strips_utf8_bom():
    text, encoding = decode_csv("﻿Date,Amount\n".encode())
    assert encoding == "utf-8-sig"
    assert text.startswith("Date")


def test_decode_csv_falls_back_to_cp1252():
    text, encoding = decode_csv("CAF\xc9 NERO".encode("cp1252"))
    assert encoding == "cp1252"
    assert text == "CAFÉ NERO"


def test_shape_collapses_word_runs_and_classifies_numbers():
    assert shape("TESCO STORES 1234 LONDON") == "W+ N4 W+"


def test_shape_keeps_dates_and_commas_as_structure():
    assert shape("AMAZON.CO.UK, 12MAR25, REF 123456789") == "W+ , DATE , W+ N+"


def test_shape_swallows_ampersand_inside_a_name():
    assert shape("MARKS & SPENCER") == "W+"
    assert shape("M&S SIMPLY FOOD") == "W+"


def test_shape_never_leaks_the_original_text():
    description = "DIRECT DEBIT ACME INSURANCE 987654 REF A1B2C3"
    result = shape(description)
    for token in description.split():
        assert token not in result


def objects_with_properties(node) -> list[dict]:
    if isinstance(node, dict):
        found = [node] if isinstance(node.get("properties"), dict) else []
        return found + [
            obj for value in node.values() for obj in objects_with_properties(value)
        ]
    if isinstance(node, list):
        return [obj for item in node for obj in objects_with_properties(item)]
    return []


def test_response_schema_leaves_no_property_optional():
    """Pydantic drops `required` for defaulted fields, and the model then answers `{}`."""
    found = objects_with_properties(response_schema())

    assert len(found) == 3  # ColumnMapping, FieldMap, FieldSource
    for obj in found:
        assert obj["required"] == sorted(obj["properties"])


def test_response_schema_asks_for_every_fact():
    assert response_schema()["$defs"]["FieldMap"]["required"] == [
        "amount",
        "balance",
        "category",
        "currency",
        "date",
        "notes",
        "payee",
        "reference",
        "txn_type",
    ]


def test_response_schema_keeps_the_column_nullable():
    """Required plus nullable is the pairing that makes "no such column" statable."""
    column = response_schema()["$defs"]["FieldSource"]["properties"]["column"]

    assert {"type": "null"} in column["anyOf"]


def mapping(
    *,
    date: str = "Date",
    amount: str = "Amount",
    payee: str = "Description",
    payee_purity: Purity = "exact",
    **overrides,
) -> ColumnMapping:
    """Build a mapping for the three facts the parser needs.

    Only date, amount and payee reach the parser, so spelling out all nine facts in
    every test would bury the behaviour each one is actually pinning.
    """
    return ColumnMapping(
        fields=FieldMap(
            date=FieldSource(column=date, purity="exact"),
            amount=FieldSource(column=amount, purity="exact"),
            payee=FieldSource(column=payee, purity=payee_purity),
        ),
        **overrides,
    )


def test_absent_purity_clears_the_column():
    """The model can name a column and still call the fact absent; absent wins."""
    source = FieldSource(column="Spending Category", purity="absent")

    assert source.column is None


def test_a_null_column_forces_absent_purity():
    """And the other direction: a confident purity with nothing to point at is absent."""
    assert FieldSource(column=None, purity="exact").purity == "absent"
    assert FieldSource(column="", purity="embedded").purity == "absent"


def test_a_field_map_defaults_every_fact_to_absent():
    fields = FieldMap()

    assert [source.purity for source in vars(fields).values()] == ["absent"] * 9


def test_parse_transactions_maps_columns_and_types():
    csv_text = (
        "Date,Description,Amount\n"
        "2025-03-12,TESCO STORES,-12.50\n"
        "2025-03-13,SALARY,2000.00\n"
    )

    rows = parse_transactions(csv_text, mapping())

    assert [row.amount for row in rows] == [-12.5, 2000.0]
    assert rows[0].date == datetime.date(2025, 3, 12)
    assert rows[0].description == "TESCO STORES"


def test_parse_transactions_reads_an_embedded_payee_column_whole():
    """An embedded payee is not split yet; layer B does that. Nothing may be dropped."""
    csv_text = (
        "Date,Description,Value\n"
        '2026-08-27,"7712 26AUG26 C , WAITROSE 742 , LONDON GB",-51.03\n'
    )

    rows = parse_transactions(
        csv_text, mapping(amount="Value", payee_purity="embedded")
    )

    assert rows[0].description == "7712 26AUG26 C , WAITROSE 742 , LONDON GB"


def test_parse_transactions_rejects_a_mapping_with_no_payee():
    """A fact the parser needs cannot be absent, and the error has to name which."""
    csv_text = "Date,Description,Amount\n2025-03-12,TESCO STORES,-12.50\n"
    no_payee = mapping()
    no_payee.fields.payee = FieldSource()

    with pytest.raises(HTTPException) as raised:
        parse_transactions(csv_text, no_payee)

    assert raised.value.status_code == 422
    assert "payee" in raised.value.detail


def test_parse_transactions_honours_skip_rows_and_delimiter():
    csv_text = "Statement for account 1234\nDate;Desc;Amt\n12/03/2025;COFFEE;-3,20\n"

    rows = parse_transactions(
        csv_text,
        mapping(
            amount="Amt",
            payee="Desc",
            skip_rows=1,
            delimiter=";",
            date_format="%d/%m/%Y",
            amount_separator=",",
        ),
    )

    assert len(rows) == 1
    assert rows[0].amount == -3.2
    assert rows[0].date == datetime.date(2025, 3, 12)


HEADERLESS_CSV = (
    '30/07/2026,"CR BRIGHTFORD LTD SALARY          ",3980.44\n'
    '30/07/2026,"DD VODAFONE LTD                   ",-24.50\n'
    '31/07/2026,"))) PRET A MANGER 0641 LONDON     ",-9.45\n'
)


def headerless_mapping(**overrides) -> ColumnMapping:
    return mapping(
        date="0",
        payee="1",
        payee_purity="embedded",
        amount="2",
        has_header=False,
        date_format="%d/%m/%Y",
        **overrides,
    )


def test_parse_transactions_reads_a_headerless_csv_by_position():
    rows = parse_transactions(HEADERLESS_CSV, headerless_mapping())

    assert len(rows) == 3
    assert rows[0].date == datetime.date(2026, 7, 30)
    assert rows[0].description == "CR BRIGHTFORD LTD SALARY"
    assert rows[0].amount == 3980.44


def test_parse_transactions_keeps_the_first_row_when_there_is_no_header():
    """The silent data-loss regression: a name-based mapping eats row one as a header."""
    promoted = parse_transactions(
        HEADERLESS_CSV,
        mapping(
            date="30/07/2026",
            payee="CR BRIGHTFORD LTD SALARY          ",
            amount="3980.44",
            date_format="%d/%m/%Y",
        ),
    )
    assert len(promoted) == 2

    assert len(parse_transactions(HEADERLESS_CSV, headerless_mapping())) == 3


def test_parse_transactions_rejects_named_columns_on_a_headerless_csv():
    named = headerless_mapping()
    named.fields.date.column = "Date"

    with pytest.raises(HTTPException) as raised:
        parse_transactions(HEADERLESS_CSV, named)

    assert raised.value.status_code == 422


def test_parse_transactions_strips_padded_descriptions():
    rows = parse_transactions(HEADERLESS_CSV, headerless_mapping())

    assert [row.description for row in rows] == [
        "CR BRIGHTFORD LTD SALARY",
        "DD VODAFONE LTD",
        "))) PRET A MANGER 0641 LONDON",
    ]
