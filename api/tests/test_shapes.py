"""Tests for description shaping and bucket refinement.

Pure computation: no network, no model, no API key. The fixture tests at the
bottom pin bucket refinement against `sample-data/`, the same way
`test_profile.py` pins the column statistics.
"""

from collections import Counter
from pathlib import Path

from budget_buddy.profile import read_raw_frame
from budget_buddy.shapes import (
    bucket_by_refined_shape,
    refined_shape,
    shape,
    slots,
    suffix_token_frequencies,
)

SAMPLE_DATA = Path(__file__).parents[2] / "sample-data"


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


def test_suffix_token_frequencies_count_tokens_from_the_end():
    """Index 0 is the last token, so a trailing token lines up across rows whose
    prefix differs in length."""
    freqs = suffix_token_frequencies(["ALPHA CO LONDON", "BETA LONDON"])

    assert freqs[0] == Counter({"LONDON": 2})
    assert freqs[1] == Counter({"CO": 1, "BETA": 1})
    assert freqs[2] == Counter({"ALPHA": 1})


def test_a_known_bank_prefix_is_split_from_the_payee():
    buckets = bucket_by_refined_shape(
        ["CR BRIGHTFORD LTD SALARY", "DD VODAFONE LTD", "VIS BOKKA CAFE LISBOA"]
    )

    assert buckets == {"PFX W+": [0, 1, 2]}


def test_an_unknown_leading_token_stays_with_the_payee():
    """`NON-STERLING` is not in the prefix vocab, so its row is not split."""
    buckets = bucket_by_refined_shape(
        [
            "CR BRIGHTFORD LTD SALARY",
            "DD VODAFONE LTD",
            "VIS BOKKA CAFE LISBOA",
            "NON-STERLING TRANSACTION FEE",
        ]
    )

    assert buckets["PFX W+"] == [0, 1, 2]
    assert buckets["W+"] == [3]


def test_a_recurring_trailing_token_is_marked_structural():
    buckets = bucket_by_refined_shape(
        ["SPOTIFY LONDON", "NETFLIX LONDON", "APPLE LONDON", "PUREGYM LEEDS"]
    )

    assert buckets["W+ PFX"] == [0, 1, 2]
    assert buckets["W+"] == [3]


def test_a_bucket_that_is_one_payee_repeated_is_never_split():
    """Roadmap caveat: a monthly payment to a named individual recurs too. A
    bucket with too few distinct leading tokens is left whole rather than
    fragmenting the name."""
    buckets = bucket_by_refined_shape(
        [
            "ALEX HOLLOWAY RENT JULY",
            "ALEX HOLLOWAY RENT AUGUST",
            "ALEX HOLLOWAY RENT SEPTEMBER",
        ]
    )

    assert buckets == {"W+": [0, 1, 2]}


def test_a_recurring_leading_token_is_not_promoted_without_the_vocab():
    """The head is split only against the prefix vocab. `RENT` recurs at the head
    in three of five rows and is still kept as part of the payee run, so those
    rows key on a leading `W+`, not `PFX`."""
    buckets = bucket_by_refined_shape(
        [
            "RENT ALICE LONDON",
            "RENT BOB LONDON",
            "RENT CAROL LONDON",
            "TESCO OXFORD",
            "GAIL BATH",
        ]
    )

    assert buckets["W+ PFX"] == [0, 1, 2]


def test_bucket_by_refined_shape_leaves_a_singleton_untouched():
    buckets = bucket_by_refined_shape(["CR BRIGHTFORD LTD SALARY"])

    assert buckets == {"W+": [0]}


def test_refined_shape_never_leaks_the_original_text():
    descriptions = [
        "VIS SAINSBURYS SUPERMARKET LONDON",
        "VIS WAITROSE STORES LONDON",
        "VIS TESCO METRO LONDON",
    ]

    for key in bucket_by_refined_shape(descriptions):
        for token in " ".join(descriptions).split():
            assert token not in key


def _slots(desc: str, *, allow_frequency: bool = False) -> list[str]:
    """`slots()` for one description in isolation, with its own suffix table."""
    return slots(
        desc, suffix_token_frequencies([desc]), 1, allow_frequency=allow_frequency
    )


def test_slot_text_is_the_payee_for_a_natwest_pos_row():
    row = "7712 26AUG26 C , WAITROSE 742 , LONDON GB"

    assert _slots(row)[3] == "WAITROSE"


def test_a_word_run_slot_keeps_interior_spaces():
    row = "7712 26AUG26 C , WAITROSE 742 , LONDON GB"

    assert _slots(row)[5] == "LONDON GB"


def test_a_bank_prefix_is_its_own_slot():
    assert _slots("CR BRIGHTFORD LTD SALARY") == ["CR", "BRIGHTFORD LTD SALARY"]


def test_an_ampersand_stays_inside_its_word_run_slot():
    assert _slots("MARKS & SPENCER") == ["MARKS & SPENCER"]
    assert _slots("M&S SIMPLY FOOD") == ["M&S SIMPLY FOOD"]


def fixture_descriptions(
    name: str, label: str, *, has_header: bool = True
) -> list[str]:
    text = (SAMPLE_DATA / name).read_text(encoding="utf-8-sig")
    frame = read_raw_frame(text, has_header=has_header)
    return [str(value).strip() for value in frame[label]]


def test_hsbc_bare_word_bucket_refines_to_prefix_plus_payee():
    """The 16-row `W+` bucket the roadmap calls out becomes `PFX W+` once the
    scheme prefix (CR, DD, VIS, ...) is split off."""
    buckets = bucket_by_refined_shape(
        fixture_descriptions("hsbc.csv", "1", has_header=False)
    )

    assert "W+" not in buckets or len(buckets["W+"]) <= 2
    assert len(buckets["PFX W+"]) >= 12


def test_amex_bare_word_bucket_splits_the_trailing_location():
    """Amex has no scheme prefix; the recurring trailing city is split instead,
    shrinking the undifferentiated `W+` bucket."""
    buckets = bucket_by_refined_shape(fixture_descriptions("amex.csv", "Description"))

    assert len(buckets["W+ PFX"]) >= 5
    assert len(buckets.get("W+", [])) < 14


def _refine_setup(descriptions: list[str]):
    """(desc, suffix_freqs, row_count, allow_frequency) per description, grouped by
    raw shape the way `bucket_by_refined_shape` sets its `refined_shape` calls up."""
    groups: dict[str, list[str]] = {}
    for desc in descriptions:
        groups.setdefault(shape(desc), []).append(desc)
    for group in groups.values():
        freqs = suffix_token_frequencies(group)
        for desc in group:
            yield desc, freqs, len(group), True


def test_slots_align_with_the_refined_shape_tokens():
    """`len(slots(...))` always equals the non-comma token count of
    `refined_shape(...)` for the same arguments, so the two folders cannot drift."""
    fixtures = [
        ("natwest.csv", "Description", True),
        ("hsbc.csv", "1", False),
        ("amex.csv", "Description", True),
    ]
    for name, label, has_header in fixtures:
        descriptions = fixture_descriptions(name, label, has_header=has_header)
        for desc, freqs, count, allow in _refine_setup(descriptions):
            shape_str = refined_shape(desc, freqs, count, allow_frequency=allow)
            non_comma = [tok for tok in shape_str.split() if tok != ","]
            got = slots(desc, freqs, count, allow_frequency=allow)
            assert len(got) == len(non_comma), (name, desc, shape_str, got)
