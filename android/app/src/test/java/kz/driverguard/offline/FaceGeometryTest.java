package kz.driverguard.offline;

import org.junit.Test;
import static org.junit.Assert.*;

public class FaceGeometryTest {
    private float[][] points(int width, int height) {
        float[][] p = new float[3][478];
        int[] indices = {33,160,158,133,153,144,362,385,387,263,373,380,234,454,1,152,10,61,291,13,14};
        float[] px = {100,110,130,140,130,110,200,210,230,240,230,210,50,290,170,170,170,145,195,170,170};
        float[] py = {100,94,94,100,106,106,100,94,94,100,106,106,125,125,125,200,50,160,160,155,165};
        for (int i = 0; i < indices.length; i++) {
            p[0][indices[i]] = px[i] / width; p[1][indices[i]] = py[i] / height;
        }
        p[2][152] = .2f;
        return p;
    }
    @Test public void pixelCorrectEarIsIndependentOfImageAspectRatio() {
        for (int height : new int[]{300, 800}) {
            float[][] p = points(400, height);
            FaceGeometry.Measurements result = FaceGeometry.measure(p[0],p[1],p[2],400,height);
            assertTrue(result.valid()); assertEquals(.3f,result.ear(),.0001f);
            assertEquals(0,result.yaw(),.0001f); assertEquals(.2f,result.headDepth(),.0001f);
            assertTrue(result.mouthValid());
        }
    }
    @Test public void yawIsNormalizedByPixelCheekDistance() {
        float[][] p = points(400, 300); p[0][1] = 230f / 400;
        assertEquals(.5f, FaceGeometry.measure(p[0],p[1],p[2],400,300).yaw(), .0001f);
    }
    @Test public void invalidAndDegenerateLandmarksAreNotEyeClosureEvidence() {
        float[][] p = points(400, 300); p[1][385] = Float.NaN;
        assertFalse(FaceGeometry.measure(p[0],p[1],p[2],400,300).valid());
        p = points(400, 300); p[0][133] = p[0][33];
        assertFalse(FaceGeometry.measure(p[0],p[1],p[2],400,300).valid());
        assertFalse(FaceGeometry.measure(null,null,null,400,300).valid());
        assertFalse(FaceGeometry.measure(p[0],p[1],p[2],0,300).valid());
    }
    @Test public void closedEyeGeometryWithValidWidthIsAccepted() {
        float[][] p = points(400, 300);
        for (int index : new int[]{160,158,153,144,385,387,373,380}) p[1][index] = 100f / 300;
        FaceGeometry.Measurements result = FaceGeometry.measure(p[0],p[1],p[2],400,300);
        assertTrue(result.valid()); assertEquals(0,result.ear(),.0001f);
    }
    @Test public void eyeOutsideImageIsUnavailableInsteadOfClosed() {
        float[][] p=points(400,300);p[0][33]=-.05f;
        assertFalse(FaceGeometry.measure(p[0],p[1],p[2],400,300).valid());
        p=points(400,300);p[1][385]=1.02f;
        assertFalse(FaceGeometry.measure(p[0],p[1],p[2],400,300).valid());
    }
}
