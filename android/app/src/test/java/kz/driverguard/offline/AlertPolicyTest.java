package kz.driverguard.offline;
import org.junit.Test;
import static org.junit.Assert.*;

public class AlertPolicyTest {
    private DmsRules activeRules() {
        DmsRules rules=new DmsRules();
        for(int t=0;t<1500;t+=100)rules.update(t,true,1,1);
        return rules;
    }
    @Test public void pulsesContinueWithoutRepeatingJournalEvents() {
        DmsRules rules=activeRules();AlertPolicy policy=new AlertPolicy();int pulses=0,events=0;
        for(int t=1500;t<=6000;t+=100) {
            DmsRules.Result result=rules.update(t,true,1,1);
            if(result.events().contains("eyes_closed"))events++;
            policy.onFrame(t,result);AlertPolicy.Decision decision=policy.poll(t,true,false);
            assertTrue(decision.active());if(decision.playPulse())pulses++;
        }
        assertEquals(1,events);assertEquals(6,pulses);
    }
    @Test public void confirmedOpenEyesStopAndNewEpisodeRearms() {
        DmsRules rules=activeRules();AlertPolicy policy=new AlertPolicy();
        policy.onFrame(1500,rules.update(1500,true,1,1));assertTrue(policy.poll(1500,true,false).playPulse());
        policy.onFrame(1600,rules.update(1600,true,0,0));assertTrue(policy.poll(1600,true,false).active());
        policy.onFrame(1800,rules.update(1800,true,0,0));assertFalse(policy.poll(1800,true,false).active());
        for(int t=1900;t<=3400;t+=100)policy.onFrame(t,rules.update(t,true,1,1));
        assertTrue(policy.poll(3400,true,false).playPulse());
    }
    @Test public void missingFaceStopsSound() {
        DmsRules rules=activeRules();AlertPolicy policy=new AlertPolicy();
        policy.onFrame(1500,rules.update(1500,true,1,1));policy.poll(1500,true,false);
        policy.onFrame(1600,rules.update(1600,false,1,1));
        assertFalse(policy.poll(1600,true,false).active());
    }
    @Test public void frozenCameraStopsSoundWithoutAnotherFrame() {
        DmsRules rules=activeRules();AlertPolicy policy=new AlertPolicy();
        policy.onFrame(1500,rules.update(1500,true,1,1));policy.poll(1500,true,false);
        assertTrue(policy.poll(2400,true,false).playPulse());
        assertFalse(policy.poll(2501,true,false).active());
        assertFalse(policy.poll(10000,true,false).playPulse());
    }
    @Test public void muteDoesNotChangeDetectionAndUnmuteCanResume() {
        DmsRules rules=activeRules();AlertPolicy policy=new AlertPolicy();
        DmsRules.Result result=rules.update(1500,true,1,1);policy.onFrame(1500,result);
        assertTrue(result.closureAlarm());assertFalse(policy.poll(1500,true,true).active());
        assertTrue(policy.poll(1600,true,false).playPulse());
    }
    @Test public void stopAndResetCannotKeepOldAlarmAlive() {
        DmsRules rules=activeRules();AlertPolicy policy=new AlertPolicy();
        policy.onFrame(1500,rules.update(1500,true,1,1));policy.poll(1500,true,false);
        assertFalse(policy.poll(1600,false,false).active());
        assertFalse(policy.poll(1700,true,false).active());
        policy.reset();assertFalse(policy.poll(1800,true,false).active());
    }
    @Test public void invalidTimeAndDelayedInferenceCannotStartPulse() {
        DmsRules rules=activeRules();AlertPolicy policy=new AlertPolicy();
        policy.onFrame(1500,rules.update(1500,true,1,1));
        assertFalse(policy.poll(3000,true,false).active());
        assertFalse(policy.poll(1000,true,false).active());
        policy.onFrame(-1,null);assertFalse(policy.poll(1600,true,false).active());
    }
    @Test public void fatigueWarningIsOneShortPulseAndNotEachOrdinaryYawn() {
        DmsRules rules=new DmsRules();AlertPolicy policy=new AlertPolicy();int warnings=0;
        for(int t=0;t<=9000;t+=200) {
            policy.onFrame(t,rules.update(t,true,0,0,t%3000<=1400?1:0));
            AlertPolicy.Decision result=policy.poll(t,true,false);
            assertFalse(result.active());assertFalse(result.playPulse());
            if(result.warningPulse()){assertEquals(7200,t);warnings++;}
        }
        assertEquals(1,warnings);
    }
    @Test public void perclosWarningHasCooldownWithoutRepeatedSoundEveryFrame() {
        DmsRules rules=new DmsRules();AlertPolicy policy=new AlertPolicy();int warnings=0;
        for(int t=0;t<=46000;t+=100) {
            // Shorter closures raise the window fraction without reaching the long-closure alarm.
            float blink=t%2000<800?1:0;
            policy.onFrame(t,rules.update(t,true,blink,blink,0));
            AlertPolicy.Decision result=policy.poll(t,true,false);
            assertFalse(result.active());
            if(result.warningPulse()){assertTrue(t==15000||t==45000);warnings++;}
        }
        assertEquals(2,warnings);
    }
    @Test public void stalePendingWarningCannotBePlayedAfterGap() {
        DmsRules rules=new DmsRules();AlertPolicy policy=new AlertPolicy();
        DmsRules.Result result=null;
        for(int t=0;t<=15000;t+=100) {
            float blink=t%2000<800?1:0;
            result=rules.update(t,true,blink,blink,0);
        }
        assertTrue(result.events().contains("fatigue_perclos"));policy.onFrame(15000,result);
        policy.onFrame(20000,rules.update(20000,true,0,0,0));
        assertFalse(policy.poll(20000,true,false).warningPulse());
    }
}
