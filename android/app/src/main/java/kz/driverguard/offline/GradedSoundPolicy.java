package kz.driverguard.offline;

/** Sound escalation only; detection, event thresholds and saved measurements stay unchanged. */
final class GradedSoundPolicy {
    static final long URGENT_CLOSURE_MS=5000, SOFT_REPEAT_MS=2500, URGENT_REPEAT_MS=1500;
    enum Level { NONE, SOFT, URGENT }
    record Decision(Level level,boolean play,boolean alarm) {}
    private Level previous=Level.NONE;
    private long played=-1;
    Decision poll(long now,AlertPolicy.Decision alert,long closedMs,boolean movingDistraction){
        if(!alert.active()){
            reset();
            return new Decision(alert.warningPulse()?Level.SOFT:Level.NONE,alert.warningPulse(),false);
        }
        Level level=closedMs>=URGENT_CLOSURE_MS||movingDistraction?Level.URGENT:Level.SOFT;
        long period=level==Level.URGENT?URGENT_REPEAT_MS:SOFT_REPEAT_MS;
        boolean due=level!=previous||played<0||now<played||now-played>=period;
        previous=level;if(due)played=now;
        return new Decision(level,due,true);
    }
    void reset(){previous=Level.NONE;played=-1;}
}
