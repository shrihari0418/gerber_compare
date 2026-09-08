import math

import pytest

pytest.importorskip("shapely")
from shapely.geometry import Polygon

from gerber_comparator import core
from gerber_comparator.core import _local_deviation, compare_gerbers
from gerber_comparator.model import ComparisonConfig


def gerber(aperture="R,2X2", flashes=((1, 1),)):
    commands = ["%MOMM*%", "%FSLAX24Y24*%"]
    if aperture:
        commands.extend([f"%ADD10{aperture}*%", "D10*"])
    commands.extend(f"X{round(x * 10000):06d}Y{round(y * 10000):06d}D03*" for x, y in flashes)
    return "".join(commands) + "M02*"


def compare(original, working, tolerance=.05, *, auto_alignment=False):
    return compare_gerbers(
        original,
        working,
        ComparisonConfig(
            geometric_tolerance_mm=tolerance,
            auto_alignment=auto_alignment,
            snapshot_generation=False,
        ),
    )


def test_local_deviation_uses_boundary_distance_for_polygons():
    square = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    assert _local_deviation(square, square, square, 1) == pytest.approx(0)


def test_local_deviation_is_nonzero_for_translated_polygons_and_infinite_when_local_is_empty():
    square = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    shifted = Polygon([(1, 0), (3, 0), (3, 2), (1, 2)])
    assert _local_deviation(square, square, shifted, 1) > 0
    far_region = Polygon([(20, 20), (21, 20), (21, 21), (20, 21)])
    assert math.isinf(_local_deviation(far_region, square, square, 0))


def test_local_deviation_falls_back_when_boundary_is_unavailable(monkeypatch):
    class LocalGeometry:
        is_empty = False
        boundary = None

        def hausdorff_distance(self, other):
            assert other is working
            return 1.25

    original = LocalGeometry()
    working = LocalGeometry()

    class Geometry:
        def intersection(self, _neighbourhood):
            return original if self is source_original else working

    class Region:
        bounds = (0, 0, 1, 1)

    source_original, source_working = Geometry(), Geometry()
    monkeypatch.setattr(core, "normalize_geometry", lambda geometry, **_kwargs: geometry)
    assert _local_deviation(Region(), source_original, source_working, 1) == pytest.approx(1.25)


def test_complete_removal_is_missing_from_working():
    result = compare(gerber(), gerber(aperture=None, flashes=()))
    assert result.missing_geometry.area == pytest.approx(4)
    assert result.added_geometry.is_empty
    assert {region.classification for region in result.regions} == {"MISSING_FROM_WORKING"}
    assert result.statistics()["missing_from_working"] == 1


def test_complete_addition_is_added_in_working():
    result = compare(gerber(aperture=None, flashes=()), gerber())
    assert result.missing_geometry.is_empty
    assert result.added_geometry.area == pytest.approx(4)
    assert {region.classification for region in result.regions} == {"ADDED_IN_WORKING"}
    assert result.statistics()["added_in_working"] == 1


def test_partial_removal_only_reports_removed_copper():
    result = compare(gerber("R,10X2"), gerber("R,6X2"))
    assert result.missing_geometry.area == pytest.approx(8)
    assert result.added_geometry.is_empty
    assert {region.classification for region in result.regions} == {"MISSING_FROM_WORKING"}


def test_partial_addition_only_reports_added_copper():
    result = compare(gerber("R,6X2"), gerber("R,10X2"))
    assert result.missing_geometry.is_empty
    assert result.added_geometry.area == pytest.approx(8)
    assert {region.classification for region in result.regions} == {"ADDED_IN_WORKING"}


def test_small_translation_residual_is_ignored_not_directional():
    result = compare(gerber(flashes=((1, 1),)), gerber(flashes=((1.02, 1),)))
    assert {region.classification for region in result.regions} == {"IGNORE"}


def test_topology_reason_is_preserved_for_directional_addition():
    result = compare(gerber(), gerber(flashes=((1, 1), (5, 1))))
    assert {region.classification for region in result.regions} == {"ADDED_IN_WORKING"}
    assert {region.classification_reason for region in result.regions} == {"TOPOLOGY_CHANGE"}
