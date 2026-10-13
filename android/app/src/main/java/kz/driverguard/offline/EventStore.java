package kz.driverguard.offline;
import android.content.Context;
import android.content.ContentValues;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import android.database.Cursor;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.*;

final class EventStore extends SQLiteOpenHelper implements EventOutbox {
    // Local observations and acknowledged events expire; unsent owner-scoped events never do.
    static final String EXPIRED_EVENTS_SELECTION = "state IN ('sent','local') AND at<?";
    EventStore(Context c) {super(c,"events.db",null,5);setWriteAheadLoggingEnabled(true);}
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, uuid TEXT UNIQUE, owner TEXT, state TEXT NOT NULL DEFAULT 'local', closed_ms INTEGER NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT 0, value REAL NOT NULL DEFAULT 0, metadata TEXT)");
        extras(db);
    }
    @Override public void onUpgrade(SQLiteDatabase db,int oldVersion,int newVersion) {
        if(oldVersion<2){
            db.execSQL("ALTER TABLE events ADD COLUMN uuid TEXT");db.execSQL("ALTER TABLE events ADD COLUMN owner TEXT");
            db.execSQL("ALTER TABLE events ADD COLUMN state TEXT NOT NULL DEFAULT 'local'");
            db.execSQL("ALTER TABLE events ADD COLUMN closed_ms INTEGER NOT NULL DEFAULT 0");
            db.execSQL("ALTER TABLE events ADD COLUMN confidence REAL NOT NULL DEFAULT 0");db.execSQL("CREATE UNIQUE INDEX events_uuid ON events(uuid)");
        }
        if(oldVersion<3){db.execSQL("ALTER TABLE events ADD COLUMN value REAL NOT NULL DEFAULT 0");db.execSQL("UPDATE events SET value=closed_ms/1000.0 WHERE kind='eyes_closed'");}
        if(oldVersion<4)db.execSQL("ALTER TABLE events ADD COLUMN metadata TEXT");
        if(oldVersion<5)extras(db);
    }
    private static void extras(SQLiteDatabase db){
        db.execSQL("CREATE TABLE IF NOT EXISTS rests (owner_key TEXT PRIMARY KEY, started INTEGER NOT NULL, elapsed INTEGER NOT NULL, boot INTEGER NOT NULL)");
        db.execSQL("CREATE TABLE IF NOT EXISTS feedback (event_uuid TEXT PRIMARY KEY, owner TEXT NOT NULL, request_id TEXT NOT NULL, comment TEXT NOT NULL, at TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0)");
    }
    void add(String kind,String source,String owner,long at,long closedMs,float confidence) {
        add(kind,source,owner,at,closedMs,confidence,closedMs/1000.0);
    }
    void add(String kind,String source,String owner,long at,long closedMs,float confidence,double value) {
        add(kind,source,owner,at,closedMs,confidence,value,null);
    }
    String add(String kind,String source,String owner,long at,long closedMs,float confidence,double value,String metadata) {
        SQLiteDatabase db=getWritableDatabase();
        db.delete("events",EXPIRED_EVENTS_SELECTION+" AND uuid NOT IN (SELECT event_uuid FROM feedback WHERE sent=0)",new String[]{Instant.now().minusSeconds(30L*86400).toString()});
        db.delete("feedback","sent=1 AND event_uuid NOT IN (SELECT uuid FROM events)",null);
        try(Cursor c=db.rawQuery("SELECT COUNT(*) FROM events",null)){c.moveToFirst();if(c.getLong(0)>=50000)throw new IllegalStateException("Journal is full. Export the saved events.");}
        ContentValues v=new ContentValues();v.put("at",Instant.ofEpochMilli(at).toString());v.put("kind",kind);v.put("source",source);
        String id=UUID.randomUUID().toString();v.put("uuid",id);v.put("owner",owner);v.put("state",owner!=null&&EventPayload.uploadable(kind)?"pending":"local");
        v.put("closed_ms",closedMs);v.put("confidence",confidence);v.put("value",value);v.put("metadata",metadata);db.insertOrThrow("events",null,v);
        return id;
    }
    record Rest(long started,long elapsed,int boot) {}
    Rest rest(String owner){try(Cursor c=getReadableDatabase().rawQuery("SELECT started,elapsed,boot FROM rests WHERE owner_key=?",new String[]{owner==null?"local":owner})){return c.moveToFirst()?new Rest(c.getLong(0),c.getLong(1),c.getInt(2)):null;}}
    void beginRest(String owner,long wall,long elapsed,int boot){
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{
            if(rest(owner)==null){ContentValues v=new ContentValues();v.put("owner_key",owner==null?"local":owner);v.put("started",wall);v.put("elapsed",elapsed);v.put("boot",boot);db.insertOrThrow("rests",null,v);add("rest_started","manual",owner,wall,0,0,0,null);}
            db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    void endRest(String owner,long wall,long elapsed,int boot){
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();try{
            Rest r=rest(owner);if(r!=null){long duration=RestPolicy.duration(r.started(),r.elapsed(),r.boot(),wall,elapsed,boot);add("rest_ended","manual",owner,wall,0,0,duration/1000.0,null);db.delete("rests","owner_key=?",new String[]{owner==null?"local":owner});}db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    record Entry(String uuid,String at,String kind,String state) {}
    List<Entry> entries(String owner){List<Entry> rows=new ArrayList<>();try(Cursor c=getReadableDatabase().rawQuery("SELECT uuid,at,kind,state FROM events WHERE "+(owner==null?"owner IS NULL":"owner=?")+" ORDER BY id DESC LIMIT 30",owner==null?null:new String[]{owner})){while(c.moveToNext())rows.add(new Entry(c.getString(0),c.getString(1),c.getString(2),c.getString(3)));}return rows;}
    void feedback(String owner,String uuid,String comment){
        if(owner==null||comment.trim().isEmpty()||comment.length()>500)throw new IllegalArgumentException("Введите комментарий до 500 символов");
        try(Cursor c=getReadableDatabase().rawQuery("SELECT 1 FROM events WHERE owner=? AND uuid=? AND state IN ('pending','sent')",new String[]{owner,uuid})){if(!c.moveToFirst())throw new IllegalArgumentException("Эта запись недоступна для отправки");}
        ContentValues v=new ContentValues();v.put("event_uuid",uuid);v.put("owner",owner);v.put("request_id",UUID.randomUUID().toString());v.put("comment",comment.trim());v.put("at",Instant.now().toString());
        if(getWritableDatabase().insertWithOnConflict("feedback",null,v,SQLiteDatabase.CONFLICT_IGNORE)==-1)throw new IllegalArgumentException("Комментарий к этому событию уже сохранён");
    }
    long feedbackPending(String owner){if(owner==null)return 0;try(Cursor c=getReadableDatabase().rawQuery("SELECT COUNT(*) FROM feedback WHERE owner=? AND sent=0",new String[]{owner})){c.moveToFirst();return c.getLong(0);}}
    void flushFeedback(DriverApi api,String owner)throws Exception{
        try(Cursor c=getReadableDatabase().rawQuery("SELECT f.event_uuid,f.request_id,f.comment,f.at FROM feedback f JOIN events e ON e.uuid=f.event_uuid AND e.owner=f.owner WHERE f.owner=? AND f.sent=0 AND e.state='sent' LIMIT 20",new String[]{owner})){
            while(c.moveToNext()){
                var s=api.session();if(s==null||!s.owner().equals(owner))throw new SecurityException("Аккаунт изменился");
                var body=new org.json.JSONObject().put("request_id",c.getString(1)).put("comment",c.getString(2)).put("ts",c.getString(3));
                var ack=new org.json.JSONObject(api.request("PUT","/drivers/me/camera-events/"+c.getString(0)+"/feedback",body.toString()));
                if(!ack.optBoolean("ok")||!c.getString(1).equals(ack.optString("request_id")))throw new java.io.IOException("Нет подтверждения комментария");
                ContentValues v=new ContentValues();v.put("sent",1);getWritableDatabase().update("feedback",v,"event_uuid=? AND owner=? AND request_id=?",new String[]{c.getString(0),owner,c.getString(1)});
            }
        }
    }
    public List<Pending> pending(String owner) {
        List<Pending> list=new ArrayList<>();if(owner==null)return list;
        try(Cursor c=getReadableDatabase().rawQuery("SELECT uuid,at,source,closed_ms,confidence,kind,value,metadata FROM events WHERE owner=? AND state='pending' ORDER BY id LIMIT 20",new String[]{owner})){
            while(c.moveToNext())list.add(new Pending(c.getString(0),c.getString(1),c.getString(2),c.getLong(3),c.getFloat(4),c.getString(5),c.getDouble(6),c.isNull(7)?null:c.getString(7)));
        }return list;
    }
    public void acknowledge(String owner,List<Pending> batch) {
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();
        try {ContentValues v=new ContentValues();v.put("state","sent");
            for(Pending p:batch)db.update("events",v,"uuid=? AND owner=? AND state='pending'",new String[]{p.uuid(),owner});db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    public long pendingCount(String owner) {
        if(owner==null)return 0;
        try(Cursor c=getReadableDatabase().rawQuery("SELECT COUNT(*) FROM events WHERE owner=? AND state='pending'",new String[]{owner})){c.moveToFirst();return c.getLong(0);}
    }
    String csv() {return csv(null);}
    String csv(String owner) {
        StringBuilder b=new StringBuilder("time_utc,event,source,uuid,delivery,closed_ms,value,metadata_json\n");
        try(Cursor c=getReadableDatabase().rawQuery("SELECT at,kind,source,uuid,state,closed_ms,value,metadata FROM events WHERE "+(owner==null?"owner IS NULL":"owner=?")+" ORDER BY id",owner==null?null:new String[]{owner})) {
            while(c.moveToNext()){for(int i=0;i<8;i++){if(i>0)b.append(',');b.append(EventText.csv(c.isNull(i)?"":c.getString(i)));}b.append('\n');}
        } return b.toString();
    }
    String recent() {return recent(null);}
    String recent(String owner) {
        StringBuilder b=new StringBuilder();
        DateTimeFormatter display=DateTimeFormatter.ofPattern("dd MMM HH:mm:ss",Locale.forLanguageTag("ru")).withZone(ZoneId.systemDefault());
        try(Cursor c=getReadableDatabase().rawQuery("SELECT at,kind,state,closed_ms,value FROM events WHERE "+(owner==null?"owner IS NULL":"owner=?")+" ORDER BY id DESC LIMIT 30",owner==null?null:new String[]{owner})) {
            while(c.moveToNext()) {
                String at=c.getString(0);try{at=display.format(Instant.parse(at));}catch(Exception ignored){}
                String kind=c.getString(1),label=switch(kind){case "eyes_closed"->"Длительное закрытие глаз";case "face_missing"->"Лицо или глаза не видны";case "yawn"->"Открывание рта / возможный зевок";case "fatigue_perclos"->"Частое закрытие глаз · PERCLOS "+Math.round(c.getDouble(4))+"%";case "fatigue_yawning"->"Повторные зевки · "+(int)c.getDouble(4);case "head_nod"->"Длительный наклон головы";default->EventText.label(kind);};
                b.append(at).append("\n").append(label);
                if(kind.equals("eyes_closed"))b.append(String.format(Locale.ENGLISH," · %.1f s",c.getLong(3)/1000.0));
                b.append(" · ").append(switch(c.getString(2)){case "sent"->"отправлено";case "pending"->"ждёт сети";default->"на телефоне";}).append("\n\n");
            }
        } return b.length()==0?"Событий пока нет. Они появятся после наблюдения камерой.":b.toString();
    }
}
