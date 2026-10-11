package kz.driverguard.offline;

import java.util.*;

/** Select only completed app-owned clips. Never selects event database or active recording. */
final class RetentionPolicy {
    record Clip(String name,long bytes,long modified,boolean active) {}
    static List<String> removable(List<Clip> clips,long now,long maxAge,long maxBytes) {
        List<Clip> sorted=new ArrayList<>(clips);
        sorted.sort(Comparator.comparingLong(Clip::modified));
        long total=sorted.stream().mapToLong(c->Math.max(0,c.bytes())).sum();
        List<String> result=new ArrayList<>();
        for(Clip clip:sorted) {
            if(clip.active())continue;
            if(clip.modified()<now-maxAge || total>maxBytes) {
                result.add(clip.name()); total-=Math.max(0,clip.bytes());
            }
        }
        return result;
    }
}
