package kz.driverguard.offline;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Offline prototype rules over pretrained FaceLandmarker blendshapes. Scores are
 * expression scores, not probabilities of sleep. Mouth opening can also be speech.
 * PERCLOS here is an eye-closure proxy; these thresholds require device/field validation.
 * Time-weighted valid intervals avoid making dropped frames look like closed eyes.
 */
public final class DmsRules {
    public static final long MAX_FRAME_GAP_MS = 1000;
    public static final long EYES_CLOSED_MS = 1500;
    public static final long EYES_OPEN_CONFIRM_MS = 200;
    public static final long PERCLOS_WINDOW_MS = 60_000;
    public static final long PERCLOS_MIN_VALID_MS = 15_000;
    public static final float PERCLOS_MIN_COVERAGE = 0.8f;
    public static final float PERCLOS_WARN = 0.20f;
    public static final long FATIGUE_COOLDOWN_MS = 30_000;
    public static final long YAWN_MS = 1200;
    public static final long YAWN_WINDOW_MS = 600_000;
    public static final long HEAD_DOWN_MS = 2000;
    public static final float HEAD_DOWN_RADIANS = (float) Math.toRadians(15);
    public static final float HEAD_DOWN_DEPTH = 0.13f;
    public static final float YAW_DELTA = 0.35f;
    public static final long CALIBRATION_MS = 3000;
    public static final long BLINK_WINDOW_MS = 60_000;
    public static final long DISTRACTION_WARN_MS = 8000, DISTRACTION_CRITICAL_MS = 15_000;
    public static final long CAMERA_MISSING_MS = 3000, CAMERA_SABOTAGE_MS = 300_000;
    public static final long SPEEDING_MS = 10_000, SPEEDING_COOLDOWN_MS = 60_000;
    private static final long YAWN_MIN_INTERVAL_MS = 2500;
    private static final float EYE_SCORE = 0.55f;
    private static final float EYE_OPEN_SCORE = 0.30f;
    private static final float JAW_SCORE = 0.50f;

    public record Result(String status, String event, long closedMs, float confidence,
                         List<String> events, boolean faceVisible, boolean eyesClosed,
                         boolean closureAlarm, float perclos, boolean perclosReady,
                         float validCoverage, long validMs, int yawnCount, long jawOpenMs,
                         boolean fatigueActive, boolean headCalibrated, long headDownMs,
                         int blinkCount, float ear, float earBaseline, boolean eyeCalibrated,
                         float yawDelta, long awayMs, long missingMs, float headDelta,
                         boolean distractionCritical, long movingAwayMs, long movingMissingMs) {}
    private record Interval(long from, long to, boolean closed) {}
    private record Window(float perclos, float coverage, long validMs, boolean ready) {}

    private final ArrayDeque<Interval> intervals = new ArrayDeque<>();
    private final ArrayDeque<Long> yawns = new ArrayDeque<>();
    private final ArrayDeque<Long> blinks = new ArrayDeque<>();
    private final Baseline eyeBase = new Baseline(), yawBase = new Baseline();
    private long last = -1, started = -1, closedSince = -1, eyeOpenSince = -1, missingSince = -1, jawSince = -1;
    private long lastPerclosEvent = -1, lastYawnEvent = -1, lastYawnFatigueEvent = -1;
    private boolean previousValid, previousClosed, closedEmitted, missingEmitted, jawCounted;
    private long headBaselineSince = -1, headSince = -1;
    private float headBaseline, headSum, headMin, headMax;
    private int headSamples;
    private boolean headCalibrated, headEmitted;
    private float currentEar = Float.NaN, currentYawDelta = Float.NaN, currentHeadDelta = Float.NaN;
    private long awaySince = -1, movingAwaySince = -1, movingMissingSince = -1, speedingSince = -1;
    private long lastSpeedingEvent = -1;
    private int distractionLevel, previousSpeedLimit;
    private boolean sabotageEmitted, rawGeometryMode;

