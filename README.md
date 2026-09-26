# D4speedmeter

Compteur pour le vélo électrique **Decathlon Rockrider E-ACTV 100**, écrit en Python avec Kivy (Android).

- Cadran 0–50 km/h + affichage numérique
- Vitesse max, vitesse moyenne, distance depuis le dernier reset (bouton « Remise à zéro »)
- Batterie du vélo (%) et autonomie
- Connexion Bluetooth Low Energy au vélo ; vitesse GPS du téléphone en secours
- Bouton « Paramètres » : version, auteur, résumé

## Bluetooth : état actuel

Le vélo communique avec l'appli *Decathlon Ride* via un protocole BLE **propriétaire et non documenté**.
L'application :

1. lit les services BLE **standard** s'ils existent : batterie (`0x180F`) et vitesse/cadence (`0x1816`) ;
2. s'abonne à **toutes** les caractéristiques du vélo et enregistre les trames brutes dans
   `ble_log.txt` (chemin affiché dans Paramètres) ;
3. passe les trames inconnues à `parse_proprietary()` dans [bike.py](bike.py), à compléter.

Pour décoder le protocole : roulez avec l'appli connectée, notez la vitesse/batterie/autonomie
affichées par l'écran du vélo, puis cherchez dans le journal les octets qui varient en conséquence.
Complétez ensuite `parse_proprietary()` pour renvoyer `speed_kmh`, `battery_pct`, `range_km`.

Tant que l'autonomie n'est pas lue sur le vélo, elle est **estimée** : `batterie % × 70 km`
(autonomie annoncée par Decathlon, constante `NOMINAL_RANGE_KM` dans [main.py](main.py)).

## Lancer sur PC (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Sur PC, « Connecter le vélo » propose un vélo simulé.

## Compiler l'APK Android

Buildozer ne fonctionne que sous Linux/macOS. Sous Windows, utilisez **WSL** (Ubuntu) :

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
    autoconf libtool pkg-config zlib1g-dev libncurses-dev cmake libffi-dev libssl-dev
pip install --user buildozer cython
cd /mnt/c/Users/jean_/source/repos/D4speedmeter
buildozer -v android debug
```

L'APK est généré dans `bin/` (`d4speedmeter-<version>-arm64-v8a-debug.apk`).

Particularités de [buildozer.spec](buildozer.spec), nécessaires avec python-for-android actuel (Python 3.14) :
- `kivy==2.3.1` (2.3.0 ne compile pas avec Python 3.14) ;
- `android.archs = arm64-v8a` seul : avec deux architectures, p4a corrompt son venv pip interne ;
- `charset_normalizer==3.4.5` (avec `_`) : évite qu'une roue binaire Android soit refusée par pip ;
- la bibliothèque BLE `able` est intégrée au projet (`able/` + `java_src/` via `android.add_src`). Pour l'installer sur un téléphone branché en USB (débogage activé) :

```bash
buildozer android deploy run logcat
```

## Structure

| Fichier | Rôle |
|---|---|
| `main.py` | Application : écran, GPS, permissions, popups |
| `bike.py` | Connexion BLE au vélo (lib `able`), décodage, vélo simulé |
| `able/`, `java_src/` | Bibliothèque BLE [able](https://github.com/b3b/able) 1.0.17 (MIT), partie Python et Java |
| `trip.py` | Distance, vitesse max/moyenne, sauvegarde |
| `gauge.py` | Widget cadran |
| `icons.py` | Bouton roue dentée (paramètres), dessiné en code |
| `assets/icon.png` | Icône de l'appli, générée par `tools_make_icon.py` (Pillow, non inclus dans l'APK) |
| `d4speedmeter.kv` | Interface |
| `buildozer.spec` | Configuration du build Android |
