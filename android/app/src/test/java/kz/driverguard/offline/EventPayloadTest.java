package kz.driverguard.offline;
import org.junit.Test;
import static org.junit.Assert.*;
public class EventPayloadTest {
    private EventOutbox.Pending event(String kind,double value){return new EventOutbox.Pending("id","2026-10-11T10:00:00Z","phone",1600,.9f,kind,value);}
    @Test public void differentFatigueTriggersKeepTheirMeaning()throws Exception{
        var perclos=EventPayload.of(event("fatigue_perclos",25));
        var yawns=EventPayload.of(event("fatigue_yawning",3));
        assertEquals("fatigue",perclos.getString("type"));assertEquals("warning",perclos.getString("severity"));
        assertEquals(25,perclos.getDouble("value"),0);assertTrue(perclos.getString("note").contains("PERCLOS"));
        assertEquals(3,yawns.getDouble("value"),0);assertTrue(yawns.getString("note").contains("mouth-opening"));
        assertEquals(0,perclos.getDouble("confidence"),0);
    }
    @Test public void singleYawnAndMissingFaceNeverBecomeConfirmedViolation(){
        assertFalse(EventPayload.uploadable("yawn"));assertFalse(EventPayload.uploadable("face_missing"));
        assertThrows(IllegalArgumentException.class,()->EventPayload.of(event("yawn",1)));
    }
    @Test public void headAndEyeObservationsMapToSupportedTypes()throws Exception{
        assertEquals("head_nod",EventPayload.of(event("head_nod",2)).getString("type"));
        assertEquals("critical",EventPayload.of(event("eyes_closed",1.6)).getString("severity"));
    }
}
