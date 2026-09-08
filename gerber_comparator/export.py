"""Offline, auditable output package generation."""
from __future__ import annotations
import csv, json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from . import __version__
from .core import ComparisonResult

def _geojson(geometry):
    from shapely.geometry import mapping
    return mapping(geometry)

def _write_gerber(path: Path, geometry) -> None:
    """Write polygonal XOR geometry as a simple mm RS-274X region file."""
    lines = ["G04 Gerber Comparator XOR*", "%MOMM*%", "%FSLAX46Y46*%", "G36*"]
    polygons = [geometry] if geometry.geom_type == "Polygon" else [g for g in geometry.geoms if g.geom_type == "Polygon"]
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            coords = list(ring.coords); lines.append("G36*")
            for i, (x,y) in enumerate(coords): lines.append(f"X{round(x*1e6):07d}Y{round(y*1e6):07d}D{2 if i == 0 else 1}*")
            lines.append("G37*")
    lines.append("M02*"); path.write_text("\n".join(lines), encoding="ascii")

def export_package(result: ComparisonResult, output_dir: str | Path) -> Path:
    root = Path(output_dir); report, gerber, data, diagnostics = (root / "report", root / "gerber", root / "data", root / "diagnostics")
    for directory in (report / "flagged", gerber, data, diagnostics): directory.mkdir(parents=True, exist_ok=True)
    snapshots = _snapshots(result, report / "flagged") if result.config.snapshot_generation else {}
    for region in result.regions: region.snapshot = snapshots.get(region.region_id)
    payload = {"metadata": {"tool_version": __version__, "created_at": datetime.now(timezone.utc).isoformat(), "overall_result": result.overall_result}, "configuration": asdict(result.config), "alignment": result.alignment, "statistics": result.statistics(), "geometry_diagnostics": result.geometry_diagnostics, "warnings": result.warnings, "regions": [r.as_dict() for r in result.regions], "outputs": {}}
    (data / "comparison.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (data / "raw_differences.json").write_text(json.dumps(_geojson(result.raw_xor), indent=2), encoding="utf-8")
    with (data / "difference_regions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[k for k in result.regions[0].as_dict() if k != "bbox"] if result.regions else ["region_id"]); writer.writeheader(); writer.writerows([{k:v for k,v in r.as_dict().items() if k != "bbox"} for r in result.regions])
    diagnostics_data = {"original": [asdict(a) for a in result.original.apertures.values()], "working": [asdict(a) for a in result.working.apertures.values()]}
    (diagnostics / "apertures.json").write_text(json.dumps(diagnostics_data, indent=2), encoding="utf-8")
    (diagnostics / "parser_warnings.json").write_text(json.dumps(result.warnings, indent=2), encoding="utf-8")
    _write_gerber(gerber / "XOR_difference.gbr", result.raw_xor); _write_gerber(gerber / "XOR_difference_flagged.gbr", result.flagged_xor)
    _html(result, report / "Gerber_Comparison_Report.html")
    (root / "README.txt").write_text("Offline Gerber Comparator output package. See report/Gerber_Comparison_Report.html.\n", encoding="utf-8")
    manifest = {"tool_version": __version__, "original_file": result.original.filename, "working_file": result.working.filename, "configuration": asdict(result.config), "statistics": result.statistics(), "outputs": {"report": "report/Gerber_Comparison_Report.html"}}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = root.with_suffix(".zip");
    with ZipFile(archive, "w", ZIP_DEFLATED) as zf:
        for item in root.rglob("*"):
            if item.is_file(): zf.write(item, item.relative_to(root.parent))
    return archive

def _snapshots(result, directory: Path):
    try:
        import matplotlib.pyplot as plt
    except ImportError: return {}
    snapshots = {}
    for n, region in enumerate((r for r in result.regions if r.classification not in {"IGNORE", "UNRESOLVED"}), 1):
        fig, ax = plt.subplots(figsize=(7, 7), dpi=result.config.snapshot_dpi)
        directional = (
            (region.geometry, "#d7191c", "Missing from Working")
            if region.classification == "MISSING_FROM_WORKING" else
            (region.geometry, "#1b9e77", "Added in Working")
            if region.classification == "ADDED_IN_WORKING" else
            (region.geometry, "#d7191c", "Difference")
        )
        for geom, color, label in ((result.original_geometry, "#167ac6", "Original"), (result.working_geometry, "#d06c18", "Working"), directional):
            for polygon in ([geom] if geom.geom_type == "Polygon" else geom.geoms):
                if polygon.is_empty: continue
                x,y = polygon.exterior.xy; ax.fill(x,y, color=color, alpha=.25, label=label)
        x1,y1,x2,y2 = region.bbox; m = result.config.snapshot_margin_mm; ax.set(xlim=(x1-m,x2+m), ylim=(y1-m,y2+m), aspect="equal", title=f"{region.region_id}: {region.classification_reason}"); ax.legend();
        name = f"flagged_region_{n:03d}.png"; fig.savefig(directory / name, bbox_inches="tight"); plt.close(fig); snapshots[region.region_id] = f"flagged/{name}"
    return snapshots

def _html(result, path: Path):
    rows = "".join(f"<tr><td>{r.region_id}</td><td>{r.classification}</td><td>{r.classification_reason}</td><td>{r.area_mm2:.3f}</td><td>{r.geometric_deviation_mm:.3f}</td><td>{r.translation_mm:.3f}</td><td>{'yes' if r.topology_changed else 'no'}</td><td>{f'<a href=\"{r.snapshot}\">snapshot</a>' if r.snapshot else ''}</td></tr>" for r in result.regions)
    stats = result.statistics(); path.write_text(f"""<!doctype html><html><head><meta charset='utf-8'><title>Gerber Comparison Report</title><style>body{{font-family:Arial;margin:2rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #777;padding:.45rem}}th{{background:#eee}}.FAIL{{color:#b00}}</style></head><body><h1>Universal Gerber Comparator</h1><h2 class='{result.overall_result}'>{result.overall_result}</h2><p>Original: {result.original.filename}<br>Working: {result.working.filename}</p><p>Geometry tolerance: {result.config.geometric_tolerance_mm:.3f} mm; Translation tolerance: {result.config.translation_tolerance_mm:.3f} mm.</p><p>Flagged: {stats['flagged_regions']} / Total regions: {stats['total_difference_regions']}; Missing from Working: {stats['missing_from_working']}; Added in Working: {stats['added_in_working']}; Raw XOR area: {stats['total_xor_area_mm2']:.3f} mm².</p><table><tr><th>Region</th><th>Class</th><th>Reason</th><th>Area mm²</th><th>Deviation mm</th><th>Translation mm</th><th>Topology</th><th>Snapshot</th></tr>{rows}</table></body></html>""", encoding="utf-8")
