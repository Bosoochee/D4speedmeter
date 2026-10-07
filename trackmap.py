"""Carte OpenTopoMap affichant le tracé GPS du trajet (bibliothèque mapview intégrée)."""

import os

from kivy.graphics import Color, Ellipse, Line
from kivy.metrics import dp
from kivy.properties import ListProperty
from kivy_garden.mapview import MapLayer, MapSource, MapView
from kivy_garden.mapview import downloader

# OpenTopoMap refuse les clients sans User-Agent identifiable
downloader.USER_AGENT = "D4speedmeter/1.0 (Kivy mapview; compteur velo Android)"

MAX_ZOOM = 17                  # zoom maximal d'OpenTopoMap
DEFAULT_CENTER = (46.6, 2.4)   # France entière quand il n'y a pas encore de tracé
DEFAULT_ZOOM = 5
TRACK_COLOR = (0.92, 0.25, 0.1, 1)


def opentopomap_source(cache_dir):
    os.makedirs(cache_dir, exist_ok=True)  # mapview ne crée que son dossier par défaut
    return MapSource(
        url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        cache_key="opentopomap",
        cache_dir=cache_dir,
        min_zoom=1,
        max_zoom=MAX_ZOOM,
        subdomains="abc",
        attribution="© OpenStreetMap, SRTM | © OpenTopoMap (CC-BY-SA)",
    )


class TrackLayer(MapLayer):
    """Dessine le tracé (ligne), son départ (vert) et la dernière position (orange)."""

    points = ListProperty([])

    def on_points(self, *_):
        self.reposition()

    def reposition(self):
        mapview = self.parent
        self.canvas.clear()
        if mapview is None or not self.points:
            return
        xy = []
        for lat, lon in self.points:
            xy += mapview.get_window_xy_from(lat, lon, mapview.zoom)
        radius = dp(6)
        with self.canvas:
            Color(*TRACK_COLOR)
            if len(xy) >= 4:
                Line(points=xy, width=dp(2.2), joint="round", cap="round")
            for (x, y), color in (((xy[0], xy[1]), (0.2, 0.75, 0.3, 1)),
                                  ((xy[-2], xy[-1]), (1, 0.6, 0.1, 1))):
                Color(1, 1, 1, 1)
                Ellipse(pos=(x - radius - dp(2), y - radius - dp(2)),
                        size=(2 * radius + dp(4), 2 * radius + dp(4)))
                Color(*color)
                Ellipse(pos=(x - radius, y - radius), size=(2 * radius, 2 * radius))


class TrackMap(MapView):
    def __init__(self, cache_dir, **kwargs):
        kwargs.setdefault("map_source", opentopomap_source(cache_dir))
        kwargs.setdefault("cache_dir", cache_dir)  # MapView impose son cache_dir à la source
        kwargs.setdefault("double_tap_zoom", True)
        super().__init__(**kwargs)
        self.track_layer = TrackLayer()
        self.add_layer(self.track_layer, mode="window")

    def show_track(self, points):
        self.track_layer.points = [tuple(p) for p in points]
        self.fit_track()

    def fit_track(self, *_):
        """Centre la carte et choisit le plus grand zoom montrant tout le tracé."""
        points = self.track_layer.points
        if not points:
            self.zoom = DEFAULT_ZOOM
            self.center_on(*DEFAULT_CENTER)
            return
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        source = self.map_source
        width, height = self.width - dp(40), self.height - dp(40)
        zoom = MAX_ZOOM
        while zoom > 1:
            span_x = source.get_x(zoom, max(lons)) - source.get_x(zoom, min(lons))
            span_y = source.get_y(zoom, min(lats)) - source.get_y(zoom, max(lats))
            if span_x <= width and span_y <= height:
                break
            zoom -= 1
        self.zoom = zoom
        self.center_on((min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2)
        self.track_layer.reposition()
