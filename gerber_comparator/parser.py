"""Conservative RS-274X parser. Unknown apertures are retained, never guessed."""
from __future__ import annotations
import re
from pathlib import Path
from .model import Aperture, ParsedLayer

_ADD = re.compile(r"^ADD(?P<number>\d+)(?P<name>[A-Za-z_][A-Za-z0-9_]*)?(?:,(?P<params>.*))?$")
_FS = re.compile(r"^FS[LT]A?X(?P<xint>\d)(?P<xdec>\d)Y(?P<yint>\d)(?P<ydec>\d).*$", re.I)
_COORD = re.compile(r"(?:(X)([+-]?\d+))?(?:(Y)([+-]?\d+))?(?:D0?([123]))?")
_STANDARD = {"C": "circle", "CIRCLE": "circle", "CIRCULAR": "circle", "R": "rectangle", "RECTANGLE": "rectangle", "O": "oblong", "OBLONG": "oblong", "OVAL": "oblong", "P": "polygon", "POLYGON": "polygon"}

def _parameters(value: str | None) -> tuple[float, ...]:
    if not value: return ()
    try: return tuple(float(part) for part in value.split("X"))
    except ValueError as exc: raise ValueError(f"Invalid aperture parameters: {value}") from exc

def parse_gerber(source: str | Path, *, filename: str | None = None) -> ParsedLayer:
    """Parse text/path into commands. Geometry is resolved separately by ``geometry``."""
    path = Path(source)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else str(source)
    layer = ParsedLayer(filename=filename or (path.name if path.exists() else "uploaded.gbr"))
    tokens = [item.strip() for item in text.replace("\r", "").split("*") if item.strip()]
    current_aperture: int | None = None; x = y = 0.0; in_region = False; region: list[tuple[float, float]] = []
    scale = 1.0; decimals = 4
    for line_no, raw in enumerate(tokens, 1):
        token = raw.strip("%")
        if token.startswith("MO"):
            layer.units = "inch" if "IN" in token.upper() else "mm"; scale = 25.4 if layer.units == "inch" else 1.0; continue
        fs = _FS.match(token)
        if fs: decimals = int(fs.group("xdec")); layer.coordinate_format = f"{fs.group('xint')}.{fs.group('xdec')}"; continue
        if token.startswith("AM"):
            name, _, body = token[2:].partition("*"); layer.macros[name] = body; continue
        match = _ADD.match(token)
        if match:
            name = (match.group("name") or "").upper(); params = _parameters(match.group("params"))
            geometry_type = _STANDARD.get(name); macro = name if name in layer.macros else None
            aperture = Aperture(int(match.group("number")), name, params, token, geometry_type, "standard" if geometry_type else ("macro" if macro else None), macro)
            layer.apertures[aperture.number] = aperture
            if not aperture.geometry_type and not aperture.macro_name: layer.unresolved_apertures.append(aperture)
            continue
        if token.startswith("D") and token[1:].isdigit() and int(token[1:]) >= 10:
            current_aperture = int(token[1:]); continue
        if token in {"G36", "G36D02"}: in_region = True; region = []; continue
        if token in {"G37", "G37D02"}:
            in_region = False
            if len(region) >= 3: layer.primitives.append(("region", tuple(region)))
            continue
        if token.startswith("G04") or token.startswith("M02") or token.startswith("LP") or token.startswith("G01"): continue
        if token.startswith("D") and token[1:].isdigit(): continue
        coord = _COORD.fullmatch(token.replace("G01", ""))
        if not coord or (coord.group(2) is None and coord.group(4) is None):
            layer.warnings.append(f"Line {line_no}: unsupported command {raw[:80]}"); continue
        def val(raw_value: str | None, prior: float) -> float:
            return prior if raw_value is None else int(raw_value) / 10**decimals * scale
        nx, ny = val(coord.group(2), x), val(coord.group(4), y); operation = coord.group(5)
        if in_region: region.append((nx, ny))
        elif operation == "3": layer.primitives.append(("flash", current_aperture, nx, ny))
        elif operation == "1": layer.primitives.append(("stroke", current_aperture, x, y, nx, ny))
        x, y = nx, ny
    return layer
