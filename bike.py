"""Connexion Bluetooth Low Energy au vélo (Rockrider E-ACTV 100).

Le protocole Bluetooth du vélo est propriétaire (utilisé par l'appli Decathlon Ride)
et n'est pas documenté publiquement. Ce module :

1. lit les services BLE *standard* s'ils sont exposés par le vélo :
   - Battery Service (0x180F / 0x2A19)            -> batterie en %
   - Cycling Speed and Cadence (0x1816 / 0x2A5B)  -> vitesse (tours de roue)
2. s'abonne à *toutes* les caractéristiques notifiables et enregistre les trames
   brutes dans un journal, pour permettre de décoder le protocole propriétaire ;
3. passe chaque trame inconnue à `parse_proprietary()`, à compléter une fois
   le protocole identifié.

Sur Android, la couche BLE repose sur la bibliothèque `able` (licence MIT), intégrée
au projet : code Python dans `able/`, code Java dans `java_src/`.
"""

import struct
import time

from kivy.clock import Clock, mainthread
from kivy.utils import platform

WHEEL_CIRCUMFERENCE_M = 2.19  # roue 27,5" x 2,2 environ ; à ajuster si besoin

UUID_BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"
UUID_CSC_MEASUREMENT = "00002a5b-0000-1000-8000-00805f9b34fb"

PROP_NOTIFY = 0x10
PROP_INDICATE = 0x20
PROP_READ = 0x02
STATE_CONNECTED = 2  # android.bluetooth.BluetoothProfile.STATE_CONNECTED
UNNAMED = "(sans nom)"


def java_bytes(value):
    """Convertit un byte[] Java (entiers signés via pyjnius) en bytes Python."""
    return bytes((b & 0xFF) for b in (value or []))


def parse_battery(data):
    return data[0] if data else None


class CscParser:
    """Décode la caractéristique CSC Measurement (0x2A5B) en vitesse km/h."""

    def __init__(self):
        self._last = None  # (tours cumulés, horodatage en 1/1024 s)

    def parse(self, data):
        if not data or not (data[0] & 0x01) or len(data) < 7:
            return None
        revs, event_time = struct.unpack_from("<IH", data, 1)
        last, self._last = self._last, (revs, event_time)
        if last is None:
            return None
        d_revs = (revs - last[0]) & 0xFFFFFFFF
        d_time = ((event_time - last[1]) & 0xFFFF) / 1024
        if d_time <= 0:
            return 0.0 if d_revs == 0 else None
        return d_revs * WHEEL_CIRCUMFERENCE_M / d_time * 3.6


def parse_proprietary(uuid, data):
    """Décode une trame propriétaire Decathlon.

    Retourne un dict avec tout ou partie des clés : speed_kmh, battery_pct, range_km.
    Le format n'étant pas documenté, rien n'est décodé pour l'instant : utilisez le
    journal BLE (voir Paramètres) pour identifier les octets correspondants.
    """
    return {}


class BikeLinkBase:
    """Interface commune : les callbacks reçoivent des valeurs déjà décodées."""

    def __init__(self, on_data, on_status, on_devices, log_path=None):
        self.on_data = on_data          # on_data(dict)
        self.on_status = on_status      # on_status(str)
        self.on_devices = on_devices    # on_devices(list[(nom, adresse)])
        self.log_path = log_path
        self.connected = False

    def log(self, line):
        if not self.log_path:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {line}\n")
        except OSError:
            pass

    def scan(self):
        raise NotImplementedError

    def connect(self, address):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError


