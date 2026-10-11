package kz.driverguard.offline;
import org.junit.Test;
import static org.junit.Assert.*;
public class DmsRulesTest {
    @Test public void blinkIsNotAlarm() {
        DmsRules r = new DmsRules();
        assertNull(r.update(0,true,1,1).event());
        assertNull(r.update(200,true,0,0).event());
    }
    @Test public void continuousClosureTriggersOnceAndRearmsOnOpen() {
        DmsRules r = new DmsRules();
        for (int t=0;t<1500;t+=250) assertNull(r.update(t,true,1,1).event());
        assertEquals("eyes_closed",r.update(1500,true,1,1).event());
        assertNull(r.update(1750,true,1,1).event());
        r.update(2000,true,0,0);
        r.update(2200,true,0,0);
        for (int t=2250;t<3750;t+=250) r.update(t,true,1,1);
        assertEquals("eyes_closed",r.update(3750,true,1,1).event());
    }
    @Test public void missingFaceAndFrozenStreamResetEvidence() {
        DmsRules r=new DmsRules(); r.update(0,true,1,1); r.update(800,true,1,1);
        r.update(900,false,0,0); assertNull(r.update(1600,true,1,1).event());
        assertNull(r.update(6000,true,1,1).event());
        assertEquals(0,r.update(5500,true,1,1).closedMs());
    }
    @Test public void oneEyeAndInvalidScoreCannotTriggerClosure() {
        DmsRules r=new DmsRules();
        for(int t=0;t<5000;t+=200) assertNull(r.update(t,true,1,0).event());
        assertEquals("Face not visible. Adjust the camera.",r.update(5100,true,Float.NaN,1).status());
    }
    @Test public void restartDoesNotCarryClosureIntoNewSession() {
        DmsRules r=new DmsRules();r.update(0,true,1,1);r.update(800,true,1,1);r.reset();
        assertEquals(0,r.update(900,true,1,1).closedMs());
        assertNull(r.update(1600,true,1,1).event());
    }
    @Test public void missingFaceEmitsOnceAndRearmsAfterVisibleFace() {
        DmsRules r=new DmsRules();
        for(int t=0;t<3000;t+=200)assertNull(r.update(t,false,0,0).event());
        assertEquals("face_missing",r.update(3000,false,0,0).event());
        assertNull(r.update(3200,false,0,0).event());
        r.update(3400,true,0,0);
        assertNull(r.update(3600,false,0,0).event());
    }
    @Test public void slowProcessingGapCannotProduceAnEyeAlarm() {
        DmsRules r=new DmsRules();r.update(0,true,1,1);r.update(800,true,1,1);
        assertEquals(0,r.update(1901,true,1,1).closedMs());
        assertNull(r.update(2101,true,1,1).event());
    }

    @Test public void prolongedClosureStaysActiveWithoutDuplicatingItsEvent() {
        DmsRules r=new DmsRules(); int events=0;
        for(int t=0;t<=10000;t+=100) {
            DmsRules.Result result=r.update(t,true,1,1);
            if(result.events().contains("eyes_closed")) events++;
            assertEquals(t>=1500,result.closureAlarm());
        }
        assertEquals(1,events);
        assertTrue(r.update(10100,true,0,0).closureAlarm());
        assertFalse(r.update(10300,true,0,0).closureAlarm());
    }

    @Test public void outOfRangeScoresAndNegativeTimeAreNotEvidence() {
        DmsRules r=new DmsRules();
        assertFalse(r.update(0,true,1.1f,1).faceVisible());
        assertFalse(r.update(500,true,-0.1f,1).faceVisible());
        assertFalse(r.update(1000,true,Float.POSITIVE_INFINITY,1).faceVisible());
        assertFalse(r.update(-1,true,1,1).faceVisible());
        assertEquals(0,r.update(2000,true,1,1).closedMs());
    }

    @Test public void perclosIsWeightedByTimeRatherThanFrameCount() {
        DmsRules r=new DmsRules();
        r.update(0,true,1,1);r.update(100,true,1,1);r.update(200,true,1,1);
        DmsRules.Result result=r.update(1000,true,0,0);
        assertEquals(0.2f,result.perclos(),0.0001f);
        assertEquals(1000,result.validMs());
        assertFalse(result.perclosReady());
    }

