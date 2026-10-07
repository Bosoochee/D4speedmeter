"""Statistiques de trajet persistées sur disque.

- distance : différence entre le compteur total du vélo (odomètre, en mètres) et la
  valeur mémorisée lors de la dernière remise à zéro ;
- temps de déplacement : ne compte que lorsque le vélo roule ;
- vitesse, puissance et cadence : maximum, moyenne et historique (pour les courbes) ;
- tracé GPS (pour la carte).
"""

import json
import math
import os

MOVING_THRESHOLD_KMH = 1.0  # en dessous, on considère le vélo à l'arrêt
SERIES = ("speed", "power", "cadence")
MAX_POINTS = 1200           # au-delà, l'historique est sous-échantillonné par 2
TRACK_MIN_STEP_M = 5        # tracé GPS : distance minimale entre deux points
TRACK_MAX_ACCURACY_M = 30   # tracé GPS : positions moins précises ignorées
EARTH_RADIUS_M = 6371000


def distance_m(a, b):
    """Distance entre deux points (lat, lon) en mètres (haversine)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _mean(values):
    known = [v for v in values if v is not None]
    return round(sum(known) / len(known), 2) if known else None


class TripStats:
    def __init__(self, path):
        self.path = path
        self.odometer_m = None   # dernier compteur total lu sur le vélo
        self.reference_m = None  # compteur total mémorisé à la remise à zéro
        self.battery_pct = None  # dernière batterie lue (réaffichée au redémarrage)
        self._clear()
        self.load()

    def _clear(self):
        self.moving_s = 0.0
        self.peak = dict.fromkeys(SERIES, 0.0)
        self._sum = dict.fromkeys(SERIES, 0.0)      # intégrale valeur × temps
        self._known_s = dict.fromkeys(SERIES, 0.0)  # durée pendant laquelle la valeur est connue
        # Historique : un point par `history_step_s` secondes de déplacement (None = inconnu)
        self.history = {key: [] for key in SERIES}
        self.history_step_s = 1.0
        self.track = []  # tracé GPS : [[lat, lon], ...]
        self._clear_bucket()

    def _clear_bucket(self):
        self._bucket = {key: [0.0, 0.0] for key in SERIES}  # (intégrale, durée connue)
        self._bucket_s = 0.0

    @property
    def distance_km(self):
        if self.odometer_m is None or self.reference_m is None:
            return 0.0
        return max(0, self.odometer_m - self.reference_m) / 1000

    @property
    def max_kmh(self):
        return self.peak["speed"]

    @property
    def avg_kmh(self):
        if self.moving_s < 1:
            return 0.0
        if self.distance_km > 0:
            return self.distance_km / (self.moving_s / 3600)
        return self.mean("speed")  # pas d'odomètre (vitesse GPS)

    def mean(self, key):
        return self._sum[key] / self._known_s[key] if self._known_s[key] >= 1 else 0.0

    def update(self, dt, speed_kmh, power_w=None, cadence_rpm=None):
        """Cumule temps de déplacement, maximums, moyennes et historique sur dt secondes."""
        if speed_kmh < MOVING_THRESHOLD_KMH:
            return
        self.moving_s += dt
        values = {"speed": speed_kmh, "power": power_w, "cadence": cadence_rpm}
        for key, value in values.items():
            if value is None:
                continue
            self.peak[key] = max(self.peak[key], value)
            self._sum[key] += value * dt
            self._known_s[key] += dt
            self._bucket[key][0] += value * dt
            self._bucket[key][1] += dt
        self._bucket_s += dt
        if self._bucket_s >= self.history_step_s:
            for key, (total, known) in self._bucket.items():
                self.history[key].append(round(total / known, 2) if known else None)
            self._clear_bucket()
            if len(self.history["speed"]) > MAX_POINTS:
                for key, points in self.history.items():
                    self.history[key] = [_mean(points[i:i + 2]) for i in range(0, len(points), 2)]
                self.history_step_s *= 2

    def add_position(self, lat, lon, accuracy_m=None):
        """Ajoute une position GPS au tracé si elle est précise et assez éloignée de la précédente."""
        if accuracy_m is not None and accuracy_m > TRACK_MAX_ACCURACY_M:
            return
        point = [round(lat, 6), round(lon, 6)]
        # Écart inférieur à l'incertitude de position : bruit GPS, pas un déplacement
        min_step = max(TRACK_MIN_STEP_M, accuracy_m or 0)
        if self.track and distance_m(self.track[-1], point) < min_step:
            return
        self.track.append(point)

    def update_odometer(self, odometer_m):
        self.odometer_m = odometer_m
        # Pas encore de référence (remise à zéro faite vélo déconnecté) ou compteur du
        # vélo revenu en arrière (autre vélo) : le trajet repart de ce point.
        if self.reference_m is None or odometer_m < self.reference_m:
            self.reference_m = odometer_m

    def reset(self):
        self.reference_m = self.odometer_m
        self._clear()
        self.save()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.odometer_m = data.get("odometer_m")
            self.reference_m = data.get("reference_m")
            self.battery_pct = data.get("battery_pct")
            self.moving_s = float(data.get("moving_s", 0))
            self.peak.update(data.get("peak", {"speed": float(data.get("max_kmh", 0))}))
            self._sum.update(data.get("sum", {}))
            self._known_s.update(data.get("known_s", {}))
            self.history.update(data.get("history", {}))
            self.history_step_s = float(data.get("history_step_s", 1.0))
            self.track = data.get("track", [])
        except (OSError, ValueError, TypeError):
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # Fichier temporaire puis renommage : un arrêt brutal ne corrompt pas la sauvegarde
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"odometer_m": self.odometer_m, "reference_m": self.reference_m,
                       "battery_pct": self.battery_pct,
                       "moving_s": self.moving_s, "peak": self.peak, "sum": self._sum,
                       "known_s": self._known_s, "history": self.history,
                       "history_step_s": self.history_step_s, "track": self.track}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self.path)
