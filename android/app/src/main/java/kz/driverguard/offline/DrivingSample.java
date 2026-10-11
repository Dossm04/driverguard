package kz.driverguard.offline;

/** A measured GPS sample. Missing speed/accuracy is unavailable, never fabricated as zero. */
record DrivingSample(double latitude, double longitude, double speedKmh, long elapsedMs,
                     float accuracyMeters, float speedAccuracyMps, boolean mock) {
    static DrivingSample unavailable() {
        return new DrivingSample(Double.NaN, Double.NaN, Double.NaN, -1, Float.NaN, Float.NaN, false);
    }
    boolean validAt(long now) {
        return !mock && now >= 0 && elapsedMs >= 0 && elapsedMs <= now && now - elapsedMs <= 5000
            && Double.isFinite(latitude) && latitude >= -90 && latitude <= 90
            && Double.isFinite(longitude) && longitude >= -180 && longitude <= 180
            && Double.isFinite(speedKmh) && speedKmh >= 0 && speedKmh <= 300
            && Float.isFinite(accuracyMeters) && accuracyMeters >= 0 && accuracyMeters <= 30
            && Float.isFinite(speedAccuracyMps) && speedAccuracyMps >= 0 && speedAccuracyMps <= 3;
    }
}
