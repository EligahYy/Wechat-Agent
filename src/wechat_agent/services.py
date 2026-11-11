"""Explicit runtime dependencies; no global source or model client."""

from dataclasses import dataclass

from .source.contracts import SourceAdapter


@dataclass(slots=True)
class Services:
    source: SourceAdapter | None = None
