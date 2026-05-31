"""Equirectangular projection helpers for geographic quiz tools.

A simple plate-carrée projection sufficient for regional school maps where
shape accuracy matters more than area accuracy. Latitude is scaled by
1/cos(mid_lat) so that north-south distances near the map's central latitude
look proportional to east-west distances.
"""
import math


def make_projection(extent_lon, extent_lat, mid_lat_for_aspect, width_px):
    """Build a (px_function, width_px, height_px) tuple.

    px_function(lon, lat) returns (x, y) in pixels with origin at top-left,
    so latitude is flipped (y increases downward).

    extent_lon: (min_lon, max_lon)
    extent_lat: (min_lat, max_lat)
    mid_lat_for_aspect: latitude (deg) at which aspect is preserved
    width_px: desired map width in pixels; height is derived
    """
    lon0, lon1 = extent_lon
    lat0, lat1 = extent_lat
    aspect = 1.0 / math.cos(math.radians(mid_lat_for_aspect))
    sx = width_px / (lon1 - lon0)
    sy = sx * aspect
    height_px = (lat1 - lat0) * sy

    def px(lon, lat):
        return ((lon - lon0) * sx, (lat1 - lat) * sy)

    return px, width_px, height_px
