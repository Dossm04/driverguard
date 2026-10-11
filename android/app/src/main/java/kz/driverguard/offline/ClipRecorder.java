package kz.driverguard.offline;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import androidx.camera.video.*;
import androidx.core.content.ContextCompat;
import java.io.File;
import java.util.*;
import java.util.function.Consumer;

/** Main-thread CameraX recorder. Clips are best-effort, with explicit gaps at segment boundaries. */
final class ClipRecorder {
    static final long QUOTA=512L*1024*1024, RESERVE=40L*1024*1024;
    static final long AGE=48L*60*60*1000;
    private final Context context;
    private final File directory;
    private final Consumer<String> notice;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Set<String> active=new HashSet<>();
    private Recording recording;
    private int generation;
    ClipRecorder(Context context,Consumer<String> notice) {
        this.context=context; this.notice=notice;
        directory=new File(context.getFilesDir(),"recordings");
    }
    private boolean owned(File f) {
        try {return f.isFile() && f.getCanonicalFile().getParentFile().equals(directory.getCanonicalFile())
            && f.getName().matches("DG-[0-9]+-[a-f0-9-]+\\.mp4");} catch(Exception e){return false;}
    }
    List<File> clips() {
        File[] files=directory.listFiles(); List<File> result=new ArrayList<>();
        if(files!=null)for(File f:files)if(owned(f)&&!active.contains(f.getName()))result.add(f);
        result.sort(Comparator.comparingLong(File::lastModified).reversed());return result;
    }
    void prune() {
        File[] files=directory.listFiles(); if(files==null)return;
        List<RetentionPolicy.Clip> entries=new ArrayList<>();
        for(File f:files)if(owned(f))entries.add(new RetentionPolicy.Clip(f.getName(),f.length(),f.lastModified(),active.contains(f.getName())));
        for(String name:RetentionPolicy.removable(entries,System.currentTimeMillis(),AGE,QUOTA-RESERVE)) {
            File f=new File(directory,name);
            if(owned(f)&&!active.contains(name)&&!f.delete())notice.accept("Could not remove an old clip. Check storage.");
        }
    }
    void start(Recorder recorder) {stop();segment(recorder,generation);}
    private void segment(Recorder recorder,int token) {
        if(token!=generation)return;
        if(!directory.isDirectory()&&!directory.mkdirs()){notice.accept("Could not create the recordings folder.");return;}
        prune();
        long used=0;File[] files=directory.listFiles();if(files!=null)for(File f:files)if(owned(f))used+=f.length();
        if(directory.getUsableSpace()<128L*1024*1024||used>QUOTA-RESERVE){notice.accept("Recording stopped: storage is low. Monitoring continues.");return;}
        File file=new File(directory,"DG-"+System.currentTimeMillis()+"-"+UUID.randomUUID()+".mp4");
        active.add(file.getName());
        try {
            recording=recorder.prepareRecording(context,new FileOutputOptions.Builder(file).setFileSizeLimit(32L*1024*1024).build())
                .start(ContextCompat.getMainExecutor(context),event->{
                    if(event instanceof VideoRecordEvent.Start && token==generation)notice.accept("Recording 30-second clips without audio");
                    if(event instanceof VideoRecordEvent.Finalize done) {
                        active.remove(file.getName());
                        boolean usable=!done.hasError()||done.getError()==VideoRecordEvent.Finalize.ERROR_FILE_SIZE_LIMIT_REACHED;
                        if(!usable&&owned(file))file.delete();
                        prune();
                        if(token!=generation)return;
                        recording=null;handler.removeCallbacksAndMessages(null);
                        if(usable)segment(recorder,token);
                        else notice.accept("Recording stopped (code "+done.getError()+"). Monitoring continues.");
                    }
                });
            handler.postDelayed(()->{if(token==generation&&recording!=null)recording.stop();},30_000);
        } catch(Exception e){active.remove(file.getName());notice.accept("Recording could not start. Monitoring continues.");}
    }
    void stop() {
        generation++;handler.removeCallbacksAndMessages(null);
        if(recording!=null){recording.stop();recording=null;}
    }
}
