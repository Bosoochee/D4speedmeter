[app]
title = D4speedmeter
package.name = d4speedmeter
package.domain = org.d4
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
source.exclude_dirs = java_src,bin,.venv
source.exclude_patterns = tools_*.py
version = 0.10.0

requirements = python3,kivy==2.3.1,plyer,android,charset_normalizer==3.4.5

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/assets/icon.png
presplash.filename = %(source.dir)s/assets/icon.png
android.presplash_color = #121217

android.permissions = ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,(name=android.permission.BLUETOOTH;maxSdkVersion=30),(name=android.permission.BLUETOOTH_ADMIN;maxSdkVersion=30),(name=android.permission.BLUETOOTH_SCAN;usesPermissionFlags=neverForLocation),BLUETOOTH_CONNECT,FOREGROUND_SERVICE,FOREGROUND_SERVICE_CONNECTED_DEVICE,FOREGROUND_SERVICE_LOCATION,WAKE_LOCK,POST_NOTIFICATIONS,INTERNET
android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.add_src = java_src

# Service de premier plan Java (java_src/org/d4/KeepAliveService.java), dans le processus de
# l'appli : fonctionnement écran éteint. Le gabarit p4a n'écrit que android:name pour un
# service natif ; les attributs suivants sont ajoutés en refermant les guillemets du nom.
p4a.extra_args = '--native-service=org.d4.KeepAliveService" android:foregroundServiceType="connectedDevice|location" android:exported="false'

[buildozer]
log_level = 2
warn_on_root = 1
