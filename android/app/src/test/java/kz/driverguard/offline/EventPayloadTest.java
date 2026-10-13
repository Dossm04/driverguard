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
    @Test public void singleYawnAndMissingFaceUploadAsNeutralObservations()throws Exception{
        assertTrue(EventPayload.uploadable("yawn"));assertTrue(EventPayload.uploadable("face_missing"));
        assertEquals("info",EventPayload.of(event("yawn",1)).getString("severity"));
        assertEquals("camera_unavailable",EventPayload.of(event("face_missing",3)).getString("type"));
        assertEquals(0,EventPayload.of(event("face_missing",3)).getDouble("confidence"),0);
        assertFalse(EventPayload.uploadable("phone"));assertFalse(EventPayload.uploadable("seatbelt"));
    }
    @Test public void headAndEyeObservationsMapToSupportedTypes()throws Exception{
        assertEquals("head_nod",EventPayload.of(event("head_nod",2)).getString("type"));
        assertEquals("critical",EventPayload.of(event("eyes_closed",1.6)).getString("severity"));
    }
    @Test public void actualMeasurementsAndOriginalCaptureTimeSurviveDelayedUpload()throws Exception{
        String meta="{\"measurements\":{\"rule_version\":\"android-0.6\",\"closed_ms\":1700,\"ear\":0.12,\"ear_baseline\":0.29,\"perclos_pct\":24.5,\"yawns_10min\":3},\"gps_valid\":false}";
        var p=new EventOutbox.Pending("id","2026-10-11T10:00:00Z","phone",1700,.8f,"eyes_closed",1.7,meta);
        var payload=EventPayload.of(p);
        assertEquals("android_camera",payload.getString("source"));
        assertEquals("2026-10-11T10:00:00Z",payload.getString("ts"));
        assertEquals(.12,payload.getJSONObject("measurements").getDouble("ear"),.00001);
        assertFalse(payload.getBoolean("gps_valid"));assertFalse(payload.has("lat"));
    }
    @Test public void movementEventsCannotUploadWithoutCapturedGps(){
        for(String kind:new String[]{"distraction_warning","distraction_critical","camera_sabotage","speeding"})
            assertThrows(IllegalArgumentException.class,()->EventPayload.of(event(kind,15)));
    }
    @Test public void speedingAndDistractionKeepEvidenceAndSeverity()throws Exception{
        String meta="{\"gps_valid\":true,\"lat\":51.1,\"lon\":71.4,\"speed_kmh\":72,\"measurements\":{\"speed_limit_kmh\":60}}";
        var speeding=EventPayload.of(new EventOutbox.Pending("id","2026-10-11T10:00:00Z","phone",0,0,"speeding",12,meta));
        assertEquals("gps_rules",speeding.getString("detector"));assertEquals(12,speeding.getDouble("value"),0);
        assertTrue(speeding.getBoolean("gps_valid"));assertEquals(72,speeding.getDouble("speed_kmh"),0);
        var critical=EventPayload.of(new EventOutbox.Pending("id","2026-10-11T10:00:00Z","phone",0,0,"distraction_critical",15,meta));
        assertEquals("distraction",critical.getString("type"));assertEquals("critical",critical.getString("severity"));
    }
}
