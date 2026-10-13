package kz.driverguard.offline;

import org.junit.Test;
import static org.junit.Assert.*;

public class DriverCareTest {
    @Test public void clockChangesDoNotInflateRestWithinSameBoot(){assertEquals(120000,RestPolicy.duration(1000,500,2,9999999,120500,2));}
    @Test public void rebootAndBackwardClockAreBounded(){assertEquals(0,RestPolicy.duration(5000,0,1,4000,10,2));assertEquals(7L*86400_000,RestPolicy.duration(0,0,1,Long.MAX_VALUE,10,2));}
    @Test public void timerHasHoursMinutesSeconds(){assertEquals("01:01:01",RestPolicy.timer(3661000));assertEquals("00:00:00",RestPolicy.timer(-5));}
    @Test public void restIsExplicitNeutralActionAndNotFaceInference()throws Exception{
        for(String kind:new String[]{"rest_started","rest_ended"}){assertTrue(EventPayload.uploadable(kind));var p=new EventOutbox.Pending("id","2026-10-14T10:00:00Z","manual",0,0,kind,120,null);var json=EventPayload.of(p);assertEquals("driver_action",json.getString("detector"));assertEquals("info",json.getString("severity"));assertEquals(120,json.getDouble("value"),0);}
    }
    @Test public void exposureDoesNotTurnMissingImageIntoGoodQuality(){assertTrue(FrameQuality.inspect(new int[0]).tooDark());assertTrue(FrameQuality.inspect(new int[]{0xff000000}).tooDark());assertFalse(FrameQuality.inspect(new int[]{0xff808080}).tooDark());assertEquals(1,FrameQuality.inspect(new int[]{0xffffffff}).brightFraction(),0);}
    @Test public void clipWindowsOverlapAndNeedPreAndPostHistory(){assertTrue(ClipWindow.intersects(0,30000,25000));assertTrue(ClipWindow.intersects(30000,60000,29000));assertFalse(ClipWindow.intersects(0,30000,50000));assertFalse(ClipWindow.complete(20000,31000,25000));assertTrue(ClipWindow.complete(15000,30000,25000));}
}
