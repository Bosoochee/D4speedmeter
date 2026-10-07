"""Courbe d'historique (vitesse, puissance ou cadence) depuis la dernière remise à zéro."""

import math

from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp, sp
from kivy.properties import ColorProperty, ListProperty, NumericProperty
from kivy.uix.widget import Widget

TARGET_GRID_LINES = 5


def nice_step(value):
    """Arrondit vers le haut à 1, 2 ou 5 × 10^n (graduations lisibles de l'axe)."""
    if value <= 0:
        return 1
    magnitude = 10 ** math.floor(math.log10(value))
    for factor in (1, 2, 5, 10):
        if value <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


def format_duration(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class HistoryChart(Widget):
    values = ListProperty([])      # un point par `step_s` secondes (None = inconnu)
    step_s = NumericProperty(1)
    color = ColorProperty([1, 0.75, 0.3, 1])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(pos=self.redraw, size=self.redraw, values=self.redraw, step_s=self.redraw)

    @staticmethod
    def _text(text, size=sp(11)):
        label = CoreLabel(text=text, font_size=size)
        label.refresh()
        return label.texture

    def _draw_text(self, texture, x, y):
        Color(0.6, 0.6, 0.66, 1)
        Rectangle(texture=texture, size=texture.size, pos=(x, y))

    def redraw(self, *_):
        self.canvas.clear()
        known = [v for v in self.values if v is not None]
        with self.canvas:
            if not known:
                tex = self._text("Pas encore de données : roulez !", sp(14))
                self._draw_text(tex, self.center_x - tex.width / 2, self.center_y - tex.height / 2)
                return

            peak = max(known)
            step = nice_step(peak / TARGET_GRID_LINES)
            lines = max(1, math.ceil(peak / step))
            top_value = step * lines
            labels = [self._text(f"{step * i:g}") for i in range(lines + 1)]
            left = self.x + max(t.width for t in labels) + dp(6)
            bottom = self.y + dp(18)
            width = self.right - left - dp(6)
            height = self.top - bottom - dp(8)
            if width <= 0 or height <= 0:
                return

            # Grille horizontale et graduations de l'axe des valeurs
            for i, tex in enumerate(labels):
                y = bottom + height * i / lines
                Color(1, 1, 1, 0.25 if i == 0 else 0.08)
                Line(points=[left, y, left + width, y], width=1)
                self._draw_text(tex, left - tex.width - dp(4), y - tex.height / 2)

            # Axe du temps (temps de déplacement)
            total_s = len(self.values) * self.step_s
            start, end = self._text("0:00"), self._text(format_duration(total_s))
            self._draw_text(start, left, self.y)
            self._draw_text(end, left + width - end.width, self.y)

            # Courbe, interrompue là où la valeur est inconnue
            Color(*self.color)
            count = max(len(self.values) - 1, 1)
            segment = []
            for i, value in enumerate(self.values + [None]):
                if value is None:
                    if len(segment) >= 4:
                        Line(points=segment, width=dp(1.4))
                    elif len(segment) == 2:  # point isolé
                        Line(points=segment + [segment[0] + dp(1), segment[1]], width=dp(1.4))
                    segment = []
                    continue
                segment += [left + width * i / count, bottom + height * min(value / top_value, 1)]
