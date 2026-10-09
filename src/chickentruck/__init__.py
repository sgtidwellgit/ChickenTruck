"""ChickenTruck -- Knowledge Engineering for Python.

Turning information into structured, validated, traceable knowledge, one
nugget at a time:

    Nugget -> ChickenTender -> ChickenCoop.resolve_tender -> grill -> ChickenStock

See README.md for a walkthrough and PROJECT.md for design decisions.
"""

from chickentruck._sqlite import SqliteStock
from chickentruck._temporal import TimePoint, parse_time
from chickentruck.coop import ChickenCoop, Entity, Mention, Ref, Resolution, Resolver
from chickentruck.grilled import (
    ACCEPTED,
    NEEDS_REVIEW,
    REJECTED,
    Fact,
    Finding,
    GrillResult,
    grill,
)
from chickentruck.nuggets import Nugget, extract_nuggets
from chickentruck.platter import Graph, to_graph, to_ntriples, to_tables
from chickentruck.recipe import EntityType, Predicate, Schema
from chickentruck.soup import (
    CONTRADICTED,
    DISPUTED,
    SUPPORTED,
    UNKNOWN,
    ClaimCheck,
    check_claim,
    render_facts,
)
from chickentruck.stock import (
    ChickenStock,
    Conflict,
    StockBackend,
    highest_authority,
    highest_confidence,
    keep_both,
    most_recent_evidence,
)
from chickentruck.tenders import ChickenTender, Evidence, Source, noisy_or

__version__ = "2026.10.9"

__all__ = [
    "Nugget",
    "extract_nuggets",
    "ChickenTender",
    "Source",
    "Evidence",
    "noisy_or",
    "TimePoint",
    "parse_time",
    "Entity",
    "Ref",
    "Mention",
    "Resolution",
    "Resolver",
    "ChickenCoop",
    "EntityType",
    "Predicate",
    "Schema",
    "Finding",
    "Fact",
    "GrillResult",
    "grill",
    "ACCEPTED",
    "REJECTED",
    "NEEDS_REVIEW",
    "ChickenStock",
    "SqliteStock",
    "StockBackend",
    "Conflict",
    "keep_both",
    "highest_confidence",
    "highest_authority",
    "most_recent_evidence",
    "Graph",
    "to_graph",
    "to_tables",
    "to_ntriples",
    "render_facts",
    "check_claim",
    "ClaimCheck",
    "SUPPORTED",
    "CONTRADICTED",
    "DISPUTED",
    "UNKNOWN",
]
