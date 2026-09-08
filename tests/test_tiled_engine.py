import pytest

pytest.importorskip("shapely")
from shapely.geometry import GeometryCollection, box

from gerber_comparator.model import ComparisonConfig
from gerber_comparator.performance.tiled_compare import Candidate, _merge_screening, _pair_translations, compare_tiled, iter_tiles, tile_size


def test_tile_size_is_tolerance_aware_and_tiles_cover_non_square_bounds():
    config = ComparisonConfig(geometric_tolerance_mm=.05, minimum_tile_size=1, maximum_tile_size=3)
    assert tile_size(config) == pytest.approx(2.5)
    tiles = list(iter_tiles((0, 0, 7, 3), tile_size(config)))
    assert len(tiles) == 6
    assert tiles[-1][1].bounds == pytest.approx((5, 2.5, 7, 3))


def test_tiled_comparison_merges_boundary_crossing_missing_geometry():
    config = ComparisonConfig(geometric_tolerance_mm=.05, minimum_tile_size=1, maximum_tile_size=1)
    candidates, raw_xor, missing, added, performance = compare_tiled(box(0, 0, 3, 1), box(0, 0, 1, 1), config, [])
    assert len(candidates) == 1
    assert candidates[0].classification == "MISSING_FROM_WORKING"
    assert missing.area == pytest.approx(2)
    assert added.is_empty
    assert raw_xor.area == pytest.approx(2)
    assert performance["occupied_tile_count"] == 3


def test_tiled_comparison_reports_candidate_limit_without_partial_result():
    config = ComparisonConfig(minimum_tile_size=1, maximum_tile_size=1, max_candidate_regions=1)
    candidates, raw_xor, missing, added, performance = compare_tiled(box(0, 0, 3, 1), box(0, 0, 1, 1), config, [])
    assert not candidates and raw_xor.is_empty and missing.is_empty and added.is_empty
    assert performance["candidate_limit_exceeded"]


def test_candidate_merge_uses_spatial_lookup_for_many_distant_bounds():
    candidates = [Candidate((index * 3, 0, index * 3 + 1, 1), "MISSING_FROM_WORKING") for index in range(1500)]
    merged = _merge_screening(candidates, .05)
    assert len(merged) == len(candidates)


def test_translation_pairing_is_one_to_one_and_reports_direction():
    config = ComparisonConfig(translation_tolerance_mm=1.0)
    missing = Candidate((0, 0, 1, 1), "MISSING_FROM_WORKING", geometry=box(0, 0, 1, 1))
    added = Candidate((.5, 0, 1.5, 1), "ADDED_IN_WORKING", geometry=box(.5, 0, 1.5, 1))
    translated = _pair_translations([missing, added], config)
    assert len(translated) == 1
    assert translated[0].classification == "TRANSLATION"
    assert translated[0].direction == "RIGHT"
    assert translated[0].dx == pytest.approx(.5)


def test_synthetic_pcb_like_grid_produces_bounded_telemetry():
    original_parts = [box(column * 2, row * 2, column * 2 + 1, row * 2 + 1) for row in range(25) for column in range(25)]
    working_parts = original_parts[2:] + [box(60, 0, 61, 1)]
    config = ComparisonConfig(minimum_tile_size=2, maximum_tile_size=2, max_candidate_regions=100)
    candidates, _xor, _missing, _added, performance = compare_tiled(GeometryCollection(original_parts), GeometryCollection(working_parts), config, [])
    assert not performance["candidate_limit_exceeded"]
    assert performance["tile_count"] == 775
    assert performance["verified_candidate_count"] == len(candidates)
