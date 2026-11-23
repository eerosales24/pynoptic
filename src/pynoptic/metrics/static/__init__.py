"""Static metric detectors.

Importing this package registers every detector, so the dispatcher and the
reconciliation test see a populated registry.
"""

from __future__ import annotations

from . import (
    branches,
    comments,
    conditions,
    containers,
    control_flow,
    data_flow,
    naming,
    operators,
    returns,
    signature,
)
from .context import FunctionContext, build_context
from .registry import DETECTORS, Detector, detector, get_detector

#: Imported for their side effect: importing a module registers its
#: detectors. Naming them here keeps linters from removing the imports.
_MODULES = (
    branches,
    comments,
    conditions,
    containers,
    control_flow,
    data_flow,
    naming,
    operators,
    returns,
    signature,
)

__all__ = [
    "DETECTORS",
    "Detector",
    "FunctionContext",
    "build_context",
    "detector",
    "get_detector",
]
