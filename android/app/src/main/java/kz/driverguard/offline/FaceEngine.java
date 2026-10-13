package kz.driverguard.offline;

import android.content.Context;
import android.graphics.Bitmap;
import com.google.mediapipe.framework.image.BitmapImageBuilder;
import com.google.mediapipe.framework.image.MPImage;
import com.google.mediapipe.tasks.core.BaseOptions;
import com.google.mediapipe.tasks.vision.core.RunningMode;
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarker;
import com.google.mediapipe.tasks.components.containers.Category;

final class FaceEngine implements AutoCloseable {
    private final FaceLandmarker model;
    private long lastTime=-1;
    String quality="Проверяем изображение";
    final DmsRules rules = new DmsRules();
    FaceEngine(Context context) {
        model=FaceLandmarker.createFromOptions(context, FaceLandmarker.FaceLandmarkerOptions.builder()
            .setBaseOptions(BaseOptions.builder().setModelAssetPath("face_landmarker.task").build())
            .setRunningMode(RunningMode.VIDEO).setNumFaces(1).setOutputFaceBlendshapes(true)
            .setMinFaceDetectionConfidence(0.6f).setMinFacePresenceConfidence(0.6f)
            .setMinTrackingConfidence(0.6f).build());
    }
    DmsRules.Result analyze(Bitmap bitmap,long now) {
        return analyze(bitmap, now, Double.NaN, 90);
    }
    DmsRules.Result analyze(Bitmap bitmap,long now,double verifiedSpeedKmh,int speedLimitKmh) {
        long timestamp=Math.max(now,lastTime+1); lastTime=timestamp;
        Bitmap sample=Bitmap.createScaledBitmap(bitmap,32,24,true);int[] pixels=new int[32*24];sample.getPixels(pixels,0,32,0,0,32,24);if(sample!=bitmap)sample.recycle();
        FrameQuality.Reading q=FrameQuality.inspect(pixels);quality=q.message();
        MPImage image=new BitmapImageBuilder(bitmap).build();
        try {
            var r=model.detectForVideo(image,timestamp);
            float left=Float.NaN,right=Float.NaN,jaw=Float.NaN;
            if(r.faceBlendshapes().isPresent() && !r.faceBlendshapes().get().isEmpty()) {
                for(Category c:r.faceBlendshapes().get().get(0)) {
                    if(c.categoryName().equals("eyeBlinkLeft")) left=c.score();
                    if(c.categoryName().equals("eyeBlinkRight")) right=c.score();
                    if(c.categoryName().equals("jawOpen")) jaw=c.score();
                }
            }
            FaceGeometry.Measurements geometry = null;
            if(!r.faceLandmarks().isEmpty() && r.faceLandmarks().get(0).size()>454) {
                var points=r.faceLandmarks().get(0);
                float[] x=new float[points.size()],y=new float[points.size()],z=new float[points.size()];
                for(int i=0;i<points.size();i++) {
                    var p=points.get(i); x[i]=p.x(); y[i]=p.y(); z[i]=p.z();
                }
                geometry=FaceGeometry.measure(x,y,z,bitmap.getWidth(),bitmap.getHeight());
                float minX=1,maxX=0;for(float value:x){minX=Math.min(minX,value);maxX=Math.max(maxX,value);}
                if(maxX-minX<.12f){quality="Лицо слишком далеко · приблизьте телефон";left=right=Float.NaN;}
                if(q.tooDark())left=right=Float.NaN;
                // Geometry checks validate the measurement; mouth opening is not proof of a yawn.
                if(!geometry.mouthValid())jaw=Float.NaN;
            }
            return rules.update(now,!r.faceLandmarks().isEmpty(),left,right,jaw,
                geometry==null?Float.NaN:geometry.headDepth(), geometry==null?Float.NaN:geometry.ear(),
                geometry==null?Float.NaN:geometry.yaw(),verifiedSpeedKmh,speedLimitKmh);
        } finally { image.close(); }
    }
    @Override public void close() { model.close(); }
}
