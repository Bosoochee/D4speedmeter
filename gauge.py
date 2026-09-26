"""Widget cadran analogique du compteur."""

import math

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.widget import Widget


class Gauge(Widget):
    """Cadran : graduations, arc de progression et aiguille."""

    value = NumericProperty(0)
    max_value = NumericProperty(50)
    major_step = NumericProperty(10)
    minor_step = NumericProperty(5)
    start_angle = NumericProperty(-135)  # 0 = haut, sens horaire (convention Kivy)
    end_angle = NumericProperty(135)

    # Géométrie calculée, utilisable depuis le .kv pour placer l'affichage numérique
    radius = NumericProperty(0)
    dial_cx = NumericProperty(0)
    dial_cy = NumericProperty(0)

    # Le cadran est ouvert en bas : sa hauteur utile vaut r * (1 + cos 45°)
    _HEIGHT_RATIO = 1 + math.cos(math.radians(45))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._labels = {}
        self.bind(pos=self.redraw, size=self.redraw, value=self.redraw, max_value=self.redraw)

    def value_to_angle(self, value):
        ratio = max(0.0, min(value / self.max_value, 1.0))
        return self.start_angle + ratio * (self.end_angle - self.start_angle)

    def _polar(self, angle_deg, radius):
        a = math.radians(angle_deg)
        return self.dial_cx + radius * math.sin(a), self.dial_cy + radius * math.cos(a)

    def _update_geometry(self):
        margin = dp(6)
        r = min((self.width - 2 * margin) / 2, (self.height - 2 * margin) / self._HEIGHT_RATIO)
        self.radius = max(r, 0) * 0.96  # place pour l'épaisseur de l'arc
        self.dial_cx = self.center_x
        # Cadran calé en haut de la zone : le haut de l'arc touche la marge supérieure
        # y + height plutôt que self.top : `top` peut ne pas être encore à jour ici
        self.dial_cy = self.y + self.height - margin - self.radius * 1.03

    def _label_texture(self, text, font_size):
        key = (text, int(font_size))
        if key not in self._labels:
            lbl = CoreLabel(text=text, font_size=font_size, bold=True)
            lbl.refresh()
            self._labels[key] = lbl.texture
        return self._labels[key]

    def redraw(self, *_):
        self.canvas.clear()
        self._update_geometry()
        r = self.radius
        if r <= 0:
            return
        cx, cy = self.dial_cx, self.dial_cy
        box = (cx - r, cy - r, 2 * r, 2 * r)
        thickness = max(dp(4), r * 0.05)
        value_angle = self.value_to_angle(self.value)
        ratio = max(0.0, min(self.value / self.max_value, 1.0))

        with self.canvas:
            # Fond de l'arc
            Color(0.18, 0.18, 0.22, 1)
            Line(ellipse=(*box, self.start_angle, self.end_angle), width=thickness, cap="round")
            # Arc de progression : vert -> orange -> rouge
            Color(min(1, ratio * 2), min(1, 2 - ratio * 2), 0.1, 1)
            if self.value >= 0.5:
                Line(ellipse=(*box, self.start_angle, value_angle), width=thickness, cap="round")

            # Graduations
            v = 0
            while v <= self.max_value:
                angle = self.value_to_angle(v)
                major = v % self.major_step == 0
                inner = r * (0.80 if major else 0.86)
                Color(1, 1, 1, 0.9 if major else 0.5)
                Line(points=[*self._polar(angle, inner), *self._polar(angle, r * 0.92)],
                     width=dp(1.6) if major else dp(1))
                if major:
                    tex = self._label_texture(str(int(v)), r * 0.10)
                    lx, ly = self._polar(angle, r * 0.66)
                    Color(1, 1, 1, 0.85)
                    Rectangle(texture=tex, size=tex.size,
                              pos=(lx - tex.width / 2, ly - tex.height / 2))
                v += self.minor_step

            # Aiguille
            Color(1, 0.25, 0.2, 1)
            Line(points=[cx, cy, *self._polar(value_angle, r * 0.78)], width=dp(3), cap="round")
            Color(0.9, 0.9, 0.9, 1)
            Ellipse(pos=(cx - dp(9), cy - dp(9)), size=(dp(18), dp(18)))
