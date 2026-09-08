# Architecture

The pipeline is `RS-274X input -> ParsedLayer -> Shapely normalized geometry (mm) -> alignment -> raw symmetric difference -> region analysis -> export adapters`. Raw XOR is always generated before tolerance classification. Region significance uses local boundary Hausdorff distance, translation magnitude, and component-count topology checks; XOR area is only reported.

The default V2.2 execution path is tiled: normalized/aligned geometry is STRtree-indexed, lazy tiles screen spatially local components, and merged candidates are reconstructed and verified with local vector operations. Candidate-local XOR is reported as such; the engine does not perform a normal full-board XOR overlay.

Every primitive union and XOR passes through the same centralized validation pipeline. Invalid geometry is repaired with GEOS `make_valid` when available, with `buffer(0)` used only as a documented legacy-Shapely compatibility fallback. Polygonal components of a repair are retained, checked again, and never simplified or filtered by area. A failed repair raises `GeometryError`; it never returns an empty board or fake comparison result. If GEOS still rejects an XOR, a 0.000001 mm precision retry is recorded in diagnostics before a descriptive failure is raised.

`Aperture` stores identity, source name, numeric parameters, source definition, resolved type/provider, and macro linkage. A resolver is intentionally conservative: unsupported vendors remain unresolved and affect the final result rather than receiving invented geometry.

The core has no Colab imports. V2 can directly call `compare_gerbers(original, working, config)` and render the structured `ComparisonResult` in a desktop workspace.
