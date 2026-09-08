from __future__ import annotations
import argparse
from .core import ComparisonConfig, compare_gerbers
from .export import export_package
def main():
    p=argparse.ArgumentParser(description="Geometry-based Gerber comparison")
    p.add_argument("original"); p.add_argument("working"); p.add_argument("--geometric-tolerance-mm", type=float, default=.05); p.add_argument("--translation-tolerance-mm", type=float, default=.10); p.add_argument("--auto-align", action="store_true"); p.add_argument("--dx", type=float, default=0); p.add_argument("--dy", type=float, default=0); p.add_argument("--rotation", type=float, default=0); p.add_argument("--topology-check", action=argparse.BooleanOptionalAction, default=True); p.add_argument("--output-dir", default="Gerber_Comparison"); p.add_argument("--report", action=argparse.BooleanOptionalAction, default=True); p.add_argument("--snapshots", action=argparse.BooleanOptionalAction, default=True)
    a=p.parse_args(); c=ComparisonConfig(a.geometric_tolerance_mm,a.translation_tolerance_mm,a.topology_check,a.auto_align,a.dx,a.dy,a.rotation,a.snapshots,generate_html_report=a.report); r=compare_gerbers(a.original,a.working,c); archive=export_package(r,a.output_dir); print(f"RESULT: {r.overall_result}\nFlagged regions: {r.statistics()['flagged_regions']}\nPackage: {archive}")
if __name__ == "__main__": main()
