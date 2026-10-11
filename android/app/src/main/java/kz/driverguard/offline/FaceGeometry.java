package kz.driverguard.offline;

/** Pixel-aspect-correct landmark measurements, without Android dependencies.
 * Yaw and depth are dimensionless landmark proxies, not head angles in degrees.
 */
final class FaceGeometry {
    private static final int[] LEFT_EYE = {33, 160, 158, 133, 153, 144};
    private static final int[] RIGHT_EYE = {362, 385, 387, 263, 373, 380};
    record Measurements(float ear, float headDepth, float yaw, boolean mouthValid) {
        boolean valid() { return Float.isFinite(ear) && Float.isFinite(headDepth) && Float.isFinite(yaw); }
    }

    static Measurements measure(float[] x, float[] y, float[] z, int width, int height) {
        if (width <= 0 || height <= 0 || x == null || y == null || z == null
            || x.length <= 454 || y.length <= 454 || z.length <= 454) return invalid();
        double left = eye(x, y, LEFT_EYE, width, height);
        double right = eye(x, y, RIGHT_EYE, width, height);
        double cheekWidth = distance(x, y, 234, 454, width, height);
        double faceHeight = distance(x, y, 152, 10, width, height);
        if (!Double.isFinite(left) || !Double.isFinite(right)
            || !Double.isFinite(cheekWidth) || cheekWidth < 4 || !Double.isFinite(faceHeight) || faceHeight < 4)
            return invalid();
        double yaw = (distance(x, y, 1, 234, width, height)
            - distance(x, y, 1, 454, width, height)) / cheekWidth;
        float depth = z[152] - z[10];
        double mouthWidth = distance(x, y, 61, 291, width, height);
        double mouthGap = distance(x, y, 13, 14, width, height);
        boolean mouthValid = Double.isFinite(mouthWidth) && mouthWidth >= 2
            && Double.isFinite(mouthGap) && mouthGap / mouthWidth <= 3;
        if (!Double.isFinite(yaw) || Math.abs(yaw) > 1.00001 || !Float.isFinite(depth) || Math.abs(depth) > 2)
            return invalid();
        return new Measurements((float) ((left + right) / 2), depth, (float) Math.max(-1, Math.min(1, yaw)), mouthValid);
    }

    private static double eye(float[] x, float[] y, int[] p, int width, int height) {
        double horizontal = distance(x, y, p[0], p[3], width, height);
        if (!Double.isFinite(horizontal) || horizontal < 2) return Double.NaN;
        double value = (distance(x, y, p[1], p[5], width, height)
            + distance(x, y, p[2], p[4], width, height)) / (2 * horizontal);
        return Double.isFinite(value) && value >= 0 && value <= 0.8 ? value : Double.NaN;
    }

    private static double distance(float[] x, float[] y, int a, int b, int width, int height) {
        return Math.hypot((x[a] - x[b]) * width, (y[a] - y[b]) * height);
    }

    private static Measurements invalid() {
        return new Measurements(Float.NaN, Float.NaN, Float.NaN, false);
    }
}
