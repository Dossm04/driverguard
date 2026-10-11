package kz.driverguard.offline;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.json.*;

/** Called on one network executor. Session persistence is delegated to SessionStore. */
final class EventSync {
    record Account(String base,String owner,String accessToken) {}
    private Account account;
    interface Transport {String post(String address,String token,String body)throws Exception;}
    private final Transport transport;
    EventSync(){this(EventSync::post);}
    EventSync(Transport transport){this.transport=transport;}
    void attach(Account value){account=value;}
    private static String post(String address,String token,String body) throws Exception {
        HttpURLConnection c=(HttpURLConnection)new URL(address).openConnection();
        try {
            c.setInstanceFollowRedirects(false);c.setConnectTimeout(5000);c.setReadTimeout(8000);c.setRequestMethod("POST");c.setDoOutput(true);
            c.setRequestProperty("Content-Type","application/json");c.setRequestProperty("Accept","application/json");
            if(token!=null)c.setRequestProperty("Authorization","Bearer "+token);
            try(OutputStream out=c.getOutputStream()){out.write(body.getBytes(StandardCharsets.UTF_8));}
            int code=c.getResponseCode();
            if(code==401||code==403)throw new SecurityException("Sign in again. Events remain on the phone.");
            if(code<200||code>=300)throw new IOException("Server returned "+code+". Events remain saved.");
            try(InputStream in=c.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
                byte[] bytes=new byte[4096];int n;
                while((n=in.read(bytes))!=-1){if(out.size()+n>262144)throw new IOException("Server reply is too large.");out.write(bytes,0,n);}
                return out.toString(StandardCharsets.UTF_8.name());
            }
        }finally{c.disconnect();}
    }
    Account login(String raw,String phone,String pin) throws Exception {
        account=null;String base=SyncPolicy.base(raw);
        JSONObject body=new JSONObject().put("phone",phone.trim()).put("pin",pin);
        JSONObject reply=new JSONObject(transport.post(base+"/auth/driver-login",null,body.toString()));
        String token=reply.getString("access_token");int id=reply.getInt("driver_id");
        if(token.isBlank())throw new IOException("Server did not provide access.");
        account=new Account(base,SyncPolicy.owner(base,id),token);return account;
    }
    String flush(EventOutbox store) throws Exception {
        if(account==null)return "Локальный режим · войдите, чтобы отправлять события";
        List<EventOutbox.Pending> batch=store.pending(account.owner());
        if(batch.isEmpty())return "Все события отправлены · видео хранится на телефоне";
        JSONArray data=new JSONArray();
        for(var p:batch)data.put(EventPayload.of(p));
        JSONObject reply;
        try {reply=new JSONObject(transport.post(account.base()+"/drivers/me/camera-events",account.accessToken(),data.toString()));}
        catch(SecurityException e){account=null;throw e;}
        if(!SyncPolicy.completeAck(batch.size(),reply.getInt("accepted"),reply.getInt("duplicates")))throw new IOException("Incomplete server confirmation. Events remain saved.");
        store.acknowledge(account.owner(),batch);
        return "Отправлено: "+batch.size()+" · в очереди: "+store.pendingCount(account.owner());
    }
    void logout(){account=null;}
}
