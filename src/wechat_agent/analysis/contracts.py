"""Strategies consume fixed snapshots; they never publish their own candidates."""
from __future__ import annotations
from typing import TYPE_CHECKING, Protocol
from ..profiles.contracts import AnalysisResult
if TYPE_CHECKING:
    from ..context.contracts import ContextSnapshot
    from ..operations.contracts import CancellationToken

class AnalysisStrategy(Protocol):
    async def run(self,snapshot:ContextSnapshot,checkpoint:dict|None,cancellation:CancellationToken)->AnalysisResult: ...
