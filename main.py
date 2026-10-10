"""D4speedmeter - compteur pour vélo électrique Rockrider E-ACTV 100 (Kivy / Android)."""

import json
import os
import threading
import time

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import FadeTransition, Screen, ScreenManager
from kivy.utils import platform

import gauge  # noqa: F401  (enregistre le widget Gauge pour le fichier .kv)
import icons  # noqa: F401  (enregistre GearButton pour le fichier .kv)
from bike import create_bike_link
from chart import HistoryChart, format_duration  # noqa: F401  (HistoryChart : fichier .kv)
from gpx import export_gpx
from trip import TripStats

__version__ = "0.13.1"
AUTHOR = "Bosoochee"
SUMMARY = (
    "D4speedmeter est un compteur pour le vélo électrique Decathlon Rockrider E-ACTV 100. "
    "Il se connecte au vélo en Bluetooth pour afficher la vitesse, la puissance humaine, la "
    "puissance du vélo et la batterie, et calcule le temps de déplacement, la vitesse moyenne et la "
    "distance parcourue (d'après le compteur total du vélo) depuis la dernière remise à "
    "zéro. Touchez le cadran, P hum ou P vélo pour voir la courbe du trajet. "
    "Sans vélo connecté, la vitesse est mesurée par le GPS du téléphone."
)

MS_TO_KMH = 3.6
BIKE_SPEED_TIMEOUT_S = 3   # au-delà, on repasse sur la vitesse GPS
GPS_MIN_SPEED_KMH = 5      # vitesse GPS en dessous : bruit de position à l'arrêt
GPS_CONFIRM_FIXES = 3      # positions successives au-dessus du seuil avant de compter le mouvement
GPS_MAX_ACCURACY_M = 20    # position moins précise (intérieur...) : vitesse GPS ignorée
TICK_S = 1.0
SAVE_EVERY_S = 10
LOCATION_CHECK_TICKS = 5
SPLASH_S = 3               # durée de l'écran de démarrage (un point de plus par seconde)

# Courbes : clé de l'historique -> (titre, unité, format des valeurs)
CHARTS = {
    "speed": ("Vitesse", "km/h", "{:.1f}"),
    "power": ("P hum", "W", "{:.0f}"),
    "cadence": ("P vélo", "W", "{:.0f}"),
}


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


def set_background_service(running):
    """Démarre/arrête le service de premier plan (fonctionnement écran éteint)."""
    if platform != "android":
        return
    try:
        from jnius import autoclass

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        service = autoclass("org.d4.KeepAliveService")
        if running:
            service.start(activity)
        else:
            service.stop(activity)
    except Exception as exc:
        print(f"KeepAliveService indisponible : {exc!r}")


def toast(text):
    """Message bref en bas de l'écran (Android), console sinon."""
    if platform != "android":
        print(text)
        return
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass, cast

        @run_on_ui_thread
        def show():
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            message = cast("java.lang.CharSequence", autoclass("java.lang.String")(text))
            autoclass("android.widget.Toast").makeText(activity, message, 1).show()

        show()
    except Exception as exc:
        print(f"Toast indisponible : {exc!r}")


class SplashScreen(FloatLayout):
    """Logo + « By Bosoochee » suivi d'un point de plus chaque seconde."""
    dots = NumericProperty(0)


