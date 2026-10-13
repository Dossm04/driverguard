package kz.driverguard.offline;

import android.content.Context;
import android.media.MediaPlayer;

/** All speech is bundled audio. Failure falls back to the existing tone alarm. */
final class AlertVoice implements AutoCloseable {
    private final Context context;private MediaPlayer player;private String key="";private long last=-1;
    AlertVoice(Context c){context=c;}
    boolean playing(){try{return player!=null&&player.isPlaying();}catch(Exception e){return false;}}
    boolean testPlaying(){return key.equals("test")&&playing();}
    boolean speak(String next,long now){
        if(next==null)return false;
        if(playing()){if(!next.equals("eyes")||key.equals("eyes"))return true;stop();}
        if(next.equals(key)&&last>=0&&now-last<8000)return false;
        int id=switch(next){case "eyes"->R.raw.alert_eyes;case "camera"->R.raw.alert_camera;case "yawn"->R.raw.alert_yawn;case "fatigue"->R.raw.alert_fatigue;case "attention"->R.raw.alert_attention;case "quality"->R.raw.alert_quality;default->R.raw.alert_test;};
        try{release();player=MediaPlayer.create(context,id);if(player==null)return false;key=next;last=now;player.setOnCompletionListener(p->release());player.setOnErrorListener((p,w,e)->{release();return true;});player.start();return true;}
        catch(Exception e){release();return false;}
    }
    void clearCritical(boolean critical){if(!critical&&key.equals("eyes")){stop();}}
    private void release(){if(player!=null){try{player.release();}catch(Exception ignored){}player=null;}}
    void stop(){release();key="";last=-1;}
    @Override public void close(){stop();}
}