class SimulatedBike(BikeLinkBase):
    """Vélo simulé pour tester l'interface sur PC."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._event = None
        self._speed = 0.0
        self._battery = 100.0

    def scan(self):
        self.on_status("Recherche (simulation)...")
        Clock.schedule_once(lambda dt: self.on_devices([("E-ACTV 100 (simulé)", "SIM")]), 1)

    def connect(self, address):
        import random
        self._rand = random
        self.connected = True
        self.on_status("Connecté au vélo simulé")
        self._event = Clock.schedule_interval(self._tick, 0.5)

    def disconnect(self):
        if self._event:
            self._event.cancel()
        self.connected = False
        self.on_status("Déconnecté")

    def _tick(self, dt):
        self._speed = max(0.0, min(self._speed + self._rand.uniform(-3, 3.5), 32.0))
        self._battery = max(0.0, self._battery - 0.02)
        self.on_data({"speed_kmh": self._speed, "battery_pct": self._battery})


if platform == "android":
    from able import GATT_SUCCESS, BluetoothDispatcher
    from able.permissions import SDK_INT, Permission

    class _BleDispatcher(BluetoothDispatcher):
        """Relaie les événements `able` vers AndroidBikeLink."""

        def __init__(self, link, **kwargs):
            self.link = link
            # Par défaut, able exige aussi BLUETOOTH_ADVERTISE (inutile ici, non déclarée
            # dans le manifeste) et bloque alors tout scan : on limite la liste.
            if SDK_INT >= 31:
                kwargs.setdefault("runtime_permissions", [
                    Permission.BLUETOOTH_SCAN, Permission.BLUETOOTH_CONNECT,
                    Permission.ACCESS_FINE_LOCATION])
            super().__init__(**kwargs)

        def on_device(self, device, rssi, advertisement):
            self.link.handle_device(device)

        def on_scan_completed(self):
            self.link.handle_scan_completed()

        def on_connection_state_change(self, status, state):
            self.link.handle_connection(status, state)

        def on_services(self, services, status):
            self.link.handle_services(services, status)

        def on_characteristic_read(self, characteristic, status):
            if status == GATT_SUCCESS:
                self.link.handle_value(characteristic)

        def on_characteristic_changed(self, characteristic):
            self.link.handle_value(characteristic)

    class AndroidBikeLink(BikeLinkBase):
        SCAN_SECONDS = 10

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.ble = _BleDispatcher(self)
            self._found = {}
            self._csc = CscParser()

        # ----- Scan -----
        def scan(self):
            self._found = {}
            self._status("Recherche du vélo...")
            self.ble.start_scan()
            Clock.schedule_once(lambda dt: self.ble.stop_scan(), self.SCAN_SECONDS)

        def handle_device(self, device):
            address = device.getAddress()
            if address not in self._found:
                self._found[address] = (device.getName() or UNNAMED, device)
                self._devices()

        def handle_scan_completed(self):
            if not self._found:
                self._status("Aucun appareil trouvé")

        # ----- Connexion -----
        def connect(self, address):
            self.ble.stop_scan()
            entry = self._found.get(address)
            if entry is None:
                self._status("Appareil introuvable")
                return
            self._status(f"Connexion à {entry[0]}...")
            self.log(f"CONNECT {entry[0]} {address}")
            self.ble.connect_gatt(entry[1])

        def disconnect(self):
            self.ble.close_gatt()
            self.connected = False
            self._status("Déconnecté")

        def handle_connection(self, status, state):
            if status == GATT_SUCCESS and state == STATE_CONNECTED:
                self.connected = True
                self._status("Connecté - découverte des services...")
                self.ble.discover_services()
            else:
                self.connected = False
                self._status("Connexion perdue")
                self.ble.close_gatt()

        def handle_services(self, services, status):
            if status != GATT_SUCCESS:
                self._status("Échec de la découverte des services")
                return
            # `able` met les opérations GATT en file d'attente : on peut tout demander d'un coup.
            for service_uuid, chars in services.items():
                for char_uuid, char in chars.items():
                    props = char.getProperties()
                    self.log(f"CHAR service={service_uuid} char={char_uuid} props=0x{props:02x}")
                    if props & PROP_NOTIFY:
                        self.ble.enable_notifications(char, True, False)
                    elif props & PROP_INDICATE:
                        self.ble.enable_notifications(char, True, True)
                    if props & PROP_READ:
                        self.ble.read_characteristic(char)
            self._status("Vélo connecté")

        # ----- Décodage -----
        def handle_value(self, characteristic):
            uuid = str(characteristic.getUuid().toString()).lower()
            data = java_bytes(characteristic.getValue())
            self.log(f"DATA {uuid} {data.hex(' ')}")
            values = {}
            if uuid == UUID_BATTERY_LEVEL:
                values["battery_pct"] = parse_battery(data)
            elif uuid == UUID_CSC_MEASUREMENT:
                values["speed_kmh"] = self._csc.parse(data)
            else:
                values.update(parse_proprietary(uuid, data))
            values = {k: v for k, v in values.items() if v is not None}
            if values:
                self._data(values)

        # ----- Retour sur le thread UI -----
        @mainthread
        def _status(self, text):
            self.on_status(text)

        @mainthread
        def _data(self, values):
            self.on_data(values)

        @mainthread
        def _devices(self):
            # Appareils nommés d'abord (le vélo diffuse un nom), puis les anonymes
            devices = [(name, addr) for addr, (name, _) in self._found.items()]
            devices.sort(key=lambda d: (d[0] == UNNAMED, d[0].lower()))
            self.on_devices(devices)


def create_bike_link(on_data, on_status, on_devices, log_path=None):
    if platform == "android":
        return AndroidBikeLink(on_data, on_status, on_devices, log_path)
    return SimulatedBike(on_data, on_status, on_devices, log_path)
