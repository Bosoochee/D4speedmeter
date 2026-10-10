"""Connexion Bluetooth Low Energy au vélo (Rockrider E-ACTV 100, nom BLE « EB100 »).

Le protocole propriétaire du vélo a été reconstruit à partir d'une capture des échanges
avec l'appli Decathlon. Caractéristiques utilisées (repérées par leur handle GATT) :

- 0x0045 (écriture)  : canal de commande (init, lecture de registres, mode d'assistance) ;
- 0x0047 (notify)    : réponses aux commandes (non exploitées) ;
- 0x003a (notify)    : mesures - P hum (W/10), vitesse, P vélo (W/100), tension (mV) ;
- 0x003d (notify)    : statut - compteur total du vélo (odomètre) en mètres ;
- 0x0037 (indicate)  : événements - octet 2 = phare (0 éteint, 1 allumé ; le phare se
  commande au guidon, aucune commande BLE), octet 3 = mode d'assistance actif (1 Eco,
  2 Medium, 3 Boost) ; émis à chaque changement d'état et périodiquement.

La batterie (%) vient du Battery Service *standard* (0x2A19, handle 0x0033), vérifié
contre l'affichage du vélo. Le service standard vitesse/cadence (0x2A5B) est lu s'il
existe, et toutes les trames sont enregistrées dans le journal BLE.

Sur Android, la couche BLE repose sur la bibliothèque `able` (licence MIT), intégrée
au projet : code Python dans `able/`, code Java dans `java_src/`.
"""

import struct
import time
import traceback

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

# Handles GATT du protocole EB100. Sur Android, BluetoothGattCharacteristic.getInstanceId()
# renvoie le handle de la valeur de la caractéristique.
H_EVENTS = 0x0037
H_MEASURE = 0x003A
H_STATUS = 0x003D
H_COMMAND = 0x0045

ASSIST_MODES = {1: "Eco", 2: "Medium", 3: "Boost"}

# Registre lu par l'appli Decathlon à la connexion : il vaut toujours 0x64 et ce n'est
# PAS la batterie (le vélo affiche 65 % quand 0x2A19 vaut 65). On le lit pour reproduire
# la séquence de l'appli.
REG_41 = 0x41
BATTERY_POLL_S = 30
CMD_INIT = bytes.fromhex("010500000001")
# NB : « 02 05 00000020 0M » CHANGE le mode d'assistance (M = 1 Eco, 2 Medium, 3 Boost).
# L'appli ne l'envoie donc pas à la connexion : le flux de mesures démarre sans.


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


def cmd_read_register(register):
    return bytes((0x01, 0x01, 0x07, 0x41, 0x00, register))


def parse_measure(data):
    """Flux 0x003a : mots de 16 bits little-endian aux offsets 0, 6, 12 et 16."""
    if len(data) < 18:
        return {}
    power, speed, cadence, millivolts = (struct.unpack_from("<H", data, offset)[0]
                                         for offset in (0, 6, 12, 16))
    return {"power_w": power / 10, "speed_kmh": speed / 100,
            "cadence_rpm": cadence / 100, "voltage_v": millivolts / 1000}


def parse_status(data):
    """Flux 0x003d : octet 0 = batterie (%), puis compteur total en mètres (octets 1 à 4, LE)."""
    if len(data) < 5:
        return {}
    return {"odometer_m": struct.unpack_from("<I", data, 1)[0]}


def parse_events(data):
    """Événements 0x0037 : octet 2 = phare (0 éteint, 1 allumé), octet 3 = mode d'assistance."""
    values = {}
    if len(data) >= 3 and data[2] in (0, 1):
        values["light_on"] = bool(data[2])
    if len(data) >= 4 and data[3] in ASSIST_MODES:
        values["assist_mode"] = data[3]
    return values


