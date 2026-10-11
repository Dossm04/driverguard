package kz.driverguard.offline;
import java.util.List;
interface EventOutbox {
    record Pending(String uuid,String at,String source,long closedMs,float confidence,String kind,double value) {
        Pending(String uuid,String at,String source,long closedMs,float confidence){this(uuid,at,source,closedMs,confidence,"eyes_closed",closedMs/1000.0);}
    }
    List<Pending> pending(String owner);
    void acknowledge(String owner,List<Pending> batch);
    long pendingCount(String owner);
}
