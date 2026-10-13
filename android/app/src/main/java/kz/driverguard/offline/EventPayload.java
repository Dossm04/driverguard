package kz.driverguard.offline;
import org.json.JSONObject;

final class EventPayload {
    static boolean uploadable(String kind){return kind.equals("rest_started")||kind.equals("rest_ended")||kind.equals("yawn")||kind.equals("face_missing")||kind.equals("eyes_closed")||kind.equals("fatigue_perclos")||kind.equals("fatigue_yawning")||kind.equals("head_nod")||kind.equals("distraction_warning")||kind.equals("distraction_critical")||kind.equals("speeding")||kind.equals("camera_sabotage");}
    static JSONObject of(EventOutbox.Pending p)throws Exception{
        String type,severity,note;
        switch(p.kind()){
            case "rest_started":type="rest_started";severity="info";note="Driver manually started rest; monitoring paused";break;
            case "rest_ended":type="rest_ended";severity="info";note="Driver manually ended rest; duration seconds="+p.value()+"; not proof of fitness to drive";break;
            case "yawn":type="yawn";severity="info";note="Sustained mouth opening / possible yawn; not proof of fatigue";break;
            case "face_missing":type="camera_unavailable";severity="info";note="Face or eye measurement unavailable for at least 3 seconds; adjust camera; no driver penalty";break;
            case "eyes_closed":type="microsleep";severity="critical";note="Prolonged eye closure: "+p.closedMs()+" ms";break;
            case "fatigue_perclos":type="fatigue";severity="warning";note="Time-weighted PERCLOS: "+p.value()+" percent of valid observed time; 60 s sliding window, minimum 15 s valid observations";break;
            case "fatigue_yawning":type="fatigue";severity="warning";note="Repeated mouth-opening observations: "+(int)p.value()+" in 10 minutes; possible yawning";break;
            case "head_nod":type="head_nod";severity="warning";note="Sustained downward head pose relative to calibrated baseline";break;
            case "distraction_warning":type="distraction";severity="warning";note="Head turned from calibrated baseline for at least 8 s with verified GPS speed above 20 km/h";break;
            case "distraction_critical":type="distraction";severity="critical";note="Head turned from calibrated baseline for at least 15 s with verified GPS speed above 20 km/h";break;
            case "speeding":type="speeding";severity="warning";note="GPS speed continuously exceeds selected route limit for more than 10 s";break;
            case "camera_sabotage":type="camera_sabotage";severity="critical";note="Face unavailable for at least 5 minutes while verified GPS speed exceeds 5 km/h; camera visibility needs review";break;
            default:throw new IllegalArgumentException("This observation is local only");
        }
        JSONObject out=new JSONObject().put("uuid",p.uuid()).put("type",type).put("severity",severity).put("ts",p.at())
            .put("value",p.value()).put("confidence",0.0).put("gps_valid",false).put("source","android_camera").put("detector",type.startsWith("rest_")?"driver_action":type.equals("speeding")?"gps_rules":"face_rules")
            .put("note","Android DriverGuard: "+note+"; source="+p.source()+(type.startsWith("rest_")?"":"; confidence uncalibrated (0 placeholder); visual observation, not a confirmed diagnosis"));
        // Eye blendshape activation is a measurement, not calibrated event confidence.
        if(p.metadata()!=null){
            JSONObject meta=new JSONObject(p.metadata());
            JSONObject measurements=meta.optJSONObject("measurements");
            if(measurements!=null)out.put("measurements",measurements);
            if(meta.optBoolean("gps_valid",false)){
                out.put("gps_valid",true).put("lat",meta.getDouble("lat"))
                    .put("lon",meta.getDouble("lon")).put("speed_kmh",meta.getDouble("speed_kmh"));
            }
        }
        if((type.equals("speeding")||type.equals("distraction")||type.equals("camera_sabotage"))&&!out.getBoolean("gps_valid"))
            throw new IllegalArgumentException("Movement-dependent events require captured GPS evidence");
        return out;
    }
}
