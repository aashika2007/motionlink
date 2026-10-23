"""MotionInk circuit module (Person 2): real circuit data, racing-line geometry and
simplified performance estimates. Coordinates are circuit metres, y up."""
from .compare import compare_lines, detect_sections, equal_sections
from .editing import clamp_offsets, drag_offsets, drag_to_point, line_from_offsets, offsets_from_path
from .geometry import CurvatureProfile, calculate_curvature, calculate_path_length, resample
from .loader import Circuit, available_circuits, load_circuit
from .performance import ESTIMATE_LABEL, ILLUSTRATIVE_PARAMETERS, VehicleParameters, estimate_performance
from .validation import project_to_centreline, validate_path

__all__ = [
    "Circuit", "available_circuits", "load_circuit",
    "calculate_path_length", "calculate_curvature", "CurvatureProfile", "resample",
    "validate_path", "project_to_centreline",
    "VehicleParameters", "ILLUSTRATIVE_PARAMETERS", "ESTIMATE_LABEL", "estimate_performance",
    "compare_lines", "detect_sections", "equal_sections",
    "line_from_offsets", "offsets_from_path", "clamp_offsets", "drag_offsets", "drag_to_point",
]
