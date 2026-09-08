from gerber_comparator.parser import parse_gerber

def test_named_and_vendor_apertures_are_preserved_without_guessing():
    layer = parse_gerber("%MOMM*%%ADD10RECTANGLE,2X1*%%ADD24VB_RECTANGLE,1X1X0*%D10*X010000Y020000D03*M02*")
    assert layer.apertures[10].geometry_type == "rectangle"
    vendor = layer.apertures[24]
    assert vendor.name == "VB_RECTANGLE"
    assert vendor.geometry_type is None
    assert vendor in layer.unresolved_apertures

def test_inch_coordinates_normalize_to_mm():
    layer = parse_gerber("%MOIN*%%FSLAX24Y24*%%ADD10C,0.1*%D10*X010000Y020000D03*M02*")
    assert layer.units == "inch"
    assert layer.primitives[0][2:] == (25.4, 50.8)
