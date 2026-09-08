"""Comparison orchestration: parse -> normalized vectors -> XOR -> classification."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from math import hypot
from pathlib import Path
import time
from .geometry import normalize_geometry, resolve_geometry, safe_union
from .model import ComparisonConfig, DifferenceRegion, ParsedLayer
from .parser import parse_gerber

@dataclass
class ComparisonResult:
    original: ParsedLayer
    working: ParsedLayer
    config: ComparisonConfig
    original_geometry: object
    working_geometry: object
    raw_xor: object
    flagged_xor: object
    regions: list[DifferenceRegion]
    alignment: dict
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    geometry_diagnostics: dict = field(default_factory=dict)
    missing_geometry: object | None = None
    added_geometry: object | None = None
    incomplete: bool = False
    @property
    def overall_result(self) -> str:
        if self.incomplete: return "COMPARISON_INCOMPLETE"
        if any(r.classification == "UNRESOLVED" for r in self.regions) or self.original.unresolved_apertures or self.working.unresolved_apertures: return "UNRESOLVED"
        if any(r.classification not in {"IGNORE", "UNRESOLVED"} for r in self.regions): return "FAIL"
        return "PASS WITH WARNINGS" if self.warnings else "PASS"
    def statistics(self):
        return {"total_difference_regions": len(self.regions), "flagged_regions": sum(r.classification not in {"IGNORE", "UNRESOLVED"} for r in self.regions), "ignored_regions": sum(r.classification == "IGNORE" for r in self.regions), "unresolved_regions": sum(r.classification == "UNRESOLVED" for r in self.regions), "missing_from_working": sum(r.classification == "MISSING_FROM_WORKING" for r in self.regions), "added_in_working": sum(r.classification == "ADDED_IN_WORKING" for r in self.regions), "topology_regions": sum(r.classification_reason == "TOPOLOGY_CHANGE" for r in self.regions), "geometry_change_regions": sum(r.classification_reason == "GEOMETRY_CHANGE" for r in self.regions), "translation_regions": sum(r.classification_reason == "TRANSLATION" for r in self.regions), "total_xor_area_mm2": self.raw_xor.area, "flagged_xor_area_mm2": self.flagged_xor.area}

def _parts(geometry): return list(geometry.geoms) if geometry.geom_type.startswith("Multi") or geometry.geom_type == "GeometryCollection" else ([geometry] if not geometry.is_empty else [])
def _local_deviation(region, original, working, margin):
    """Measure only the board neighbourhood represented by this XOR component."""
    from shapely.geometry import box
    min_x, min_y, max_x, max_y = region.bounds
    neighbourhood = box(min_x-margin, min_y-margin, max_x+margin, max_y+margin)
    local_original = normalize_geometry(original.intersection(neighbourhood), label="Local original geometry")
    local_working = normalize_geometry(working.intersection(neighbourhood), label="Local working geometry")
    if local_original.is_empty or local_working.is_empty: return float("inf")
    original_boundary = local_original.boundary
    working_boundary = local_working.boundary
    if (original_boundary is not None and working_boundary is not None
            and not original_boundary.is_empty and not working_boundary.is_empty):
        return original_boundary.hausdorff_distance(working_boundary)
    return local_original.hausdorff_distance(local_working)


def compare_gerbers(original: str | Path, working: str | Path, config: ComparisonConfig | None = None, *, progress_callback=None) -> ComparisonResult:
    from shapely import affinity
    config = config or ComparisonConfig(); started = time.perf_counter()
    original_layer, working_layer = parse_gerber(original), parse_gerber(working); parsed = time.perf_counter()
    original_geometry, working_geometry = resolve_geometry(original_layer), resolve_geometry(working_layer); geometry_time = time.perf_counter()
    repair_warnings = original_layer.warnings + working_layer.warnings
    # ``resolve_geometry`` already uses safe_union, but normalize here as the
    # authoritative comparison boundary as well.  This keeps future geometry
    # providers from bypassing the vector-validity contract before alignment
    # and raw XOR are performed.
    original_geometry = normalize_geometry(
        original_geometry, label="Original geometry", warnings=repair_warnings
    )
    working_geometry = normalize_geometry(
        working_geometry, label="Working geometry", warnings=repair_warnings
    )
    dx, dy, rotation = config.dx_mm, config.dy_mm, config.rotation_deg
    if config.auto_alignment and not original_geometry.is_empty and not working_geometry.is_empty:
        oc, wc = original_geometry.centroid, working_geometry.centroid; dx += oc.x - wc.x; dy += oc.y - wc.y
    aligned_working = affinity.rotate(affinity.translate(working_geometry, dx, dy), rotation, origin="centroid")
    aligned_working = normalize_geometry(aligned_working, label="Aligned Working geometry", warnings=repair_warnings)
    from .performance.tiled_compare import compare_tiled
    candidates, raw_xor, missing_geometry, added_geometry, performance = compare_tiled(original_geometry, aligned_working, config, repair_warnings, progress=progress_callback)
    regions = []
    for index, candidate in enumerate(candidates, 1):
        centroid = candidate.geometry.centroid
        min_x, min_y, max_x, max_y = candidate.bounds
        thin_residual = min(max_x - min_x, max_y - min_y) <= config.geometric_tolerance_mm
        classification = "IGNORE" if thin_residual else candidate.classification
        reason = "BELOW_TOLERANCE" if thin_residual else candidate.reason
        regions.append(DifferenceRegion(f"F-{index:03d}", candidate.geometry, candidate.geometry.area, candidate.geometry.length, candidate.bounds, (centroid.x, centroid.y), float("inf"), hypot(candidate.dx, candidate.dy), candidate.topology_changed, classification, reason, direction=candidate.direction, dx_mm=candidate.dx, dy_mm=candidate.dy, displacement_mm=hypot(candidate.dx, candidate.dy), confidence=candidate.confidence))
    flagged_xor = safe_union([region.geometry for region in regions], label="Flagged candidate geometry", warnings=repair_warnings)
    diagnostics = {"original_geometry_valid_before": getattr(original_layer, "geometry_valid_before", True), "original_geometry_valid_after": original_geometry.is_valid, "working_geometry_valid_before": getattr(working_layer, "geometry_valid_before", True), "working_geometry_valid_after": aligned_working.is_valid, "geometry_repair_applied": any("repair" in warning.lower() for warning in repair_warnings), **performance}
    result = ComparisonResult(original_layer, working_layer, config, original_geometry, aligned_working, raw_xor, flagged_xor, regions, {"translation_x_mm": dx, "translation_y_mm": dy, "rotation_deg": rotation, "method": "centroid" if config.auto_alignment else "manual"}, repair_warnings, {"parse_seconds": parsed-started, "geometry_seconds": geometry_time-parsed, **performance, "total_seconds": time.perf_counter()-started}, diagnostics, missing_geometry, added_geometry, performance["candidate_limit_exceeded"] or performance["verification_limit_exceeded"])
    return result
