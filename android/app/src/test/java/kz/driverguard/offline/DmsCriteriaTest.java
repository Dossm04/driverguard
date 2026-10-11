package kz.driverguard.offline;

import org.junit.Test;
import static org.junit.Assert.*;

/** Tests the original DriverGuard criteria without camera or GPS hardware. */
public class DmsCriteriaTest {
    private DmsRules.Result frame(DmsRules rules, long t, boolean face, float blink,
                                  float ear, float head, float yaw, double speed, int limit) {
        return rules.update(t, face, blink, blink, 0, head, ear, yaw, speed, limit);
    }
    private DmsRules calibrated() {
        DmsRules rules = new DmsRules();
        for (int t = 0; t <= 3000; t += 100) frame(rules, t, true, 0, .30f, 0, 0, 0, 90);
        return rules;
    }

    @Test public void earFallbackDetectsClosureWhenBlendshapesMissItAndRequiresEarRecovery() {
        DmsRules rules = calibrated(); DmsRules.Result result = null; int emitted = 0;
        for (int t = 3100; t <= 4800; t += 100) {
            result = frame(rules, t, true, 0, .10f, 0, 0, Double.NaN, 90);
            if (result.events().contains("eyes_closed")) { emitted++; assertEquals(4600, t); }
        }
        assertEquals(1, emitted); assertTrue(result.eyeCalibrated());
        assertEquals(.30f, result.earBaseline(), .0001f); assertTrue(result.closureAlarm());
        assertTrue(frame(rules, 4900, true, 0, .19f, 0, 0, 0, 90).closureAlarm());
        assertTrue(frame(rules, 5000, true, 0, .30f, 0, 0, 0, 90).closureAlarm());
        assertFalse(frame(rules, 5200, true, 0, .30f, 0, 0, 0, 90).closureAlarm());
        assertEquals(0, frame(rules, 5300, true, 0, .30f, 0, 0, 0, 90).blinkCount());
    }

    @Test public void calibrationRequiresThreeSecondsStableOpenEyes() {
        DmsRules rules = new DmsRules();
        for (int t = 0; t <= 5000; t += 100)
            assertFalse(frame(rules, t, true, 1, .30f, 0, 0, 0, 90).eyeCalibrated());
        for (int t = 5100; t <= 10000; t += 100)
            assertFalse(frame(rules, t, true, 0, t % 200 == 0 ? .20f : .40f, 0, 0, 0, 90).eyeCalibrated());
        rules.reset();
        for (int t = 0; t < 3000; t += 100)
            assertFalse(frame(rules, t, true, 0, .30f, 0, 0, 0, 90).eyeCalibrated());
        assertTrue(frame(rules, 3000, true, 0, .30f, 0, 0, 0, 90).eyeCalibrated());
    }

    @Test public void missingFaceStaleFrameAndInvalidGeometryResetPersonalEvidence() {
        DmsRules rules = calibrated();
        assertFalse(frame(rules, 3100, false, 0, .30f, 0, 0, 0, 90).eyeCalibrated());
        assertFalse(frame(rules, 3200, true, 0, .10f, 0, 0, 0, 90).eyesClosed());
        rules = calibrated();
        assertFalse(frame(rules, 4001, true, 0, .10f, 0, 0, 0, 90).eyeCalibrated());
        rules = calibrated();
        for (int t = 3100; t <= 4700; t += 100) frame(rules, t, true, 0, .10f, 0, 0, 0, 90);
        DmsRules.Result invalid = frame(rules, 4800, true, 0, Float.NaN, 0, 0, 0, 90);
        assertFalse(invalid.closureAlarm()); assertFalse(invalid.eyeCalibrated()); assertFalse(invalid.faceVisible());
    }

    @Test public void blinksUseObservedClosureDurationWithoutAddingOpeningGrace() {
        for (int duration : new int[]{50, 60, 300, 500, 501, 600}) {
            DmsRules rules = new DmsRules(); rules.update(0, true, 1, 1);
            DmsRules.Result firstOpen = rules.update(duration, true, 0, 0);
            assertEquals(0, firstOpen.blinkCount());
            DmsRules.Result confirmed = rules.update(duration + 200, true, 0, 0);
            assertEquals("duration=" + duration, duration >= 60 && duration <= 500 ? 1 : 0, confirmed.blinkCount());
        }
    }

