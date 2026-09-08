# Development

Run `python -m pytest -q` and `python -m compileall gerber_comparator` before committing. Tests cover parser normalization, safe handling of vendor apertures, invalid-polygon repair, robust union, and repaired vector XOR. Extend the suite with physical geometry fixtures for every newly supported command.

The project depends on Shapely for robust vector operations and Matplotlib only for snapshots. Do not replace vector comparison with pixel differences. Do not add unknown-aperture fallbacks: implement a named resolver/provider with tests instead.
