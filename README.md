# Universal Gerber Comparator

By Shrihari Kulkarni

This repository contains the V1, geometry-first comparison core for RS-274X Gerber layers. Its API is UI-neutral (`compare_gerbers`) so a Colab notebook, CLI, and future desktop application share one engine.

## Install and run

```bash
python -m pip install -e .
python -m gerber_comparator original.gtl working.gtl --auto-align --output-dir Gerber_Comparison
```

The package writes an offline report, JSON/CSV diagnostics, raw and flagged XOR Gerbers, snapshots when Matplotlib is available, and a ZIP archive.

## Safety and feature boundaries

The parser supports standard and semantic named apertures (`C`, `R`, `O`, `P`, `CIRCLE`, `RECTANGLE`, `OBLONG`, `POLYGON`), flashes, strokes, and simple regions. Every aperture retains its raw definition. Unknown/vendor apertures are parsed but **explicitly unresolved**; the engine never guesses their geometry. Aperture macro definitions are preserved for diagnostics but macro primitive execution, clear polarity, arcs, transforms, and negative-image semantics require further implementation before use on production data containing them.

## Architecture

`parser.py` separates lexical aperture capture from `geometry.py` resolution. `core.py` performs normalized-mm vector XOR and distance/topology classification. `export.py` is a presentation/export adapter; it does not participate in comparison decisions. This separation lets a future PySide/Qt desktop frontend call the exact same core API.

See [ARCHITECTURE.md](ARCHITECTURE.md), [USER_GUIDE.md](USER_GUIDE.md), and [DEVELOPMENT.md](DEVELOPMENT.md).

For Colab, run `from gerber_comparator.colab_runner import run_colab; run_colab()` after installing the package. Colab-only imports are contained in that adapter.