    public void reset() {
        last = started = closedSince = eyeOpenSince = missingSince = jawSince = -1;
        lastPerclosEvent = lastYawnEvent = lastYawnFatigueEvent = -1;
        previousValid = previousClosed = closedEmitted = missingEmitted = jawCounted = false;
        intervals.clear(); yawns.clear(); blinks.clear();
        eyeBase.reset(); yawBase.reset();
        currentEar = currentYawDelta = currentHeadDelta = Float.NaN;
        lastSpeedingEvent = -1; previousSpeedLimit = 0;
        resetMotion();
        resetHeadCalibration();
    }

    /** Compatibility overload for callers without mouth blendshapes. */
    public Result update(long now, boolean face, float leftBlink, float rightBlink) {
        return update(now, face, leftBlink, rightBlink, Float.NaN);
    }

    public Result update(long now, boolean face, float leftBlink, float rightBlink, float jawOpen) {
        return update(now, face, leftBlink, rightBlink, jawOpen, Float.NaN);
    }

    /** Pitch is a chin/forehead landmark angle in radians; positive change means chin moving away. */
    public Result update(long now, boolean face, float leftBlink, float rightBlink, float jawOpen, float pitch) {
        return updateFrame(now, face, leftBlink, rightBlink, jawOpen, pitch,
            Float.NaN, Float.NaN, Double.NaN, 90, false);
    }

    /** Full landmark path: raw z(chin)-z(forehead), pixel-correct EAR and yaw proxy.
     * Speed must already have passed source age/accuracy/mock-location checks; NaN is unknown.
     * The legacy pitch overload remains radians and cannot create motion-dependent events.
     */
    public Result update(long now, boolean face, float leftBlink, float rightBlink, float jawOpen,
                         float headDepth, float ear, float yaw, double speedKmh, int speedLimitKmh) {
        return updateFrame(now, face, leftBlink, rightBlink, jawOpen, headDepth,
            ear, yaw, speedKmh, speedLimitKmh, true);
    }

