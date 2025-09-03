"""
Dataclasses for keyword extraction.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List

@dataclass
class SubDoc:
    community_id: str
    name: str
    url: str
    rank: int | None
    subscribers_count: int | None
    desc_text: str
    name_terms: List[str]