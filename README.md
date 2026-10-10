# D4speedmeter

Compteur pour le vélo électrique **Decathlon Rockrider E-ACTV 100**, écrit en Python avec Kivy (Android).

- Cadran 0–50 km/h + affichage numérique ; cercle aux couleurs du mode d'assistance du vélo
  (Eco vert, Medium orange, Boost rouge)
- Voyant du phare du vélo sous le titre (gris : éteint, vert : allumé)
- Écran de démarrage : logo + « By Bosoochee » (un point de plus par seconde)
- Vitesse, P hum (puissance humaine, W) et P vélo (puissance du moteur, W) fournies par le vélo
- Temps de déplacement (arrêté quand le vélo ne roule pas), vitesse moyenne, distance
  depuis le dernier reset (bouton « Trip reset ») ; heure du téléphone
- Toucher le cadran, P hum ou P vélo : courbe depuis le dernier reset, avec
  maximum et moyenne (remis à zéro par « Trip reset »)
- Batterie du vélo (%)
- Connexion Bluetooth Low Energy au vélo ; vitesse GPS du téléphone en secours
- Voyant GPS dans le cadran (rouge : aucun satellite, orange : moins de 5, vert : 5 ou plus) ;
  le toucher affiche le tracé GPS du trajet sur une carte OpenTopoMap (effacé par « Trip reset »)
- Au lancement, propose d'activer la localisation si elle est coupée
- Fonctionne écran éteint (service de premier plan + notification) ; bouton rond marche/arrêt
  pour quitter ; toutes les données sont sauvegardées et réaffichées au redémarrage
- « Trip reset » demande confirmation et peut d'abord exporter le parcours GPS en GPX
- Bouton « Paramètres » : version, auteur, km total du vélo, résumé

## Export du parcours (Strava...)

Au « Trip reset », « Exporter le parcours et remettre à zéro » enregistre le tracé GPS en
fichier GPX dans **Téléchargements/D4speedmeter** puis ouvre le menu de partage Android
(Drive, mail...). Pour Strava (compte gratuit) : sur <https://www.strava.com/upload/select>,
importer le fichier depuis le navigateur du téléphone ou d'un PC. Le fichier contient
aussi un résumé (distance, temps, vitesse, P hum, P vélo). Code : [gpx.py](gpx.py).

L'envoi automatique par l'API Strava n'est pas utilisé : il exige un abonnement Strava.
Seuls les points GPS horodatés (enregistrés depuis la version 0.12.0) sont exportés.

## Protocole Bluetooth (EB100)

Le vélo s'annonce en BLE sous le nom `EB100`. Son protocole propriétaire a été reconstruit
à partir d'une capture des échanges avec l'appli Decathlon ; il est décodé dans [bike.py](bike.py).
Les caractéristiques sont repérées par leur handle GATT (`getInstanceId()` sous Android) :

| Handle | Rôle | Contenu |
|---|---|---|
| `0x0045` | commande (écriture) | init `01 05 00000001`, lecture registre `01 01 07 41 00 RR`, réglage du mode d'assistance `02 05 00000020 0M` (M = 1 Eco, 2 Medium, 3 Boost) |
| `0x0047` | réponse (notify) | écho de la commande + valeur ; trames `FF` = remplissage. Le registre `0x41` vaut toujours `0x64` : ce n'est **pas** la batterie |
| `0x0033` | batterie (standard `0x2A19`, read/notify) | batterie en %, octet décimal (`0x41` = 65 %, vérifié sur l'écran du vélo) |
| `0x003a` | mesures (notify) | mots 16 bits LE : P hum W×100 (offset 0), vitesse km/h×100 (6), P vélo W×10 (12), tension mV (16) |
| `0x003d` | statut (notify) | `41` puis compteur total du vélo en mètres (octets 1-4, LE) ; vérifié : +281 m pour 280 m intégrés depuis la vitesse |
| `0x0037` | événements (indicate) | octet 2 = phare (0 éteint, 1 allumé ; commandé au guidon, pas de commande BLE), octet 3 = mode d'assistance actif (1 Eco, 2 Medium, 3 Boost) ; à chaque changement et périodiquement |

À la connexion, l'appli envoie l'init et la lecture du registre `0x41` (comme l'appli
Decathlon), mais **pas** de commande `02 05` : elle changerait le mode d'assistance. Elle
relit ensuite la batterie toutes les 30 s. Toutes les trames
et les messages d'état sont enregistrés dans `ble_log.txt` (chemin affiché dans Paramètres).

**Distance du trajet** : « Trip reset » mémorise le compteur total du vélo ; la distance
affichée est la différence entre le compteur actuel et cette valeur mémorisée.

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
Les fichiers intermédiaires sont placés sur le disque Linux de WSL (`build_dir` dans
[buildozer.spec](buildozer.spec)) : bien plus rapide que `/mnt/c`, et les recompilations
réutilisent les bibliothèques déjà construites.

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
| `trip.py` | Distance (compteur du vélo), temps de déplacement, max/moyennes, historique des courbes, sauvegarde |
| `chart.py` | Widget courbe d'historique |
| `trackmap.py` | Carte OpenTopoMap + tracé GPS (tuiles en cache dans le dossier de l'appli) |
| `kivy_garden/mapview/` | Bibliothèque carte [mapview](https://github.com/kivy-garden/mapview) 1.0.6 (MIT), intégrée |
| `java_src/org/d4/` | Service de premier plan (écran éteint) et compteur de satellites GNSS |
| `gauge.py` | Widget cadran |
| `icons.py` | Bouton roue dentée (paramètres), dessiné en code |
| `assets/icon.png` | Icône de l'appli, générée par `tools_make_icon.py` (Pillow, non inclus dans l'APK) |
| `d4speedmeter.kv` | Interface |
| `buildozer.spec` | Configuration du build Android |
