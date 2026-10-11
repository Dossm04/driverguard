package kz.driverguard.offline;

import org.junit.Test;
import static org.junit.Assert.*;

public class DrivingSampleTest {
    private DrivingSample sample(double lat, double lon, double speed, long elapsed, float accuracy, float speedAccuracy, boolean mock) {
        return new DrivingSample(lat,lon,speed,elapsed,accuracy,speedAccuracy,mock);
    }
    @Test public void acceptsFreshMeasuredPositionAndSpeedAtQualityBoundaries() {
        assertTrue(sample(51.1,71.4,45,10000,30,3,false).validAt(15000));
        assertTrue(sample(-90,-180,0,10000,0,0,false).validAt(10000));
        assertTrue(sample(90,180,300,10000,1,1,false).validAt(10001));
    }
    @Test public void rejectsStaleFutureAndUnavailableSamples() {
        assertFalse(sample(51,71,40,10000,1,1,false).validAt(15001));
        assertFalse(sample(51,71,40,10001,1,1,false).validAt(10000));
        assertFalse(sample(51,71,40,-1,1,1,false).validAt(0));
        assertFalse(DrivingSample.unavailable().validAt(10000));
        assertFalse(sample(51,71,40,0,1,1,false).validAt(-1));
    }
    @Test public void rejectsUncertainMeasurements() {
        assertFalse(sample(51,71,40,10000,30.01f,1,false).validAt(10000));
        assertFalse(sample(51,71,40,10000,1,3.01f,false).validAt(10000));
        assertFalse(sample(51,71,40,10000,-1,1,false).validAt(10000));
        assertFalse(sample(51,71,40,10000,1,-1,false).validAt(10000));
        assertFalse(sample(51,71,40,10000,Float.NaN,1,false).validAt(10000));
        assertFalse(sample(51,71,40,10000,1,Float.POSITIVE_INFINITY,false).validAt(10000));
    }
    @Test public void rejectsMockLocationsEvenWhenOtherwiseAccurate() {
        assertFalse(sample(51,71,40,10000,1,1,true).validAt(10000));
    }
    @Test public void rejectsInvalidCoordinatesAndSpeed() {
        assertFalse(sample(90.01,71,40,10000,1,1,false).validAt(10000));
        assertFalse(sample(51,-180.01,40,10000,1,1,false).validAt(10000));
        assertFalse(sample(Double.NaN,71,40,10000,1,1,false).validAt(10000));
        assertFalse(sample(51,Double.POSITIVE_INFINITY,40,10000,1,1,false).validAt(10000));
        assertFalse(sample(51,71,Double.NaN,10000,1,1,false).validAt(10000));
        assertFalse(sample(51,71,-0.1,10000,1,1,false).validAt(10000));
        assertFalse(sample(51,71,300.01,10000,1,1,false).validAt(10000));
    }
    @Test public void elapsedArithmeticDoesNotAcceptOverflowedTime() {
        assertFalse(sample(51,71,40,0,1,1,false).validAt(Long.MAX_VALUE));
        assertFalse(sample(51,71,40,Long.MAX_VALUE,1,1,false).validAt(0));
        assertFalse(sample(51,71,40,Long.MIN_VALUE,1,1,false).validAt(Long.MAX_VALUE));
    }
}
