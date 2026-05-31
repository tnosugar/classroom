"""GeoJSON loading and viewport-culling helpers for quiz map renderers."""
import json


def load_geojson(path):
    """Load a GeoJSON FeatureCollection from disk."""
    with open(path) as f:
        return json.load(f)


def iter_polygon_rings(features, extent_lon, extent_lat, padding=5):
    """Yield (ring, is_exterior) for every polygon ring in `features` that
    overlaps the bounding box [extent_lon] x [extent_lat], padded by `padding`
    degrees.

    A ring is a list of [lon, lat] pairs. `is_exterior` is True for the first
    ring of each polygon (the outer boundary) and False for holes.

    Polygons fully outside the padded box are culled.
    """
    lon0, lon1 = extent_lon
    lat0, lat1 = extent_lat
    pad_lon0, pad_lon1 = lon0 - padding, lon1 + padding
    pad_lat0, pad_lat1 = lat0 - padding, lat1 + padding

    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        if geom["type"] == "Polygon":
            polys = [geom["coordinates"]]
        elif geom["type"] == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        for poly in polys:
            for ri, ring in enumerate(poly):
                xs = [c[0] for c in ring]
                ys = [c[1] for c in ring]
                if max(xs) < pad_lon0 or min(xs) > pad_lon1:
                    continue
                if max(ys) < pad_lat0 or min(ys) > pad_lat1:
                    continue
                yield ring, (ri == 0)
