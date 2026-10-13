package kz.driverguard.offline;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import ai.onnxruntime.*;
import java.nio.FloatBuffer;
import java.util.Collections;
import java.util.Locale;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;

/** External research weights. Scores are observations, not verified driving violations. */
final class CandidateEngine implements AutoCloseable {
    private final OrtEnvironment env=OrtEnvironment.getEnvironment();
    private final OrtSession belt,smoking;
    private final PhoneObjectEngine phone;
    CandidateEngine(Context context) throws Exception {
        try(OrtSession.SessionOptions options=new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(2);options.setInterOpNumThreads(1);
            try(var stream=context.getAssets().open("seatbelt_classifier.onnx")) {
                belt=env.createSession(readAll(stream),options);
            }
            OrtSession temporary;
            try(var stream=context.getAssets().open("smoking_yolov8.onnx")) {
                temporary=env.createSession(readAll(stream),options);
            } catch(Exception e) {belt.close();throw e;}
            smoking=temporary;
            try{phone=new PhoneObjectEngine(context);}catch(Exception e){belt.close();smoking.close();throw e;}
        }
    }
    private static byte[] readAll(InputStream input) throws java.io.IOException {
        ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] buffer=new byte[65536];int count;
        while((count=input.read(buffer))!=-1)output.write(buffer,0,count);
        return output.toByteArray();
    }
    private float[] tensor(Bitmap original,int side,boolean letterbox) {
        Bitmap square=Bitmap.createBitmap(side,side,Bitmap.Config.ARGB_8888);
        Canvas canvas=new Canvas(square);canvas.drawColor(Color.rgb(114,114,114));
        Rect dst=new Rect(0,0,side,side);
        if(letterbox) {
            float scale=Math.min((float)side/original.getWidth(),(float)side/original.getHeight());
            int w=Math.round(original.getWidth()*scale),h=Math.round(original.getHeight()*scale);
            dst=new Rect((side-w)/2,(side-h)/2,(side-w)/2+w,(side-h)/2+h);
        }
        Paint paint=new Paint(Paint.FILTER_BITMAP_FLAG);canvas.drawBitmap(original,null,dst,paint);
        int[] pixels=new int[side*side];square.getPixels(pixels,0,side,0,0,side,side);square.recycle();
        int count=side*side;float[] values=new float[count*3];
        for(int i=0;i<count;i++){values[i]=((pixels[i]>>16)&255)/255f;values[count+i]=((pixels[i]>>8)&255)/255f;values[count*2+i]=(pixels[i]&255)/255f;}
        return values;
    }
    String analyze(Bitmap image) throws OrtException {
        float[] probabilities;
        try(OnnxTensor input=OnnxTensor.createTensor(env,FloatBuffer.wrap(tensor(image,224,false)),new long[]{1,3,224,224});
            OrtSession.Result output=belt.run(Collections.singletonMap("images",input))) {
            probabilities=((float[][])output.get(0).getValue())[0];
        }
        float cigarette=0;
        try(OnnxTensor input=OnnxTensor.createTensor(env,FloatBuffer.wrap(tensor(image,640,true)),new long[]{1,3,640,640});
            OrtSession.Result output=smoking.run(Collections.singletonMap("images",input))) {
            float[][] detections=((float[][][])output.get(0).getValue())[0];
            for(float score:detections[4]) if(Float.isFinite(score))cigarette=Math.max(cigarette,score);
        }
        float off=probabilities[0],on=probabilities[1];
        boolean valid=Float.isFinite(off)&&Float.isFinite(on)&&off>=0&&off<=1&&on>=0&&on<=1;
        String beltLabel=!valid||Math.max(off,on)<0.85f?"неопределённо":(off>on?"возможно, не пристёгнут":"возможно, пристёгнут");
        return phone.analyze(image)+String.format(Locale.ROOT,"\nРемень: %s\nСигарета: %s · оценка модели %.2f\nПроверка предметов: выводы не подтверждают нарушение и не отправляются как штрафные события.",
            beltLabel,cigarette>=0.6f?"возможный предмет в кадре":"не обнаружена",cigarette);
    }
    @Override public void close() {phone.close();try{belt.close();smoking.close();}catch(OrtException ignored){}}
}
