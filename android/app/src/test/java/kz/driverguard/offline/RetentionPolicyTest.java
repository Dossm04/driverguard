package kz.driverguard.offline;
import org.junit.Test;
import java.util.List;
import static org.junit.Assert.*;
public class RetentionPolicyTest {
    @Test public void expiresOnlyCompletedClips() {
        var clips=List.of(new RetentionPolicy.Clip("old",20,1,false),new RetentionPolicy.Clip("active",20,1,true),new RetentionPolicy.Clip("fresh",20,95,false));
        assertEquals(List.of("old"),RetentionPolicy.removable(clips,100,50,1000));
    }
    @Test public void quotaDeletesOldestFirstAndKeepsCurrent() {
        var clips=List.of(new RetentionPolicy.Clip("new",40,30,false),new RetentionPolicy.Clip("old",40,10,false),new RetentionPolicy.Clip("active",40,1,true));
        assertEquals(List.of("old"),RetentionPolicy.removable(clips,100,1000,80));
    }
    @Test public void clockRollbackDoesNotExpireNewerFiles() {
        assertTrue(RetentionPolicy.removable(List.of(new RetentionPolicy.Clip("future",10,1000,false)),100,50,100).isEmpty());
    }
    @Test public void noDeletionAtQuotaBoundary() {
        assertTrue(RetentionPolicy.removable(List.of(new RetentionPolicy.Clip("ok",100,90,false)),100,100,100).isEmpty());
    }
}
