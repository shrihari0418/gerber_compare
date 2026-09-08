"""Physical-geometry resolution and controlled GEOS validity recovery."""
from __future__ import annotations
from math import cos, pi, sin
from typing import Iterable
from .model import Aperture, ParsedLayer

class GeometryError(RuntimeError):
    """A vector geometry could not be safely made valid for comparison."""

def _shapely():
    try:
        from shapely.geometry import LineString, Point, Polygon
        from shapely.ops import unary_union
        return LineString, Point, Polygon, unary_union
    except ImportError as exc:
        raise RuntimeError("Geometry support requires Shapely. Install project dependencies before comparing.") from exc

def _make_valid(geometry):
    """Use the strongest available Shapely repair API, with a documented fallback."""
    try:
        from shapely import make_valid
        return make_valid(geometry), "make_valid"
    except ImportError:
        try:
            from shapely.validation import make_valid
            return make_valid(geometry), "make_valid"
        except ImportError:
            # GEOS buffer(0) is only a compatibility fallback for old Shapely.
            return geometry.buffer(0), "buffer(0) compatibility fallback"

def _polygonal_components(geometry):
    """Retain every polygonal component; lines/points have no copper area."""
    if geometry.is_empty: return []
    if geometry.geom_type == "Polygon": return [geometry]
    if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
        parts = []
        for member in geometry.geoms: parts.extend(_polygonal_components(member))
        return parts
    return []


def _has_non_polygonal_components(geometry):
    """Whether a geometry has line/point content besides any polygonal copper."""
    if geometry.is_empty or geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return False
    if geometry.geom_type == "GeometryCollection":
        return any(_has_non_polygonal_components(member) for member in geometry.geoms)
    return True


def _raw_polygonal_union(polygons, *, label: str):
    """Union known polygonal members without invoking the public recovery API."""
    _, _, _, unary_union = _shapely()
    try:
        return unary_union(polygons)
    except Exception as exc:
        raise GeometryError(f"{label} polygonal components could not be unioned safely.") from exc


def _polygonal_geometry(geometry, *, label: str, warnings: list[str] | None = None):
    """Build a valid polygonal representation with bounded recovery stages.

    This low-level function intentionally never calls :func:`safe_union` or
    :func:`normalize_geometry`; that separation prevents recursive recovery
    loops.  It retains every polygonal component of a ``make_valid`` result.
    """
    _, _, Polygon, _ = _shapely()
    polygons = _polygonal_components(geometry)
    if not polygons:
        # A validity repair can turn a zero-width or otherwise degenerate
        # primitive into a line or point.  It carries no copper area, so it is
        # represented explicitly as empty rather than failing the whole layer.
        if warnings is not None and not geometry.is_empty:
            warnings.append(
                f"{label} produced no polygonal copper; non-area result treated as zero-area geometry."
            )
        return Polygon()
    result = _raw_polygonal_union(polygons, label=label)
    if _has_non_polygonal_components(geometry) and warnings is not None:
        warnings.append(
            f"{label} produced non-polygonal components; polygonal copper components were retained."
        )
    if result.is_valid:
        return result

    # A first make_valid can produce polygonal components whose reconstructed
    # union is still invalid due to precision artifacts. Repair that actual
    # failed union before considering precision normalization.
    repaired, method = _make_valid(result)
    repaired_polygons = _polygonal_components(repaired)
    if repaired_polygons:
        recovered = _raw_polygonal_union(repaired_polygons, label=f"{label} second repair")
        if recovered.is_valid:
            if warnings is not None:
                warnings.append(f"{label} polygonal reconstruction required a second {method} repair.")
            return recovered
    else:
        # A non-empty polygonal input must not become empty silently during a
        # recovery stage. This is irrecoverable rather than a zero-area input.
        raise GeometryError(f"{label} lost all polygonal copper during {method} reconstruction repair.")

    # Last resort: apply the documented 1 nm grid to the invalid union itself,
    # then repeat make_valid and polygonal reconstruction once.
    precision_result = _precision_normalize(result, label=f"{label} polygonal reconstruction")
    precision_repaired, precision_method = _make_valid(precision_result)
    precision_polygons = _polygonal_components(precision_repaired)
    if precision_polygons:
        recovered = _raw_polygonal_union(
            precision_polygons, label=f"{label} precision reconstruction"
        )
        if recovered.is_valid:
            if warnings is not None:
                warnings.append(
                    f"{label} polygonal reconstruction required 0.000001 mm precision normalization and {precision_method} repair."
                )
            return recovered
    raise GeometryError(
        f"{label} remains invalid after polygonal reconstruction, repair, and controlled precision recovery."
    )


