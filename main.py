"""D4speedmeter - compteur pour vélo électrique Rockrider E-ACTV 100 (Kivy / Android)."""

import json
import os
import time

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.utils import platform

import gauge  # noqa: F401  (enregistre le widget Gauge pour le fichier .kv)
import icons  # noqa: F401  (enregistre GearButton pour le fichier .kv)
from bike import create_bike_link
from trip import TripStats

try:
    from plyer import gps
except ImportError:  # plyer absent sur le poste de dev
    gps = None

__version__ = "0.5.0"
AUTHOR = "Bosoochee"
SUMMARY = (
    "D4speedmeter est un compteur pour le vélo électrique Decathlon Rockrider E-ACTV 100. "
    "Il se connecte au vélo en Bluetooth pour afficher la vitesse, la batterie et "
    "l'autonomie, et calcule la vitesse maximale, la vitesse moyenne et la distance "
    "parcourue depuis la dernière remise à zéro. Sans vélo connecté, la vitesse est "
    "mesurée par le GPS du téléphone."
)

MS_TO_KMH = 3.6
NOMINAL_RANGE_KM = 70      # autonomie annoncée par Decathlon, batterie pleine
BIKE_SPEED_TIMEOUT_S = 3   # au-delà, on repasse sur la vitesse GPS
TICK_S = 1.0
SAVE_EVERY_TICKS = 30
LOCATION_CHECK_TICKS = 5


def shared_files_dir(fallback):
    """Dossier lisible depuis un PC en USB (Android/data/<paquet>/files), sinon `fallback`."""
    if platform == "android":
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            path = activity.getExternalFilesDir(None).getAbsolutePath()
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            pass
    return fallback


class SpeedScreen(BoxLayout):
    speed = NumericProperty(0)
    max_speed = NumericProperty(0)
    avg_speed = NumericProperty(0)
    distance = NumericProperty(0)
    battery = NumericProperty(-1)      # -1 = inconnu
    range_km = NumericProperty(-1)     # -1 = inconnu
    range_estimated = BooleanProperty(True)
    speed_source = StringProperty("—")
    status = StringProperty("Vélo non connecté")
    bike_connected = BooleanProperty(False)
    inset_top = NumericProperty(0)     # barres système Android recouvrant l'appli (px)
    inset_bottom = NumericProperty(0)


