"""Statistiques de trajet (distance, vitesse max, vitesse moyenne) persistées sur disque."""

import json
import os

MOVING_THRESHOLD_KMH = 1.0  # en dessous, on considère le vélo à l'arrêt


class TripStats:
    def __init__(self, path):
        self.path = path
        self.distance_km = 0.0
        self.max_kmh = 0.0
        self.moving_s = 0.0
        self.load()

    @property
    def avg_kmh(self):
        if self.moving_s < 1:
            return 0.0
        return self.distance_km / (self.moving_s / 3600)

    def update(self, speed_kmh, dt):
        """Intègre la vitesse courante sur dt secondes."""
        if speed_kmh < MOVING_THRESHOLD_KMH:
            return
        self.distance_km += speed_kmh * dt / 3600
        self.moving_s += dt
        self.max_kmh = max(self.max_kmh, speed_kmh)

    def reset(self):
        self.distance_km = 0.0
        self.max_kmh = 0.0
        self.moving_s = 0.0
        self.save()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.distance_km = float(data.get("distance_km", 0))
            self.max_kmh = float(data.get("max_kmh", 0))
            self.moving_s = float(data.get("moving_s", 0))
        except (OSError, ValueError):
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"distance_km": self.distance_km, "max_kmh": self.max_kmh,
                       "moving_s": self.moving_s}, f)