    private Result updateFrame(long now, boolean face, float leftBlink, float rightBlink, float jawOpen,
                               float pitch, float ear, float yaw, double speedKmh, int speedLimitKmh,
                               boolean geometry) {
        if (now < 0) {
            reset();
            return result("Frame time unavailable", Collections.emptyList(), false, false, 0, 0,
                new Window(0, 0, 0, false), 0, false);
        }
        if (last >= 0 && now <= last) reset();
        if (last >= 0 && rawGeometryMode != geometry) reset();
        rawGeometryMode = geometry;
        if (started < 0) started = now;
        boolean valid = face && score(leftBlink) && score(rightBlink)
            && (!geometry || (validEar(ear) && Float.isFinite(yaw) && Math.abs(yaw) <= 1
                && Float.isFinite(pitch) && Math.abs(pitch) <= 2));
        boolean contiguous = last >= 0 && now - last <= MAX_FRAME_GAP_MS;
        if (!contiguous) { resetEpisodes(); resetCalibrations(); resetMotion(); }
        currentEar = valid && geometry ? ear : Float.NaN;
        if (valid && geometry) {
            boolean neutral = leftBlink < EYE_OPEN_SCORE && rightBlink < EYE_OPEN_SCORE
                && score(jawOpen) && jawOpen < 0.3f;
            // A low/unstable EAR cannot become the personal open-eye baseline.
            eyeBase.observe(now, ear, neutral && ear >= 0.10f && ear <= 0.60f,
                Math.max(0.015f, ear * 0.20f));
            yawBase.observe(now, yaw, neutral && Math.abs(yaw) <= 0.20f, 0.12f);
        }
        boolean closed = classifyClosed(now, valid, leftBlink, rightBlink, ear, geometry);
        // Opening confirmation may keep the alert latched briefly, but this grace
        // time is never added to PERCLOS or used to create a new closure alarm.
        boolean closedEvidence = closed && eyeOpenSince < 0;
        if (contiguous && previousValid && valid) {
            // Require closure at both ends: a long processing interval cannot add
            // closed-eye time solely because its final frame happens to be closed.
            intervals.addLast(new Interval(last, now, previousClosed && closedEvidence));
        }
        last = now; previousValid = valid; previousClosed = closedEvidence;
        Window window = window(now);
        while (!yawns.isEmpty() && yawns.peekFirst() < now - YAWN_WINDOW_MS) yawns.removeFirst();
        while (!blinks.isEmpty() && blinks.peekFirst() < now - BLINK_WINDOW_MS) blinks.removeFirst();
        List<String> events = new ArrayList<>();
        updateSpeed(now, speedKmh, speedLimitKmh, events);

        if (!valid) {
            closedSince = eyeOpenSince = jawSince = -1; closedEmitted = jawCounted = false;
            if (missingSince < 0) missingSince = now;
            if (now - missingSince >= CAMERA_MISSING_MS && !missingEmitted) {
                events.add("face_missing"); missingEmitted = true;
            }
            resetCalibrations();
            awaySince = movingAwaySince = -1; distractionLevel = 0;
            // Only an actually absent face can produce this event; invalid landmarks
            // or missing expression scores are a measurement failure, not sabotage.
            if (!face && validSpeed(speedKmh) && speedKmh > 5) {
                if (movingMissingSince < 0) movingMissingSince = now;
                if (now - movingMissingSince >= CAMERA_SABOTAGE_MS && !sabotageEmitted) {
                    events.add("camera_sabotage"); sabotageEmitted = true;
                }
            } else {
                movingMissingSince = -1;
                // A stop or lost speed fix breaks the timer, but cannot recount an
                // already reported absence before the face has actually returned.
                if (face) sabotageEmitted = false;
            }
            return result("Face not visible. Adjust the camera.", events, false, false,
                0, 0, window, 0, false);
        }
        missingSince = movingMissingSince = -1; missingEmitted = sabotageEmitted = false;
        if (closed) {
            if (closedSince < 0) closedSince = now;
            if (eyeOpenSince < 0 && now - closedSince >= EYES_CLOSED_MS && !closedEmitted) {
                events.add("eyes_closed"); closedEmitted = true;
            }
        } else {
            if (closedSince >= 0 && eyeOpenSince >= 0) {
                long duration = eyeOpenSince - closedSince;
                if (duration >= 60 && duration <= 500) blinks.addLast(eyeOpenSince);
            }
            closedSince = eyeOpenSince = -1; closedEmitted = false;
        }
        long closedMs = closedSince < 0 ? 0 : (eyeOpenSince < 0 ? now : eyeOpenSince) - closedSince;

        boolean newYawn = false;
        if (score(jawOpen) && jawOpen >= JAW_SCORE) {
            if (jawSince < 0) jawSince = now;
            if (now - jawSince >= YAWN_MS && !jawCounted
                && elapsed(now, lastYawnEvent, YAWN_MIN_INTERVAL_MS)) {
                yawns.addLast(now); lastYawnEvent = now; jawCounted = true;
                events.add("yawn"); newYawn = true;
            }
        } else {
            jawSince = -1;
            // Hysteresis keeps noise at the mouth threshold from recounting one opening.
            if (!score(jawOpen) || jawOpen < 0.3f) jawCounted = false;
        }
        long jawMs = jawSince < 0 ? 0 : now - jawSince;
        boolean perclosWarning = window.ready && window.perclos >= PERCLOS_WARN;
        if (perclosWarning && elapsed(now, lastPerclosEvent, FATIGUE_COOLDOWN_MS)) {
            events.add("fatigue_perclos"); lastPerclosEvent = now;
        }
        boolean repeatedYawns = yawns.size() >= 3;
        if (newYawn && repeatedYawns && elapsed(now, lastYawnFatigueEvent, FATIGUE_COOLDOWN_MS)) {
            events.add("fatigue_yawning"); lastYawnFatigueEvent = now;
        }
        updateHead(now, pitch, !closed && leftBlink < EYE_OPEN_SCORE && rightBlink < EYE_OPEN_SCORE
            && score(jawOpen) && jawOpen < 0.3f, geometry, events);
        updateYaw(now, yaw, geometry, speedKmh, events);
        boolean fatigue = perclosWarning || repeatedYawns;
        String status = closed && closedEmitted ? "Open your eyes"
            : closed ? "Eyes closed"
            : distractionLevel >= 2 ? "Look at the road"
            : headSince >= 0 && now - headSince >= HEAD_DOWN_MS ? "Head lowered. Check your posture."
            : fatigue ? "Fatigue indicators: consider a safe break"
            : jawMs >= YAWN_MS ? "Sustained mouth opening observed" : "Eyes open";
        return result(status, events, true, closed, closedMs,
            Math.min(leftBlink, rightBlink), window, jawMs, fatigue);
    }

