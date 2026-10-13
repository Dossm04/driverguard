package kz.driverguard.offline;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.MediaPlayer;

/** Bundled chime and short siren, controlled by the normal media volume. */
final class AlertSound implements AutoCloseable {
    private final Context context;
    private MediaPlayer player;
    private boolean alarm,testing;
    AlertSound(Context context){this.context=context;}
    boolean playing(){try{return player!=null&&player.isPlaying();}catch(Exception ignored){return false;}}
    void synchronize(boolean active,boolean monitoring,boolean muted){
        if(muted||(!monitoring&&!testing)||(alarm&&!active))stop();
    }
    boolean play(GradedSoundPolicy.Level level,boolean isAlarm,boolean isTest){
        if(level==GradedSoundPolicy.Level.NONE)return false;
        stop();
        try{
            player=MediaPlayer.create(context,level==GradedSoundPolicy.Level.URGENT?R.raw.sound_siren:R.raw.sound_soft,
                new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build(),0);
            if(player==null)return false;
            alarm=isAlarm;testing=isTest;
            float volume=level==GradedSoundPolicy.Level.URGENT?0.95f:0.45f;
            player.setVolume(volume,volume);
            player.setOnCompletionListener(p->stop());player.setOnErrorListener((p,w,e)->{stop();return true;});
            player.start();return true;
        }catch(Exception failure){stop();return false;}
    }
    void stop(){if(player!=null){try{player.release();}catch(Exception ignored){}player=null;}alarm=testing=false;}
    public void close(){stop();}
}
