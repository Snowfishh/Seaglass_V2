"""Frozen offline-only Stage 5B evaluation contract settings.

This module is deliberately inert. It holds no campaign rounds, attacker or analyzer model
identifiers, strategy lists, scoring rubrics, stagnation thresholds, ablation arms, state
directories or spend approvals, and it reads no environment variable and no campaign file.
Those are later, separately reviewed concerns.

The production service must never import ``eval.*`` and must never read this file; a
``live_enabled`` field exists only so a reviewed stage can refuse it explicitly. Stage 5B is
offline: the fake-client contract tests exercise this module and make no outbound request.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The only reviewed target contract shape in this stage: ``answer`` and ``citation_ids``.
_CONTRACT_VERSION = "v1"
#: Frozen reasoning tier for offline contract work; not inferred from the 5A signature.
_REASONING_EFFORT = "low"


@dataclass(frozen=True)
class OfflineContractConfig:
    """Immutable Stage 5B eval contract settings; every unreviewed variant fails closed."""

    contract_version: str = _CONTRACT_VERSION
    reasoning_effort: str = _REASONING_EFFORT
    live_enabled: bool = False

    def __post_init__(self):
        if self.contract_version != _CONTRACT_VERSION:
            raise ValueError("Stage 5B only implements the reviewed v1 target contract")
        if self.reasoning_effort != _REASONING_EFFORT:
            raise ValueError("Stage 5B freezes the reviewed reasoning tier")
        if self.live_enabled is not False:
            raise ValueError("Stage 5B is offline only; live dispatch is never enabled here")
