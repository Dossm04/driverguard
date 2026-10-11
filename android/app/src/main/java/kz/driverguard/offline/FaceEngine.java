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
    final DmsRules rules = new DmsRules();
    FaceEngine(Context context) {
        model=FaceLandmarker.createFromOptions(context, FaceLandmarker.FaceLandmarkerOptions.builder()
            .setBaseOptions(BaseOptions.builder().setModelAssetPath("face_landmarker.task").build())
            .setRunningMode(RunningMode.VIDEO).setNumFaces(1).setOutputFaceBlendshapes(true)
            .setMinFaceDetectionConfidence(0.6f).setMinFacePresenceConfidence(0.6f)
            .setMinTrackingConfidence(0.6f).build());
    }
    DmsRules.Result analyze(Bitmap bitmap,long now) {
        long timestamp=Math.max(now,lastTime+1); lastTime=timestamp;
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
            float pitch=Float.NaN;
            if(!r.faceLandmarks().isEmpty() && r.faceLandmarks().get(0).size()>291) {
                var points=r.faceLandmarks().get(0);
                var chin=points.get(152);var forehead=points.get(10);
                float vertical=(chin.y()-forehead.y())*bitmap.getHeight();
                float depth=(chin.z()-forehead.z())*bitmap.getWidth();
                if(vertical>bitmap.getHeight()*0.05f)pitch=(float)Math.atan2(depth,vertical);
                var top=points.get(13);var bottom=points.get(14);
                var mouthLeft=points.get(61);var mouthRight=points.get(291);
                double width=Math.hypot((mouthLeft.x()-mouthRight.x())*bitmap.getWidth(),
                    (mouthLeft.y()-mouthRight.y())*bitmap.getHeight());
                double gap=Math.hypot((top.x()-bottom.x())*bitmap.getWidth(),
                    (top.y()-bottom.y())*bitmap.getHeight());
                // Reject missing/collapsed/impossible geometry, not a second yawn classifier.
                if(width<2 || !Double.isFinite(gap) || gap/width>3)jaw=Float.NaN;
            }
            return rules.update(now,!r.faceLandmarks().isEmpty(),left,right,jaw,pitch);
        } finally { image.close(); }
    }
    @Override public void close() { model.close(); }
}
