package kz.driverguard.offline;

/**
 * Sound pulses are separate from journal events. Call onFrame for every accepted
 * inference and poll from a UI timer (e.g. 100 ms), even when frames stop arriving.
 * Stop the tone when Decision.active is false; playPulse is due at most every 900 ms.
 */
public final class AlertPolicy {
    public static final long REPEAT_MS = 900;
    public static final long CAMERA_REMINDER_MS = 5000;
    public static final long YAWN_REMINDER_MS = 2500;
    public static final long STALE_MS = DmsRules.MAX_FRAME_GAP_MS;
    public record Decision(boolean active, boolean playPulse, boolean warningPulse) {}
    private long lastFrame = -1, lastPulse = -1, lastWarning = -1;
    private boolean continuousAlarm;
    private boolean warningPending;
    private boolean cameraUnavailable, yawnPending;
    private long lastCameraPulse = -1, lastYawnPulse = -1;

    public void onFrame(long now, DmsRules.Result result) {
        if (now < 0 || (lastFrame >= 0 && now <= lastFrame)) reset();
        if (now < 0) return;
        if (lastFrame >= 0 && now - lastFrame > STALE_MS) { reset(); }
        lastFrame = now;
        continuousAlarm = result != null && result.faceVisible()
            && (result.closureAlarm() || result.distractionCritical());
        if(result!=null) {
            cameraUnavailable = !result.faceVisible() && result.missingMs() >= DmsRules.CAMERA_MISSING_MS;
            yawnPending |= result.events().contains("yawn");
            warningPending |= result.events().contains("fatigue_perclos")
                || result.events().contains("fatigue_yawning") || result.events().contains("head_nod")
                || result.events().contains("distraction_warning")
                || result.events().contains("speeding") || result.events().contains("camera_sabotage");
        } else { warningPending=false; yawnPending=false; cameraUnavailable=false; }
        if (!cameraUnavailable) lastCameraPulse=-1;
        if (!continuousAlarm) lastPulse = -1;
    }

    public Decision poll(long now, boolean monitoring, boolean muted) {
        if (!monitoring) { reset(); return new Decision(false, false, false); }
        boolean fresh = lastFrame >= 0 && now >= lastFrame && now - lastFrame <= STALE_MS;
        boolean active = fresh && continuousAlarm && !muted;
        boolean mayWarn=fresh && !muted && !active;
        boolean general=mayWarn && warningPending && due(now,lastWarning,DmsRules.FATIGUE_COOLDOWN_MS);
        boolean camera=mayWarn && cameraUnavailable && due(now,lastCameraPulse,CAMERA_REMINDER_MS);
        boolean yawn=mayWarn && yawnPending && due(now,lastYawnPulse,YAWN_REMINDER_MS);
        boolean warning=general || camera || yawn;
        warningPending=yawnPending=false;
        if(general)lastWarning=now;
        if(camera)lastCameraPulse=now;
        if(yawn)lastYawnPulse=now;
        if (!active) { lastPulse = -1; return new Decision(false, false, warning); }
        boolean pulse = lastPulse < 0 || now - lastPulse >= REPEAT_MS;
        if (pulse) lastPulse = now;
        return new Decision(true, pulse, false);
    }

    private static boolean due(long now,long previous,long period){return previous<0 || now-previous>=period;}
    public void reset() { lastFrame = lastPulse = lastWarning = lastCameraPulse = lastYawnPulse = -1; continuousAlarm = warningPending = cameraUnavailable = yawnPending = false; }
}
