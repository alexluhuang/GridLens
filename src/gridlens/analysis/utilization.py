from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


NONTRANSFORMER_BRANCH = "nontransformer_branch"
TWO_WINDING_TRANSFORMER_BRANCH = "two_winding_transformer_branch"
THREE_WINDING_TRANSFORMER_BRANCH = "three_winding_transformer_branch"
TRANSFORMER_EQUIVALENT_BRANCH = "transformer_equivalent_branch"
TRANSFORMER_BRANCH_TYPES = frozenset(
    {
        TWO_WINDING_TRANSFORMER_BRANCH,
        THREE_WINDING_TRANSFORMER_BRANCH,
        TRANSFORMER_EQUIVALENT_BRANCH,
    }
)


@dataclass(frozen=True)
class UtilizationBranchOptions:
    include_nontransformer_branches: bool = True
    include_two_winding_transformers: bool = False
    include_three_winding_transformers: bool = False
    include_transformer_equivalents: bool = False


DEFAULT_UTILIZATION_BRANCH_OPTIONS = UtilizationBranchOptions()


def selected_utilization_branch_types(
    options: UtilizationBranchOptions | None = None,
) -> set[str]:
    selected = set()
    options = options or DEFAULT_UTILIZATION_BRANCH_OPTIONS
    if options.include_nontransformer_branches:
        selected.add(NONTRANSFORMER_BRANCH)
    if options.include_two_winding_transformers:
        selected.add(TWO_WINDING_TRANSFORMER_BRANCH)
    if options.include_three_winding_transformers:
        selected.add(THREE_WINDING_TRANSFORMER_BRANCH)
    if options.include_transformer_equivalents:
        selected.add(TRANSFORMER_EQUIVALENT_BRANCH)
    return selected


def is_utilizable_branch_type(
    branch_type: object,
    options: UtilizationBranchOptions | None = None,
) -> bool:
    return str(branch_type or "").strip() in selected_utilization_branch_types(options)


def is_utilizable_branch(
    row: Mapping[str, object] | None,
    options: UtilizationBranchOptions | None = None,
) -> bool:
    if not row:
        return False
    return is_utilizable_branch_type(row.get("raw_branch_type") or NONTRANSFORMER_BRANCH, options)


def is_transformer_branch_type(branch_type: object) -> bool:
    return str(branch_type or "").strip() in TRANSFORMER_BRANCH_TYPES


__all__ = [
    "DEFAULT_UTILIZATION_BRANCH_OPTIONS",
    "NONTRANSFORMER_BRANCH",
    "THREE_WINDING_TRANSFORMER_BRANCH",
    "TRANSFORMER_BRANCH_TYPES",
    "TRANSFORMER_EQUIVALENT_BRANCH",
    "TWO_WINDING_TRANSFORMER_BRANCH",
    "UtilizationBranchOptions",
    "is_transformer_branch_type",
    "is_utilizable_branch",
    "is_utilizable_branch_type",
    "selected_utilization_branch_types",
]
