"""Registry of static metric detectors.

The NCC visitor hardcodes restriction ids inside ``visit_*`` methods, so the
catalog's ``ast`` label and the code that implements it are coupled by
convention only. Here the catalog's ``Metric.static`` is the registry key and
the dispatcher looks the detector up by it, which is what lets the test suite
prove that every metric has an implementation.
"""

from __future__ import annotations

from collections.abc import Callable

from ..models import MetricDetection
from .context import FunctionContext

__all__ = ["DETECTORS", "Detector", "detector", "get_detector"]

#: A detector always answers. Returning NOT_APPLICABLE when the construct it
#: asks about is absent is part of the contract, because the LLM judge is held
#: to the same requirement and the two answers have to be comparable.
Detector = Callable[[FunctionContext], MetricDetection]

DETECTORS: dict[str, Detector] = {}


def detector(key: str) -> Callable[[Detector], Detector]:
    """Register a detector under a catalog key.

    Parameters:
        - key: The value of Metric.static for the metric implemented.

    Returns:
        - A decorator that records the function and returns it unchanged.

    Raises:
        - ValueError: When the key is already registered.
    """

    def register(function: Detector) -> Detector:
        if key in DETECTORS:
            raise ValueError(f"duplicate metric detector: {key}")
        DETECTORS[key] = function
        return function

    return register


def get_detector(key: str) -> Detector:
    """Return the detector registered under a key.

    Parameters:
        - key: The value of Metric.static.

    Returns:
        - The registered callable.

    Raises:
        - KeyError: When no detector is registered under that key.
    """
    return DETECTORS[key]
