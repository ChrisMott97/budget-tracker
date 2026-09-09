"""Description shapes and bucket refinement, measured without a model.

`shape()` turns a raw transaction descriptor into a coarse token pattern so rows
with the same structure bucket together. But it collapses every run of words into
one `W+`, so `CR BRIGHTFORD LTD SALARY` and `DD VODAFONE LTD` share the bare shape
`W+` -- a bucket whose single slot spans the whole string, which is useless to
layer B (it needs a slot index for the payee).

`bucket_by_refined_shape()` splits such a bucket. Within one raw-shape group it
distinguishes *structural* tokens from the payee two ways, both pure computation:

- A curated bank-prefix vocabulary at the head (`CR`, `DD`, `VIS`, `BP`, `SO`,
  `ATM`, `)))`). The head is where a payee or a person's name sits, so it is only
  ever split against a known list, never on frequency -- a monthly payment to a
  named individual recurs just as reliably as a scheme code.
- A token that recurs at a fixed distance from the *end* of the string across the
  bucket (a trailing location or scheme suffix). Frequency is indexed from the
  end because the structural tail sits a fixed offset from the end while the
  payee's length varies (Amex `... LONDON`, Monzo `... LONDON`). This path is
  disabled for a bucket that is really one payee repeated -- see
  `MIN_DISTINCT_LEADING`.

`slots()` then cuts a description into the text under each non-comma token of its
refined shape, so layer B can lift a fact out of every row in a bucket by slot
index.
"""

import re
from collections import Counter

# The word/comma/space tokeniser. `profile.py` imports `word_tokens` from here
# rather than re-deriving the word alternative, now that main -> shapes and
# profile -> shapes both resolve without a cycle.
TOKEN_RE = re.compile(r"(?P<comma>\s*,\s*)|(?P<space>\s+)|(?P<word>[^\s,]+)")
WORD_TOKEN_RE = re.compile(r"[^\s,]+")

# TODO: extend to other date formats
DATE_RE = re.compile(
    r"""^(
    \d{1,2}[A-Z]{3}\d{2,4}          # 12MAR25
  | \d{1,2}[/-]\d{1,2}[/-]\d{2,4}   # 12/03/25
  | \d{4}-\d{2}-\d{2}               # 2025-03-12
)$""",
    re.VERBOSE,
)

WORD_RE = re.compile(r"[*]?[^\W\d_][\w'&.\-*]*", re.UNICODE)

# Structural prefixes that lead a raw bank descriptor. Each of CR, DD, BP, SO,
# VIS, ATM and ))) leads a row in `sample-data/hsbc.csv` (VIS = Visa, ))) = the
# contactless glyph, SO = standing order, BP = bill payment, CR/DD = credit and
# direct debit). DR, BGC, TFR, CHG, FPO and FPI are the common siblings of the
# same UK clearing vocabulary, listed so a real statement is not missed for want
# of one code; none of them is a plausible merchant or personal name.
BANK_PREFIX_VOCAB = frozenset(
    {
        "CR",
        "DR",
        "DD",
        "BP",
        "SO",
        "VIS",
        "ATM",
        ")))",
        "BGC",
        "TFR",
        "CHG",
        "FPO",
        "FPI",
    }
)

# A trailing token counts as structural once it recurs at its from-the-end
# position in at least this fraction of the bucket and at least this many rows --
# a trailing token in two of every five structurally-alike rows is not incidental,
# and the row floor keeps a tiny bucket from splitting on a coincidence. First
# cut; layer B will show whether they need tuning.
RECUR_FRACTION = 0.4
RECUR_MIN_ROWS = 3

# Frequency-based splitting is only allowed for a bucket with at least this many
# distinct leading tokens. A bucket of `ALEX HOLLOWAY RENT JULY`,
# `ALEX HOLLOWAY RENT AUGUST`, ... is one payee repeated: every token past the
# first recurs, and splitting on that would fragment the very name the head rule
# is there to protect.
MIN_DISTINCT_LEADING = 3


def word_tokens(value: str) -> list[str]:
    """The non-space, non-comma tokens of a value, in order."""
    return WORD_TOKEN_RE.findall(value)


def classify(tok: str) -> str:
    if DATE_RE.match(tok):
        return "DATE"
    if re.fullmatch(r"\d+", tok):
        return f"N{len(tok)}" if len(tok) <= 6 else "N+"
    if tok == "&":
        return "AMP"
    if WORD_RE.fullmatch(tok):
        return "W"
    return "X"


