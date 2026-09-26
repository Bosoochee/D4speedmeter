"""Boutons-icônes dessinés (la police par défaut de Kivy n'a pas ces symboles)."""

import math

from kivy.graphics import Color, Line
from kivy.metrics import dp
from kivy.uix.button import Button


class GearButton(Button):
    """Bouton affichant une roue dentée (paramètres)."""

    TEETH = 8

    def __init__(self, **kwargs):
        kwargs.setdefault("text", "")
        super().__init__(**kwargs)
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_):
        self.canvas.after.clear()
        size = min(self.width, self.height) * 0.62
        cx, cy = self.center
        r_out, r_in, r_hole = size / 2, size / 2 * 0.74, size / 2 * 0.32
        step = 2 * math.pi / self.TEETH
        points = []
        for k in range(self.TEETH):
            a = k * step
            for offset, radius in ((-0.30, r_in), (-0.18, r_out), (0.18, r_out), (0.30, r_in)):
                angle = a + offset * step
                points += [cx + radius * math.cos(angle), cy + radius * math.sin(angle)]
        width = max(dp(1.4), size * 0.06)
        with self.canvas.after:
            Color(1, 1, 1, 1)
            Line(points=points, close=True, width=width, joint="miter")
            Line(circle=(cx, cy, r_hole), width=width)
