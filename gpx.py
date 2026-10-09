"""Export du parcours GPS au format GPX (à importer sur strava.com, Komoot...).

Android 10+ : le fichier est enregistré dans Téléchargements/D4speedmeter (MediaStore,
sans permission) puis proposé au menu de partage Android. Sinon : dossier `fallback_dir`.
"""

import os
import time
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from kivy.utils import platform

MIME_TYPE = "application/gpx+xml"
SUBFOLDER = "D4speedmeter"


def build_gpx(track, description=""):
    """GPX d'un tracé [[lat, lon, t_epoch], ...] ; None s'il y a moins de 2 points horodatés."""
    points = [p for p in track if len(p) >= 3]
    if len(points) < 2:
        return None
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="D4speedmeter" xmlns="http://www.topografix.com/GPX/1/1">',
             f"<metadata><time>{_iso(points[0][2])}</time></metadata>",
             f"<trk><name>D4speedmeter</name><desc>{escape(description)}</desc>",
             "<type>cycling</type><trkseg>"]
    for lat, lon, t, *_ in points:
        lines.append(f'<trkpt lat="{lat}" lon="{lon}"><time>{_iso(t)}</time></trkpt>')
    lines.append("</trkseg></trk></gpx>")
    return "\n".join(lines)


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def export_gpx(track, description, fallback_dir):
    """Enregistre le parcours et ouvre le partage ; renvoie l'emplacement, None sans tracé."""
    gpx = build_gpx(track, description)
    if gpx is None:
        return None
    start = next(p[2] for p in track if len(p) >= 3)
    name = time.strftime("D4speedmeter_%Y-%m-%d_%Hh%M.gpx", time.localtime(start))
    data = gpx.encode("utf-8")
    if platform == "android":
        try:
            uri = _save_to_downloads(name, data)
            _share(uri)
            return f"Téléchargements/{SUBFOLDER}/{name}"
        except Exception as exc:
            print(f"Export dans Téléchargements impossible : {exc!r}")
    folder = os.path.join(fallback_dir, "parcours")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _save_to_downloads(name, data):
    """Écrit le fichier dans Téléchargements/D4speedmeter (Android 10+) ; renvoie son Uri."""
    from jnius import autoclass

    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    media_columns = autoclass("android.provider.MediaStore$MediaColumns")
    values = autoclass("android.content.ContentValues")()
    values.put(media_columns.DISPLAY_NAME, name)
    values.put(media_columns.MIME_TYPE, MIME_TYPE)
    values.put(media_columns.RELATIVE_PATH,
               autoclass("android.os.Environment").DIRECTORY_DOWNLOADS + "/" + SUBFOLDER)
    resolver = activity.getContentResolver()
    uri = resolver.insert(autoclass("android.provider.MediaStore$Downloads").EXTERNAL_CONTENT_URI,
                          values)
    stream = resolver.openOutputStream(uri)
    try:
        stream.write(data)
    finally:
        stream.close()
    return uri


def _share(uri):
    """Menu de partage Android (Drive, mail, messagerie...) pour le fichier."""
    from android.runnable import run_on_ui_thread
    from jnius import autoclass, cast

    @run_on_ui_thread
    def show():
        intent_class = autoclass("android.content.Intent")
        intent = intent_class(intent_class.ACTION_SEND)
        intent.setType(MIME_TYPE)
        intent.putExtra(intent_class.EXTRA_STREAM, cast("android.os.Parcelable", uri))
        intent.addFlags(intent_class.FLAG_GRANT_READ_URI_PERMISSION)
        chooser = intent_class.createChooser(intent, cast("java.lang.CharSequence",
                                             autoclass("java.lang.String")("Partager le parcours")))
        autoclass("org.kivy.android.PythonActivity").mActivity.startActivity(chooser)

    show()
