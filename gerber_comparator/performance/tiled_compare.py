"""STRtree-screened, local-vector tiled comparison."""
from __future__ import annotations
from dataclasses import dataclass
from math import ceil, hypot
import time

from shapely.geometry import GeometryCollection, box
from shapely.strtree import STRtree
from ..geometry import safe_difference, safe_union

@dataclass
class Candidate:
    geometry: object
    classification: str
    tile_ids: set[str]
    dx: float = 0.0
    dy: float = 0.0
    confidence: float = 1.0
    @property
    def bounds(self): return self.geometry.bounds

def tile_size(config):
    tolerance = config.geometric_tolerance_mm if config.geometric_tolerance_mm > 0 else .05
    return min(max(tolerance * config.tile_tolerance_factor, config.minimum_tile_size), config.maximum_tile_size)

def iter_tiles(bounds, size):
    min_x, min_y, max_x, max_y = bounds
    for row in range(max(1, ceil((max_y-min_y)/size))):
        for column in range(max(1, ceil((max_x-min_x)/size))):
            yield f"T-{row}-{column}", box(min_x+column*size, min_y+row*size, min(max_x, min_x+(column+1)*size), min(max_y, min_y+(row+1)*size))

def _parts(geometry):
    if geometry.is_empty: return []
    return list(geometry.geoms) if geometry.geom_type in {"MultiPolygon", "GeometryCollection"} else [geometry]

def _query(tree, components, window):
    found = tree.query(window)
    if hasattr(found, "tolist"): found = found.tolist()
    if not found: return []
    if isinstance(found[0], int): return [components[index] for index in found]
    lookup = {id(geometry): geometry for geometry in components}
    return [lookup[id(geometry)] for geometry in found]

def _merge(candidates, gap, warnings):
    merged=[]
    for kind in ("MISSING_FROM_WORKING", "ADDED_IN_WORKING"):
        pending=[candidate for candidate in candidates if candidate.classification == kind]
        while pending:
            group=[pending.pop()]; changed=True
            while changed:
                changed=False
                for candidate in pending[:]:
                    if any(member.geometry.buffer(gap).intersects(candidate.geometry) for member in group): pending.remove(candidate); group.append(candidate); changed=True
            merged.append(Candidate(safe_union([item.geometry for item in group], label=f"Merged {kind}", warnings=warnings), kind, set().union(*(item.tile_ids for item in group))))
    return merged

def compare_tiled(original, working, config, warnings, progress=None):
    """Pass 1 screens indexed tiles; pass 2 merges local exact vector fragments."""
    started=time.perf_counter(); original_components=_parts(original); working_components=_parts(working)
    original_tree=STRtree(original_components) if original_components else None; working_tree=STRtree(working_components) if working_components else None
    if original.is_empty and working.is_empty: return [], GeometryCollection(), GeometryCollection(), GeometryCollection(), {"tile_count":0,"occupied_tile_count":0,"skipped_tile_count":0,"candidate_count":0,"verified_candidate_count":0,"candidate_limit_exceeded":False,"spatial_index_seconds":0.,"screening_seconds":0.,"candidate_merge_seconds":0.,"verification_seconds":0.}
    bounds=original.bounds if working.is_empty else working.bounds if original.is_empty else (min(original.bounds[0],working.bounds[0]),min(original.bounds[1],working.bounds[1]),max(original.bounds[2],working.bounds[2]),max(original.bounds[3],working.bounds[3]))
    size=tile_size(config); tiles=list(iter_tiles(bounds,size)); margin=max(0.,config.tile_margin_factor*config.geometric_tolerance_mm); candidates=[]; occupied=skipped=0; screen=time.perf_counter()
    for number,(tile_id,tile) in enumerate(tiles,1):
        window=tile.buffer(margin); left=_query(original_tree,original_components,window) if original_tree else []; right=_query(working_tree,working_components,window) if working_tree else []
        if progress and number in {1, len(tiles), max(1, len(tiles)//4), max(1, len(tiles)//2), max(1, len(tiles)*3//4)}: progress(number, len(tiles))
        if not left and not right: skipped+=1; continue
        occupied+=1; local_original=safe_union([item.intersection(window) for item in left],label="Tile original",warnings=warnings); local_working=safe_union([item.intersection(window) for item in right],label="Tile working",warnings=warnings)
        for kind,difference in (("MISSING_FROM_WORKING",safe_difference(local_original,local_working,label="Tile missing",warnings=warnings)),("ADDED_IN_WORKING",safe_difference(local_working,local_original,label="Tile added",warnings=warnings))):
            for part in _parts(difference.intersection(tile)):
                if part.area <= config.minimum_difference_area: continue
                candidates.append(Candidate(part,kind,{tile_id}))
                if len(candidates)>config.max_candidate_regions: return [],GeometryCollection(),GeometryCollection(),GeometryCollection(),{"tile_count":len(tiles),"occupied_tile_count":occupied,"skipped_tile_count":skipped,"candidate_count":len(candidates),"verified_candidate_count":0,"candidate_limit_exceeded":True,"screening_seconds":time.perf_counter()-screen}
    screening=time.perf_counter()-screen; merge=time.perf_counter(); candidates=_merge(candidates,max(margin,config.geometric_tolerance_mm),warnings); merge_seconds=time.perf_counter()-merge
    missing=[item.geometry for item in candidates if item.classification=="MISSING_FROM_WORKING"]; added=[item.geometry for item in candidates if item.classification=="ADDED_IN_WORKING"]
    return candidates,GeometryCollection([item.geometry for item in candidates]),GeometryCollection(missing),GeometryCollection(added),{"tile_count":len(tiles),"occupied_tile_count":occupied,"skipped_tile_count":skipped,"candidate_count":len(candidates),"verified_candidate_count":len(candidates),"candidate_limit_exceeded":False,"spatial_index_seconds":0.,"screening_seconds":screening,"candidate_merge_seconds":merge_seconds,"verification_seconds":0.,"total_seconds":time.perf_counter()-started}
