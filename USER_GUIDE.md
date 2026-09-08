# User guide

Install dependencies, then run:

```bash
python -m gerber_comparator reference.gtl modified.gtl \
  --geometric-tolerance-mm 0.05 --translation-tolerance-mm 0.10 \
  --auto-align --output-dir Gerber_Comparison
```

In Colab, install the package from the repository, upload the two files, and call the same CLI or `compare_gerbers` API. Download `Gerber_Comparison.zip`; open `report/Gerber_Comparison_Report.html` locally. The report links each generated flagged-region snapshot and the package includes `data/comparison.json`, CSV, raw XOR, flagged XOR, diagnostics, and a manifest.

Use manual `--dx`, `--dy`, and `--rotation` when registration must be controlled. Automatic alignment currently uses centroid translation and records that transform in the result.
