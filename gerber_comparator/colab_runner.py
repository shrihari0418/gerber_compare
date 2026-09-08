"""Optional V1 Colab adapter; it deliberately does not affect the core engine."""
from __future__ import annotations
from pathlib import Path
from .core import ComparisonConfig, compare_gerbers
from .export import export_package

def run_colab() -> None:
    """Upload two Gerbers, prompt for tolerances, preview result, and download ZIP."""
    try:
        from google.colab import files
        from IPython.display import Image, display
    except ImportError as exc:
        raise RuntimeError("run_colab() must be executed in Google Colab.") from exc
    print("=" * 40 + "\nUNIVERSAL GERBER COMPARATOR\n" + "=" * 40)
    uploaded = files.upload()
    names = list(uploaded)
    if len(names) < 2: raise ValueError("Upload an Original and Working Gerber file.")
    for i, name in enumerate(names): print(f"[{i}] {name}")
    original = names[int(input("Original file number [0]: ") or 0)]
    working = names[int(input("Working file number [1]: ") or 1)]
    geometry_tolerance = float(input("Geometric tolerance in mm [0.05]: ") or .05)
    translation_tolerance = float(input("Translation tolerance in mm [0.10]: ") or .10)
    result = compare_gerbers(original, working, ComparisonConfig(geometry_tolerance, translation_tolerance, auto_alignment=(input("Automatic alignment [Y/n]: ") or "Y").lower() != "n"))
    archive = export_package(result, "Gerber_Comparison")
    print(f"\nRESULT: {result.overall_result}\nFlagged regions: {result.statistics()['flagged_regions']}")
    for region in result.regions[:3]:
        if region.snapshot: display(Image(filename=str(Path("Gerber_Comparison/report") / region.snapshot)))
    files.download(str(archive))
