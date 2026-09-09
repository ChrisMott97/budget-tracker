"""Tests for the column profiler.

Pure computation: no network, no model, no API key. The fixture tests at the
bottom pin the statistics that ROADMAP milestone 1 records against
`sample-data/`, so a change in the measurements shows up as a failing test
rather than as quietly different prompt input.
"""

from pathlib import Path

import pandas as pd
import pytest

from budget_buddy.profile import (
    ColumnProfile,
    profile_columns,
    read_raw_frame,
    sample_column_values,
)

SAMPLE_DATA = Path(__file__).parents[2] / "sample-data"


def profile_of(frame: pd.DataFrame, label: str) -> ColumnProfile:
    return next(
        column for column in profile_columns(frame).columns if column.label == label
    )


def test_cardinality_ratio_separates_an_enum_column_from_free_text():
    frame = pd.DataFrame(
        {
            "Type": ["D/D", "POS", "BAC", "D/D", "POS", "BAC"],
            "Description": ["ONE A", "TWO B", "THREE C", "FOUR D", "FIVE E", "SIX F"],
        }
    )

    assert profile_of(frame, "Type").cardinality_ratio == 0.5
    assert profile_of(frame, "Description").cardinality_ratio == 1.0


def test_cardinality_ratio_marks_a_constant_column():
    """NatWest repeats `Account Name` on every row; it holds no per-transaction data."""
    frame = pd.DataFrame({"Account Name": ["HOLLOWAY AJ"] * 20})

    assert profile_of(frame, "Account Name").cardinality_ratio == pytest.approx(0.05)


def test_case_profile_distinguishes_a_title_case_payee_from_an_upper_case_descriptor():
    frame = pd.DataFrame(
        {
            "Name": ["Tesco", "Spotify", "Alex Holloway", "Uber"],
            "Description": [
                "TESCO EXPRESS 3411 LONDON",
                "SPOTIFY LONDON",
                "ALEX HOLLOWAY",
                "UBER *TRIP HELP.UBER.COM",
            ],
        }
    )

    name = profile_of(frame, "Name")
    description = profile_of(frame, "Description")

    assert name.case_profile == "Mixed"
    assert description.case_profile == "UPPER"
    assert name.mean_token_count < description.mean_token_count


def test_fill_rate_counts_blank_and_whitespace_only_values_as_empty():
    frame = pd.DataFrame({"Notes": ["rent", "", "   ", "airport run"]})

    assert profile_of(frame, "Notes").fill_rate == 0.5


def test_an_entirely_empty_column_profiles_without_dividing_by_zero():
    """Monzo ships `Receipt` and `Category split` with no values at all."""
    frame = pd.DataFrame({"Receipt": ["", "", ""]})

    receipt = profile_of(frame, "Receipt")

    assert receipt.fill_rate == 0.0
    assert receipt.cardinality_ratio == 0.0
    assert receipt.mean_token_count == 0.0
    assert receipt.mean_length == 0.0
    assert receipt.case_profile == "none"
    assert receipt.case_consistency == 0.0


def test_mean_token_count_and_length_ignore_empty_values():
    frame = pd.DataFrame({"Reference": ["ONE TWO THREE", "", "FOUR"]})

    reference = profile_of(frame, "Reference")

    assert reference.mean_token_count == 2.0
    assert reference.mean_length == pytest.approx(8.5)


def test_containment_reports_a_narrow_column_embedded_in_a_wider_one():
    frame = pd.DataFrame(
        {
            "Name": ["Tesco", "Spotify", "Uber", "Pret"],
            "Description": [
                "TESCO EXPRESS 3411 LONDON",
                "SPOTIFY LONDON",
                "UBER TRIP LONDON",
                "PRET A MANGER LONDON",
            ],
        }
    )

    containments = profile_columns(frame).containments

    assert [(c.contained, c.container) for c in containments] == [
        ("Name", "Description")
    ]
    assert containments[0].fraction == 1.0


def test_containment_ignores_duplicate_columns_that_contain_each_other():
    """Monzo `Amount` and `Local amount` are the same value, not one inside the other."""
    frame = pd.DataFrame(
        {
            "Amount": ["-31.62", "-18.72", "-45.00", "-9.45"],
            "Local amount": ["-31.62", "-18.72", "-45.00", "-9.45"],
        }
    )

    assert profile_columns(frame).containments == []


def test_containment_stays_silent_below_the_threshold():
    """Starling `Counter Party` matches `Reference` on only half the rows."""
    frame = pd.DataFrame(
        {
            "Counter Party": [
                "Vodafone Ltd",
                "Brightford Ltd",
                "Alex Holloway",
                "Puregym Ltd",
            ],
            "Reference": [
                "VODAFONE LTD BILL",
                "SALARY PAYMENT",
                "Rent August",
                "PUREGYM LTD GYM",
            ],
        }
    )

    assert profile_columns(frame).containments == []