class D4SpeedmeterApp(App):
    title = "D4speedmeter"
    version = __version__
    author = AUTHOR
    summary = SUMMARY

    def build(self):
        self.screen = SpeedScreen()
        self.trip = TripStats(os.path.join(self.user_data_dir, "trip.json"))
        self.files_dir = shared_files_dir(self.user_data_dir)
        self.log_path = os.path.join(self.files_dir, "ble_log.txt")
        self._insets_info = {}
        self.bike = create_bike_link(self.on_bike_data, self.on_bike_status,
                                     self.on_bike_devices, self.log_path)
        self._bike_speed = None
        self._bike_speed_time = 0.0
        self._gps_speed = None
        self._location_enabled = True
        self._ticks = 0
        self._devices_popup = None
        self._refresh_trip()
        Clock.schedule_interval(self._tick, TICK_S)
        return self.screen

    def on_start(self):
        if platform == "android":
            self.request_android_permissions()
            Window.bind(size=lambda *_: Clock.schedule_once(self.update_insets, 0.3))
            Clock.schedule_once(self.update_insets, 0.5)
        Clock.schedule_once(self.write_diagnostic, 4)

    def update_insets(self, *_):
        """Réserve la place des barres d'état/navigation si l'appli s'affiche dessous."""
        info = self._insets_info
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            decor = activity.getWindow().getDecorView()
            info["decor_size"] = [decor.getWidth(), decor.getHeight()]
            metrics = autoclass("android.util.DisplayMetrics")()
            activity.getWindowManager().getDefaultDisplay().getRealMetrics(metrics)
            info["real_display"] = [metrics.widthPixels, metrics.heightPixels, metrics.density]
            info["sdk"] = autoclass("android.os.Build$VERSION").SDK_INT
            insets = decor.getRootWindowInsets()
            if insets is None:
                info["insets"] = None
                return
            top, bottom = insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetBottom()
            info["insets"] = {"top": top, "bottom": bottom}
            # La surface Kivy ne passe sous les barres que si elle couvre tout l'écran
            edge_to_edge = Window.height >= decor.getHeight() - 1
            info["edge_to_edge"] = edge_to_edge
            self.screen.inset_top = top if edge_to_edge else 0
            self.screen.inset_bottom = bottom if edge_to_edge else 0
        except Exception as exc:  # API Android indisponible : on garde les marges par défaut
            info["error"] = repr(exc)

    def write_diagnostic(self, *_):
        """Écrit dimensions, marges et géométrie des widgets (debug)."""
        s = self.screen
        gauge = s.ids.gauge
        data = {
            "version": __version__,
            "window_size": list(Window.size),
            "system_size": list(Window.system_size),
            "dp1": dp(1), "sp1": sp(1),
            "insets_info": self._insets_info,
            "screen": {"pos": list(s.pos), "size": list(s.size),
                       "inset_top": s.inset_top, "inset_bottom": s.inset_bottom},
            "gauge": {"pos": list(gauge.pos), "size": list(gauge.size), "radius": gauge.radius,
                      "dial_cx": gauge.dial_cx, "dial_cy": gauge.dial_cy},
            "children_top_to_bottom": [
                {"type": type(w).__name__, "y": w.y, "height": w.height} for w in reversed(s.children)
            ],
        }
        try:
            with open(os.path.join(self.files_dir, "diagnostic.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def on_stop(self):
        self.trip.save()

    # ---------- Permissions / GPS ----------
    def request_android_permissions(self):
        from android.permissions import Permission, request_permissions

        perms = [Permission.ACCESS_FINE_LOCATION, Permission.ACCESS_COARSE_LOCATION]
        # Android 12+ : permissions Bluetooth dédiées
        for name in ("BLUETOOTH_SCAN", "BLUETOOTH_CONNECT"):
            if hasattr(Permission, name):
                perms.append(getattr(Permission, name))

        def callback(permissions, results):
            if all(results):
                self.start_gps()
            else:
                self.screen.status = "Permissions refusées : GPS/Bluetooth indisponibles"

        request_permissions(perms, callback)

    def start_gps(self):
        if gps is None:
            return
        try:
            gps.configure(on_location=self.on_location)
            gps.start(minTime=1000, minDistance=0)
        except NotImplementedError:
            pass

    @mainthread
    def on_location(self, **kwargs):
        self._gps_speed = float(kwargs.get("speed", 0) or 0) * MS_TO_KMH

    # ---------- Bluetooth ----------
    def bike_button(self):
        if self.bike.connected:
            self.bike.disconnect()
            self.screen.bike_connected = False
        else:
            self._devices_popup = Factory.DevicesPopup()
            self._devices_popup.open()
            self.bike.scan()

    def select_device(self, address):
        if self._devices_popup:
            self._devices_popup.dismiss()
        self.bike.connect(address)

    def on_bike_devices(self, devices):
        if not self._devices_popup:
            return
        box = self._devices_popup.ids.device_list
        box.clear_widgets()
        for name, address in devices:
            btn = Factory.DeviceButton(text=f"{name}\n[size=12sp]{address}[/size]")
            btn.bind(on_release=lambda _b, a=address: self.select_device(a))
            box.add_widget(btn)

    def on_bike_status(self, text):
        self.screen.status = text
        self.screen.bike_connected = self.bike.connected

    def on_bike_data(self, values):
        self.screen.bike_connected = True
        if "speed_kmh" in values:
            self._bike_speed = values["speed_kmh"]
            self._bike_speed_time = time.monotonic()
        if "battery_pct" in values:
            self.screen.battery = values["battery_pct"]
        if "range_km" in values:
            self.screen.range_km = values["range_km"]
            self.screen.range_estimated = False
        elif self.screen.battery >= 0 and self.screen.range_estimated:
            self.screen.range_km = self.screen.battery / 100 * NOMINAL_RANGE_KM

    # ---------- Mise à jour périodique ----------
    def _current_speed(self):
        if self._bike_speed is not None and \
                time.monotonic() - self._bike_speed_time < BIKE_SPEED_TIMEOUT_S:
            self.screen.speed_source = "vélo"
            return self._bike_speed
        if self._gps_speed is not None and self._location_enabled:
            self.screen.speed_source = "GPS"
            return self._gps_speed
        self.screen.speed_source = "—" if self._location_enabled else "GPS désactivé"
        return 0.0

    def _check_location_enabled(self):
        """Vérifie que la localisation du téléphone est activée (Android 9+)."""
        if platform != "android":
            return
        try:
            from jnius import autoclass

            context = autoclass("org.kivy.android.PythonActivity").mActivity
            manager = context.getSystemService(autoclass("android.content.Context").LOCATION_SERVICE)
            self._location_enabled = bool(manager.isLocationEnabled())
        except Exception:
            self._location_enabled = True

    def _tick(self, dt):
        if self._ticks % LOCATION_CHECK_TICKS == 0:
            self._check_location_enabled()
        speed = self._current_speed()
        Animation.cancel_all(self.screen, "speed")
        Animation(speed=speed, duration=0.6, t="out_quad").start(self.screen)
        self.trip.update(speed, dt)
        self._refresh_trip()
        self._ticks += 1
        if self._ticks % SAVE_EVERY_TICKS == 0:
            self.trip.save()

    def _refresh_trip(self):
        self.screen.max_speed = self.trip.max_kmh
        self.screen.avg_speed = self.trip.avg_kmh
        self.screen.distance = self.trip.distance_km

    def reset_trip(self):
        self.trip.reset()
        self._refresh_trip()

    # ---------- Paramètres ----------
    def open_settings_popup(self):
        Factory.SettingsPopup().open()

    # ---------- Cycle de vie Android ----------
    def on_pause(self):
        self.trip.save()
        return True  # garde la connexion Bluetooth et le GPS actifs


if __name__ == "__main__":
    D4SpeedmeterApp().run()
