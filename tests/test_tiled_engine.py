import pytest

pytest.importorskip("shapely")
from shapely.geometry import box

from gerber_comparator.model import ComparisonConfig
from gerber_comparator.performance.tiled_compare import compare_tiled, iter_tiles, tile_size


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