def _precision_normalize(geometry, *, label: str):
    """Apply the last-resort 1 nm precision grid used for GEOS recovery only."""
    try:
        from shapely import set_precision
    except ImportError as exc:
        raise GeometryError(
            f"{label} needs precision recovery, but this Shapely version has no set_precision support."
        ) from exc
    try:
        # Coordinates are normalized to millimetres.  One nanometre is far
        # below the supported manufacturing tolerances and is never a normal
        # comparison path.
        return set_precision(geometry, 0.000001)
    except Exception as exc:
        raise GeometryError(f"{label} precision normalization failed.") from exc

def normalize_geometry(geometry, *, label: str = "Geometry", warnings: list[str] | None = None):
    """Return valid polygonal geometry or raise a descriptive ``GeometryError``.

    No simplification, scaling, or area threshold is applied. GeometryCollection
    repairs are flattened only to their polygonal copper components.
    """
    _, _, Polygon, _ = _shapely()
    if geometry is None or geometry.is_empty: return Polygon()
    valid_before = geometry.is_valid
    if valid_before and geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return geometry
    if valid_before:
        # The comparison model is copper-area based.  Valid collections and
        # line/point-only inputs use the same explicit polygonal projection as
        # repair results so degenerate primitives cannot poison a union.
        normalized = _polygonal_geometry(geometry, label=label, warnings=warnings)
        if not normalized.is_valid:
            raise GeometryError(f"{label} polygonal normalization produced invalid geometry.")
        return normalized
    # A zero-area polygon can legitimately repair to a line or point.  Keep
    # that case non-fatal, but never silently erase an input that carried
    # polygonal area before repair.
    source_has_area = bool(_polygonal_components(geometry)) and geometry.area > 0
    repaired, method = _make_valid(geometry)
    normalized = _polygonal_geometry(repaired, label=f"{label} repair", warnings=warnings)
    if not normalized.is_valid:
        raise GeometryError(f"{label} remains invalid after {method} repair.")
    if normalized.is_empty and source_has_area:
        raise GeometryError(f"{label} lost polygonal copper during {method} repair.")
    if warnings is not None:
        warnings.append(f"{label} was invalid and required GEOS {method} repair.")
    return normalized

def safe_union(geometries: Iterable, *, label: str = "Geometry", warnings: list[str] | None = None):
    """Union vector copper safely, retrying normalized inputs after a GEOS error."""
    _, _, Polygon, unary_union = _shapely()
    inputs = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not inputs: return Polygon()

    # Validate every primitive before asking GEOS to overlay them.  In
    # particular, this keeps a single bow-tie region from poisoning the union.
    normalized_inputs = [
        normalize_geometry(item, label=f"{label} primitive {index}", warnings=warnings)
        for index, item in enumerate(inputs, 1)
    ]
    normalized_inputs = [item for item in normalized_inputs if not item.is_empty]
    if not normalized_inputs:
        return Polygon()
    try:
        return normalize_geometry(unary_union(normalized_inputs), label=label, warnings=warnings)
    except Exception:
        # A second pass is intentional: GEOS can still reject two individually
        # valid polygons with nearly coincident boundaries.
        repaired = [normalize_geometry(item, label=f"{label} primitive {index}", warnings=warnings) for index, item in enumerate(normalized_inputs, 1)]
        try:
            result = normalize_geometry(unary_union(repaired), label=label, warnings=warnings)
        except Exception:
            # The precision grid is deliberately a final fallback.  It is not
            # used to change normal Gerber construction semantics.
            precision_inputs = [
                _precision_normalize(item, label=f"{label} primitive {index}")
                for index, item in enumerate(repaired, 1)
            ]
            try:
                result = normalize_geometry(
                    unary_union(precision_inputs), label=label, warnings=warnings
                )
            except Exception as exc:
                raise GeometryError(
                    f"{label} union failed after individual repair and controlled precision normalization."
                ) from exc
            if warnings is not None:
                warnings.append(
                    f"{label} union required 0.000001 mm precision normalization after a GEOS topology exception."
                )
        if warnings is not None:
            warnings.append(f"{label} union required retry after a GEOS topology failure.")
        return result