def tokenise(desc: str) -> list[tuple[str, str, int, int]]:
    """Returns [(kind, text, start, end)] covering the whole string."""
    out = []
    for m in TOKEN_RE.finditer(desc):
        kind = m.lastgroup
        out.append((kind, m.group(), m.start(), m.end()))
    return out


def _collapse_runs(tagged: list[tuple[str, ...]]) -> str:
    """Fold a list of (class, text, ...) tokens into a shape string.

    A run of adjacent `W` becomes a single `W+`; an `&` inside a name is swallowed
    with the word after it; a comma is structure; anything else (`DATE`, `N4`,
    `PFX`, `X`, ...) is emitted verbatim. Shared by `shape()` and `refined_shape()`
    so the two cannot drift apart. Only element `[0]` (the class) is read, so the
    same tagging works whether or not each token also carries its source span --
    `_collapse_runs_with_spans` is the span-keeping sibling.
    """
    parts, run, i = [], False, 0
    while i < len(tagged):
        cls = tagged[i][0]

        if cls == "COMMA":
            parts.append(",")
            run = False

        elif cls == "AMP":
            nxt = tagged[i + 1][0] if i + 1 < len(tagged) else None
            if run and nxt == "W":
                i += 2  # swallow the & and the word after it
                continue
            run = False
            parts.append("X")  # dangling &, treat as junk

        elif cls == "W":
            if not run:
                parts.append("W+")
                run = True

        else:
            parts.append(cls)
            run = False

        i += 1
    return " ".join(parts)


def _tag_tokens(desc: str) -> list[tuple[str, str]]:
    """(class, text) for the word and comma tokens of a description."""
    tagged = [
        (classify(t), t) for k, t, _, _ in tokenise(desc) if k == "word" or k == "comma"
    ]
    return [("COMMA", t) if t.strip() == "," else (c, t) for c, t in tagged]


def shape(desc: str) -> str:
    return _collapse_runs(_tag_tokens(desc))


def suffix_token_frequencies(descriptions: list[str]) -> list[Counter[str]]:
    """`freqs[j][TOKEN]` = rows whose j-th token counting from the end is TOKEN.

    Upper-cased, matching how `profile.file_token_frequencies` and containment
    compare tokens. Indexed from the end so a trailing location lines up across
    rows whose payee prefix differs in length.
    """
    rows = [[t.upper() for t in word_tokens(d)] for d in descriptions]
    width = max((len(r) for r in rows), default=0)
    freqs = [Counter[str]() for _ in range(width)]
    for row in rows:
        for j, tok in enumerate(reversed(row)):
            freqs[j][tok] += 1
    return freqs


def _distinct_leading(descriptions: list[str]) -> int:
    return len({toks[0].upper() for d in descriptions if (toks := word_tokens(d))})


def _refined_tags(
    desc: str,
    suffix_freqs: list[Counter[str]],
    row_count: int,
    *,
    allow_frequency: bool,
) -> list[tuple[str, str, int, int]]:
    """`(class, text, start, end)` per word and comma token, with structural
    tokens re-tagged `PFX`.

    A token is structural when it is a known bank prefix still inside the leading
    run, or -- for a bucket eligible for it -- when it recurs near the end of the
    string across the bucket. Everything else keeps its `shape()` class. Factored
    out of `refined_shape` so `refined_shape` and `slots` tag the string once,
    the same way `_collapse_runs` is shared with `shape`.
    """
    words = word_tokens(desc)
    tagged: list[tuple[str, str, int, int]] = []
    position = 0
    leading = True
    for kind, text, start, end in tokenise(desc):
        if kind == "comma":
            tagged.append(("COMMA", text, start, end))
            leading = False
            continue
        if kind != "word":
            continue

        upper = text.upper()
        suffix_index = len(words) - 1 - position
        by_vocab = leading and upper in BANK_PREFIX_VOCAB
        by_frequency = (
            allow_frequency
            and not leading
            and suffix_freqs[suffix_index][upper] >= RECUR_MIN_ROWS
            and suffix_freqs[suffix_index][upper] / row_count >= RECUR_FRACTION
        )

        if by_vocab or by_frequency:
            tagged.append(("PFX", text, start, end))
        else:
            tagged.append((classify(text), text, start, end))
            leading = False
        position += 1

    return tagged


