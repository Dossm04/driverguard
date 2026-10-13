package kz.driverguard.offline;
import android.os.*;
import android.widget.*;
import android.app.AlertDialog;
import androidx.activity.ComponentActivity;
import org.json.*;

/** Native reading and knowledge check. Only an actual assigned lesson may update the server. */
public final class LearningActivity extends ComponentActivity {
    private DriverApi api;private LearningStore store;private String owner;
    private final Handler ui=new Handler(Looper.getMainLooper());
    private boolean visible;private long readingMs,lastTick;private LessonCatalog.Lesson current;private int assignment;
    private Button complete;private TextView time;private RadioGroup answers;
    @Override public void onCreate(Bundle state){super.onCreate(state);api=new DriverApi(this);store=new LearningStore(this);var s=api.session();if(s==null){finish();return;}owner=s.owner();catalog();}
    private boolean same(){var s=api.session();return s!=null&&s.owner().equals(owner);}
    private void catalog(){
        current=null;ui.removeCallbacks(tick);if(!same()){finish();return;}
        LinearLayout page=Ui.page(this,"Уроки водителя","Содержание встроено в приложение и открывается без интернета.");
        Ui.secondary(this,page,"‹  Мой профиль",this::finish);
        JSONArray assigned=api.session().profile().optJSONArray("trainings");
        if(assigned!=null)for(int i=0;i<assigned.length();i++){
            JSONObject item=assigned.optJSONObject(i);if(item==null)continue;
            var lesson=LessonCatalog.title(item.optString("title"));if(lesson==null)continue;
            int id=item.optInt("id");if(id<=0)continue;
            LinearLayout card=Ui.card(this,page);Ui.text(this,card,"НАЗНАЧЕНО КООРДИНАТОРОМ",11,Ui.BLUE);Ui.text(this,card,lesson.title(),22,Ui.TEXT);
            String state=store.status(owner,id,lesson.id());
            Ui.text(this,card,item.optString("status").equals("completed")||state.equals("sent")?"Пройдено · подтверждено сервером":state.equals("pending")?"Пройдено на телефоне · ждёт отправки":"Прочитайте урок и ответьте на вопрос",14,Ui.MUTED);
            Ui.button(this,card,"Открыть урок",()->open(lesson,id));
        }
        Ui.text(this,page,"Библиотека · для самостоятельного чтения",20,Ui.TEXT);
        for(var lesson:LessonCatalog.ALL){LinearLayout card=Ui.card(this,page);Ui.text(this,card,lesson.title(),22,Ui.TEXT);
            Ui.text(this,card,store.status(owner,0,lesson.id()).equals("local")?"Прочитано на этом телефоне":"Около минуты · короткий вопрос",14,Ui.MUTED);
            Ui.secondary(this,card,"Читать",()->open(lesson,0));}
        Ui.text(this,page,"Самостоятельное чтение не заменяет назначение координатора или допуск к рейсу. Результат назначенного урока отправится при открытом приложении после восстановления сети.",13,Ui.MUTED);
    }
    private void open(LessonCatalog.Lesson lesson,int id){
        current=lesson;assignment=id;readingMs=0;lastTick=SystemClock.elapsedRealtime();
        LinearLayout page=Ui.page(this,lesson.title(),"Изучайте только на остановке.");Ui.secondary(this,page,"‹  Все уроки",this::catalog);
        LinearLayout card=Ui.card(this,page);int n=0;for(String step:lesson.steps())Ui.text(this,card,(++n)+". "+step,17,Ui.TEXT);
        Ui.text(this,card,"Источник: "+lesson.source(),12,Ui.MUTED);
        LinearLayout quiz=Ui.card(this,page);Ui.text(this,quiz,lesson.question(),20,Ui.TEXT);
        answers=new RadioGroup(this);quiz.addView(answers);
        for(int i=0;i<lesson.answers().size();i++){RadioButton option=new RadioButton(this);option.setId(100+i);option.setText(lesson.answers().get(i));option.setTextColor(Ui.TEXT);option.setPadding(0,Ui.dp(this,9),0,Ui.dp(this,9));answers.addView(option);}
        time=Ui.text(this,quiz,"Прочитайте материал · 30 с",14,Ui.MUTED);
        complete=Ui.button(this,quiz,"Сохранить результат",()->{
            if(!same()){finish();return;}
            if(answers.getCheckedRadioButtonId()!=100+lesson.correct()){new AlertDialog.Builder(this).setMessage("Ответ пока неверный. Перечитайте материал и попробуйте снова.").setPositiveButton("Понятно",null).show();return;}
            try{store.complete(owner,assignment,lesson.id());Toast.makeText(this,assignment>0?"Сохранено. При связи результат отправится координатору.":"Прочитано · сохранено на телефоне",Toast.LENGTH_LONG).show();catalog();}
            catch(Exception e){new AlertDialog.Builder(this).setMessage(e.getMessage()).setPositiveButton("Понятно",null).show();}
        });complete.setEnabled(false);ui.removeCallbacks(tick);if(visible)ui.post(tick);
    }
    private final Runnable tick=new Runnable(){public void run(){if(!visible||current==null)return;long now=SystemClock.elapsedRealtime();readingMs+=Math.max(0,Math.min(1500,now-lastTick));lastTick=now;long left=Math.max(0,30_000-readingMs);time.setText(left==0?"Ответьте на вопрос, чтобы сохранить результат":"Прочитайте материал · ещё "+((left+999)/1000)+" с");complete.setEnabled(left==0);ui.postDelayed(this,250);}};
    @Override protected void onResume(){super.onResume();visible=true;lastTick=SystemClock.elapsedRealtime();if(current!=null)ui.post(tick);}
    @Override protected void onPause(){visible=false;ui.removeCallbacks(tick);super.onPause();}
    @Override protected void onDestroy(){ui.removeCallbacksAndMessages(null);super.onDestroy();}
}
