"""Data models intentionally independent of UI and Gerber syntax."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass(frozen=True)
class Aperture:
    number: int
    name: str
    parameters: tuple[float, ...]
    raw_definition: str
    geometry_type: str | None = None
    resolver: str | None = None
    macro_name: str | None = None

@dataclass
class ParsedLayer:
    filename: str
    units: str = "mm"
    coordinate_format: str | None = None
    apertures: dict[int, Aperture] = field(default_factory=dict)
    macros: dict[str, str] = field(default_factory=dict)
    primitives: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unresolved_apertures: list[Aperture] = field(default_factory=list)

@dataclass(frozen=True)
class ComparisonConfig:
    geometric_tolerance_mm: float = 0.05
    translation_tolerance_mm: float = 0.10
    topology_check: bool = True
    auto_alignment: bool = True
    dx_mm: float = 0.0
    dy_mm: float = 0.0
    rotation_deg: float = 0.0
    snapshot_generation: bool = True
    snapshot_dpi: int = 200
    snapshot_margin_mm: float = 1.0
    generate_html_report: bool = True
    tile_tolerance_factor: float = 50.0
    minimum_tile_size: float = 1.0
    maximum_tile_size: float = 10.0
    tile_margin_factor: float = 2.0
    minimum_difference_area: float = 0.0
    max_candidate_regions: int = 10000

@dataclass
class DifferenceRegion:
    region_id: str
    geometry: Any
    area_mm2: float
    perimeter_mm: float
    bbox: tuple[float, float, float, float]
    centroid: tuple[float, float]
    geometric_deviation_mm: float
    translation_mm: float
    topology_changed: bool
    classification: str
    classification_reason: str
    snapshot: str | None = None
    direction: str | None = None
    dx_mm: float = 0.0
    dy_mm: float = 0.0
    displacement_mm: float = 0.0
    confidence: float = 1.0
    def as_dict(self) -> dict[str, Any]:
        data = asdict(self); data.pop("geometry", None)
        data["bbox"] = dict(zip(("min_x", "min_y", "max_x", "max_y"), self.bbox))
        return data
