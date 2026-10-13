package kz.driverguard.offline;
import android.content.Context;
import android.content.SharedPreferences;
import org.json.*;

/** Assignments and local reading stay scoped to their original server and driver. */
final class LearningStore {
    private static final Object LOCK=new Object();
    private static final Object FLUSH_LOCK=new Object();
    private final SharedPreferences prefs;
    LearningStore(Context c){prefs=c.getSharedPreferences("learning_v1",Context.MODE_PRIVATE);}
    private String key(String owner,int assignment,String lesson){return owner+"|"+assignment+"|"+lesson;}
    String status(String owner,int assignment,String lesson){return prefs.getString(key(owner,assignment,lesson),"");}
    void complete(String owner,int assignment,String lesson){
        synchronized(LOCK){if(owner==null)throw new IllegalArgumentException("Сначала войдите");
            String key=key(owner,assignment,lesson);if(prefs.getString(key,"").equals("sent"))return;
            if(!prefs.edit().putString(key,assignment>0?"pending":"local").commit())throw new IllegalStateException("Не удалось сохранить прохождение урока");
        }
    }
    String flush(DriverApi api)throws Exception{
        synchronized(FLUSH_LOCK){var s=api.session();if(s==null)return "Уроки доступны после входа";
            JSONObject driver=s.profile().optJSONObject("driver");int driverId=driver==null?0:driver.optInt("id");if(driverId<=0)return "Обновите профиль для отправки уроков";
            int sent=0;
            for(var e:prefs.getAll().entrySet()){
                if(!e.getKey().startsWith(s.owner()+"|")||!"pending".equals(e.getValue()))continue;
                String[] parts=e.getKey().substring(s.owner().length()+1).split("\\|",2);if(parts.length!=2)continue;
                int id=Integer.parseInt(parts[0]);if(id<=0)continue;
                var current=api.session();if(current==null||!s.owner().equals(current.owner()))throw new SecurityException("Аккаунт изменился");
                JSONObject result=api.post("/drivers/"+driverId+"/trainings/"+id+"/complete",new JSONObject());
                if(result.optInt("id")!=id||!result.optString("status").equals("completed"))throw new IllegalStateException("Сервер не подтвердил урок");
                if(!prefs.edit().putString(e.getKey(),"sent").commit())throw new IllegalStateException("Подтверждение урока не сохранено");sent++;
            }
            return sent>0?"Прохождение уроков отправлено: "+sent:"Очередь уроков отправлена";
        }
    }
}
