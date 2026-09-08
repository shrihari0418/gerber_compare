import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, Polygon
from gerber_comparator import geometry as geometry_module
from gerber_comparator.geometry import normalize_geometry, safe_symmetric_difference, safe_union

def test_invalid_polygon_is_repaired_to_valid_polygonal_geometry():
    bow_tie = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
    repaired = normalize_geometry(bow_tie)
    assert repaired.is_valid
    assert repaired.area > 0

def test_touching_polygons_and_overlapping_strokes_union_safely():
    touching = safe_union([Polygon([(0,0),(1,0),(1,1),(0,1)]), Polygon([(1,0),(2,0),(2,1),(1,1)])])
    strokes = safe_union([LineString([(0,0),(2,0)]).buffer(.25), LineString([(1,0),(3,0)]).buffer(.25)])
    assert touching.is_valid and touching.area == pytest.approx(2)
    assert strokes.is_valid and strokes.area > 0

def test_invalid_geometries_produce_valid_vector_xor():
    original = Polygon([(0,0),(2,2),(0,2),(2,0),(0,0)])
    working = Polygon([(0,0),(3,3),(0,3),(3,0),(0,0)])
    xor = safe_symmetric_difference(original, working)
    assert xor.is_valid
    assert xor.area > 0


def test_polygonal_members_of_a_geometry_collection_are_retained():
    warnings = []
    geometry = GeometryCollection([
        Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
        LineString([(0, 0), (2, 2)]),
    ])

    normalized = normalize_geometry(geometry, label="mixed repair", warnings=warnings)

    assert normalized.is_valid
    assert normalized.area == pytest.approx(4)
    assert any("polygonal copper components were retained" in warning for warning in warnings)


@pytest.mark.parametrize("geometry", [
    GeometryCollection([LineString([(0, 0), (1, 1)])]),
    GeometryCollection([Point(1, 1)]),
    MultiLineString([[(0, 0), (1, 1)], [(1, 1), (2, 1)]]),
])
def test_non_area_geometry_is_explicitly_normalized_to_empty_polygon(geometry):
    warnings = []

    normalized = normalize_geometry(geometry, label="primitive 509 repair", warnings=warnings)

    assert normalized.is_empty
    assert normalized.geom_type == "Polygon"
    assert any("primitive 509 repair" in warning for warning in warnings)
    assert any("zero-area geometry" in warning for warning in warnings)


def test_invalid_polygonal_reconstruction_gets_a_second_repair_stage(monkeypatch):
    invalid_union = Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
    recovered_union = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    results = iter([invalid_union, recovered_union])
    monkeypatch.setattr(
        geometry_module, "_raw_polygonal_union", lambda _polygons, **_kwargs: next(results)
    )
    warnings = []

    normalized = geometry_module._polygonal_geometry(
        recovered_union, label="reconstruction", warnings=warnings
    )

    assert normalized.is_valid
    assert normalized.area == pytest.approx(4)
    assert any("second make_valid repair" in warning for warning in warnings)


def test_nonzero_area_geometry_that_loses_copper_during_repair_raises(monkeypatch):
    invalid_polygon = Polygon(
        [(0, 0), (3, 0), (3, 3), (0, 3)],
        holes=[[(4, 4), (5, 4), (5, 5), (4, 5)]],
    )
    monkeypatch.setattr(
        geometry_module,
        "_make_valid",
        lambda _geometry: (GeometryCollection([LineString([(0, 0), (1, 1)])]), "test repair"),
    )

    with pytest.raises(geometry_module.GeometryError, match="lost polygonal copper"):
        normalize_geometry(invalid_polygon, label="meaningful primitive")
