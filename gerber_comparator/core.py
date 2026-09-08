"""Comparison orchestration: parse -> normalized vectors -> XOR -> classification."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
import time
from .geometry import normalize_geometry, resolve_geometry, safe_symmetric_difference, safe_union
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
    @property
    def overall_result(self) -> str:
        if any(r.classification == "UNRESOLVED" for r in self.regions) or self.original.unresolved_apertures or self.working.unresolved_apertures: return "UNRESOLVED"
        if any(r.classification == "FLAG" for r in self.regions): return "FAIL"
        return "PASS WITH WARNINGS" if self.warnings else "PASS"
    def statistics(self):
        return {"total_difference_regions": len(self.regions), "flagged_regions": sum(r.classification == "FLAG" for r in self.regions), "ignored_regions": sum(r.classification == "IGNORE" for r in self.regions), "unresolved_regions": sum(r.classification == "UNRESOLVED" for r in self.regions), "total_xor_area_mm2": self.raw_xor.area, "flagged_xor_area_mm2": self.flagged_xor.area}

def _parts(geometry): return list(geometry.geoms) if geometry.geom_type.startswith("Multi") or geometry.geom_type == "GeometryCollection" else ([geometry] if not geometry.is_empty else [])
def _local_deviation(region, original, working, margin):
    """Measure only the board neighbourhood represented by this XOR component."""
    from shapely.geometry import box
    min_x, min_y, max_x, max_y = region.bounds
    neighbourhood = box(min_x-margin, min_y-margin, max_x+margin, max_y+margin)
    local_original = original.intersection(neighbourhood)
    local_working = working.intersection(neighbourhood)
    if local_original.is_empty or local_working.is_empty: return float("inf")
    return local_original.boundary.hausdorff_distance(local_working.boundary)
def compare_gerbers(original: str | Path, working: str | Path, config: ComparisonConfig | None = None) -> ComparisonResult:
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
    raw_xor = safe_symmetric_difference(original_geometry, aligned_working, warnings=repair_warnings); xor_time = time.perf_counter()
    regions = []; flagged = []
    topology_changed = len(_parts(original_geometry)) != len(_parts(aligned_working))
    for index, part in enumerate(_parts(raw_xor), 1):
        deviation = _local_deviation(part, original_geometry, aligned_working, max(config.geometric_tolerance_mm * 3, config.snapshot_margin_mm))
        translation = (dx*dx + dy*dy) ** .5
        if topology_changed and config.topology_check: classification, reason = "FLAG", "TOPOLOGY_CHANGE"
        elif deviation > config.geometric_tolerance_mm: classification, reason = "FLAG", "GEOMETRY_CHANGE"
        elif translation > config.translation_tolerance_mm: classification, reason = "FLAG", "TRANSLATION"
        else: classification, reason = "IGNORE", "BELOW_TOLERANCE"
        if classification == "FLAG": flagged.append(part)
        b = part.bounds; c = part.centroid
        regions.append(DifferenceRegion(f"F-{index:03d}", part, part.area, part.length, b, (c.x,c.y), deviation, translation, topology_changed, classification, reason))
    flagged_xor = safe_union(flagged, label="Flagged XOR geometry", warnings=repair_warnings)
    diagnostics = {"original_geometry_valid_before": getattr(original_layer, "geometry_valid_before", True), "original_geometry_valid_after": original_geometry.is_valid, "working_geometry_valid_before": getattr(working_layer, "geometry_valid_before", True), "working_geometry_valid_after": aligned_working.is_valid, "original_geometry_type": original_geometry.geom_type, "working_geometry_type": aligned_working.geom_type, "geometry_repair_applied": any("repair" in warning.lower() for warning in repair_warnings)}
    result = ComparisonResult(original_layer, working_layer, config, original_geometry, aligned_working, raw_xor, flagged_xor, regions, {"translation_x_mm": dx, "translation_y_mm": dy, "rotation_deg": rotation, "method": "centroid" if config.auto_alignment else "manual"}, repair_warnings, {"parse_seconds": parsed-started, "geometry_seconds": geometry_time-parsed, "xor_and_analysis_seconds": time.perf_counter()-xor_time, "total_seconds": time.perf_counter()-started}, diagnostics)
    return result
