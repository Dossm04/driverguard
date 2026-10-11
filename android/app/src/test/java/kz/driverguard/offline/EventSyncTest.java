package kz.driverguard.offline;
import org.junit.Test;
import org.json.*;
import java.io.IOException;
import java.util.*;
import static org.junit.Assert.*;

public class EventSyncTest {
    static final String BASE="https://demo.example/api/v1";
    static final EventOutbox.Pending EVENT=new EventOutbox.Pending("c47f893a-0ca2-4d4a-8945-d3e1555e4321","2026-10-07T10:00:00Z","phone",1750,.9f);
    static class Box implements EventOutbox {
        List<Pending> events=new ArrayList<>(List.of(EVENT));String owner=SyncPolicy.owner(BASE,1);int acks;
        public List<Pending> pending(String value){return value.equals(owner)?new ArrayList<>(events):List.of();}
        public void acknowledge(String value,List<Pending> batch){assertEquals(owner,value);events.removeAll(batch);acks++;}
        public long pendingCount(String value){return pending(value).size();}
    }
    static class Wire implements EventSync.Transport {
        int driver=1;String response="{\"accepted\":1,\"duplicates\":0}";Exception failure;List<String> sent=new ArrayList<>();
        public String post(String address,String token,String body)throws Exception{
            if(address.endsWith("/auth/driver-login"))return "{\"access_token\":\"test-token\",\"driver_id\":"+driver+"}";
            assertEquals(BASE+"/drivers/me/camera-events",address);assertEquals("test-token",token);sent.add(body);
            if(failure!=null)throw failure;return response;
        }
    }
    @Test public void originalTimestampAndIdentityAreSentAndAcknowledged()throws Exception{
        Wire w=new Wire();Box b=new Box();EventSync sync=new EventSync(w);sync.login(BASE,"+70000000000","0000");sync.flush(b);
        JSONObject event=new JSONArray(w.sent.get(0)).getJSONObject(0);
        assertEquals(EVENT.uuid(),event.getString("uuid"));assertEquals(EVENT.at(),event.getString("ts"));assertEquals("face_rules",event.getString("detector"));assertFalse(event.getBoolean("gps_valid"));assertEquals(1,b.acks);assertTrue(b.events.isEmpty());
    }
    @Test public void lostResponseRetriesSameUuidAndDuplicateAckIsAccepted()throws Exception{
        Wire w=new Wire();Box b=new Box();EventSync sync=new EventSync(w);sync.login(BASE,"+70000000000","0000");
        w.failure=new IOException("offline");assertThrows(IOException.class,()->sync.flush(b));assertEquals(0,b.acks);
        w.failure=null;w.response="{\"accepted\":0,\"duplicates\":1}";sync.flush(b);
        assertEquals(w.sent.get(0),w.sent.get(1));assertEquals(1,b.acks);
    }
    @Test public void malformedOrPartialAckDoesNotDelete()throws Exception{
        for(String response:List.of("{}","<html>error</html>","{\"accepted\":0,\"duplicates\":0}")){
            Wire w=new Wire();w.response=response;Box b=new Box();EventSync sync=new EventSync(w);sync.login(BASE,"+70000000000","0000");assertThrows(Exception.class,()->sync.flush(b));assertEquals(0,b.acks);
        }
    }
    @Test public void differentDriverCannotUploadPreviousQueue()throws Exception{
        Wire w=new Wire();w.driver=2;Box b=new Box();EventSync sync=new EventSync(w);sync.login(BASE,"+70000000001","0000");sync.flush(b);assertTrue(w.sent.isEmpty());assertEquals(1,b.events.size());
    }
    @Test public void expiredLoginKeepsDataAndStopsAutomaticRetries()throws Exception{
        Wire w=new Wire();Box b=new Box();EventSync sync=new EventSync(w);sync.login(BASE,"+70000000000","0000");w.failure=new SecurityException("expired");assertThrows(SecurityException.class,()->sync.flush(b));sync.flush(b);assertEquals(1,w.sent.size());assertEquals(0,b.acks);
    }
    @Test public void withoutLoginThereAreNoNetworkRequests()throws Exception{
        Wire w=new Wire();Box b=new Box();new EventSync(w).flush(b);assertTrue(w.sent.isEmpty());assertEquals(0,b.acks);
    }
}