class SpeedScreen(BoxLayout):
    speed = NumericProperty(0)
    avg_speed = NumericProperty(0)
    distance = NumericProperty(0)
    moving_time = StringProperty("0:00")
    clock = StringProperty("--:--")
    battery = NumericProperty(-1)      # -1 = inconnu
    power = NumericProperty(-1)        # -1 = inconnu
    cadence = NumericProperty(-1)      # -1 = inconnu
    odometer_km = NumericProperty(-1)  # -1 = inconnu
    gps_sats = NumericProperty(-1)     # satellites utilisés pour la position, -1 = inconnu
    assist_mode = NumericProperty(-1)  # 1 Eco, 2 Medium, 3 Boost, -1 = inconnu
    light_on = BooleanProperty(False)  # phare du vélo allumé
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
        # État partagé entre le thread de calcul, le Bluetooth et l'interface
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._bike_speed = None
        self._bike_speed_time = 0.0
        self._gps_speed = None
        self._power = None              # dernières mesures du vélo (None = inconnu)
        self._cadence = None
        self._assist_mode = None
        self._light_on = False
        self._speed = 0.0
        self._speed_source = "—"
        self._location_enabled = True
        self._gps = None                # org.d4.GpsMonitor (Android)
        self._gps_count = 0             # numéro de la dernière position GPS traitée
        self._gps_fast_fixes = 0        # positions successives au-dessus de GPS_MIN_SPEED_KMH
        self._map_popup = None
        self._ticks = 0
        self._devices_popup = None
        self._chart_popup = None
        self._refresh_ui()
        # Calculs dans un thread : la boucle Kivy (Clock) est suspendue écran éteint
        threading.Thread(target=self._worker, name="trip", daemon=True).start()
        Clock.schedule_interval(self._refresh_ui, TICK_S)

        self.splash = SplashScreen()
        self.root_manager = ScreenManager(transition=FadeTransition(duration=0.4))
        for name, widget in (("splash", self.splash), ("main", self.screen)):
            holder = Screen(name=name)
            holder.add_widget(widget)
            self.root_manager.add_widget(holder)
        self._splash_event = Clock.schedule_interval(self._splash_tick, 1)
        return self.root_manager

    def _splash_tick(self, dt):
        self.splash.dots += 1
        if self.splash.dots >= SPLASH_S:
            self._splash_event.cancel()
            Clock.schedule_once(lambda dt: setattr(self.root_manager, "current", "main"), 0.6)

    def on_start(self):
        if platform == "android":
            self.keep_screen_on()
            self.request_android_permissions()
            Window.bind(size=lambda *_: Clock.schedule_once(self.update_insets, 0.3))
            Clock.schedule_once(self.update_insets, 0.5)
        Clock.schedule_once(self.write_diagnostic, SPLASH_S + 2)

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
        self._stopping.set()
        self.save_state()

    def save_state(self):
        with self._lock:
            self.trip.save()

    # ---------- Permissions / GPS ----------
    def request_android_permissions(self):
        from android.permissions import Permission, request_permissions

        perms = [Permission.ACCESS_FINE_LOCATION, Permission.ACCESS_COARSE_LOCATION]
        # Android 12+ : permissions Bluetooth dédiées
        for name in ("BLUETOOTH_SCAN", "BLUETOOTH_CONNECT"):
            if hasattr(Permission, name):
                perms.append(getattr(Permission, name))
        # Android 13+ : notification du service de tâche de fond (facultative)
        optional = [Permission.POST_NOTIFICATIONS] if hasattr(Permission, "POST_NOTIFICATIONS") else []

        def callback(permissions, results):
            granted = dict(zip(permissions, results))
            self._on_permissions(all(granted.get(p, True) for p in perms))

        request_permissions(perms + optional, callback)

    @mainthread
    def _on_permissions(self, granted):
        if granted:
            self.start_gps()
        else:
            self.screen.status = "Permissions refusées : GPS/Bluetooth indisponibles"
        # Après les permissions Bluetooth/localisation : Android 14 les exige pour ce service
        set_background_service(True)
        self._check_location_enabled()
        if granted and not self._location_enabled:
            Factory.GpsOffPopup().open()

    def start_gps(self):
        """Démarre le relais GPS Java (positions + satellites), lu par le thread de calcul."""
        if platform != "android":
            return
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            monitor = autoclass("org.d4.GpsMonitor")
            if monitor.start(activity):
                self._gps = monitor
        except Exception as exc:
            print(f"GpsMonitor indisponible : {exc!r}")

    def open_location_settings(self):
        """Ouvre les réglages Android de localisation pour activer le GPS."""
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            intent = autoclass("android.content.Intent")(
                autoclass("android.provider.Settings").ACTION_LOCATION_SOURCE_SETTINGS)
            activity.startActivity(intent)
        except Exception as exc:
            print(f"Réglages de localisation indisponibles : {exc!r}")

    def on_position(self, lat, lon, speed_ms=None, accuracy_m=None):
        """Nouvelle position GPS : vitesse de secours et tracé (à appeler sous self._lock)."""
        precise = accuracy_m is None or accuracy_m <= GPS_MAX_ACCURACY_M
        self._gps_speed = speed_ms * MS_TO_KMH if speed_ms is not None and precise else None
        if self._gps_speed is not None and self._gps_speed >= GPS_MIN_SPEED_KMH:
            self._gps_fast_fixes += 1
        else:
            self._gps_fast_fixes = 0
        self.trip.add_position(lat, lon, accuracy_m)

    def _poll_gps(self):
        """Lit la dernière position du relais Java (thread de calcul, sous self._lock)."""
        gps = self._gps
        if gps is None:
            return
        count = gps.getLocationCount()
        if count != self._gps_count:
            self._gps_count = count
            speed, accuracy = gps.getSpeed(), gps.getAccuracy()
            self.on_position(gps.getLatitude(), gps.getLongitude(),
                             speed if speed >= 0 else None, accuracy if accuracy >= 0 else None)
        elif not gps.hasRecentLocation():
            self._gps_speed = None  # plus de position : pas de vitesse GPS périmée
            self._gps_fast_fixes = 0

    def _satellites(self):
        """Satellites utilisés pour la position, -1 si inconnu (pas d'Android)."""
        if self._gps is None:
            return -1
        if not self._location_enabled:
            return 0
        try:
            return int(self._gps.getUsedInFix())
        except Exception:
            return -1

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
        if not self.bike.connected:  # mesures instantanées périmées
            with self._lock:
                self._power = self._cadence = self._assist_mode = None
                self._light_on = False
        self._refresh_ui()

    def on_bike_data(self, values):
        """Appelé depuis le thread Bluetooth, y compris écran éteint."""
        with self._lock:
            if "speed_kmh" in values:
                self._bike_speed = values["speed_kmh"]
                self._bike_speed_time = time.monotonic()
            if "battery_pct" in values:
                self.trip.battery_pct = values["battery_pct"]
            if "power_w" in values:
                self._power = values["power_w"]
            if "cadence_rpm" in values:
                self._cadence = values["cadence_rpm"]
            if "assist_mode" in values:
                self._assist_mode = values["assist_mode"]
            if "light_on" in values:
                self._light_on = values["light_on"]
            if "odometer_m" in values:
                self.trip.update_odometer(values["odometer_m"])

    # ---------- Calcul en tâche de fond ----------
    def _current_speed(self):
        """Vitesse courante et sa source (à appeler sous self._lock)."""
        if self._bike_speed is not None and \
                time.monotonic() - self._bike_speed_time < BIKE_SPEED_TIMEOUT_S:
            return self._bike_speed, "vélo"
        if self._gps_speed is not None and self._location_enabled:
            # À l'arrêt, le GPS « bouge » de quelques km/h : vitesse nulle tant que le
            # mouvement n'est pas confirmé par plusieurs positions au-dessus du seuil
            moving = self._gps_fast_fixes >= GPS_CONFIRM_FIXES
            return (self._gps_speed if moving else 0.0), "GPS"
        return 0.0, "—" if self._location_enabled else "GPS désactivé"

    def _worker(self):
        """Intègre le trajet chaque seconde et sauvegarde régulièrement, écran éteint compris."""
        last = last_save = time.monotonic()
        while not self._stopping.wait(TICK_S):
            now = time.monotonic()
            dt = min(now - last, 2 * TICK_S)  # pas de rattrapage après une suspension
            last = now
            with self._lock:
                try:
                    self._poll_gps()
                except Exception as exc:  # relais Java indisponible : on garde le reste
                    print(f"Lecture GPS impossible : {exc!r}")
                self._speed, self._speed_source = self._current_speed()
                self.trip.update(dt, self._speed, self._power, self._cadence)
                if now - last_save >= SAVE_EVERY_S:
                    self.trip.save()
                    last_save = now

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

    # ---------- Affichage (boucle Kivy, au premier plan) ----------
    def _refresh_ui(self, *_):
        if self._ticks % LOCATION_CHECK_TICKS == 0:
            self._check_location_enabled()
        self._ticks += 1
        s = self.screen
        with self._lock:
            speed, s.speed_source = self._speed, self._speed_source
            s.power = -1 if self._power is None else self._power
            s.cadence = -1 if self._cadence is None else self._cadence
            s.assist_mode = -1 if self._assist_mode is None else self._assist_mode
            s.light_on = self._light_on
            s.battery = -1 if self.trip.battery_pct is None else self.trip.battery_pct
            s.avg_speed = self.trip.avg_kmh
            s.distance = self.trip.distance_km
            s.moving_time = format_duration(self.trip.moving_s)
            if self.trip.odometer_m is not None:
                s.odometer_km = self.trip.odometer_m / 1000
            self._update_chart()
            track = self.trip.track
            if self._map_popup is not None and len(track) != len(self._map_popup.map.track_layer.points):
                self._map_popup.map.track_layer.points = [tuple(p) for p in track]
        s.gps_sats = self._satellites()
        s.clock = time.strftime("%H:%M")
        Animation.cancel_all(s, "speed")
        Animation(speed=speed, duration=0.6, t="out_quad").start(s)

    def open_reset_popup(self):
        popup = Factory.ResetPopup()
        with self._lock:
            popup.gps_points = sum(1 for p in self.trip.track if len(p) >= 3)
        popup.open()

    def reset_trip(self, export=False):
        with self._lock:
            track, description = list(self.trip.track), self._trip_description()
            self.trip.reset()
        self._refresh_ui()
        if export:
            try:
                location = export_gpx(track, description, self.files_dir)
                toast(f"Parcours enregistré : {location}" if location else "Pas de parcours GPS.")
            except Exception as exc:
                toast(f"Export du parcours impossible : {exc}")

    def _trip_description(self):
        """Résumé du trajet pour le fichier GPX (à appeler sous self._lock)."""
        t = self.trip
        lines = []
        if t.distance_km > 0:
            lines.append(f"Distance (compteur du vélo) : {t.distance_km:.2f} km")
        lines.append(f"Temps de déplacement : {format_duration(t.moving_s)}")
        lines.append(f"Vitesse moyenne : {t.avg_kmh:.1f} km/h · max {t.peak['speed']:.1f} km/h")
        if t.peak["power"] > 0:
            lines.append(f"P hum moyenne : {t.mean('power'):.0f} W · max {t.peak['power']:.0f} W")
        if t.peak["cadence"] > 0:
            lines.append(f"P vélo moyenne : {t.mean('cadence'):.0f} W · max {t.peak['cadence']:.0f} W")
        lines.append("Enregistré avec D4speedmeter (Rockrider E-ACTV 100)")
        return "\n".join(lines)

    # ---------- Arrêt ----------
    def quit_app(self):
        """Bouton « Quitter » : sauvegarde, coupe le Bluetooth et le service, ferme l'appli."""
        self._stopping.set()
        self.save_state()
        if self.bike.connected:
            self.bike.disconnect()
        set_background_service(False)
        self.stop()

    # ---------- Courbes ----------
    def open_chart(self, key):
        title, unit, _ = CHARTS[key]
        popup = Factory.ChartPopup(title=f"{title} depuis le dernier reset ({unit})")
        popup.key = key
        popup.bind(on_dismiss=lambda *_: setattr(self, "_chart_popup", None))
        self._chart_popup = popup
        with self._lock:
            self._update_chart()
        popup.open()

    def _update_chart(self):
        """Met à jour la courbe ouverte (à appeler sous self._lock)."""
        popup = self._chart_popup
        if popup is None:
            return
        _, unit, fmt = CHARTS[popup.key]
        chart = popup.ids.chart
        chart.step_s = self.trip.history_step_s
        chart.values = list(self.trip.history[popup.key])
        mean = self.trip.avg_kmh if popup.key == "speed" else self.trip.mean(popup.key)
        popup.summary = (f"Max : {fmt.format(self.trip.peak[popup.key])} {unit}     "
                         f"Moyenne : {fmt.format(mean)} {unit}")

    # ---------- Carte du tracé GPS ----------
    def open_map(self):
        from trackmap import TrackMap  # import tardif : la carte n'est pas utile au démarrage

        popup = Factory.MapPopup()
        popup.map = TrackMap(cache_dir=os.path.join(self.user_data_dir, "tiles"))
        popup.ids.map_holder.add_widget(popup.map)
        with self._lock:
            points = list(self.trip.track)
        popup.bind(on_dismiss=lambda *_: setattr(self, "_map_popup", None))
        self._map_popup = popup
        popup.open()
        # La taille de la carte n'est connue qu'après l'ouverture
        Clock.schedule_once(lambda dt: popup.map.show_track(points), 0.2)

    def recenter_map(self):
        if self._map_popup is not None:
            self._map_popup.map.fit_track()

    # ---------- Paramètres ----------
    def open_settings_popup(self):
        Factory.SettingsPopup().open()

    # ---------- Cycle de vie Android ----------
    def keep_screen_on(self):
        """Empêche la mise en veille de l'écran tant que l'appli est affichée."""
        from android.runnable import run_on_ui_thread
        from jnius import autoclass

        @run_on_ui_thread
        def _add_flag():
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            params = autoclass("android.view.WindowManager$LayoutParams")
            activity.getWindow().addFlags(params.FLAG_KEEP_SCREEN_ON)

        _add_flag()

    def on_pause(self):
        self.save_state()
        return True  # le thread de calcul et le Bluetooth continuent (service de premier plan)

    def on_resume(self):
        if platform == "android":
            self.keep_screen_on()


if __name__ == "__main__":
    D4SpeedmeterApp().run()
