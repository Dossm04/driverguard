package kz.driverguard.offline;
import java.net.URI;
import java.util.Locale;
final class SyncPolicy {
    static String base(String raw) {
        try {
            URI u=new URI(raw.trim());String host=u.getHost();String scheme=u.getScheme();
            if(host==null||u.getRawUserInfo()!=null||u.getRawQuery()!=null||u.getRawFragment()!=null)throw new IllegalArgumentException();
            scheme=scheme==null?"":scheme.toLowerCase(Locale.ROOT);host=host.toLowerCase(Locale.ROOT);
            if(!scheme.equals("https")&&!(scheme.equals("http")&&privateIPv4(host)))throw new IllegalArgumentException();
            if(u.getPort()==0||u.getPort()>65535)throw new IllegalArgumentException();
            String path=u.getPath()==null?"":u.getPath().replaceAll("/+$","");
            if(!path.isEmpty()&&!path.equals("/api/v1"))throw new IllegalArgumentException();
            return scheme+"://"+host+(u.getPort()==-1?"":":"+u.getPort())+"/api/v1";
        }catch(Exception e){throw new IllegalArgumentException("Укажите адрес HTTPS-сервера без пробелов, логина и параметров. Например: https://api-production-bd8b2.up.railway.app");}
    }
    static boolean privateIPv4(String host) {
        if(!host.matches("(?:[0-9]{1,3}\\.){3}[0-9]{1,3}"))return false;
        String[] p=host.split("\\.");int[] n=new int[4];
        for(int i=0;i<4;i++){n[i]=Integer.parseInt(p[i]);if(n[i]>255)return false;}
        return n[0]==10||(n[0]==192&&n[1]==168)||(n[0]==172&&n[1]>=16&&n[1]<=31);
    }
    static boolean completeAck(int sent,int accepted,int duplicates){return sent>0&&accepted>=0&&duplicates>=0&&(long)accepted+duplicates==sent;}
    static String owner(String base,int driver){if(driver<=0)throw new IllegalArgumentException("No driver profile");return base+"|driver:"+driver;}
}
