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
            EventSync sync=new EventSync((address,token,body)->{
                var current=api.session();
                if(current==null||!current.owner().equals(session.owner()))throw new SecurityException("Аккаунт изменился. Очередь сохранена.");
                return api.request("POST",address.substring(session.base().length()),body);
            });
            sync.attach(new EventSync.Account(session.base(),session.owner(),session.accessToken()));
            String status="";
            for(int i=0;i<5;i++){status=sync.flush(store);if(store.pendingCount(session.owner())==0)break;}
            return status;
        }
    }
    static void heartbeat(Context c,double fps)throws Exception{
        DriverApi api=new DriverApi(c);if(api.session()==null)return;
        api.post("/drivers/me/camera-heartbeat",new JSONObject().put("gps_valid",false).put("fps",Math.max(0,Math.min(120,fps))));
    }
}