    private Result result(String status, List<String> events, boolean valid, boolean closed,
                          long closedMs, float confidence, Window window, long jawMs, boolean fatigue) {
        return new Result(status, events.isEmpty() ? null : events.get(0), closedMs, confidence,
            Collections.unmodifiableList(new ArrayList<>(events)), valid, closed, valid && closed && closedEmitted,
            window.perclos, window.ready, window.coverage, window.validMs, yawns.size(), jawMs, fatigue,
            headCalibrated, headSince < 0 || last < 0 ? 0 : last - headSince,
            blinks.size(), currentEar, eyeBase.ready ? eyeBase.mean : Float.NaN, eyeBase.ready,
            currentYawDelta, awaySince < 0 || last < 0 ? 0 : last - awaySince,
            missingSince < 0 || last < 0 ? 0 : last - missingSince, currentHeadDelta,
            valid && distractionLevel >= 2,
            movingAwaySince < 0 || last < 0 ? 0 : last - movingAwaySince,
            movingMissingSince < 0 || last < 0 ? 0 : last - movingMissingSince);
    }
    private void resetEpisodes() {
        closedSince = eyeOpenSince = missingSince = jawSince = -1;
        closedEmitted = missingEmitted = jawCounted = false;
        headSince = -1; headEmitted = false;
    }
    private boolean classifyClosed(long now, boolean valid, float left, float right, float ear, boolean geometry) {
        if (!valid) { eyeOpenSince = -1; return false; }
        boolean earClosed = geometry && eyeBase.ready && ear < eyeBase.mean * 0.55f;
        if (closedSince < 0) {
            eyeOpenSince = -1;
            return (left >= EYE_SCORE && right >= EYE_SCORE) || earClosed;
        }
        if (left < EYE_OPEN_SCORE && right < EYE_OPEN_SCORE
            && (!geometry || !eyeBase.ready || ear >= eyeBase.mean * 0.65f)) {
            if (eyeOpenSince < 0) eyeOpenSince = now;
            return now - eyeOpenSince < EYES_OPEN_CONFIRM_MS;
        }
        eyeOpenSince = -1;
        return true;
    }
    private void resetHeadCalibration() {
        headBaselineSince = headSince = -1; headSamples = 0;
        headSum = headBaseline = 0; headMin = Float.POSITIVE_INFINITY; headMax = Float.NEGATIVE_INFINITY;
        headCalibrated = headEmitted = false;
        currentHeadDelta = Float.NaN;
    }
    private void updateHead(long now, float pitch, boolean neutral, boolean geometry, List<String> events) {
        if (!Float.isFinite(pitch) || Math.abs(pitch) > (geometry ? 2 : Math.PI / 2)) {
            headSince = -1; headEmitted = false;
            if (!headCalibrated) resetHeadCalibration();
            return;
        }
        if (!headCalibrated) {
            if (!neutral) { resetHeadCalibration(); return; }
            if (headBaselineSince < 0) headBaselineSince = now;
            headMin = Math.min(headMin, pitch); headMax = Math.max(headMax, pitch);
            if (headMax - headMin > (geometry ? 0.06f : 0.12f)) { resetHeadCalibration(); return; }
            headSum += pitch; headSamples++;
            if (now - headBaselineSince >= CALIBRATION_MS && headSamples >= 10) {
                headBaseline = headSum / headSamples; headCalibrated = true;
            }
            return;
        }
        currentHeadDelta = pitch - headBaseline;
        if (geometry ? currentHeadDelta > HEAD_DOWN_DEPTH : currentHeadDelta >= HEAD_DOWN_RADIANS) {
            if (headSince < 0) headSince = now;
            if (now - headSince >= HEAD_DOWN_MS && !headEmitted) {
                events.add("head_nod"); headEmitted = true;
            }
        } else { headSince = -1; headEmitted = false; }
    }

