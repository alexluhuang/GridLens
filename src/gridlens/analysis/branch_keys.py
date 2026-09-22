"""Canonical circuit and section labels shared by flat CSV and indexed results."""
from __future__ import annotations

def canonical_branch_label(value: object) -> str:
    """Return one literal circuit/section label for a CSV value; row parsers and queries use it."""
    if value is None:
        return ""
    return " ".join(str(value).strip().strip("'\"").strip().split())


def canonical_branch_series(values):
    """Normalize a pandas/cuDF column without changing labels such as 01 or 1.0; frame parsing uses it."""
    return (
        values.fillna("").astype("str")
        .str.strip().str.strip("'\"").str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )


def canonical_branch_arrow(values):
    """Normalize a PyArrow column with the same quote and space rules; event indexing uses it."""
    import pyarrow.compute as pc

    result = pc.utf8_trim_whitespace(pc.fill_null(values, ""))
    result = pc.replace_substring_regex(result, pattern=r"^['\"]+|['\"]+$", replacement="")
    result = pc.utf8_trim_whitespace(result)
    return pc.replace_substring_regex(result, pattern=r"\s+", replacement=" ")
