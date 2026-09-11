"""ChickenTruck -- Knowledge Engineering for Python.

Turning information into structured, traceable knowledge, one nugget at a
time. This is an early architectural stub: see PROJECT.md for the
design-stage roadmap and README.md for scope and fleet boundaries.
"""

from chickentruck.grilled import GrillResult, grill
from chickentruck.nuggets import Nugget, extract_nuggets
from chickentruck.stock import ChickenStock
from chickentruck.tenders import ChickenTender

__version__ = "0.1.0"

__all__ = [
    "Nugget",
    "extract_nuggets",
    "ChickenTender",
    "GrillResult",
    "grill",
    "ChickenStock",
]
