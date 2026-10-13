package kz.driverguard.offline;

/** Elapsed time wins within one boot, so changing the clock cannot inflate a break. */
final class RestPolicy {
    static long duration(long startWall,long startElapsed,int startBoot,long wall,long elapsed,int boot){
        if(startBoot==boot&&elapsed>=startElapsed)return Math.min(7L*86400_000,elapsed-startElapsed);
        return Math.max(0,Math.min(7L*86400_000,wall-startWall));
    }
    static String timer(long duration){long sec=Math.max(0,duration)/1000;return String.format(java.util.Locale.ROOT,"%02d:%02d:%02d",sec/3600,(sec/60)%60,sec%60);}
}
