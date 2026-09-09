"""Tests for the pure parsing and anonymisation functions in budget_buddy.main.

These run with no network and no API key.
"""

import datetime

from budget_buddy.main import ColumnMapping, decode_csv, parse_transactions, shape


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


def test_parse_transactions_maps_columns_and_types():
    csv_text = (
        "Date,Description,Amount\n"
        "2025-03-12,TESCO STORES,-12.50\n"
        "2025-03-13,SALARY,2000.00\n"
    )
    mapping = ColumnMapping(
        date_column="Date", description_column="Description", amount_column="Amount"
    )

    rows = parse_transactions(csv_text, mapping)

    assert [row.amount for row in rows] == [-12.5, 2000.0]
    assert rows[0].date == datetime.date(2025, 3, 12)
    assert rows[0].description == "TESCO STORES"


def test_parse_transactions_honours_skip_rows_and_delimiter():
    csv_text = "Statement for account 1234\nDate;Desc;Amt\n12/03/2025;COFFEE;-3,20\n"
    mapping = ColumnMapping(
        skip_rows=1,
        delimiter=";",
        date_column="Date",
        date_format="%d/%m/%Y",
        description_column="Desc",
        amount_column="Amt",
        amount_separator=",",
    )

    rows = parse_transactions(csv_text, mapping)

    assert len(rows) == 1
    assert rows[0].amount == -3.2
    assert rows[0].date == datetime.date(2025, 3, 12)
