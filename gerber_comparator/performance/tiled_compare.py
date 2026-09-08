"""Lazy two-pass STRtree comparison; GEOS overlays are always local."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, ceil, degrees, hypot
from numbers import Integral
import time

from shapely.geometry import GeometryCollection, box
from shapely.strtree import STRtree

from ..geometry import safe_difference, safe_union


@dataclass
class Candidate:
    bounds: tuple[float, float, float, float]
    classification: str
    tile_ids: set[str] = field(default_factory=set)
    geometry: object | None = None
    reason: str = ""
    topology_changed: bool = False
    dx: float = 0.0
    dy: float = 0.0
    direction: str | None = None
    confidence: float = 1.0


class _DSU:
    def __init__(self, size): self.parent = list(range(size))
    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]; item = self.parent[item]
        return item
    def join(self, left, right):
        left, right = self.find(left), self.find(right)
        if left != right: self.parent[right] = left


def tile_size(config):
    tolerance = config.geometric_tolerance_mm if config.geometric_tolerance_mm > 0 else .05
    return min(max(tolerance * config.tile_tolerance_factor, config.minimum_tile_size), config.maximum_tile_size)


def tile_count(bounds, size):
    return max(1, ceil((bounds[2] - bounds[0]) / size)) * max(1, ceil((bounds[3] - bounds[1]) / size))


def iter_tiles(bounds, size):
    min_x, min_y, max_x, max_y = bounds
    for row in range(max(1, ceil((max_y - min_y) / size))):
        for column in range(max(1, ceil((max_x - min_x) / size))):
            yield f"T-{row}-{column}", box(min_x + column * size, min_y + row * size,
                min(max_x, min_x + (column + 1) * size), min(max_y, min_y + (row + 1) * size))


def _parts(geometry):
    if geometry.is_empty: return []
    return list(geometry.geoms) if geometry.geom_type in {"MultiPolygon", "GeometryCollection"} else [geometry]


def _query(tree, components, lookup, window):
    if tree is None: return []
    values = tree.query(window)
    if hasattr(values, "tolist"): values = values.tolist()
    if not values: return []
    return [components[index] for index in values] if isinstance(values[0], Integral) else [lookup[id(value)] for value in values]


def _expanded_bounds(bounds, margin):
    return box(bounds[0] - margin, bounds[1] - margin, bounds[2] + margin, bounds[3] + margin)


def _merge_screening(candidates, gap):
    """STRtree + DSU merge: no pairwise scan and no per-candidate buffer."""
    merged = []
    for classification in ("MISSING_FROM_WORKING", "ADDED_IN_WORKING"):
        items = [item for item in candidates if item.classification == classification]
        if not items: continue
        envelopes = [box(*item.bounds) for item in items]; tree = STRtree(envelopes)
        lookup = {id(envelope): index for index, envelope in enumerate(envelopes)}; dsu = _DSU(len(items))
        for index, item in enumerate(items):
            for nearby in _query(tree, envelopes, lookup, _expanded_bounds(item.bounds, gap)):
                other = lookup[id(nearby)]
                if other > index: dsu.join(index, other)
        groups = {}
        for index, item in enumerate(items): groups.setdefault(dsu.find(index), []).append(item)
        for group in groups.values():
            bounds = (min(item.bounds[0] for item in group), min(item.bounds[1] for item in group), max(item.bounds[2] for item in group), max(item.bounds[3] for item in group))
            merged.append(Candidate(bounds, classification, set().union(*(item.tile_ids for item in group))))
    return merged


def _local_geometry(tree, components, lookup, window, label, warnings):
    values = _query(tree, components, lookup, window)
    return safe_union([value.intersection(window) for value in values], label=label, warnings=warnings)


def _topology_signature(geometry):
    parts = _parts(geometry)
    return len(parts), sum(len(part.interiors) for part in parts if part.geom_type == "Polygon")


def _direction(dx, dy):
    names = ("RIGHT", "UP_RIGHT", "UP", "UP_LEFT", "LEFT", "DOWN_LEFT", "DOWN", "DOWN_RIGHT")
    return names[int(((degrees(atan2(dy, dx)) + 360) % 360 + 22.5) // 45) % 8]


def _pair_translations(candidates, config):
    missing = [item for item in candidates if item.classification == "MISSING_FROM_WORKING"]
    added = [item for item in candidates if item.classification == "ADDED_IN_WORKING"]
    if not missing or not added or not config.enable_displacement_pairing: return candidates
    envelopes = [box(*item.bounds) for item in added]; tree = STRtree(envelopes); lookup = {id(item): index for index, item in enumerate(envelopes)}
    pairs = []
    for left_index, left in enumerate(missing):
        centroid = left.geometry.centroid
        for envelope in _query(tree, envelopes, lookup, _expanded_bounds(left.bounds, config.translation_tolerance_mm)):
            right_index = lookup[id(envelope)]; right = added[right_index]; right_centroid = right.geometry.centroid
            distance = hypot(right_centroid.x - centroid.x, right_centroid.y - centroid.y)
            ratio = min(left.geometry.area, right.geometry.area) / max(left.geometry.area, right.geometry.area)
            if distance <= config.translation_tolerance_mm and ratio >= config.translation_area_similarity:
                pairs.append((distance, 1 - ratio, left_index, right_index))
    used_left = set(); used_right = set(); translations = []
    for _, _, left_index, right_index in sorted(pairs):
        if left_index in used_left or right_index in used_right: continue
        left, right = missing[left_index], added[right_index]; lc, rc = left.geometry.centroid, right.geometry.centroid
        dx, dy = rc.x - lc.x, rc.y - lc.y
        translations.append(Candidate((min(left.bounds[0], right.bounds[0]), min(left.bounds[1], right.bounds[1]), max(left.bounds[2], right.bounds[2]), max(left.bounds[3], right.bounds[3])), "TRANSLATION", left.tile_ids | right.tile_ids, safe_union([left.geometry, right.geometry], label="Translation", warnings=[]), "DISPLACEMENT_PAIR", False, dx, dy, _direction(dx, dy), .8))
        used_left.add(left_index); used_right.add(right_index)
    return [item for index, item in enumerate(missing) if index not in used_left] + [item for index, item in enumerate(added) if index not in used_right] + translations


def compare_tiled(original, working, config, warnings, progress=None):
    """Pass 1 stores bounds-only screening candidates; pass 2 reconstructs exact local geometry."""
    started = time.perf_counter(); index_started = time.perf_counter()
    original_components, working_components = _parts(original), _parts(working)
    original_tree = STRtree(original_components) if original_components else None; working_tree = STRtree(working_components) if working_components else None
    original_lookup = {id(item): item for item in original_components}; working_lookup = {id(item): item for item in working_components}
    index_seconds = time.perf_counter() - index_started
    if original.is_empty and working.is_empty:
        return [], GeometryCollection(), GeometryCollection(), GeometryCollection(), {"tile_count": 0, "occupied_tile_count": 0, "skipped_tile_count": 0, "candidate_count": 0, "merged_candidate_count": 0, "verified_candidate_count": 0, "candidate_limit_exceeded": False, "verification_limit_exceeded": False, "spatial_index_seconds": index_seconds, "tile_generation_seconds": 0.0, "screening_seconds": 0.0, "candidate_merge_seconds": 0.0, "verification_seconds": 0.0, "total_seconds": time.perf_counter()-started}
    bounds = original.bounds if working.is_empty else working.bounds if original.is_empty else (min(original.bounds[0], working.bounds[0]), min(original.bounds[1], working.bounds[1]), max(original.bounds[2], working.bounds[2]), max(original.bounds[3], working.bounds[3]))
    tile_started = time.perf_counter(); size = tile_size(config); total_tiles = tile_count(bounds, size); margin = max(0.0, config.tile_margin_factor * config.geometric_tolerance_mm); tile_generation_seconds = time.perf_counter() - tile_started
    screening = []; occupied = skipped = ignored_count = 0; ignored_area = 0.0; screen_started = time.perf_counter()
    milestones = {1, total_tiles, max(1, total_tiles // 4), max(1, total_tiles // 2), max(1, total_tiles * 3 // 4)}
    for count, (tile_id, tile) in enumerate(iter_tiles(bounds, size), 1):
        if progress and count in milestones: progress(count, total_tiles)
        window = _expanded_bounds(tile.bounds, margin)
        left = _query(original_tree, original_components, original_lookup, window); right = _query(working_tree, working_components, working_lookup, window)
        if not left and not right: skipped += 1; continue
        occupied += 1
        # Exact work is local; screening retains only bounds and tile identity.
        local_original = safe_union([item.intersection(window) for item in left], label="Tile original", warnings=warnings)
        local_working = safe_union([item.intersection(window) for item in right], label="Tile working", warnings=warnings)
        for classification, difference in (("MISSING_FROM_WORKING", safe_difference(local_original, local_working, label="Tile missing", warnings=warnings)), ("ADDED_IN_WORKING", safe_difference(local_working, local_original, label="Tile added", warnings=warnings))):
            for part in _parts(difference.intersection(tile)):
                if part.area <= config.minimum_difference_area:
                    ignored_count += 1; ignored_area += part.area; continue
                screening.append(Candidate(part.bounds, classification, {tile_id}))
                if len(screening) > config.max_candidate_regions:
                    return [], GeometryCollection(), GeometryCollection(), GeometryCollection(), {"tile_count": total_tiles, "occupied_tile_count": occupied, "skipped_tile_count": skipped, "candidate_count": len(screening), "merged_candidate_count": 0, "verified_candidate_count": 0, "candidate_limit_exceeded": True, "verification_limit_exceeded": False, "spatial_index_seconds": index_seconds, "tile_generation_seconds": tile_generation_seconds, "screening_seconds": time.perf_counter()-screen_started, "candidate_merge_seconds": 0.0, "verification_seconds": 0.0, "ignored_small_difference_count": ignored_count, "ignored_small_difference_area": ignored_area, "total_seconds": time.perf_counter()-started}
        del local_original, local_working, difference
    screening_seconds = time.perf_counter() - screen_started; merge_started = time.perf_counter()
    merged = _merge_screening(screening, max(margin, config.geometric_tolerance_mm)); merge_seconds = time.perf_counter() - merge_started
    if len(merged) > config.max_verification_regions:
        return [], GeometryCollection(), GeometryCollection(), GeometryCollection(), {"tile_count": total_tiles, "occupied_tile_count": occupied, "skipped_tile_count": skipped, "candidate_count": len(screening), "merged_candidate_count": len(merged), "verified_candidate_count": 0, "candidate_limit_exceeded": False, "verification_limit_exceeded": True, "spatial_index_seconds": index_seconds, "tile_generation_seconds": tile_generation_seconds, "screening_seconds": screening_seconds, "candidate_merge_seconds": merge_seconds, "verification_seconds": 0.0, "total_seconds": time.perf_counter()-started}
    verification_started = time.perf_counter(); verified = []
    for candidate in merged:
        window = _expanded_bounds(candidate.bounds, margin)
        local_original = _local_geometry(original_tree, original_components, original_lookup, window, "Candidate original", warnings)
        local_working = _local_geometry(working_tree, working_components, working_lookup, window, "Candidate working", warnings)
        difference = safe_difference(local_original, local_working, label="Candidate missing", warnings=warnings) if candidate.classification == "MISSING_FROM_WORKING" else safe_difference(local_working, local_original, label="Candidate added", warnings=warnings)
        candidate.geometry = difference.intersection(box(*candidate.bounds))
        candidate.topology_changed = config.enable_local_topology and _topology_signature(local_original) != _topology_signature(local_working)
        candidate.reason = "TOPOLOGY_CHANGE" if candidate.topology_changed else candidate.classification
        if not candidate.geometry.is_empty: verified.append(candidate)
        del local_original, local_working, difference
    verified = _pair_translations(verified, config); verification_seconds = time.perf_counter() - verification_started
    missing = [item.geometry for item in verified if item.classification == "MISSING_FROM_WORKING"]; added = [item.geometry for item in verified if item.classification == "ADDED_IN_WORKING"]
    return verified, GeometryCollection([item.geometry for item in verified]), GeometryCollection(missing), GeometryCollection(added), {"tile_count": total_tiles, "occupied_tile_count": occupied, "skipped_tile_count": skipped, "candidate_count": len(screening), "merged_candidate_count": len(merged), "verified_candidate_count": len(verified), "candidate_limit_exceeded": False, "verification_limit_exceeded": False, "spatial_index_seconds": index_seconds, "tile_generation_seconds": tile_generation_seconds, "screening_seconds": screening_seconds, "candidate_merge_seconds": merge_seconds, "verification_seconds": verification_seconds, "ignored_small_difference_count": ignored_count, "ignored_small_difference_area": ignored_area, "total_seconds": time.perf_counter()-started}
