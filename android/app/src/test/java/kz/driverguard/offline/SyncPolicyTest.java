package kz.driverguard.offline;
import org.junit.Test;
import static org.junit.Assert.*;
public class SyncPolicyTest {
    @Test public void originIsStableAndIncludesApiPath(){assertEquals("https://demo.example/api/v1",SyncPolicy.base("https://demo.example/"));assertEquals("http://192.168.1.8:8000/api/v1",SyncPolicy.base("http://192.168.1.8:8000/api/v1/"));}
    @Test public void refusesCleartextPublicAndCredentials(){for(String s:new String[]{"http://example.com","https://user:pass@example.com","https://example.com?token=x","https://example.com/other","http://172.32.0.1","http://192.168.999.1"})assertThrows(IllegalArgumentException.class,()->SyncPolicy.base(s));}
    @Test public void onlyFullAckAllowsRemoval(){assertTrue(SyncPolicy.completeAck(20,12,8));assertFalse(SyncPolicy.completeAck(20,12,7));assertFalse(SyncPolicy.completeAck(1,2,-1));assertFalse(SyncPolicy.completeAck(0,0,0));}
    @Test public void accountQueueIncludesServerAndDriver(){assertNotEquals(SyncPolicy.owner("https://a/api/v1",1),SyncPolicy.owner("https://b/api/v1",1));assertNotEquals(SyncPolicy.owner("https://a/api/v1",1),SyncPolicy.owner("https://a/api/v1",2));}
}