def safe_symmetric_difference(original, working, *, warnings: list[str] | None = None):
    """Calculate complete vector XOR after validation, with precision retry only on GEOS failure."""
    original = normalize_geometry(original, label="Original geometry", warnings=warnings)
    working = normalize_geometry(working, label="Working geometry", warnings=warnings)
    try:
        return normalize_geometry(original.symmetric_difference(working), label="Raw XOR geometry", warnings=warnings)
    except Exception:
        # Retry explicitly after a second normalization pass before changing
        # precision.  This accommodates GEOS overlay failures whose first
        # operation leaves a repairable representation behind.
        original = normalize_geometry(original, label="Original geometry", warnings=warnings)
        working = normalize_geometry(working, label="Working geometry", warnings=warnings)
        try:
            return normalize_geometry(
                original.symmetric_difference(working), label="Raw XOR geometry", warnings=warnings
            )
        except Exception:
            pass
        precision_original = _precision_normalize(original, label="Original geometry")
        precision_working = _precision_normalize(working, label="Working geometry")
        try:
            xor = precision_original.symmetric_difference(precision_working)
            result = normalize_geometry(xor, label="Raw XOR geometry", warnings=warnings)
        except Exception as exc:
            raise GeometryError("Raw XOR failed after repair and controlled precision normalization.") from exc
        if warnings is not None:
            warnings.append("XOR required 0.000001 mm precision normalization after a GEOS topology exception.")
        return result

def aperture_shape(aperture: Aperture):
    LineString, Point, Polygon, _ = _shapely()
    if aperture.geometry_type == "circle": return Point(0, 0).buffer(aperture.parameters[0] / 2)
    if aperture.geometry_type == "rectangle":
        w, h = aperture.parameters[:2]; return Polygon([(-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)])
    if aperture.geometry_type == "oblong":
        w, h = aperture.parameters[:2]
        if w >= h: return LineString([(-((w-h)/2),0),((w-h)/2,0)]).buffer(h/2)
        return LineString([(0,-((h-w)/2)),(0,((h-w)/2))]).buffer(w/2)
    if aperture.geometry_type == "polygon":
        diameter, vertices = aperture.parameters[:2]; r = diameter / 2
        return Polygon([(r*cos(2*pi*i/int(vertices)), r*sin(2*pi*i/int(vertices))) for i in range(int(vertices))])
    raise ValueError(f"No geometry provider available for aperture {aperture.number} ({aperture.name})")

def resolve_geometry(layer: ParsedLayer):
    """Resolve primitives then validate/repair their final normalized-mm union."""
    LineString, _, Polygon, _ = _shapely(); dark = []
    for primitive in layer.primitives:
        kind = primitive[0]
        if kind == "region": dark.append(Polygon(primitive[1])); continue
        aperture = layer.apertures.get(primitive[1])
        if aperture is None:
            layer.warnings.append(f"Primitive uses undefined aperture D{primitive[1]}"); continue
        if aperture.geometry_type is None:
            if aperture not in layer.unresolved_apertures: layer.unresolved_apertures.append(aperture)
            continue
        shape = aperture_shape(aperture)
        if kind == "flash":
            from shapely import affinity
            dark.append(affinity.translate(shape, primitive[2], primitive[3]))
        else: dark.append(LineString([(primitive[2], primitive[3]), (primitive[4], primitive[5])]).buffer(aperture.parameters[0]/2))
    layer.geometry_valid_before = all(geometry.is_valid for geometry in dark)
    result = safe_union(dark, label=f"{layer.filename} geometry", warnings=layer.warnings)
    layer.geometry_valid_after = result.is_valid
    layer.geometry_type = result.geom_type
    return result
