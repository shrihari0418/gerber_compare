import pytest

pytest.importorskip("shapely")
from gerber_comparator.core import compare_gerbers
from gerber_comparator.model import ComparisonConfig

def gerber(aperture="R,2X2", flashes=((1, 1),)):
    commands = ["%MOMM*%", "%FSLAX24Y24*%", f"%ADD10{aperture}*%", "D10*"]
    commands.extend(f"X{round(x * 10000):06d}Y{round(y * 10000):06d}D03*" for x, y in flashes)
    return "".join(commands) + "M02*"

def compare(original, working, tolerance=.05):
    return compare_gerbers(original, working, ComparisonConfig(geometric_tolerance_mm=tolerance, auto_alignment=False, snapshot_generation=False))

def test_identical_gerbers_pass_with_empty_raw_xor():
    result = compare(gerber(), gerber())
    assert result.overall_result == "PASS"
    assert result.raw_xor.area == pytest.approx(0)

def test_small_change_is_ignored_and_large_change_is_flagged():
    ignored = compare(gerber(), gerber("R,2.02X2"))
    flagged = compare(gerber(), gerber("R,2.2X2"))
    assert {region.classification for region in ignored.regions} == {"IGNORE"}
    assert {region.classification for region in flagged.regions} == {"ADDED_IN_WORKING"}
    assert flagged.overall_result == "FAIL"

def test_component_count_topology_change_is_flagged():
    result = compare(gerber(), gerber(flashes=((1, 1), (5, 1))))
    assert result.regions
    assert {region.classification_reason for region in result.regions} == {"TOPOLOGY_CHANGE"}
