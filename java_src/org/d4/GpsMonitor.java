package org.d4;

import android.content.Context;
import android.location.GnssStatus;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;

import java.util.List;

/**
 * Relais GPS lu par Python (sondage chaque seconde, écran éteint compris) :
 * dernière position (vitesse, précision) et nombre de satellites utilisés.
 *
 * Remplace le GPS de plyer, dont l'écouteur Python n'implémente pas
 * onLocationChanged(List) appelé par Android 12+ (positions perdues), et
 * GnssStatus.Callback, classe abstraite que pyjnius ne sait pas implémenter.
 */
public class GpsMonitor {
    private static final String TAG = "GpsMonitor";
    private static final long STALE_MS = 5000;

    private static volatile int usedInFix = 0;
    private static volatile long satellitesUpdate = 0;

    private static volatile double latitude, longitude;
    private static volatile float speed, accuracy;
    private static volatile boolean hasSpeed, hasAccuracy;
    private static volatile long locationCount = 0;   // incrémenté à chaque nouvelle position
    private static volatile long locationUpdate = 0;

    private static GnssStatus.Callback gnssCallback;
    private static LocationListener locationListener;

    /** Démarre l'écoute (permission de localisation requise). */
    public static synchronized boolean start(Context context) {
        if (locationListener != null) {
            return true;
        }
        LocationManager manager = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
        Looper looper = Looper.getMainLooper();
        locationListener = new LocationListener() {
            @Override
            public void onLocationChanged(Location location) {
                latitude = location.getLatitude();
                longitude = location.getLongitude();
                hasSpeed = location.hasSpeed();
                speed = location.getSpeed();
                hasAccuracy = location.hasAccuracy();
                accuracy = location.getAccuracy();
                locationUpdate = SystemClock.elapsedRealtime();
                locationCount++;
            }

            @Override
            public void onLocationChanged(List<Location> locations) {
                for (Location location : locations) {
                    onLocationChanged(location);
                }
            }

            @Override
            public void onStatusChanged(String provider, int status, Bundle extras) {
            }

            @Override
            public void onProviderEnabled(String provider) {
            }

            @Override
            public void onProviderDisabled(String provider) {
            }
        };
        try {
            manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000, 0, locationListener, looper);
            if (Build.VERSION.SDK_INT >= 24) {
                gnssCallback = new GnssStatus.Callback() {
                    @Override
                    public void onSatelliteStatusChanged(GnssStatus status) {
                        int used = 0;
                        for (int i = 0; i < status.getSatelliteCount(); i++) {
                            if (status.usedInFix(i)) {
                                used++;
                            }
                        }
                        usedInFix = used;
                        satellitesUpdate = SystemClock.elapsedRealtime();
                    }

                    @Override
                    public void onStopped() {
                        usedInFix = 0;
                    }
                };
                manager.registerGnssStatusCallback(gnssCallback, new Handler(looper));
            }
            return true;
        } catch (SecurityException e) {
            Log.e(TAG, "permission de localisation manquante", e);
            locationListener = null;
            gnssCallback = null;
            return false;
        }
    }

    private static boolean fresh(long update) {
        return SystemClock.elapsedRealtime() - update < STALE_MS;
    }

    /** Satellites utilisés pour calculer la position (0 si pas d'information récente). */
    public static int getUsedInFix() {
        return fresh(satellitesUpdate) ? usedInFix : 0;
    }

    /** Numéro de la dernière position reçue (0 = aucune) : sert à détecter les nouvelles. */
    public static long getLocationCount() {
        return locationCount;
    }

    public static boolean hasRecentLocation() {
        return locationCount > 0 && fresh(locationUpdate);
    }

    public static double getLatitude() {
        return latitude;
    }

    public static double getLongitude() {
        return longitude;
    }

    /** Vitesse en m/s (-1 si inconnue). */
    public static float getSpeed() {
        return hasSpeed ? speed : -1;
    }

    /** Précision horizontale en mètres (-1 si inconnue). */
    public static float getAccuracy() {
        return hasAccuracy ? accuracy : -1;
    }
}
