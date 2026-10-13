package kz.driverguard.offline;

import org.junit.Test;
import static org.junit.Assert.*;

public class GradedSoundPolicyTest {
    private final AlertPolicy.Decision active=new AlertPolicy.Decision(true,true,false);
    @Test public void startsSoftAndEscalatesAtFiveSeconds(){
        var p=new GradedSoundPolicy();
        assertEquals(GradedSoundPolicy.Level.SOFT,p.poll(1500,active,1500,false).level());
        assertFalse(p.poll(2400,active,2400,false).play());
        assertTrue(p.poll(4000,active,4000,false).play());
        var loud=p.poll(5000,active,5000,false);assertTrue(loud.play());assertEquals(GradedSoundPolicy.Level.URGENT,loud.level());
        assertFalse(p.poll(5900,active,5900,false).play());assertTrue(p.poll(6500,active,6500,false).play());
    }
    @Test public void openEyesMuteMissingFramesAndStopCannotKeepSiren(){
        var p=new GradedSoundPolicy();p.poll(6000,active,6000,false);
        var stopped=p.poll(6100,new AlertPolicy.Decision(false,false,false),6000,false);
        assertEquals(GradedSoundPolicy.Level.NONE,stopped.level());assertFalse(stopped.play());assertFalse(stopped.alarm());
        var next=p.poll(8000,active,1500,false);assertEquals(GradedSoundPolicy.Level.SOFT,next.level());assertTrue(next.play());
    }
    @Test public void warningAndMissingCameraAreSoftNotSiren(){
        var d=new GradedSoundPolicy().poll(3000,new AlertPolicy.Decision(false,false,true),0,false);
        assertEquals(GradedSoundPolicy.Level.SOFT,d.level());assertTrue(d.play());assertFalse(d.alarm());
    }
    @Test public void prolongedMovingDistractionUsesUrgentSound(){
        var d=new GradedSoundPolicy().poll(18000,active,0,true);
        assertEquals(GradedSoundPolicy.Level.URGENT,d.level());assertTrue(d.play());
    }
}
