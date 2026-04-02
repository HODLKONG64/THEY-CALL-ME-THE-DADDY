from typing import Any, List
from .models import PatchAction

def _value_score_bonus(patch: PatchAction, tracked_files: List[str]) -> float:
    """Internal scoring for a single patch."""
    score = 0.0
    path = getattr(patch, "path", "") or ""
    # reward runtime/observability improvements
    if any(k in path.lower() for k in ("trace", "logging", "observability")):
        score += 1.5
    # penalize redundant or banned paths
    if path in {"src/the_***/runtime/command_runner.py"}:
        score -= 1.0
    return score

def rank_patch_set(patches: List[PatchAction], tracked_files: List[str]) -> float:
    """
    Compute a score for a patch set.

    :param patches: List of PatchAction objects
    :param tracked_files: List of tracked repo files
    :return: float score
    """
    total_score = 0.0
    for patch in patches:
        total_score += _value_score_bonus(patch, tracked_files)
    return total_score
