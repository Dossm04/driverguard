package kz.driverguard.offline;

import android.content.Context;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.media.MediaMuxer;
import java.io.File;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONObject;

/** Video-only remux; gaps at CameraX segment boundaries are preserved, never invented. */
final class EventClips {
    record Segment(File file,long start,long end) {}
    static File find(Context context,String id,String owner){
        if(!id.matches("[a-f0-9-]{36}"))return null;
        File dir=new File(context.getFilesDir(),"event-clips"),file=new File(dir,id+".mp4"),meta=new File(dir,id+".json");
        try{JSONObject data=new JSONObject(readText(meta));if(!Objects.equals(owner,data.isNull("owner")?null:data.getString("owner")))return null;return file.isFile()?file:null;}catch(Exception e){return null;}
    }
    static void create(Context context,String id,String owner,long at,List<Segment> segments)throws Exception{
        File dir=new File(context.getFilesDir(),"event-clips");if(!dir.isDirectory()&&!dir.mkdirs())throw new java.io.IOException("Clip directory unavailable");
        prune(dir);if(dir.getUsableSpace()<512L*1024*1024)throw new java.io.IOException("Not enough space for event video");
        List<Segment> input=segments.stream().filter(s->ClipWindow.intersects(s.start(),s.end(),at)&&s.file().isFile()).sorted(Comparator.comparingLong(Segment::start)).collect(java.util.stream.Collectors.toList());
        if(input.isEmpty())return;
        File temp=new File(dir,id+".partial.mp4"),output=new File(dir,id+".mp4");
        MediaMuxer muxer=null;boolean started=false,success=false;long first=-1,last=-1,frames=0,previousEnd=-1,gaps=0;int target=-1;
        try{
            muxer=new MediaMuxer(temp.getPath(),MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4);
            ByteBuffer buffer=ByteBuffer.allocateDirect(4*1024*1024);MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();
            for(Segment segment:input){MediaExtractor extractor=new MediaExtractor();try{
                extractor.setDataSource(segment.file().getPath());int video=-1;
                for(int i=0;i<extractor.getTrackCount();i++)if(String.valueOf(extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME)).startsWith("video/")){video=i;break;}
                if(video<0)continue;MediaFormat format=extractor.getTrackFormat(video);
                if(!started){if(format.containsKey(MediaFormat.KEY_ROTATION))muxer.setOrientationHint(format.getInteger(MediaFormat.KEY_ROTATION));target=muxer.addTrack(format);muxer.start();started=true;}
                extractor.selectTrack(video);extractor.seekTo(Math.max(0,at-ClipWindow.BEFORE-segment.start())*1000,MediaExtractor.SEEK_TO_PREVIOUS_SYNC);
                if(previousEnd>=0&&segment.start()>previousEnd+150)gaps+=segment.start()-previousEnd;
                previousEnd=segment.end();
                while(true){buffer.clear();int size=extractor.readSampleData(buffer,0);if(size<0)break;
                    long global=segment.start()*1000+extractor.getSampleTime();
                    if(global>(at+ClipWindow.AFTER)*1000)break;
                    if(first<0)first=global;
                    long pts=global-first;
                    int sampleFlags=extractor.getSampleFlags();
                    if((sampleFlags&MediaExtractor.SAMPLE_FLAG_ENCRYPTED)!=0)throw new java.io.IOException("Encrypted sample is unsupported");
                    int codecFlags=(sampleFlags&MediaExtractor.SAMPLE_FLAG_SYNC)!=0?MediaCodec.BUFFER_FLAG_KEY_FRAME:0;
                    if((sampleFlags&MediaExtractor.SAMPLE_FLAG_PARTIAL_FRAME)!=0)codecFlags|=MediaCodec.BUFFER_FLAG_PARTIAL_FRAME;
                    if(pts>last){info.set(0,size,pts,codecFlags);muxer.writeSampleData(target,buffer,info);last=pts;frames++;}
                    if(!extractor.advance())break;
                }
            }finally{extractor.release();}}
            if(!started||frames<2)throw new java.io.IOException("Insufficient video frames");
            muxer.stop();started=false;muxer.release();muxer=null;
            Files.move(temp.toPath(),output.toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            JSONObject metadata=new JSONObject().put("owner",owner==null?JSONObject.NULL:owner).put("event_uuid",id).put("event_ms",at)
                .put("wanted_before_ms",ClipWindow.BEFORE).put("wanted_after_ms",ClipWindow.AFTER).put("actual_start_ms",first/1000).put("actual_end_ms",(first+last)/1000)
                .put("partial",!ClipWindow.complete(first/1000,(first+last)/1000,at)||gaps>150).put("segment_gaps_ms",gaps).put("note","Approximate window; keyframe-aligned; no audio; never auto-uploaded");
            Files.write(new File(dir,id+".json").toPath(),metadata.toString().getBytes(StandardCharsets.UTF_8));success=true;
        }finally{if(muxer!=null){try{if(started)muxer.stop();}catch(Exception ignored){}muxer.release();}if(temp.isFile())temp.delete();if(!success&&output.isFile())output.delete();}
    }
    private static String readText(File file)throws java.io.IOException{return new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8);}
    static String description(Context c,String id){try{var m=new JSONObject(readText(new File(c.getFilesDir(),"event-clips/"+id+".json")));return m.optBoolean("partial")?"Фрагмент неполный: запись началась недавно, была остановлена или имеет разрыв.":"Около 10 секунд до и 5 после события; границы округлены до ключевых кадров.";}catch(Exception e){return "Локальный фрагмент события";}}
    private static void prune(File directory){
        File[] items=directory.listFiles((d,n)->n.matches("[a-f0-9-]{36}\\.mp4"));if(items==null)return;
        Arrays.sort(items,Comparator.comparingLong(File::lastModified));long used=0;for(File f:items)used+=f.length();
        for(File file:items){if(System.currentTimeMillis()-file.lastModified()<48L*3600_000&&used<=224L*1024*1024)continue;long size=file.length();if(file.delete()){used-=size;new File(directory,file.getName().replace(".mp4",".json")).delete();}}
    }
}