PARSERS = {H_MEASURE: parse_measure, H_STATUS: parse_status, H_EVENTS: parse_events}


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
        self._odometer_m = 33557.0

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
        self._odometer_m += self._speed / 3.6 * dt
        moving = self._speed > 1
        self.on_data({
            "speed_kmh": self._speed,
            "cadence_rpm": self._speed * 2.2 if moving else 0.0,
            "power_w": self._rand.uniform(80, 250) if moving else 0.0,
            "voltage_v": 36 + 6 * self._battery / 100,
            "battery_pct": round(self._battery),
            "odometer_m": int(self._odometer_m),
            "assist_mode": 1 + int(time.monotonic() // 5) % 3,  # change toutes les 5 s
            "light_on": int(time.monotonic() // 7) % 2 == 1,     # bascule toutes les 7 s
        })


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

        def on_services(self, status, services):
            # able/android/jni.py envoie (status, services), à l'inverse de sa doc
            try:
                self.link.handle_services(services, status)
            except Exception:  # appelé depuis un thread Java : l'erreur serait perdue
                self.link.log("ERROR " + traceback.format_exc())

        def on_characteristic_read(self, characteristic, status):
            if status == GATT_SUCCESS:
                self.on_characteristic_changed(characteristic)

        def on_characteristic_changed(self, characteristic):
            try:
                self.link.handle_value(characteristic)
            except Exception:
                self.link.log("ERROR " + traceback.format_exc())

    class AndroidBikeLink(BikeLinkBase):
        SCAN_SECONDS = 10

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.ble = _BleDispatcher(self)
            self._found = {}
            self._csc = CscParser()
            self._command = None
            self._battery_char = None
            self._poll_event = None

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
            self._stop_polling()
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
                self._stop_polling()
                self._status("Connexion perdue")
                self.ble.close_gatt()

        def handle_services(self, services, status):
            if status != GATT_SUCCESS:
                self._status("Échec de la découverte des services")
                return
            # `able` met les opérations GATT en file d'attente : on peut tout demander d'un coup.
            self._command = None
            self._battery_char = None
            for service_uuid, chars in services.items():
                for char_uuid, char in chars.items():
                    props = char.getProperties()
                    handle = char.getInstanceId()
                    self.log(f"CHAR service={service_uuid} char={char_uuid} "
                             f"handle=0x{handle:04x} props=0x{props:02x}")
                    if handle == H_COMMAND:
                        self._command = char
                    if char_uuid == UUID_BATTERY_LEVEL:
                        self._battery_char = char
                    if props & PROP_NOTIFY:
                        self.ble.enable_notifications(char, True, False)
                    elif props & PROP_INDICATE:
                        self.ble.enable_notifications(char, True, True)
                    if props & PROP_READ:
                        self.ble.read_characteristic(char)
            if self._command is None:
                self.log("Canal de commande EB100 (handle 0x0045) introuvable")
                self._status("Vélo connecté (protocole EB100 non reconnu)")
                return
            # Début de la séquence de l'appli Decathlon : init, lecture du registre 0x41
            for command in (CMD_INIT, cmd_read_register(REG_41)):
                self._send(command)
            self._start_polling()
            self._status("Vélo connecté")

        def _send(self, command):
            if self._command is not None:
                self.log(f"SEND {command.hex(' ')}")
                self.ble.write_characteristic(self._command, command)

        @mainthread
        def _start_polling(self):
            """Relit la batterie régulièrement, en plus de ses notifications."""
            self._stop_polling()
            if self._battery_char is not None:
                self._poll_event = Clock.schedule_interval(
                    lambda dt: self.ble.read_characteristic(self._battery_char), BATTERY_POLL_S)

        def _stop_polling(self):
            if self._poll_event is not None:
                self._poll_event.cancel()
                self._poll_event = None

        # ----- Décodage -----
        def handle_value(self, characteristic):
            uuid = str(characteristic.getUuid().toString()).lower()
            handle = characteristic.getInstanceId()
            data = java_bytes(characteristic.getValue())
            self.log(f"DATA 0x{handle:04x} {uuid} {data.hex(' ')}")
            values = {}
            if uuid == UUID_BATTERY_LEVEL:
                values["battery_pct"] = parse_battery(data)
            elif uuid == UUID_CSC_MEASUREMENT:
                values["speed_kmh"] = self._csc.parse(data)
            elif handle in PARSERS:
                values.update(PARSERS[handle](data))
            values = {k: v for k, v in values.items() if v is not None}
            if values:
                self._data(values)

        # ----- Retour sur le thread UI -----
        def _status(self, text):
            self.log(f"STATUS {text}")
            self._status_ui(text)

        @mainthread
        def _status_ui(self, text):
            self.on_status(text)

        def _data(self, values):
            # Appelé directement depuis le thread Bluetooth (pas via @mainthread) : la boucle
            # Kivy est suspendue écran éteint, les mesures doivent continuer à être traitées.
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
