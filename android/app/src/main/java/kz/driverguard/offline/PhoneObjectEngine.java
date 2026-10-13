package kz.driverguard.offline;

import android.content.Context;
import android.graphics.Bitmap;
import com.google.mediapipe.framework.image.BitmapImageBuilder;
import com.google.mediapipe.framework.image.MPImage;
import com.google.mediapipe.tasks.core.BaseOptions;
import com.google.mediapipe.tasks.vision.core.RunningMode;
import com.google.mediapipe.tasks.vision.objectdetector.ObjectDetector;
import java.util.Collections;
import java.util.Locale;

/** Generic COCO object presence, never a conclusion about phone use or the driver. */
final class PhoneObjectEngine implements AutoCloseable {
    private final ObjectDetector model;
    PhoneObjectEngine(Context context){
        model=ObjectDetector.createFromOptions(context,ObjectDetector.ObjectDetectorOptions.builder()
            .setBaseOptions(BaseOptions.builder().setModelAssetPath("phone_detector.tflite").build())
            .setRunningMode(RunningMode.IMAGE).setMaxResults(3).setScoreThreshold(.45f)
            .setCategoryAllowlist(Collections.singletonList("cell phone")).build());
    }
    String analyze(Bitmap bitmap){
        MPImage image=new BitmapImageBuilder(bitmap).build();
        try{
            float best=0;
            for(var detection:model.detect(image).detections())for(var category:detection.categories())
                if("cell phone".equals(category.categoryName())&&Float.isFinite(category.score()))
                    best=Math.max(best,category.score());
            return best>0?String.format(Locale.ROOT,"Телефон: предмет в кадре · оценка модели %.2f",best)
                :"Телефон: не обнаружен (это не доказывает отсутствие)";
        }finally{image.close();}
    }
    @Override public void close(){model.close();}
}