def test_headerless_columns_are_labelled_by_position():
    """Matches how ColumnMapping addresses a headerless CSV: the index as a string."""
    frame = read_raw_frame(
        '30/07/2026,"CR BRIGHTFORD LTD SALARY   ",3980.44\n'
        '30/07/2026,"DD VODAFONE LTD            ",-24.50\n',
        has_header=False,
    )

    assert [column.label for column in profile_columns(frame).columns] == [
        "0",
        "1",
        "2",
    ]


def test_read_raw_frame_keeps_a_literal_na_as_text():
    """`keep_default_na` off: an empty cell and the string "NA" must not collapse together."""
    frame = read_raw_frame("Payee,Notes\nNA,\n")

    assert profile_of(frame, "Payee").fill_rate == 1.0
    assert profile_of(frame, "Notes").fill_rate == 0.0


def test_sample_column_values_prefers_values_built_from_common_tokens():
    """A once-only merchant name is passed over for a value whose tokens recur file-wide."""
    columns = {
        "Description": [
            "DIRECT DEBIT VODAFONE",
            "DIRECT DEBIT BRITISH GAS",
            "DIRECT DEBIT COUNCIL",
            "CARD PAYMENT KOFFEEWERK ROASTERY",
        ],
        "Type": ["DIRECT DEBIT", "DIRECT DEBIT", "DIRECT DEBIT", "CARD PAYMENT"],
    }

    samples = sample_column_values(columns, size=2)

    assert "CARD PAYMENT KOFFEEWERK ROASTERY" not in samples["Description"]
    assert "DIRECT DEBIT VODAFONE" in samples["Description"]


def test_sample_column_values_caps_at_the_requested_size():
    columns = {"Payee": [f"MERCHANT {n}" for n in range(20)]}

    assert len(sample_column_values(columns, size=3)["Payee"]) == 3


def test_sample_column_values_order_is_independent_of_row_order():
    """The emitted list is sorted, so shuffling the rows cannot change what is sent."""
    forwards = {"Payee": ["ALPHA LTD", "BRAVO LTD", "CHARLIE LTD", "DELTA LTD"]}
    backwards = {"Payee": list(reversed(forwards["Payee"]))}

    assert sample_column_values(forwards) == sample_column_values(backwards)


def test_sample_column_values_handles_a_single_row_and_empty_columns():
    columns = {"Payee": ["TESCO"], "Notes": ["", "", ""]}

    samples = sample_column_values(columns)

    assert samples["Payee"] == ["TESCO"]
    assert samples["Notes"] == []


def fixture_frame(name: str) -> pd.DataFrame:
    text = (SAMPLE_DATA / name).read_text(encoding="utf-8-sig")
    return read_raw_frame(text, has_header=name != "hsbc.csv")


# (fixture, column, metric, expected) -- the numbers ROADMAP milestone 1 quotes,
# which are rounded to the precision the roadmap states them at.
MEASURED = [
    ("natwest.csv", "Type", "cardinality_ratio", 0.17),
    ("natwest.csv", "Account Name", "cardinality_ratio", 0.03),
    ("natwest.csv", "Description", "mean_token_count", 6.9),
    ("natwest.csv", "Description", "case_consistency", 0.97),
    ("starling.csv", "Spending Category", "cardinality_ratio", 0.50),
    ("monzo.csv", "Name", "mean_token_count", 1.6),
    ("monzo.csv", "Name", "cardinality_ratio", 1.0),
    ("monzo.csv", "Receipt", "fill_rate", 0.0),
    ("amex.csv", "Description", "mean_token_count", 3.8),
    ("hsbc.csv", "1", "mean_token_count", 4.2),
]


@pytest.mark.parametrize("name,label,metric,expected", MEASURED)
def test_fixture_profiles_match_the_measured_column_statistics(
    name: str, label: str, metric: str, expected: float
):
    profile = profile_of(fixture_frame(name), label)

    assert getattr(profile, metric) == pytest.approx(expected, abs=0.05)


def test_natwest_description_is_upper_case_and_monzo_name_is_not():
    """Case is what separates a raw descriptor from a bank-cleaned counterparty."""
    assert (
        profile_of(fixture_frame("natwest.csv"), "Description").case_profile == "UPPER"
    )
    assert profile_of(fixture_frame("monzo.csv"), "Name").case_profile == "Mixed"


def test_monzo_name_is_detected_as_embedded_in_description():
    containments = profile_columns(fixture_frame("monzo.csv")).containments

    name = next(c for c in containments if c.contained == "Name")
    assert name.container == "Description"
    assert name.fraction == pytest.approx(0.80, abs=0.05)


def test_monzo_duplicate_amount_and_currency_columns_are_not_reported_as_containment():
    """The guard that keeps the profile's containment list usable on a 16-column file."""
    pairs = {
        (c.contained, c.container)
        for c in profile_columns(fixture_frame("monzo.csv")).containments
    }

    assert ("Amount", "Local amount") not in pairs
    assert ("Currency", "Local currency") not in pairs


def test_starling_counter_party_and_reference_report_no_containment():
    """The roadmap's explicit case: containment must stay silent when it does not fire."""
    pairs = {
        (c.contained, c.container)
        for c in profile_columns(fixture_frame("starling.csv")).containments
    }

    assert ("Counter Party", "Reference") not in pairs
