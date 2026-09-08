# Performance architecture

The former comparison path performed full-board directional difference and XOR, then intersected every XOR component with both full boards for local deviation. Large connected copper creates expensive GEOS overlay graphs; retaining those graphs and repeatedly clipping full-board geometry explains the reported RAM growth and long runtime.

V2.2 preserves parse, repair, normalization, and alignment. It then builds one `STRtree` per board, generates tolerance-aware tiles, queries only components intersecting each expanded tile, and computes exact vector differences only locally. A second pass merges directional tile fragments. This changes normal comparison work from repeated full-board overlays to indexed local overlays. Final output geometries are collections of verified local candidates; no global XOR/difference is used in the normal comparison path.

Tile size is `clamp(tolerance * factor, minimum, maximum)` and margins protect geometry crossing tile boundaries. Candidate limits report an incomplete comparison rather than discarding data. Global normalized geometry construction remains for API compatibility; representative Gerber benchmarking is still required.
