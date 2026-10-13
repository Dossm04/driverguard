package kz.driverguard.offline;

final class ClipWindow {
    static final long BEFORE=10_000,AFTER=5_000;
    static boolean intersects(long from,long to,long event){return to>from&&from<event+AFTER&&to>event-BEFORE;}
    static boolean complete(long earliest,long latest,long event){return earliest<=event-BEFORE&&latest>=event+AFTER;}
}
