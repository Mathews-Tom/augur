"""Qualifying source + publication models.

The closed `source_id` literal set is load-bearing: the labeling
protocol in docs/methodology/labeling-protocol.md §Qualifying Sources
requires at least two distinct qualifying sources per event, so the
adapter layer, the workflow enforcer, and the storage schema all key
on the exact same tag set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

SourceId = Literal["reuters", "bloomberg", "ap", "ft"]


class QualifyingSource(BaseModel):
    """One of the four protocol-approved publishers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: SourceId
    name: str


class SourcePublication(BaseModel):
    """A single publication returned by a source adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    publication_id: str
    source_id: SourceId
    timestamp: datetime
    headline: str
    url: HttpUrl
    body_excerpt: str | None = None
    keywords: list[str] = Field(default_factory=list)
