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
    private static final long YAWN_MIN_INTERVAL_MS = 2500;
    private static final float EYE_SCORE = 0.55f;
    private static final float EYE_OPEN_SCORE = 0.30f;
    private static final float JAW_SCORE = 0.50f;

    public record Result(String status, String event, long closedMs, float confidence,
                         List<String> events, boolean faceVisible, boolean eyesClosed,
                         boolean closureAlarm, float perclos, boolean perclosReady,
                         float validCoverage, long validMs, int yawnCount, long jawOpenMs,
                         boolean fatigueActive, boolean headCalibrated, long headDownMs) {}
    private record Interval(long from, long to, boolean closed) {}
    private record Window(float perclos, float coverage, long validMs, boolean ready) {}

    private final ArrayDeque<Interval> intervals = new ArrayDeque<>();
    private final ArrayDeque<Long> yawns = new ArrayDeque<>();
    private long last = -1, started = -1, closedSince = -1, eyeOpenSince = -1, missingSince = -1, jawSince = -1;
    private long lastPerclosEvent = -1, lastYawnEvent = -1, lastYawnFatigueEvent = -1;
    private boolean previousValid, previousClosed, closedEmitted, missingEmitted, jawCounted;
    private long headBaselineSince = -1, headSince = -1;
    private float headBaseline, headSum, headMin, headMax;
    private int headSamples;
    private boolean headCalibrated, headEmitted;

    public void reset() {
        last = started = closedSince = eyeOpenSince = missingSince = jawSince = -1;
        lastPerclosEvent = lastYawnEvent = lastYawnFatigueEvent = -1;
        previousValid = previousClosed = closedEmitted = missingEmitted = jawCounted = false;
        intervals.clear(); yawns.clear();
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
        if (now < 0) {
            reset();
            return result("Frame time unavailable", Collections.emptyList(), false, false, 0, 0,
                new Window(0, 0, 0, false), 0, false);
        }
        if (last >= 0 && now <= last) reset();
        if (started < 0) started = now;
        boolean valid = face && score(leftBlink) && score(rightBlink);
        boolean contiguous = last >= 0 && now - last <= MAX_FRAME_GAP_MS;
        if (!contiguous) { resetEpisodes(); resetHeadCalibration(); }
        boolean closed = classifyClosed(now, valid, leftBlink, rightBlink);
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
        List<String> events = new ArrayList<>();

        if (!valid) {
            closedSince = eyeOpenSince = jawSince = -1; closedEmitted = jawCounted = false;
            if (missingSince < 0) missingSince = now;
            if (now - missingSince >= 3000 && !missingEmitted) {
                events.add("face_missing"); missingEmitted = true;
            }
            headSince = -1; headEmitted = false;
            if (!headCalibrated || now - missingSince >= 3000) resetHeadCalibration();
            return result("Face not visible. Adjust the camera.", events, false, false,
                0, 0, window, 0, false);
        }
        missingSince = -1; missingEmitted = false;
        if (closed) {
            if (closedSince < 0) closedSince = now;
            if (eyeOpenSince < 0 && now - closedSince >= EYES_CLOSED_MS && !closedEmitted) {
                events.add("eyes_closed"); closedEmitted = true;
            }
        } else {
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
        updateHead(now, pitch, !closed && score(jawOpen) && jawOpen < 0.3f, events);
        boolean fatigue = perclosWarning || repeatedYawns;
        String status = closed && closedEmitted ? "Open your eyes"
            : closed ? "Eyes closed"
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
            headCalibrated, headSince < 0 || last < 0 ? 0 : last - headSince);
    }
    private void resetEpisodes() {
        closedSince = eyeOpenSince = missingSince = jawSince = -1;
        closedEmitted = missingEmitted = jawCounted = false;
        headSince = -1; headEmitted = false;
    }
    private boolean classifyClosed(long now, boolean valid, float left, float right) {
        if (!valid) { eyeOpenSince = -1; return false; }
        if (closedSince < 0) {
            eyeOpenSince = -1;
            return left >= EYE_SCORE && right >= EYE_SCORE;
        }
        if (left < EYE_OPEN_SCORE && right < EYE_OPEN_SCORE) {
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
    }
    private void updateHead(long now, float pitch, boolean neutral, List<String> events) {
        if (!Float.isFinite(pitch) || Math.abs(pitch) > Math.PI / 2) {
            headSince = -1; headEmitted = false;
            if (!headCalibrated) resetHeadCalibration();
            return;
        }
        if (!headCalibrated) {
            if (!neutral) { resetHeadCalibration(); return; }
            if (headBaselineSince < 0) headBaselineSince = now;
            headMin = Math.min(headMin, pitch); headMax = Math.max(headMax, pitch);
            if (headMax - headMin > 0.12f) { resetHeadCalibration(); return; }
            headSum += pitch; headSamples++;
            if (now - headBaselineSince >= 3000 && headSamples >= 10) {
                headBaseline = headSum / headSamples; headCalibrated = true;
            }
            return;
        }
        if (pitch - headBaseline >= HEAD_DOWN_RADIANS) {
            if (headSince < 0) headSince = now;
            if (now - headSince >= HEAD_DOWN_MS && !headEmitted) {
                events.add("head_nod"); headEmitted = true;
            }
        } else { headSince = -1; headEmitted = false; }
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
