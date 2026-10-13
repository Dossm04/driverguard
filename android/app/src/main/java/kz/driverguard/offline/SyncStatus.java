package kz.driverguard.offline;

import android.content.Context;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

final class SyncStatus {
    static void success(Context c,String owner){if(owner!=null)c.getSharedPreferences("sync_status",0).edit().putLong(owner+":ok",System.currentTimeMillis()).putBoolean(owner+":failed",false).apply();}
    static void failure(Context c,String owner){if(owner!=null)c.getSharedPreferences("sync_status",0).edit().putBoolean(owner+":failed",true).apply();}
    static String summary(Context c,String owner,EventStore store){
        if(owner==null)return "Локальный режим · данные остаются на телефоне";
        var p=c.getSharedPreferences("sync_status",0);long at=p.getLong(owner+":ok",0);
        String last=at==0?"успешная связь ещё не проверена":DateTimeFormatter.ofPattern("dd.MM HH:mm:ss").withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli(at));
        return (p.getBoolean(owner+":failed",false)?"Нет подтверждённой связи · данные сохранены":"Последняя успешная связь: "+last)
            +"\nЖдут отправки: "+store.pendingCount(owner)+" событий, "+store.feedbackPending(owner)+" комментариев"
            +(p.getBoolean(owner+":failed",false)?"\nПоследний успешный обмен: "+last:"");
    }
}