    @Test public void perclosNeedsCoverageThenUsesThirtySecondCooldown() {
        DmsRules r=new DmsRules(); int warnings=0;
        for(int t=0;t<=46000;t+=100) {
            float blink=t%4000<2000?1:0;
            DmsRules.Result result=r.update(t,true,blink,blink);
            assertEquals(t>=15000,result.perclosReady());
            if(result.events().contains("fatigue_perclos")) {
                assertTrue(t==15000||t==45000);warnings++;
            }
        }
        assertEquals(2,warnings);
    }

    @Test public void missingObservationCannotCreateFatigueFromTinyVisibleSubset() {
        DmsRules r=new DmsRules();
        for(int t=0;t<=15000;t+=100)r.update(t,true,1,1);
        for(int t=15100;t<30000;t+=100)r.update(t,false,1,1);
        DmsRules.Result result=r.update(30000,true,1,1);
        assertEquals(15000,result.validMs());
        assertEquals(0.5f,result.validCoverage(),0.001f);
        assertFalse(result.perclosReady());
        assertFalse(result.fatigueActive());
        assertFalse(result.closureAlarm());
    }

    @Test public void frameGapIsExcludedAndBreaksContinuousClosure() {
        DmsRules r=new DmsRules();r.update(0,true,1,1);r.update(1000,true,1,1);
        DmsRules.Result result=r.update(5000,true,1,1);
        assertEquals(1000,result.validMs());
        assertEquals(0.2f,result.validCoverage(),0.001f);
        assertEquals(0,result.closedMs());
    }

    @Test public void rollingWindowRemovesOldEyeClosure() {
        DmsRules r=new DmsRules();DmsRules.Result result=null;
        for(int t=0;t<=80000;t+=100)result=r.update(t,true,t<20000?1:0,t<20000?1:0);
        assertNotNull(result);assertEquals(60000,result.validMs());
        assertTrue(result.perclosReady());assertEquals(0,result.perclos(),0.0001f);
        assertFalse(result.fatigueActive());
    }

    @Test public void sustainedMouthOpeningIsCountedOnceAndBriefOpeningIsIgnored() {
        DmsRules r=new DmsRules();int count=0;
        for(int t=0;t<=6000;t+=200) {
            DmsRules.Result result=r.update(t,true,0,0,1);
            if(result.events().contains("yawn")){assertEquals(1200,t);count++;}
        }
        assertEquals(1,count);
        r.update(6200,true,0,0,0);
        r.update(6400,true,0,0,1);
        assertEquals(1,r.update(6800,true,0,0,0).yawnCount());
    }

    @Test public void threeSeparateOpeningsProduceRepeatedYawnWarning() {
        DmsRules r=new DmsRules();int warnings=0;DmsRules.Result result=null;
        for(int t=0;t<=9000;t+=200) {
            float jaw=t%3000<=1400?1:0;
            result=r.update(t,true,0,0,jaw);
            if(result.events().contains("fatigue_yawning")) {
                assertEquals(7200,t);assertTrue(result.events().contains("yawn"));warnings++;
            }
        }
        assertEquals(1,warnings);assertEquals(3,result.yawnCount());assertTrue(result.fatigueActive());
        assertEquals(0,r.update(610000,true,0,0,0).yawnCount());
    }

    @Test public void jawThresholdNoiseCannotRecountTheSameOpening() {
        DmsRules r=new DmsRules();
        for(int t=0;t<=1400;t+=200)r.update(t,true,0,0,1);
        r.update(1600,true,0,0,0.4f);
        for(int t=1800;t<=5000;t+=200)assertEquals(1,r.update(t,true,0,0,1).yawnCount());
    }

    @Test public void missingFaceInterruptsJawEvidenceButMissingJawDoesNotDisableEyes() {
        DmsRules r=new DmsRules();r.update(0,true,0,0,1);r.update(800,true,0,0,1);
        r.update(900,false,0,0,1);
        assertEquals(0,r.update(1300,true,0,0,1).yawnCount());
        r.reset();
        for(int t=0;t<1500;t+=100)r.update(t,true,1,1,Float.NaN);
        assertEquals("eyes_closed",r.update(1500,true,1,1,Float.NaN).event());
    }

    @Test public void resetClearsAllWindowEvidence() {
        DmsRules r=new DmsRules();
        for(int t=0;t<=20000;t+=100)r.update(t,true,1,1,1);
        r.reset();DmsRules.Result result=r.update(20100,true,0,0,0);
        assertEquals(0,result.yawnCount());assertEquals(0,result.validMs());
        assertFalse(result.perclosReady());assertFalse(result.fatigueActive());
    }