    @Test public void observedBlinkWindowExpiresAndInterruptedBlinkIsNotCounted() {
        DmsRules rules = new DmsRules(); rules.update(0, true, 1, 1); rules.update(100, true, 0, 0);
        assertEquals(1, rules.update(300, true, 0, 0).blinkCount());
        assertEquals(0, rules.update(60101, true, 0, 0).blinkCount());
        rules.reset(); rules.update(0, true, 1, 1); rules.update(100, false, 0, 0);
        assertEquals(0, rules.update(300, true, 0, 0).blinkCount());
    }

    @Test public void headRawDepthUsesPointThirteenAndTwoSeconds() {
        DmsRules rules = calibrated(); int emitted = 0;
        for (int t = 3100; t <= 6000; t += 100)
            assertFalse(frame(rules, t, true, 0, .30f, .13f, 0, 0, 90).events().contains("head_nod"));
        for (int t = 6100; t <= 9000; t += 100) {
            DmsRules.Result result = frame(rules, t, true, 0, .30f, .14f, 0, 0, 90);
            if (result.events().contains("head_nod")) { emitted++; assertEquals(8100, t); }
            assertEquals(.14f, result.headDelta(), .0001f);
        }
        assertEquals(1, emitted);
    }

    @Test public void yawHasLocalMeasurementButNeverUploadsWithoutVerifiedMotion() {
        for (double speed : new double[]{Double.NaN, Double.POSITIVE_INFINITY, -1, 0, 20, 301}) {
            DmsRules rules = calibrated(); DmsRules.Result result = null;
            for (int t = 3100; t <= 22000; t += 100) {
                result = frame(rules, t, true, 0, .30f, 0, .50f, speed, 90);
                assertFalse(result.events().contains("distraction_warning"));
                assertFalse(result.events().contains("distraction_critical")); assertFalse(result.distractionCritical());
            }
            assertEquals(18900, result.awayMs()); assertEquals(0, result.movingAwayMs());
        }
    }

    @Test public void continuousMovingYawEmitsAtEightThenFifteenSecondsAndRearms() {
        DmsRules rules = calibrated(); int warnings = 0, critical = 0;
        for (int t = 3100; t <= 20000; t += 100) {
            DmsRules.Result result = frame(rules, t, true, 0, .30f, 0, .50f, 21, 90);
            if (result.events().contains("distraction_warning")) { warnings++; assertEquals(11100, t); }
            if (result.events().contains("distraction_critical")) { critical++; assertEquals(18100, t); }
            assertEquals(t >= 18100, result.distractionCritical());
        }
        assertEquals(1, warnings); assertEquals(1, critical);
        DmsRules.Result forward = frame(rules, 20100, true, 0, .30f, 0, 0, 21, 90);
        assertFalse(forward.distractionCritical()); assertEquals(0, forward.awayMs());
        for (int t = 20200; t < 28200; t += 100) frame(rules, t, true, 0, .30f, 0, -.50f, 21, 90);
        assertTrue(frame(rules, 28200, true, 0, .30f, 0, -.50f, 21, 90).events().contains("distraction_warning"));
    }

    @Test public void unknownSpeedResetsMovingYawTimerButPreservesLocalAwayDuration() {
        DmsRules rules = calibrated();
        for (int t = 3100; t <= 11000; t += 100) frame(rules, t, true, 0, .30f, 0, .50f, 30, 90);
        DmsRules.Result lost = frame(rules, 11100, true, 0, .30f, 0, .50f, Double.NaN, 90);
        assertEquals(8000, lost.awayMs()); assertEquals(0, lost.movingAwayMs()); assertTrue(lost.events().isEmpty());
        for (int t = 11200; t < 19200; t += 100) {
            DmsRules.Result result = frame(rules, t, true, 0, .30f, 0, .50f, 30, 90);
            assertFalse(result.events().contains("distraction_warning"));
        }
        DmsRules.Result result = frame(rules, 19200, true, 0, .30f, 0, .50f, 30, 90);
        assertEquals(8000, result.movingAwayMs()); assertTrue(result.events().contains("distraction_warning"));
    }

    @Test public void missingFaceCannotBecomeDistractionAndRequiresRecalibration() {
        DmsRules rules = calibrated();
        for (int t = 3100; t <= 22000; t += 100) {
            DmsRules.Result result = frame(rules, t, false, 0, .30f, 0, .50f, 30, 90);
            assertFalse(result.distractionCritical()); assertEquals(0, result.awayMs());
            assertFalse(result.events().contains("distraction_warning"));
        }
        DmsRules.Result back = frame(rules, 22100, true, 0, .30f, 0, .50f, 30, 90);
        assertFalse(back.eyeCalibrated()); assertTrue(Float.isNaN(back.yawDelta()));
    }

