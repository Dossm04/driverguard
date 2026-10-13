package kz.driverguard.offline;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.SystemClock;
import android.provider.Settings;
import android.widget.Toast;

final class RestUi {
    static int boot(Activity a){return Settings.Global.getInt(a.getContentResolver(),Settings.Global.BOOT_COUNT,0);}
    static String label(Activity a,EventStore store,String owner){var r=store.rest(owner);return r==null?"Отдых · приостановить наблюдение":"Отдых · "+RestPolicy.timer(RestPolicy.duration(r.started(),r.elapsed(),r.boot(),System.currentTimeMillis(),SystemClock.elapsedRealtime(),boot(a)));}
    static void toggle(Activity a,EventStore store,String owner,Runnable pause,Runnable changed){
        boolean active=store.rest(owner)!=null;
        new AlertDialog.Builder(a).setTitle(active?"Завершить отдых?":"Начать отдых?")
            .setMessage(active?"После отдыха запустите наблюдение вручную. Таймер не определяет готовность к вождению.":"Сначала безопасно остановитесь. Камера, запись и предупреждения будут выключены. Начало отдыха сохранится даже без интернета.")
            .setPositiveButton(active?"Завершить отдых":"Я остановился · отдых",(d,n)->{
                try{pause.run();if(active)store.endRest(owner,System.currentTimeMillis(),SystemClock.elapsedRealtime(),boot(a));else store.beginRest(owner,System.currentTimeMillis(),SystemClock.elapsedRealtime(),boot(a));changed.run();}
                catch(Exception e){Toast.makeText(a,"Не удалось сохранить отдых. Проверьте память.",Toast.LENGTH_LONG).show();}
            }).setNegativeButton("Отмена",null).show();
    }
}
