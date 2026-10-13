package kz.driverguard.offline;

import android.content.Context;
import org.json.JSONObject;

/** One upload pass across all native screens; the queue stays bound to its original driver. */
final class SyncCoordinator {
    private static final Object LOCK=new Object();
    static String events(Context context,EventStore store)throws Exception{
        synchronized(LOCK){
            DriverApi api=new DriverApi(context);var session=api.session();
            if(session==null)return "Локальный режим · войдите для отправки";
            try{
                JSONObject capabilities=api.get("/drivers/me/camera-capabilities");
                if(capabilities.optInt("measurements_version",0)<1||!capabilities.optBoolean("gps_rules",false)||capabilities.optInt("observation_events_version",0)<1||capabilities.optInt("driver_care_version",0)<1)
                    return "Серверу нужно обновление · измерения сохранены на телефоне";
            EventSync sync=new EventSync((address,token,body)->{
                var current=api.session();
                if(current==null||!current.owner().equals(session.owner()))throw new SecurityException("Аккаунт изменился. Очередь сохранена.");
                return api.request("POST",address.substring(session.base().length()),body);
            });
            sync.attach(new EventSync.Account(session.base(),session.owner(),session.accessToken()));
            String status="";
            for(int i=0;i<5;i++){status=sync.flush(store);if(store.pendingCount(session.owner())==0)break;}
            store.flushFeedback(api,session.owner());SyncStatus.success(context,session.owner());
            return status;
            }catch(Exception e){SyncStatus.failure(context,session.owner());throw e;}
        }
    }
    static void heartbeat(Context c,double fps)throws Exception{
        heartbeat(c,fps,DrivingSample.unavailable(),0);
    }
    static void heartbeat(Context c,double fps,DrivingSample gps,long now)throws Exception{
        DriverApi api=new DriverApi(c);if(api.session()==null)return;
        JSONObject body=new JSONObject().put("gps_valid",gps.validAt(now)).put("fps",Math.max(0,Math.min(120,fps)));
        if(gps.validAt(now))body.put("lat",gps.latitude()).put("lon",gps.longitude()).put("speed_kmh",gps.speedKmh());
        api.post("/drivers/me/camera-heartbeat",body);
    }
}