    private void resetCalibrations() {
        resetHeadCalibration(); eyeBase.reset(); yawBase.reset(); currentYawDelta = Float.NaN;
    }

    private void resetMotion() {
        awaySince = movingAwaySince = movingMissingSince = speedingSince = -1;
        distractionLevel = 0; sabotageEmitted = false;
    }

    private void updateYaw(long now, float yaw, boolean geometry, double speedKmh, List<String> events) {
        currentYawDelta = geometry && yawBase.ready ? yaw - yawBase.mean : Float.NaN;
        if (!Float.isFinite(currentYawDelta) || Math.abs(currentYawDelta) <= YAW_DELTA) {
            awaySince = movingAwaySince = -1; distractionLevel = 0; return;
        }
        if (awaySince < 0) awaySince = now;
        if (!validSpeed(speedKmh) || speedKmh <= 20) {
            movingAwaySince = -1; distractionLevel = 0; return;
        }
        if (movingAwaySince < 0) movingAwaySince = now;
        long held = now - movingAwaySince;
        if (held >= DISTRACTION_CRITICAL_MS && distractionLevel < 2) {
            events.add("distraction_critical"); distractionLevel = 2;
        } else if (held >= DISTRACTION_WARN_MS && distractionLevel < 1) {
            events.add("distraction_warning"); distractionLevel = 1;
        }
    }

    private void updateSpeed(long now, double speedKmh, int limit, List<String> events) {
        if (limit != previousSpeedLimit) { speedingSince = -1; previousSpeedLimit = limit; }
        if ((limit != 60 && limit != 90) || !validSpeed(speedKmh) || speedKmh <= limit) {
            speedingSince = -1; return;
        }
        if (speedingSince < 0) speedingSince = now;
        if (now - speedingSince >= SPEEDING_MS && elapsed(now, lastSpeedingEvent, SPEEDING_COOLDOWN_MS)) {
            events.add("speeding"); lastSpeedingEvent = now;
        }
    }

    private static boolean validSpeed(double speed) {
        return Double.isFinite(speed) && speed >= 0 && speed <= 300;
    }
    private static boolean validEar(float ear) { return Float.isFinite(ear) && ear >= 0 && ear <= 0.8f; }

    /** Fixed personal baseline. It is never adapted while a possible hazard is observed. */
    private static final class Baseline {
        long since = -1; int count; float sum, min, max, mean; boolean ready;
        void reset() { since = -1; count = 0; sum = mean = 0; min = Float.POSITIVE_INFINITY;
            max = Float.NEGATIVE_INFINITY; ready = false; }
        void observe(long now, float value, boolean eligible, float maxRange) {
            if (ready) return;
            if (!eligible || !Float.isFinite(value)) { reset(); return; }
            if (since < 0) { reset(); since = now; }
            min = Math.min(min, value); max = Math.max(max, value);
            if (max - min > maxRange) { reset(); return; }
            sum += value; count++;
            if (now - since >= CALIBRATION_MS && count >= 10) { mean = sum / count; ready = true; }
        }
    }
    private Window window(long now) {
        long cutoff = now - PERCLOS_WINDOW_MS;
        while (!intervals.isEmpty() && intervals.peekFirst().to <= cutoff) intervals.removeFirst();
        long valid = 0, closed = 0;
        for (Interval interval : intervals) {
            long duration = interval.to - Math.max(cutoff, interval.from);
            valid += duration;
            if (interval.closed) closed += duration;
        }
        long observed = Math.min(PERCLOS_WINDOW_MS, now - started);
        float coverage = observed > 0 ? Math.min(1f, valid / (float) observed) : 0;
        boolean ready = valid >= PERCLOS_MIN_VALID_MS && coverage >= PERCLOS_MIN_COVERAGE;
        return new Window(valid > 0 ? closed / (float) valid : 0, coverage, valid, ready);
    }
    private static boolean score(float value) { return Float.isFinite(value) && value >= 0 && value <= 1; }
    private static boolean elapsed(long now, long previous, long cooldown) { return previous < 0 || now - previous >= cooldown; }
}
