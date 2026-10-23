"""Simplified performance estimates (Person 2). Every result is a SIMULATED ESTIMATE.
Implementation in backend/circuits/."""
from .circuits.compare import compare_lines, detect_sections  # noqa: F401
from .circuits.performance import (ESTIMATE_LABEL, ILLUSTRATIVE_PARAMETERS,  # noqa: F401
                                   VehicleParameters, estimate_performance)
