"""Dialect detection: the three facts the model is no longer asked for.

No network and no model. Every case here is a file shape that would otherwise have
been a question for layer A, and the sample CSVs double as the eval set -- see
`test_fixtures.py`, which asserts detection against the mappings pinned there.
"""

from pathlib import Path

import pytest

from budget_buddy.dialect import Dialect, detect_dialect

SAMPLE_DATA = Path(__file__).parents[2] / "sample-data"

# Only hsbc.csv is headerless; none of the fixtures carry a preamble.
EXPECTED = {
    "amex.csv": Dialect(skip_rows=0, delimiter=",", has_header=True),
    "hsbc.csv": Dialect(skip_rows=0, delimiter=",", has_header=False),
    "monzo.csv": Dialect(skip_rows=0, delimiter=",", has_header=True),
    "natwest.csv": Dialect(skip_rows=0, delimiter=",", has_header=True),
    "starling.csv": Dialect(skip_rows=0, delimiter=",", has_header=True),
}


@pytest.mark.parametrize("name", EXPECTED)
def test_detects_the_dialect_of_every_sample_csv(name: str):
    text = (SAMPLE_DATA / name).read_text(encoding="utf-8")

    assert detect_dialect(text) == EXPECTED[name]


def test_detects_a_headerless_file_from_a_numeric_first_row():
    """The hsbc.csv shape: a first row carrying an amount is data, not column names."""
    text = (
        '30/07/2026,"CR BRIGHTFORD LTD SALARY",3980.44\n'
        '30/07/2026,"DD VODAFONE LTD",-24.50\n'
    )

    assert detect_dialect(text).has_header is False


def test_detects_a_header_row_of_pure_text():
    text = (
        "Date,Description,Amount\n"
        "07/09/2026,TESCO EXPRESS,31.62\n"
        "05/09/2026,AMAZON,22.40\n"
    )

    assert detect_dialect(text).has_header is True


def test_skips_a_preamble_before_the_header_row():
    """A preamble defeats csv.Sniffer outright, which is why skip_rows is found first."""
    text = (
        "Account Statement\n"
        "Account: 1234\n"
        "\n"
        "Date,Description,Amount\n"
        "07/09/2026,TESCO EXPRESS,31.62\n"
        "05/09/2026,AMAZON,22.40\n"
        "01/09/2026,SPOTIFY,14.49\n"
    )

    dialect = detect_dialect(text)

    assert dialect.skip_rows == 3
    assert dialect.delimiter == ","
    assert dialect.has_header is True


def test_ignores_leading_blank_lines():
    text = (
        "\n\nDate,Description,Amount\n07/09/2026,TESCO,31.62\n05/09/2026,AMAZON,22.40\n"
    )

    assert detect_dialect(text).skip_rows == 2


def test_detects_a_semicolon_delimited_file():
    text = (
        "Datum;Beschreibung;Betrag\n"
        "07.09.2026;TESCO;31,62\n"
        "05.09.2026;AMAZON;22,40\n"
        "01.09.2026;SPOTIFY;14,49\n"
    )

    assert detect_dialect(text).delimiter == ";"


def test_detects_a_tab_delimited_file():
    text = (
        "Date\tDescription\tAmount\n"
        "07/09/2026\tTESCO\t31.62\n"
        "05/09/2026\tAMAZON\t22.40\n"
        "01/09/2026\tSPOTIFY\t14.49\n"
    )

    assert detect_dialect(text).delimiter == "\t"


def test_does_not_pick_a_delimiter_out_of_preamble_punctuation():
    """`Account: 1234` offers a colon; the candidate set refuses to consider it."""
    text = (
        "Account: 1234\n"
        "Sort code: 60-23-11\n"
        "Date,Description,Amount\n"
        "07/09/2026,TESCO,31.62\n"
        "05/09/2026,AMAZON,22.40\n"
    )

    assert detect_dialect(text).delimiter == ","


def test_falls_back_to_defaults_on_an_undetectable_file():
    """Detection failure must leave the parser exactly where it stood before."""
    text = "TESCO EXPRESS\nAMAZON\nSPOTIFY\n"

    assert detect_dialect(text) == Dialect()


def test_falls_back_to_defaults_on_an_empty_file():
    assert detect_dialect("") == Dialect()
