package kz.driverguard.offline;

import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.*;
import android.view.*;
import android.widget.*;
import androidx.activity.ComponentActivity;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.*;
import org.json.*;

/** Driver workspace: the account, pre-trip inspection and monitor share one identity. */
public final class DriverHubActivity extends ComponentActivity {
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private final Handler handler=new Handler(Looper.getMainLooper());
    private DriverApi api;private EventStore events;private AuditStore audits;
    private LinearLayout content;private TextView feedback;private String tab="Смена",message="";
    private boolean busy,visible,closed;
    @Override public void onCreate(Bundle state){super.onCreate(state);api=new DriverApi(this);events=new EventStore(this);audits=new AuditStore(this);render();}
    private SessionStore.Session session(){return api.session();}
    private JSONObject profile(){var s=session();return s==null?new JSONObject():s.profile();}
    private JSONObject object(JSONObject p,String name){JSONObject o=p.optJSONObject(name);return o==null?new JSONObject():o;}
    private String owner(){var s=session();return s==null?null:s.owner();}
    private void render(){
        if(closed)return;getWindow().setStatusBarColor(Ui.BG);getWindow().setNavigationBarColor(Ui.BG);
        LinearLayout shell=new LinearLayout(this);shell.setOrientation(LinearLayout.VERTICAL);shell.setBackgroundColor(Ui.BG);setContentView(shell);
        shell.setOnApplyWindowInsetsListener((v,i)->{shell.setPadding(0,i.getSystemWindowInsetTop(),0,i.getSystemWindowInsetBottom());return i;});
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);shell.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);content.setPadding(Ui.dp(this,20),Ui.dp(this,20),Ui.dp(this,20),Ui.dp(this,18));scroll.addView(content);
        Ui.text(this,content,"DRIVERGUARD",12,Ui.BLUE).setLetterSpacing(.18f);
        Ui.text(this,content,tab.equals("Смена")?"Моя смена":tab,32,Ui.TEXT);
        Ui.text(this,content,LocalDate.now().format(DateTimeFormatter.ofPattern("d MMMM, EEEE",java.util.Locale.forLanguageTag("ru"))),14,Ui.MUTED);
        feedback=Ui.text(this,content,busy?"Обновляем данные…":message,13,Ui.MUTED);
        switch(tab){case "Профиль"->account();case "Журнал"->journal();default->home();}
        LinearLayout nav=new LinearLayout(this);nav.setPadding(Ui.dp(this,6),Ui.dp(this,7),Ui.dp(this,6),Ui.dp(this,7));nav.setBackgroundColor(Ui.CARD);shell.addView(nav);
        for(String name:new String[]{"Смена","Аудит","Журнал","Профиль"}){
            TextView item=new TextView(this);item.setText(name);item.setTextColor(name.equals(tab)?Ui.BLUE:Ui.MUTED);item.setTextSize(13);item.setGravity(Gravity.CENTER);item.setMinHeight(Ui.dp(this,52));
            nav.addView(item,new LinearLayout.LayoutParams(0,-2,1));item.setOnClickListener(v->{if(name.equals("Аудит"))openAudit();else{tab=name;render();}});
        }
    }
    private void home(){
        var session=session();JSONObject p=profile(),driver=object(p,"driver"),vehicle=object(driver,"vehicle");
        LinearLayout identity=Ui.card(this,content);
        Ui.text(this,identity,session==null?"Начните со своего аккаунта":driver.optString("name",p.optString("name","Водитель")),23,Ui.TEXT);
        Ui.text(this,identity,session==null?"Вход связывает аудит и события с вашей сменой.":vehicle.optString("plate","Автомобиль не назначен")+"  ·  "+driver.optString("depot","DriverGuard"),14,Ui.MUTED);
        if(session==null)Ui.button(this,identity,"Войти в аккаунт",()->{tab="Профиль";render();});
        LinearLayout monitor=Ui.card(this,content);
        Ui.text(this,monitor,"Камера рядом.\nВнимание — на дороге.",26,Ui.TEXT);
        Ui.text(this,monitor,"Глаза, возможные зевки и положение головы. Предупреждения работают без интернета.",15,Ui.MUTED);
        Ui.button(this,monitor,"Открыть мониторинг",()->startActivity(new Intent(this,MainActivity.class)));
        Ui.text(this,monitor,"Показывайте прототип на неподвижном месте.",12,Ui.MUTED);
        LinearLayout audit=Ui.card(this,content);Ui.text(this,audit,"01  Предрейсовый аудит",21,Ui.TEXT);
        JSONObject check=object(p,"last_checklist");
        Ui.text(this,audit,check.has("id")?"Последний осмотр №"+check.optInt("id")+" · "+verdict(check):"Фотографии автомобиля и проверка перед рейсом",14,Ui.MUTED);
        Ui.button(this,audit,"Заполнить аудит",this::openAudit);
        LinearLayout shift=Ui.card(this,content);Ui.text(this,shift,"02  Рейс и отдых",21,Ui.TEXT);
        JSONObject trip=p.optJSONObject("active_trip");
        if(trip==null){Ui.text(this,shift,"Активного рейса нет",15,Ui.MUTED);Ui.secondary(this,shift,"Начать рейс",this::startTrip);}
        else{
            boolean pause=trip.optJSONObject("break")!=null;int tripId=trip.optInt("id");
            Ui.text(this,shift,pause?"Перерыв · можно отдохнуть":"Рейс №"+tripId+" · в работе",19,pause?Ui.AMBER:Ui.GREEN);
            Ui.secondary(this,shift,pause?"Завершить перерыв":"Сделать перерыв",()->{
                if(pause)call(()->{api.post("/trips/"+tripId+"/breaks/end",new JSONObject());return "Перерыв завершён";},true);
                else new AlertDialog.Builder(this).setTitle("Причина перерыва").setItems(new String[]{"устал","туалет","еда","заправка","другое"},(d,n)->call(()->{api.post("/trips/"+tripId+"/breaks",new JSONObject().put("reason",new String[]{"устал","туалет","еда","заправка","другое"}[n]));return "Перерыв начат";},true)).show();
            });
            Ui.secondary(this,shift,"Завершить рейс",()->new AlertDialog.Builder(this).setTitle("Завершить текущий рейс?").setPositiveButton("Завершить",(d,n)->call(()->{api.post("/trips/"+tripId+"/stop",new JSONObject());return "Рейс завершён";},true)).setNegativeButton("Отмена",null).show());
        }
        LinearLayout delivery=Ui.card(this,content);Ui.text(this,delivery,"03  Данные под контролем",21,Ui.TEXT);
        Ui.text(this,delivery,session==null?"Наблюдения сохраняются локально. После входа новые события будут связаны с водителем.":"Ожидают отправки: "+events.pendingCount(session.owner())+" событий · "+audits.countPending(session.owner())+" осмотров",14,Ui.MUTED);
        Ui.secondary(this,delivery,"Обновить и отправить данные",this::sync);
        Ui.text(this,delivery,"При открытом приложении очередь отправляется автоматически после восстановления связи. Видео остаётся на телефоне.",13,Ui.MUTED);
    }
    private String verdict(JSONObject c){
        String state=c.optString("status");if(state.equals("pending"))return "ожидает проверки координатора";
        if(state.equals("sent_to_repair"))return "направлен на ремонт";
        return c.optString("verdict","сохранён").replace('_',' ');
    }
    private void openAudit(){if(session()==null){tab="Профиль";message="Для аудита войдите в аккаунт водителя";render();return;}startActivity(new Intent(this,AuditActivity.class));}
    private void startTrip(){
        if(session()==null){tab="Профиль";render();return;}
        JSONObject p=profile(),check=p.optJSONObject("last_checklist"),driver=object(p,"driver"),vehicle=driver.optJSONObject("vehicle");
        if(vehicle==null){notice("Автомобиль не назначен","Координатор должен назначить автомобиль вашему профилю.");return;}
        boolean today=false;try{today=OffsetDateTime.parse(check.getString("created_at")).atZoneSameInstant(ZoneId.systemDefault()).toLocalDate().equals(LocalDate.now());}catch(Exception ignored){}
        if(check==null||!today||check.optString("verdict").equals("не_допущен")||!(check.optString("status").equals("approved")||check.optString("status").equals("approved_with_note"))){notice("Сначала предрейсовый осмотр","Заполните сегодняшний аудит и дождитесь допуска координатора. Камеру можно отдельно проверить через «Открыть мониторинг».");return;}
        call(()->{JSONObject data=new JSONObject().put("driver_id",driver.getInt("id")).put("vehicle_id",vehicle.getInt("id"));JSONObject device=p.optJSONObject("device");if(device!=null)data.put("device_id",device.getInt("id"));api.post("/trips/start",data);return "Рейс начат";},true);
    }
    private void account(){
        var s=session();
        if(s==null){
            LinearLayout login=Ui.card(this,content);Ui.text(this,login,"Вход водителя",23,Ui.TEXT);
            Ui.text(this,login,"Телефон и PIN выдаёт координатор. Первый вход требует связи с сервером.",14,Ui.MUTED);
            EditText server=Ui.field(this,login,"Адрес сервера HTTPS",getSharedPreferences("hub",MODE_PRIVATE).getString("server","https://api-production-bd8b2.up.railway.app"),false);
            EditText phone=Ui.field(this,login,"Номер телефона +7…","",false);phone.setInputType(android.text.InputType.TYPE_CLASS_PHONE);
            EditText pin=Ui.field(this,login,"PIN водителя","",true);pin.setInputType(android.text.InputType.TYPE_CLASS_NUMBER|android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD);
            TextView loginState=Ui.text(this,login,"Для входа включите интернет. Камера после входа сможет работать без сети.",14,Ui.MUTED);
            Button signIn=Ui.button(this,login,"Войти",()->{});
            signIn.setOnClickListener(v->signIn(server,phone,pin,signIn,loginState));
            Ui.secondary(this,login,"Вернуть адрес облачного сервера",()->server.setText("https://api-production-bd8b2.up.railway.app"));
            Ui.secondary(this,login,"Проверить камеру без входа",()->startActivity(new Intent(this,MainActivity.class)));
            return;
        }
        JSONObject p=profile(),d=object(p,"driver");LinearLayout card=Ui.card(this,content);
        Ui.text(this,card,d.optString("name",p.optString("name","Водитель")),25,Ui.TEXT);
        Ui.text(this,card,d.optString("phone","")+"\n"+s.base(),14,Ui.MUTED);
        Ui.secondary(this,card,"Обновить профиль",this::sync);
        JSONObject score=p.optJSONObject("score");if(score!=null){Ui.text(this,card,score.optBoolean("is_new")?"Score · первая неделя":"Score · "+score.optInt("value")+" / 100",22,Ui.GREEN);Ui.text(this,card,"Расчёт сервера по событиям водителя",13,Ui.MUTED);}
        JSONArray training=p.optJSONArray("trainings");LinearLayout learning=Ui.card(this,content);Ui.text(this,learning,"Обучение и рекомендации",21,Ui.TEXT);
        if(training==null||training.length()==0)Ui.text(this,learning,"Назначенных уроков пока нет",14,Ui.MUTED);
        else for(int i=0;i<training.length();i++){JSONObject item=training.optJSONObject(i);if(item==null)continue;Ui.text(this,learning,item.optString("title")+" · "+(item.optString("status").equals("completed")?"пройден":"назначен"),16,Ui.TEXT);}
        Ui.button(this,learning,"Уроки на телефоне · без интернета",()->startActivity(new Intent(this,LearningActivity.class)));
        Ui.secondary(this,learning,"Открыть кабинет обучения",()->openCabinet("/driver/learn"));
        LinearLayout support=Ui.card(this,content);Ui.text(this,support,"Связь с координатором",21,Ui.TEXT);
        Ui.secondary(this,support,"Отправить SOS",()->new AlertDialog.Builder(this).setTitle("Сообщить координатору?").setMessage("Сигнал появится на сервере при наличии связи. Это не вызов экстренной службы.").setPositiveButton("Отправить",(dialog,n)->call(()->{api.post("/drivers/"+d.getInt("id")+"/sos",new JSONObject().put("reason","Другое").put("comment","SOS из Android DriverGuard").put("gps_valid",false));return "SOS принят сервером";},false)).setNegativeButton("Отмена",null).show());
        Ui.secondary(this,support,"Выйти из аккаунта",()->{if(busy)return;api.logout();message="Вы вышли. Сохранённые записи остаются привязаны к прежнему аккаунту.";render();});
        Ui.secondary(this,support,"Проверить готовность телефона",this::diagnostics);
        Ui.text(this,content,"DriverGuard "+BuildConfig.VERSION_NAME+" · модель лица и уроки встроены в APK. Интернет нужен для входа и отправки данных.",13,Ui.MUTED);
    }
    private void openCabinet(String path){var s=session();if(s==null)return;
        String origin=s.base().replaceFirst("/api/v1$","");
        if(origin.equals("https://api-production-bd8b2.up.railway.app"))origin="https://web-production-c2a69.up.railway.app";
        final String address=origin+path;
        new AlertDialog.Builder(this).setTitle("Кабинет в браузере").setMessage("В браузере нужно отдельно войти тем же номером и PIN. Приложение не передаёт пароль в ссылке.")
            .setPositiveButton("Открыть",(dialog,n)->startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(address)))).setNegativeButton("Отмена",null).show();}
    private void journal(){
        LinearLayout card=Ui.card(this,content);Ui.text(this,card,"События на телефоне",22,Ui.TEXT);
        Ui.text(this,card,events.recent(owner()),15,Ui.TEXT);
        Ui.secondary(this,content,"Отправить сохранённые данные",this::sync);
        var s=session();if(s!=null){JSONObject p=profile();JSONArray remote=p.optJSONArray("recent_events");if(remote!=null&&remote.length()>0){LinearLayout server=Ui.card(this,content);Ui.text(this,server,"Последние события сервера",21,Ui.TEXT);for(int i=0;i<Math.min(10,remote.length());i++){JSONObject e=remote.optJSONObject(i);if(e!=null)Ui.text(this,server,eventLabel(e.optString("type"))+"\n"+e.optString("ts",""),14,Ui.MUTED);}}}
    }
    private String eventLabel(String t){return EventText.label(t);}
    private void signIn(EditText server,EditText phone,EditText pin,Button button,TextView state){
        if(busy)return;
        final String base,number,secret;
        try{base=SyncPolicy.base(server.getText().toString());number=LoginInput.phone(phone.getText().toString());secret=LoginInput.pin(pin.getText().toString());}
        catch(Exception e){state.setText(LoginInput.error(e));state.setTextColor(Ui.RED);notice("Проверьте данные для входа",LoginInput.error(e));return;}
        busy=true;button.setEnabled(false);button.setText("Подключаемся…");state.setTextColor(Ui.BLUE);state.setText("Проверяем номер и PIN. Обычно это занимает несколько секунд.");
        network.execute(()->{
            try{var result=api.login(base,number,secret);getSharedPreferences("hub",MODE_PRIVATE).edit().putString("server",result.base()).apply();
                handler.post(()->{busy=false;if(closed)return;pin.setText("");tab="Смена";message="Вход выполнен. Ваши новые события будут отправляться в этот аккаунт.";render();Toast.makeText(this,"Вход выполнен",Toast.LENGTH_LONG).show();});
            }catch(Exception error){String message=LoginInput.error(error);handler.post(()->{busy=false;if(closed)return;button.setEnabled(true);button.setText("Войти");state.setText(message);state.setTextColor(Ui.RED);notice("Не удалось войти",message);});}
        });
    }
    private void diagnostics(){
        String owner=owner();var profile=profile();JSONObject device=profile.optJSONObject("device");
        android.media.AudioManager audio=(android.media.AudioManager)getSystemService(AUDIO_SERVICE);
        boolean camera=androidx.core.content.ContextCompat.checkSelfPermission(this,android.Manifest.permission.CAMERA)==android.content.pm.PackageManager.PERMISSION_GRANTED;
        String report="Версия: "+BuildConfig.VERSION_NAME+"\nАккаунт: "+(owner==null?"не выполнен вход":"вход сохранён")+"\nКамера: "+(camera?"разрешена":"разрешите при запуске наблюдения")+"\nГромкость: "+audio.getStreamVolume(android.media.AudioManager.STREAM_MUSIC)+"\nСвободно: "+String.format(java.util.Locale.US,"%.1f ГБ",getFilesDir().getUsableSpace()/1073741824.0)+"\nВ очереди: "+events.pendingCount(owner)+" событий, "+(owner==null?0:audits.countPending(owner))+" осмотров\nПоследняя связь в сохранённом профиле: "+(device==null?"ещё не зарегистрирована":device.optString("last_seen","нет данных"))+"\n\nНажмите «Обновить и отправить данные» при включённом интернете. Сохранённый вход сам по себе не подтверждает связь. Мониторинг требует открытого приложения.";
        notice("Готовность телефона",report);
    }
    private void notice(String title,String text){new AlertDialog.Builder(this).setTitle(title).setMessage(text).setPositiveButton("Понятно",null).show();}
    private void call(Callable<String> work,boolean refresh){
        if(busy||closed)return;busy=true;feedback.setText("Выполняем…");
        network.execute(()->{String result;try{result=work.call();if(refresh)api.refreshProfile();}catch(Exception error){result=error instanceof DriverApi.HttpError||error instanceof SecurityException||error instanceof IllegalArgumentException?error.getMessage():"Нет связи с сервером. Сохранённые данные остаются на телефоне.";}
            String value=result;handler.post(()->{busy=false;message=value;if(!closed)render();});});
    }
    private void sync(){if(session()==null||busy||closed)return;call(()->{
        String sent,inspections,connection,lessons;
        try{sent=SyncCoordinator.events(this,events);}catch(Exception e){sent="События сохранены · отправим при восстановлении связи";}
        try{inspections=audits.flush(api);}catch(Exception e){inspections="Осмотры сохранены · отправка пока недоступна";}
        try{lessons=new LearningStore(this).flush(api);}catch(Exception e){lessons="Пройденные уроки сохранены · ждут связи";}
        try{api.refreshProfile();connection="Профиль обновлён";}catch(Exception e){connection="Показан сохранённый профиль";}
        return connection+"\n"+sent+"\n"+inspections+"\n"+lessons;
    },false);}
    private final Runnable tick=new Runnable(){public void run(){if(!visible||closed)return;sync();handler.postDelayed(this,30_000);}};
    @Override protected void onResume(){super.onResume();visible=true;render();handler.post(tick);}
    @Override protected void onPause(){super.onPause();visible=false;handler.removeCallbacks(tick);}
    @Override protected void onDestroy(){closed=true;handler.removeCallbacks(tick);network.execute(()->{events.close();audits.close();});network.shutdown();super.onDestroy();}
}
