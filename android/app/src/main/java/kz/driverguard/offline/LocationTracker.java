package kz.driverguard.offline;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.Context;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.location.LocationProvider;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;

/** Foreground-only satellite GPS. The activity controls the permission prompt and lifecycle. */
final class LocationTracker {
    private final Context context;
    private final LocationManager manager;
    private final Handler main = new Handler(Looper.getMainLooper());
    private volatile DrivingSample latest = DrivingSample.unavailable();
    private volatile boolean started;
    private final LocationListener listener = new LocationListener() {
        @Override public void onLocationChanged(Location location) {
            if (!started || !precisePermission() || !LocationManager.GPS_PROVIDER.equals(location.getProvider())
                || !location.hasAccuracy() || !location.hasSpeed() || !location.hasSpeedAccuracy()
                || location.getElapsedRealtimeNanos() < 0) {
                latest = DrivingSample.unavailable();
                return;
            }
            boolean mock = Build.VERSION.SDK_INT >= 31 ? location.isMock() : location.isFromMockProvider();
            latest = new DrivingSample(location.getLatitude(), location.getLongitude(), location.getSpeed() * 3.6,
                location.getElapsedRealtimeNanos() / 1_000_000L, location.getAccuracy(), location.getSpeedAccuracyMetersPerSecond(), mock);
        }
        @Override public void onProviderDisabled(String provider) { latest = DrivingSample.unavailable(); }
        @Override public void onProviderEnabled(String provider) { }
        @Override public void onStatusChanged(String provider, int status, Bundle extras) {
            if (status != LocationProvider.AVAILABLE) latest = DrivingSample.unavailable();
        }
    };
    LocationTracker(Context context) {
        this.context = context.getApplicationContext();
        manager = this.context.getSystemService(LocationManager.class);
    }
    @SuppressLint("MissingPermission")
    void start() {
        requireMain();
        if (!precisePermission() || manager == null) { stop(); return; }
        if (started) return;
        latest = DrivingSample.unavailable();
        try {
            if (!manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) return;
            started = true;
            manager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 1000L, 0f, listener, main.getLooper());
        } catch (SecurityException | IllegalArgumentException unavailable) { stop(); }
    }
    void stop() {
        requireMain();
        started = false;
        latest = DrivingSample.unavailable();
        if (manager != null) {
            try { manager.removeUpdates(listener); } catch (SecurityException ignored) { }
        }
    }
    DrivingSample snapshot(long now) {
        DrivingSample sample = latest;
        return started && precisePermission() && sample.validAt(now) ? sample : DrivingSample.unavailable();
    }
    private boolean precisePermission() {
        return context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }
    private void requireMain() {
        if (Looper.myLooper() != main.getLooper()) throw new IllegalStateException("GPS lifecycle must run on the main thread");
    }
}