    @Test public void cameraSabotageNeedsContinuousFiveMinuteMotionAndEmitsOnce() {
        DmsRules rules = new DmsRules(); int warning = 0, sabotage = 0;
        for (int t = 0; t <= 310000; t += 1000) {
            DmsRules.Result result = frame(rules, t, false, 0, .30f, 0, 0, 6, 90);
            if (result.events().contains("face_missing")) { warning++; assertEquals(3000, t); }
            if (result.events().contains("camera_sabotage")) { sabotage++; assertEquals(300000, t); }
        }
        assertEquals(1, warning); assertEquals(1, sabotage);
        assertEquals(0, frame(rules, 310100, true, 0, .30f, 0, 0, 6, 90).movingMissingMs());
    }

    @Test public void temporarySpeedLossCannotRecountAnAlreadyReportedFaceAbsence() {
        DmsRules rules = new DmsRules(); int events = 0;
        for (int t = 0; t <= 605000; t += 1000) {
            double speed = t == 302000 ? Double.NaN : 6;
            if (frame(rules, t, false, 0, .3f, 0, 0, speed, 90).events().contains("camera_sabotage")) events++;
        }
        assertEquals(1, events);
    }

    @Test public void unknownMotionAndInvalidLandmarksNeverProduceCameraSabotage() {
        for (boolean face : new boolean[]{false, true}) {
            DmsRules rules = new DmsRules();
            for (int t = 0; t <= 310000; t += 1000) {
                DmsRules.Result result = frame(rules, t, face, 0, Float.NaN, 0, 0,
                    face ? 30 : Double.NaN, 90);
                assertFalse(result.events().contains("camera_sabotage"));
            }
        }
        DmsRules rules = new DmsRules();
        for (int t = 0; t <= 299000; t += 1000) frame(rules, t, false, 0, .3f, 0, 0, 6, 90);
        assertEquals(0, frame(rules, 300000, false, 0, .3f, 0, 0, Double.NaN, 90).movingMissingMs());
        DmsRules.Result resumed = frame(rules, 301000, false, 0, .3f, 0, 0, 6, 90);
        assertEquals(301000, resumed.missingMs()); assertEquals(0, resumed.movingMissingMs());
        assertFalse(resumed.events().contains("camera_sabotage"));
    }

    @Test public void speedingUsesTenSecondsAndSixtySecondCooldownEvenWithoutFace() {
        DmsRules rules = new DmsRules(); int events = 0;
        for (int t = 0; t <= 71000; t += 1000) {
            DmsRules.Result result = frame(rules, t, false, 0, .3f, 0, 0, 70, 60);
            if (result.events().contains("speeding")) { events++; assertTrue(t == 10000 || t == 70000); }
        }
        assertEquals(2, events);
    }

    @Test public void speedFixLossAndProfileChangesBreakSpeedingContinuity() {
        DmsRules rules = new DmsRules();
        for (int t = 0; t <= 9000; t += 1000) frame(rules, t, true, 0, .3f, 0, 0, 100, 60);
        assertFalse(frame(rules, 10000, true, 0, .3f, 0, 0, Double.NaN, 60).events().contains("speeding"));
        for (int t = 11000; t <= 19000; t += 1000) frame(rules, t, true, 0, .3f, 0, 0, 100, 60);
        assertFalse(frame(rules, 20000, true, 0, .3f, 0, 0, 100, 90).events().contains("speeding"));
        for (int t = 21000; t < 30000; t += 1000)
            assertFalse(frame(rules, t, true, 0, .3f, 0, 0, 100, 90).events().contains("speeding"));
        assertTrue(frame(rules, 30000, true, 0, .3f, 0, 0, 100, 90).events().contains("speeding"));
    }

    @Test public void staleFrameCannotCompleteAMovingCondition() {
        DmsRules rules = calibrated();
        for (int t = 3100; t <= 10000; t += 100) frame(rules, t, true, 0, .3f, 0, .5f, 100, 90);
        DmsRules.Result result = frame(rules, 13000, true, 0, .3f, 0, .5f, 100, 90);
        assertFalse(result.eyeCalibrated()); assertEquals(0, result.movingAwayMs());
        assertFalse(result.events().contains("distraction_warning")); assertFalse(result.events().contains("speeding"));
    }
}