def _collapse_runs_with_spans(
    tagged: list[tuple[str, str, int, int]],
) -> list[tuple[str, int, int]]:
    """`_collapse_runs`, but each emitted shape token keeps the `(start, end)` it
    covers in the original string, and commas are dropped.

    Commas are structure, not a slot -- the shape string keeps them but slot
    indices count past them, matching the roadmap's `{payee: 3}` for
    `"N4 DATE W+ , W+ , W+"`. A `W+` run spans from its first word's start to its
    last word's end, so interior single spaces survive (`"LONDON GB"`); a
    swallowed `& <word>` extends the open run over both.
    """
    out: list[tuple[str, int, int]] = []
    run_start: int | None = None
    i = 0
    while i < len(tagged):
        cls, _, start, end = tagged[i]

        if cls == "COMMA":
            run_start = None

        elif cls == "AMP":
            nxt = tagged[i + 1][0] if i + 1 < len(tagged) else None
            if run_start is not None and nxt == "W":
                word_end = tagged[i + 1][3]
                out[-1] = ("W+", out[-1][1], word_end)
                i += 2  # swallow the & and the word after it
                continue
            run_start = None
            out.append(("X", start, end))  # dangling &, treat as junk

        elif cls == "W":
            if run_start is None:
                run_start = start
                out.append(("W+", start, end))
            else:
                out[-1] = ("W+", run_start, end)

        else:
            out.append((cls, start, end))
            run_start = None

        i += 1
    return out


def refined_shape(
    desc: str,
    suffix_freqs: list[Counter[str]],
    row_count: int,
    *,
    allow_frequency: bool,
) -> str:
    """`shape(desc)` with structural tokens re-tagged `PFX`.

    A token is structural when it is a known bank prefix still inside the leading
    run, or -- for a bucket eligible for it -- when it recurs near the end of the
    string across the bucket. Everything else keeps its `shape()` class, so an
    unrefined description round-trips to the same string `shape()` would give.
    """
    return _collapse_runs(
        _refined_tags(desc, suffix_freqs, row_count, allow_frequency=allow_frequency)
    )


def slots(
    desc: str,
    suffix_freqs: list[Counter[str]],
    row_count: int,
    *,
    allow_frequency: bool,
) -> list[str]:
    """The source text under each non-comma token of `refined_shape(desc, ...)`.

    `refined_shape` calls a row e.g. `"N4 DATE W+ , W+ N3 , W+"`; this returns the
    substring beneath each of those tokens except the commas, so `slots(...)[k]`
    is the text for slot `k` and can be lifted from every row that shares the
    shape. `len(slots(...))` equals the count of non-comma tokens in
    `refined_shape(...)` called with the same arguments.

    Returns real substrings, so this is a server-side step only -- it is never
    sent to a model. The shape strings that are sent stay in `refined_shape`.
    """
    tagged = _refined_tags(
        desc, suffix_freqs, row_count, allow_frequency=allow_frequency
    )
    return [desc[start:end] for _, start, end in _collapse_runs_with_spans(tagged)]


def bucket_by_refined_shape(descriptions: list[str]) -> dict[str, list[int]]:
    """Group row indices by refined shape.

    Rows are first grouped by `shape()`; every multi-row group is then re-split by
    `refined_shape()`, so one bare `W+` bucket becomes `PFX W+`, `W+ PFX`, `W+`
    sub-buckets. Returns indices, not the description strings, so a bucketing call
    never hands raw text back out. Keys are sorted for a stable result.
    """
    raw_groups: dict[str, list[int]] = {}
    for index, desc in enumerate(descriptions):
        raw_groups.setdefault(shape(desc), []).append(index)

    refined: dict[str, list[int]] = {}
    for members in raw_groups.values():
        if len(members) == 1:
            refined.setdefault(shape(descriptions[members[0]]), []).append(members[0])
            continue
        group = [descriptions[i] for i in members]
        suffix_freqs = suffix_token_frequencies(group)
        allow_frequency = _distinct_leading(group) >= MIN_DISTINCT_LEADING
        for index in members:
            key = refined_shape(
                descriptions[index],
                suffix_freqs,
                len(members),
                allow_frequency=allow_frequency,
            )
            refined.setdefault(key, []).append(index)

    return {key: refined[key] for key in sorted(refined)}
