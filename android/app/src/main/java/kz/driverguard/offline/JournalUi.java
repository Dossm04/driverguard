package kz.driverguard.offline;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.widget.EditText;
import android.widget.Toast;
import androidx.core.content.FileProvider;
import java.io.File;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;

final class JournalUi {
    static void show(Activity a,EventStore store,String owner){
        var rows=store.entries(owner);if(rows.isEmpty()){Toast.makeText(a,"Событий пока нет",Toast.LENGTH_LONG).show();return;}
        String[] labels=rows.stream().map(e->time(e.at())+" · "+EventText.label(e.kind())+" · "+(e.state().equals("sent")?"отправлено":e.state().equals("pending")?"ждёт сети":"локально")).toArray(String[]::new);
        new AlertDialog.Builder(a).setTitle("Выберите событие").setItems(labels,(d,n)->{
            var e=rows.get(n);
            new AlertDialog.Builder(a).setTitle(EventText.label(e.kind())).setItems(new String[]{"Открыть локальный клип","Срабатывание ошибочное · комментарий"},(dialog,choice)->{
                if(choice==0){File file=EventClips.find(a,e.uuid(),owner);if(file==null){Toast.makeText(a,"Клип ещё готовится, истёк или запись была выключена",Toast.LENGTH_LONG).show();return;}
                    Toast.makeText(a,EventClips.description(a,e.uuid()),Toast.LENGTH_LONG).show();
                    var uri=FileProvider.getUriForFile(a,a.getPackageName()+".files",file);
                    try{a.startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"video/mp4").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));}catch(Exception err){Toast.makeText(a,"Нет приложения для просмотра видео",Toast.LENGTH_LONG).show();}
                }else{
                    EditText text=new EditText(a);text.setHint("Что произошло на самом деле?");text.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(500)});
                    var box=new AlertDialog.Builder(a).setTitle("Комментарий координатору").setMessage("Исходное событие сохранится. Решение о ложном срабатывании принимает координатор.").setView(text).setPositiveButton("Сохранить",null).setNegativeButton("Отмена",null).create();
                    box.setOnShowListener(v->box.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(b->{try{store.feedback(owner,e.uuid(),text.getText().toString());Toast.makeText(a,"Сохранено · отправится при связи",Toast.LENGTH_LONG).show();box.dismiss();}catch(Exception err){text.setError(err.getMessage());}}));box.show();
                }
            }).setNegativeButton("Закрыть",null).show();
        }).setNegativeButton("Закрыть",null).show();
    }
    private static String time(String value){try{return DateTimeFormatter.ofPattern("dd.MM HH:mm:ss").withZone(ZoneId.systemDefault()).format(Instant.parse(value));}catch(Exception e){return value;}}
}