    @Test public void headDownNeedsStableNeutralBaselineThenTwoSeconds() {
        DmsRules r=new DmsRules();DmsRules.Result result=null;
        for(int t=0;t<=3000;t+=100)result=r.update(t,true,0,0,0,0.2f);
        assertTrue(result.headCalibrated());int events=0;
        for(int t=3100;t<=6500;t+=100) {
            result=r.update(t,true,0,0,0,0.5f);
            if(result.events().contains("head_nod")){assertEquals(5100,t);events++;}
        }
        assertEquals(1,events);assertEquals(3400,result.headDownMs());
        assertEquals(0,r.update(6600,true,0,0,0,0.2f).headDownMs());
        for(int t=6700;t<8700;t+=100)r.update(t,true,0,0,0,0.5f);
        assertTrue(r.update(8700,true,0,0,0,0.5f).events().contains("head_nod"));
    }

    @Test public void headBaselineCannotCalibrateWhileMovingOrEyesClosed() {
        DmsRules r=new DmsRules();
        for(int t=0;t<=5000;t+=100)
            assertFalse(r.update(t,true,0,0,0,t%200==0?0.1f:0.5f).headCalibrated());
        for(int t=5100;t<=10000;t+=100)
            assertFalse(r.update(t,true,1,1,0,0.2f).headCalibrated());
    }

    @Test public void losingFaceOrStaleFramesRequiresHeadRecalibration() {
        DmsRules r=new DmsRules();
        for(int t=0;t<=3000;t+=100)r.update(t,true,0,0,0,0.2f);
        assertFalse(r.update(4500,true,0,0,0,0.5f).headCalibrated());
        for(int t=4600;t<=7500;t+=100)r.update(t,true,0,0,0,0.2f);
        for(int t=7600;t<=10600;t+=100)r.update(t,false,0,0,0,0.2f);
        assertFalse(r.update(10700,false,0,0,0,0.2f).headCalibrated());
    }

    @Test public void eyeThresholdNoiseAndSingleOpenFrameDoNotResetActiveAlarm() {
        DmsRules r=new DmsRules();int events=0;
        for(int t=0;t<=5000;t+=100) {
            float left=t==1800?0:t>=2000&&t<3000?0.4f:1;
            float right=t==1800?0:t>=2000&&t<3000?0.45f:1;
            DmsRules.Result result=r.update(t,true,left,right);
            if(result.events().contains("eyes_closed"))events++;
            if(t>=1500)assertTrue(result.closureAlarm());
        }
        assertEquals(1,events);
    }

    @Test public void clearOpenConfirmationDoesNotPromoteAlmostLongClosureToAlarm() {
        DmsRules r=new DmsRules();
        for(int t=0;t<1400;t+=100)r.update(t,true,1,1);
        DmsRules.Result opening=r.update(1400,true,0,0);
        assertEquals(1400,opening.closedMs());
        for(int t=1500;t<=1700;t+=100) {
            DmsRules.Result result=r.update(t,true,0,0);
            assertFalse(result.closureAlarm());assertFalse(result.events().contains("eyes_closed"));
        }
        assertEquals(0,r.update(1800,true,1,1).closedMs());
    }

    @Test public void confirmedOpenGapsKeepRepeatedShortBlinksSeparate() {
        DmsRules r=new DmsRules();
        for(int t=0;t<=10000;t+=100) {
            float blink=t%1000<400?1:0;
            DmsRules.Result result=r.update(t,true,blink,blink);
            assertFalse(result.closureAlarm());assertFalse(result.events().contains("eyes_closed"));
        }
    }

    @Test public void openingGraceDoesNotIncreasePerclos() {
        DmsRules r=new DmsRules();
        for(int t=0;t<=1000;t+=100)r.update(t,true,1,1);
        r.update(1100,true,0,0);r.update(1200,true,0,0);
        DmsRules.Result result=r.update(1300,true,0,0);
        assertEquals(1000f/1300f,result.perclos(),0.0001f);
        assertFalse(result.eyesClosed());
    }

    @Test public void invalidOrStaleFramesBypassOpeningHysteresisImmediately() {
        DmsRules r=new DmsRules();
        for(int t=0;t<=1600;t+=100)r.update(t,true,1,1);
        assertFalse(r.update(1700,false,1,1).closureAlarm());
        for(int t=1800;t<=3400;t+=100)r.update(t,true,1,1);
        assertFalse(r.update(3500,true,Float.NaN,1).closureAlarm());
        for(int t=3600;t<=5200;t+=100)r.update(t,true,1,1);
        assertFalse(r.update(6301,true,1,1).closureAlarm());
    }
}
