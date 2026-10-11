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
    EventStore(Context c) {super(c,"events.db",null,3);setWriteAheadLoggingEnabled(true);}
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, uuid TEXT UNIQUE, owner TEXT, state TEXT NOT NULL DEFAULT 'local', closed_ms INTEGER NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT 0, value REAL NOT NULL DEFAULT 0)");
    }
    @Override public void onUpgrade(SQLiteDatabase db,int oldVersion,int newVersion) {
        if(oldVersion<2){
            db.execSQL("ALTER TABLE events ADD COLUMN uuid TEXT");db.execSQL("ALTER TABLE events ADD COLUMN owner TEXT");
            db.execSQL("ALTER TABLE events ADD COLUMN state TEXT NOT NULL DEFAULT 'local'");
            db.execSQL("ALTER TABLE events ADD COLUMN closed_ms INTEGER NOT NULL DEFAULT 0");
            db.execSQL("ALTER TABLE events ADD COLUMN confidence REAL NOT NULL DEFAULT 0");db.execSQL("CREATE UNIQUE INDEX events_uuid ON events(uuid)");
        }
        if(oldVersion<3){db.execSQL("ALTER TABLE events ADD COLUMN value REAL NOT NULL DEFAULT 0");db.execSQL("UPDATE events SET value=closed_ms/1000.0 WHERE kind='eyes_closed'");}
    }
    void add(String kind,String source,String owner,long at,long closedMs,float confidence) {
        add(kind,source,owner,at,closedMs,confidence,closedMs/1000.0);
    }
    void add(String kind,String source,String owner,long at,long closedMs,float confidence,double value) {
        SQLiteDatabase db=getWritableDatabase();
        db.delete("events","state='sent' AND at<?",new String[]{Instant.now().minusSeconds(30L*86400).toString()});
        try(Cursor c=db.rawQuery("SELECT COUNT(*) FROM events",null)){c.moveToFirst();if(c.getLong(0)>=50000)throw new IllegalStateException("Journal is full. Export the saved events.");}
        ContentValues v=new ContentValues();v.put("at",Instant.ofEpochMilli(at).toString());v.put("kind",kind);v.put("source",source);
        v.put("uuid",UUID.randomUUID().toString());v.put("owner",owner);v.put("state",owner!=null&&EventPayload.uploadable(kind)?"pending":"local");
        v.put("closed_ms",closedMs);v.put("confidence",confidence);v.put("value",value);db.insertOrThrow("events",null,v);
    }
    public List<Pending> pending(String owner) {
        List<Pending> list=new ArrayList<>();if(owner==null)return list;
        try(Cursor c=getReadableDatabase().rawQuery("SELECT uuid,at,source,closed_ms,confidence,kind,value FROM events WHERE owner=? AND state='pending' ORDER BY id LIMIT 20",new String[]{owner})){
            while(c.moveToNext())list.add(new Pending(c.getString(0),c.getString(1),c.getString(2),c.getLong(3),c.getFloat(4),c.getString(5),c.getDouble(6)));
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
        StringBuilder b=new StringBuilder("time_utc,event,source,uuid,delivery,closed_ms\n");
        try(Cursor c=getReadableDatabase().rawQuery("SELECT at,kind,source,uuid,state,closed_ms FROM events WHERE "+(owner==null?"owner IS NULL":"owner=?")+" ORDER BY id",owner==null?null:new String[]{owner})) {
            while(c.moveToNext()){for(int i=0;i<6;i++){if(i>0)b.append(',');b.append(c.isNull(i)?"":c.getString(i));}b.append('\n');}
        } return b.toString();
    }
    String recent() {return recent(null);}
    String recent(String owner) {
        StringBuilder b=new StringBuilder();
        DateTimeFormatter display=DateTimeFormatter.ofPattern("dd MMM HH:mm:ss",Locale.forLanguageTag("ru")).withZone(ZoneId.systemDefault());
        try(Cursor c=getReadableDatabase().rawQuery("SELECT at,kind,state,closed_ms,value FROM events WHERE "+(owner==null?"owner IS NULL":"owner=?")+" ORDER BY id DESC LIMIT 30",owner==null?null:new String[]{owner})) {
            while(c.moveToNext()) {
                String at=c.getString(0);try{at=display.format(Instant.parse(at));}catch(Exception ignored){}
                String kind=c.getString(1),label=switch(kind){case "eyes_closed"->"Длительное закрытие глаз";case "face_missing"->"Лицо вне кадра";case "yawn"->"Открывание рта / возможный зевок";case "fatigue_perclos"->"Частое закрытие глаз · PERCLOS "+Math.round(c.getDouble(4))+"%";case "fatigue_yawning"->"Повторные зевки · "+(int)c.getDouble(4);case "head_nod"->"Длительный наклон головы";default->kind;};
                b.append(at).append("\n").append(label);
                if(kind.equals("eyes_closed"))b.append(String.format(Locale.ENGLISH," · %.1f s",c.getLong(3)/1000.0));
                b.append(" · ").append(switch(c.getString(2)){case "sent"->"отправлено";case "pending"->"ждёт сети";default->"на телефоне";}).append("\n\n");
            }
        } return b.length()==0?"Событий пока нет. Они появятся после наблюдения камерой.":b.toString();
    }
}
