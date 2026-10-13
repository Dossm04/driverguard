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
    static final long QUOTA=2L*1024*1024*1024, RESERVE=40L*1024*1024;
    static final long AGE=48L*60*60*1000;
    private final Context context;
    private final File directory;
    private final Consumer<String> notice;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Set<String> active=new HashSet<>();
    private Recording recording;
    private static final java.util.concurrent.ExecutorService EXPORTS=java.util.concurrent.Executors.newSingleThreadExecutor();
    private final Map<Integer,List<EventClips.Segment>> sessions=new HashMap<>();
    private record Request(String id,String owner,long at,int token) {}
    private final List<Request> requests=new ArrayList<>();
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
            if(owned(f)&&!active.contains(name)&&!f.delete())notice.accept("Не удалось удалить старую запись. Проверьте память.");
        }
    }
    void start(Recorder recorder) {stop();segment(recorder,generation);}
    void markEvent(String id,String owner,long at){
        if(recording==null||requests.size()>=20)return;
        int token=generation;requests.add(new Request(id,owner,at,token));
        handler.postDelayed(()->{if(token==generation&&recording!=null)recording.stop();},Math.max(0,at+ClipWindow.AFTER-System.currentTimeMillis())+200);
    }
    private void flushRequests(int token,boolean stopped){
        List<EventClips.Segment> segments=sessions.computeIfAbsent(token,k->new ArrayList<>());
        long end=segments.isEmpty()?0:segments.get(segments.size()-1).end();
        for(var iterator=requests.iterator();iterator.hasNext();){Request request=iterator.next();if(request.token()!=token||(!stopped&&end<request.at()+ClipWindow.AFTER))continue;
            List<EventClips.Segment> copy=new ArrayList<>(segments);iterator.remove();
            EXPORTS.execute(()->{try{EventClips.create(context.getApplicationContext(),request.id(),request.owner(),request.at(),copy);}catch(Exception e){handler.post(()->notice.accept("Не удалось сохранить клип события; само событие сохранено."));}});
        }
        segments.removeIf(s->System.currentTimeMillis()-s.end()>120_000);
        if(stopped)sessions.remove(token);
    }
    private void segment(Recorder recorder,int token) {
        if(token!=generation)return;
        if(!directory.isDirectory()&&!directory.mkdirs()){notice.accept("Не удалось создать папку видеозаписей.");return;}
        prune();
        long used=0;File[] files=directory.listFiles();if(files!=null)for(File f:files)if(owned(f))used+=f.length();
        if(directory.getUsableSpace()<512L*1024*1024||used>QUOTA-RESERVE){notice.accept("Запись остановлена: мало памяти. Наблюдение продолжается.");return;}
        File file=new File(directory,"DG-"+System.currentTimeMillis()+"-"+UUID.randomUUID()+".mp4");
        final long[] actualStart={System.currentTimeMillis()};
        active.add(file.getName());
        try {
            recording=recorder.prepareRecording(context,new FileOutputOptions.Builder(file).setFileSizeLimit(32L*1024*1024).build())
                .start(ContextCompat.getMainExecutor(context),event->{
                    if(event instanceof VideoRecordEvent.Start && token==generation){actualStart[0]=System.currentTimeMillis();notice.accept("Запись включена · клипы событий около 10 с до / 5 с после");}
                    if(event instanceof VideoRecordEvent.Finalize done) {
                        active.remove(file.getName());
                        boolean usable=!done.hasError()||done.getError()==VideoRecordEvent.Finalize.ERROR_FILE_SIZE_LIMIT_REACHED;
                        if(!usable&&owned(file))file.delete();
                        if(usable){long duration=done.getRecordingStats().getRecordedDurationNanos()/1_000_000;sessions.computeIfAbsent(token,k->new ArrayList<>()).add(new EventClips.Segment(file,actualStart[0],actualStart[0]+duration));flushRequests(token,token!=generation);}
                        else flushRequests(token,true);
                        prune();
                        if(token!=generation)return;
                        recording=null;handler.removeCallbacksAndMessages(null);
                        if(usable)segment(recorder,token);
                        else notice.accept("Запись остановлена (код "+done.getError()+"). Наблюдение продолжается.");
                    }
                });
            handler.postDelayed(()->{if(token==generation&&recording!=null)recording.stop();},30_000);
        } catch(Exception e){active.remove(file.getName());if(owned(file))file.delete();notice.accept("Запись не запустилась. Наблюдение продолжается.");}
    }
    void stop() {
        generation++;handler.removeCallbacksAndMessages(null);
        if(recording!=null){recording.stop();recording=null;}
    }
}
