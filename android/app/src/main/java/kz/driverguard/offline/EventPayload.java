package kz.driverguard.offline;
import org.json.JSONObject;

final class EventPayload {
    static boolean uploadable(String kind){return kind.equals("eyes_closed")||kind.equals("fatigue_perclos")||kind.equals("fatigue_yawning")||kind.equals("head_nod");}
    static JSONObject of(EventOutbox.Pending p)throws Exception{
        String type,severity,note;
        switch(p.kind()){
            case "eyes_closed":type="microsleep";severity="critical";note="Prolonged eye closure: "+p.closedMs()+" ms";break;
            case "fatigue_perclos":type="fatigue";severity="warning";note="Time-weighted PERCLOS: "+p.value()+" percent of valid observed time; 60 s sliding window, minimum 15 s valid observations";break;
            case "fatigue_yawning":type="fatigue";severity="warning";note="Repeated mouth-opening observations: "+(int)p.value()+" in 10 minutes; possible yawning";break;
            case "head_nod":type="head_nod";severity="warning";note="Sustained downward head pose relative to calibrated baseline";break;
            default:throw new IllegalArgumentException("This observation is local only");
        }
        JSONObject out=new JSONObject().put("uuid",p.uuid()).put("type",type).put("severity",severity).put("ts",p.at())
            .put("value",p.value()).put("confidence",0.0).put("gps_valid",false).put("detector","face_rules")
            .put("note","Android DriverGuard: "+note+"; source="+p.source()+"; confidence uncalibrated (0 placeholder); visual observation, not a confirmed diagnosis");
        // Eye blendshape activation is a measurement, not calibrated event confidence.
        return out;
    }
}
