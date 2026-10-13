package kz.driverguard.offline;

/** Image measurements for setup assistance, not a validated visibility classifier. */
final class FrameQuality {
    record Reading(double mean,double brightFraction,String message,boolean tooDark) {}
    static Reading inspect(int[] pixels){
        if(pixels.length==0)return new Reading(0,0,"Нет изображения",true);
        double sum=0;int bright=0;for(int p:pixels){double y=.2126*((p>>16)&255)+.7152*((p>>8)&255)+.0722*(p&255);sum+=y;if(y>245)bright++;}
        double mean=sum/pixels.length,ratio=bright/(double)pixels.length;
        return new Reading(mean,ratio,mean<30?"Слишком темно · добавьте освещение":ratio>.65?"Сильная засветка · измените положение камеры":"Освещение: проверьте, что глаза видны без бликов",mean<12);
    }
}
