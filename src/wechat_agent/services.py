"""Explicit runtime dependencies; no global source or model client."""

from dataclasses import dataclass
from contextlib import AbstractAsyncContextManager
from typing import Callable

from .source.contracts import SourceAdapter


@dataclass(slots=True)
class Services:
    source: SourceAdapter | None = None
    source_factory: Callable[[str], AbstractAsyncContextManager] | None = None
    auto_run: bool = True
    credential_store: object | None = None
    model_transport: object | None = None
    model: object | None = None

    discovery_factory: Callable | None = None
    analysis_factory: Callable | None = None
