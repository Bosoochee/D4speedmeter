[app]
title = D4speedmeter
package.name = d4speedmeter
package.domain = org.d4
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf
source.exclude_dirs = java_src,bin,.venv
source.exclude_patterns = tools_*.py
version = 0.5.0

requirements = python3,kivy==2.3.1,plyer,android,charset_normalizer==3.4.5

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/assets/icon.png
# presplash.filename = %(source.dir)s/assets/presplash.png

android.permissions = ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,(name=android.permission.BLUETOOTH;maxSdkVersion=30),(name=android.permission.BLUETOOTH_ADMIN;maxSdkVersion=30),(name=android.permission.BLUETOOTH_SCAN;usesPermissionFlags=neverForLocation),BLUETOOTH_CONNECT
android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.add_src = java_src

[buildozer]
log_level = 2
warn_on_root = 1
