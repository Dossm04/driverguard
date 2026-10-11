package kz.driverguard.offline;

import android.Manifest;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Matrix;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.view.TextureView;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import androidx.activity.ComponentActivity;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.Preview;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.resolutionselector.ResolutionSelector;
import androidx.camera.core.resolutionselector.ResolutionStrategy;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.camera.video.Recorder;
import androidx.camera.video.VideoCapture;
import androidx.camera.video.Quality;
import androidx.camera.video.QualitySelector;
import androidx.camera.video.FallbackStrategy;
import androidx.core.content.ContextCompat;
import androidx.media3.common.MediaItem;
import androidx.media3.common.Player;
import androidx.media3.common.PlaybackException;
import androidx.media3.common.VideoSize;
import androidx.media3.exoplayer.ExoPlayer;
import androidx.media3.exoplayer.rtsp.RtspMediaSource;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import java.io.File;
import java.util.List;

public final class MainActivity extends ComponentActivity {
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final ExecutorService inference=Executors.newSingleThreadExecutor();
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private final AlertPolicy alerts=new AlertPolicy();
    private long mutedUntil, warningToneUntil;
    private TextView eyeMetric,mouthMetric,fatigueMetric,soundState;
    private Button muteButton;
    private long monitorStarted; private int observedFrames;
    private final AtomicLong newFrame=new AtomicLong();
    private TextView status,details,objects,recordStatus,syncStatus,savedEvents;
    private int sessionEventCount;
    private Button startCamera,startRtsp;
    private PreviewView preview;
    private TextureView networkVideo;
    private FrameLayout videoBox;
    private EditText host,user,password;
    private CheckBox experimental;
    private CheckBox recordVideo;
    private ClipRecorder clipRecorder;
    private volatile String activeOwner;
    private boolean syncing,foreground,authBusy;
    private ExoPlayer player;
    private ProcessCameraProvider cameras;
    private FaceEngine face;
    private CandidateEngine candidates;
    private EventStore store;
    private ToneGenerator tone;
    private boolean ready,busy;
    private volatile boolean running,destroyed,researchEnabled;
    private volatile int generation;
    private long sampledFrame,lastCapture;
    private long lastPhoneSample;
    private String source="phone";
    private String exportText="";
    private final ActivityResultLauncher<String> cameraPermission=registerForActivityResult(
        new ActivityResultContracts.RequestPermission(),granted->{if(granted)startPhone();else status.setText("Разрешите камеру в настройках приложения.");});
    private final ActivityResultLauncher<String> export=registerForActivityResult(
        new ActivityResultContracts.CreateDocument("text/csv"),uri->{
            if(uri==null)return;
            try(var out=getContentResolver().openOutputStream(uri)) {
                if(out==null)throw new java.io.IOException(); out.write(exportText.getBytes(StandardCharsets.UTF_8));
                status.setText("Журнал экспортирован");
            } catch(Exception e){status.setText("Не удалось экспортировать журнал.");}
        });

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        store=new EventStore(this);
        setVolumeControlStream(AudioManager.STREAM_MUSIC);
        try {tone=new ToneGenerator(AudioManager.STREAM_MUSIC,85);}catch(RuntimeException unavailable){tone=null;}
        var session=new DriverApi(this).session();
        activeOwner=session==null?null:session.owner();
        buildUi();
        clipRecorder=new ClipRecorder(this,message->{if(!destroyed)recordStatus.setText(message);});
        clipRecorder.prune();
        inference.execute(()->{
            try {
                face=new FaceEngine(getApplicationContext());
                ui.post(()->{if(destroyed)return;ready=true;startCamera.setEnabled(true);startRtsp.setEnabled(true);status.setText("Готов к наблюдению");});
            } catch(Exception e) {
                ui.post(()->status.setText("Модель не загрузилась. Переустановите обновление приложения."));
            }
        });
    }
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private TextView text(LinearLayout box,String value,int size) {
        TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(Color.WHITE);t.setPadding(0,dp(7),0,dp(7));box.addView(t);return t;
    }
    private Button button(LinearLayout box,String name,Runnable action) {
        Button b=new Button(this);b.setText(name);b.setAllCaps(false);b.setTextSize(16);b.setTextColor(Color.WHITE);b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff2563eb));box.addView(b);b.setOnClickListener(v->action.run());return b;
    }
    private EditText field(LinearLayout box,String hint,String value,boolean secret) {
        EditText e=new EditText(this);e.setSingleLine(true);e.setHint(hint);e.setText(value);e.setTextColor(Color.WHITE);e.setHintTextColor(0xffa0afc5);
        e.setInputType(secret?InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        e.setSaveEnabled(!secret);box.addView(e);return e;
    }
    private void buildUi() {
        LinearLayout box=Ui.page(this,"Мониторинг","Камера и анализ работают на этом телефоне");
        Ui.secondary(this,box,"‹  Моя смена",this::finish);
        LinearLayout hero=Ui.card(this,box);
        status=Ui.text(this,hero,"Подготовка модели…",25,Ui.TEXT);
        details=Ui.text(this,hero,"Поставьте телефон устойчиво: лицо целиком в кадре, без бликов.",14,Ui.MUTED);
        videoBox=new FrameLayout(this);videoBox.setBackground(Ui.shape(this,Color.BLACK,18));videoBox.setClipToOutline(true);
        hero.addView(videoBox,new LinearLayout.LayoutParams(-1,dp(300)));
        preview=new PreviewView(this);preview.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);preview.setScaleType(PreviewView.ScaleType.FIT_CENTER);
        videoBox.addView(preview,new FrameLayout.LayoutParams(-1,-1));
        networkVideo=new TextureView(this);networkVideo.setVisibility(View.GONE);videoBox.addView(networkVideo,new FrameLayout.LayoutParams(-1,-1));
        LinearLayout metrics=Ui.card(this,box);
        eyeMetric=Ui.text(this,metrics,"ГЛАЗА    —",18,Ui.TEXT);
        mouthMetric=Ui.text(this,metrics,"ЗЕВКИ    —",18,Ui.TEXT);
        fatigueMetric=Ui.text(this,metrics,"УСТАЛОСТЬ    накапливаем наблюдения",15,Ui.MUTED);
        startCamera=Ui.button(this,box,"Начать наблюдение",this::startPhone);startCamera.setEnabled(false);
        Ui.secondary(this,box,"Завершить наблюдение",()->{stop();status.setText("Наблюдение завершено");});
        LinearLayout sound=Ui.card(this,box);
        soundState=Ui.text(this,sound,"Звук включён",18,Ui.GREEN);
        muteButton=Ui.secondary(this,sound,"Без звука на 30 секунд",()->{
            if(SystemClock.elapsedRealtime()<mutedUntil)mutedUntil=0;else mutedUntil=SystemClock.elapsedRealtime()+30_000;
            if(tone!=null)tone.stopTone();updateSoundLabel();
        });
        Ui.secondary(this,sound,"Проверить громкость",this::testSound);
        savedEvents=Ui.text(this,box,"Сохранено за сеанс: 0",14,Ui.MUTED);
        syncStatus=Ui.text(this,box,activeOwner==null?"Локальный режим · войдите в аккаунт для отправки":"События привязаны к вашему аккаунту",14,Ui.MUTED);
        Ui.secondary(this,box,"Журнал событий",this::showJournal);
        Ui.text(this,box,"Оставьте приложение открытым. Если лицо пропадёт из кадра, анализ приостановится.",13,Ui.MUTED);
        CheckBox settings=new CheckBox(this);settings.setText("Камера, запись и дополнительные настройки");settings.setTextColor(Ui.MUTED);box.addView(settings);
        LinearLayout advanced=Ui.card(this,box);advanced.setVisibility(View.GONE);
        settings.setOnCheckedChangeListener((v,on)->advanced.setVisibility(on?View.VISIBLE:View.GONE));
        recordVideo=new CheckBox(this);recordVideo.setText("Записывать видео без звука");recordVideo.setTextColor(Ui.TEXT);advanced.addView(recordVideo);
        recordVideo.setOnCheckedChangeListener((b,on)->{if(running){stop();status.setText("Настройка сохранена · начните наблюдение снова");}});
        recordStatus=Ui.text(this,advanced,"Видео хранится на телефоне: до 48 часов / 512 МБ. Старые завершённые записи удаляются при работе приложения.",13,Ui.MUTED);
        Ui.secondary(this,advanced,"Записанные видео",this::showClips);
        Ui.text(this,advanced,"Внешняя IP-камера",21,Ui.TEXT);
        host=Ui.field(this,advanced,"IP камеры, например 192.168.1.64","",false);
        user=Ui.field(this,advanced,"Имя пользователя камеры","admin",false);
        password=Ui.field(this,advanced,"Пароль камеры","",true);
        startRtsp=Ui.button(this,advanced,"Подключить Hikvision",this::startNetwork);startRtsp.setEnabled(false);
        Ui.text(this,advanced,"Нужна общая локальная сеть и поток H.264 /102. Интернет для анализа не требуется.",13,Ui.MUTED);
        experimental=new CheckBox(this);experimental.setText("Исследовательские модели ремня и сигареты");experimental.setTextColor(Ui.TEXT);advanced.addView(experimental);
        objects=Ui.text(this,advanced,"Выключены. Эти оценки ещё не проверены на вашем телефоне и не отправляются как нарушения.",13,Ui.MUTED);
        experimental.setOnCheckedChangeListener((b,on)->{researchEnabled=on;objects.setText(on?"Покажите лицо и верхнюю часть тела. Дополнительный анализ может снизить скорость.":"Исследовательские модели выключены.");});
        Ui.secondary(this,advanced,"Экспорт журнала CSV",()->inference.execute(()->{exportText=store.csv(activeOwner);ui.post(()->{if(!destroyed)export.launch("DriverGuard-events.csv");});}));
        Ui.secondary(this,advanced,"Отправить очередь сейчас",this::syncNow);
        Ui.text(this,advanced,"Порог закрытия глаз: 1,5 с. Возможный зевок: открывание рта 1,2 с; предупреждение при 3 эпизодах за 10 мин. PERCLOS: доля закрытых глаз за 60 с наблюдения. Это признаки для предупреждения, а не диагноз.",13,Ui.MUTED);
    }
    private void updateSoundLabel(){
        long left=Math.max(0,mutedUntil-SystemClock.elapsedRealtime());
        AudioManager audio=(AudioManager)getSystemService(AUDIO_SERVICE);
        boolean audible=tone!=null&&audio.getStreamVolume(AudioManager.STREAM_MUSIC)>0;
        soundState.setText(left>0?"Без звука · ещё "+((left+999)/1000)+" с":!audible?"Звука нет · увеличьте громкость мультимедиа":"Звук включён");
        soundState.setTextColor(left>0||!audible?Ui.AMBER:Ui.GREEN);
        muteButton.setText(left>0?"Включить звук сейчас":"Без звука на 30 секунд");
    }
    private final Runnable soundTick=new Runnable(){public void run(){
        if(destroyed||!foreground)return;
        long now=SystemClock.elapsedRealtime();var decision=alerts.poll(now,running,now<mutedUntil);
        if(!decision.active()&&now>=warningToneUntil&&tone!=null)tone.stopTone();
        if(decision.playPulse())playAlert(600);
        else if(decision.warningPulse()){playAlert(400);warningToneUntil=now+450;}
        updateSoundLabel();ui.postDelayed(this,100);
    }};
    private void startPhone() {
        if(!ready||authBusy)return;
        if(ContextCompat.checkSelfPermission(this,Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED) {cameraPermission.launch(Manifest.permission.CAMERA);return;}
        stop();source="phone";running=true;int token=generation;resetSession();
        preview.setVisibility(View.VISIBLE);networkVideo.setVisibility(View.GONE);status.setText("Запускаем камеру…");
        var future=ProcessCameraProvider.getInstance(this);
        future.addListener(()->{
            if(token!=generation||!running)return;
            try {
                cameras=future.get();cameras.unbindAll();
                CameraSelector selected=cameras.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA)?CameraSelector.DEFAULT_FRONT_CAMERA:CameraSelector.DEFAULT_BACK_CAMERA;
                Preview p=new Preview.Builder().build();p.setSurfaceProvider(preview.getSurfaceProvider());
                ImageAnalysis analysis=new ImageAnalysis.Builder()
                    .setResolutionSelector(new ResolutionSelector.Builder().setResolutionStrategy(new ResolutionStrategy(
                        new android.util.Size(640,480),ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)).build())
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build();
                // Analyze actual camera buffers, independent of preview layout or visibility.
                analysis.setAnalyzer(inference,image->analyzePhone(image,token));
                if(recordVideo.isChecked()) {
                    Recorder recorder=new Recorder.Builder().setQualitySelector(QualitySelector.from(Quality.SD,FallbackStrategy.higherQualityOrLowerThan(Quality.SD))).build();
                    VideoCapture<Recorder> video=VideoCapture.withOutput(recorder);
                    try {cameras.bindToLifecycle(this,selected,p,analysis,video);clipRecorder.start(recorder);}
                    catch(Exception unsupported){cameras.unbindAll();cameras.bindToLifecycle(this,selected,p,analysis);recordStatus.setText("Одновременная запись недоступна. Наблюдение продолжается без видео.");}
                } else {cameras.bindToLifecycle(this,selected,p,analysis);recordStatus.setText("Запись видео выключена.");}
                lastCapture=SystemClock.elapsedRealtime();ui.post(tick);
            } catch(Exception e){stop();status.setText("Не удалось открыть камеру телефона.");}
        },ContextCompat.getMainExecutor(this));
    }
    @androidx.annotation.OptIn(markerClass = androidx.media3.common.util.UnstableApi.class)
    private void startNetwork() {
        if(!ready||authBusy)return;
        String address=host.getText().toString().trim();
        if(!address.matches("(?:[0-9]{1,3}\\.){3}[0-9]{1,3}")){status.setText(R.string.enter_camera_ip);return;}
        for(String part:address.split("\\.")) if(Integer.parseInt(part)>255){status.setText(R.string.invalid_ip);return;}
        String name=user.getText().toString();String pass=password.getText().toString();
        if(name.trim().isEmpty()||pass.trim().isEmpty()){status.setText("Введите имя и пароль камеры.");return;}
        stop();source="rtsp";running=true;int token=generation;resetSession();
        recordStatus.setText("Анализ потока Hikvision. Запись на microSD настраивается в камере отдельно.");
        preview.setVisibility(View.GONE);networkVideo.setVisibility(View.VISIBLE);status.setText("Подключаем камеру…");
        Uri uri=Uri.parse("rtsp://"+Uri.encode(name)+":"+Uri.encode(pass)+"@"+address+":554/Streaming/Channels/102");
        player=new ExoPlayer.Builder(this).build();player.setVideoTextureView(networkVideo);player.setVolume(0);
        player.setVideoFrameMetadataListener((presentationTimeUs,releaseTimeNs,format,mediaFormat)->{if(token==generation)newFrame.set(SystemClock.elapsedRealtime());});
        player.addListener(new Player.Listener(){
            @Override public void onPlayerError(PlaybackException error){
                if(token!=generation)return;stop();status.setText(R.string.no_stream);
            }
            @Override public void onVideoSizeChanged(VideoSize size){
                if(size.width<=0||size.height<=0)return;
                networkVideo.setLayoutParams(new FrameLayout.LayoutParams(-1,Math.max(dp(120),videoBox.getWidth()*size.height/size.width),android.view.Gravity.CENTER));
            }
        });
        player.setMediaSource(new RtspMediaSource.Factory().setForceUseRtpTcp(true).setTimeoutMs(8000).createMediaSource(MediaItem.fromUri(uri)));
        player.prepare();player.play();lastCapture=SystemClock.elapsedRealtime();ui.post(tick);
    }
    private final Runnable tick=new Runnable(){public void run(){
        if(!running||destroyed)return;
        long now=SystemClock.elapsedRealtime(),frame=newFrame.get();
        long recent=source.equals("phone")?Math.max(lastCapture,frame):lastCapture;
        if(now-recent>2000) {status.setText("Нет новых кадров · наблюдение приостановлено");objects.setText("Нет актуальных наблюдений");}
        if(source.equals("phone")){ui.postDelayed(this,200);return;}
        if(!busy&&frame>sampledFrame&&now-frame<1000) {
            Bitmap raw=networkVideo.getBitmap();
            if(raw!=null) {
                sampledFrame=frame;lastCapture=now;busy=true;int token=generation;String src=source,owner=activeOwner;boolean extra=experimental.isChecked();long capturedAt=System.currentTimeMillis()-(now-frame);
                Bitmap image=downscale(raw);
                inference.execute(()->{
                    try {
                        processFrame(image,frame,token,src,owner,capturedAt,extra);
                    } catch(Exception e){ui.post(()->{if(token==generation){stop();status.setText("Ошибка обработки. Запустите камеру снова.");}});}
                    finally {image.recycle();ui.post(()->busy=false);}
                });
            }
        }
        ui.postDelayed(this,200);
    }};
    private static Bitmap downscale(Bitmap raw) {
        float ratio=Math.min(1f,640f/Math.max(raw.getWidth(),raw.getHeight()));
        Bitmap image=Bitmap.createScaledBitmap(raw,Math.max(1,Math.round(raw.getWidth()*ratio)),Math.max(1,Math.round(raw.getHeight()*ratio)),true);
        if(image!=raw)raw.recycle();return image;
    }
    private void analyzePhone(ImageProxy proxy,int token) {
        Bitmap image=null;
        try {
            if(destroyed||!running||token!=generation)return;
            long frame=SystemClock.elapsedRealtime();newFrame.set(frame);
            if(frame-lastPhoneSample<200)return;
            lastPhoneSample=frame;
            long capturedAt=System.currentTimeMillis();
            image=proxy.toBitmap();
            int rotation=proxy.getImageInfo().getRotationDegrees();
            if(rotation!=0){Matrix matrix=new Matrix();matrix.postRotate(rotation);
                Bitmap upright=Bitmap.createBitmap(image,0,0,image.getWidth(),image.getHeight(),matrix,true);
                if(upright!=image)image.recycle();image=upright;}
            image=downscale(image);
            processFrame(image,frame,token,"phone",activeOwner,capturedAt,researchEnabled);
        }catch(Exception failure){ui.post(()->{if(!destroyed&&token==generation){stop();status.setText("Ошибка обработки. Запустите камеру снова.");}});}
        finally{if(image!=null&&!image.isRecycled())image.recycle();proxy.close();}
    }
    // Single inference executor owns model state and commits events before optional research work.
    private void processFrame(Bitmap image,long frame,int token,String src,String owner,long capturedAt,boolean extra) {
        if(destroyed||!running||token!=generation)return;
        DmsRules.Result result=face.analyze(image,frame);
        long latency=SystemClock.elapsedRealtime()-frame;
        if(destroyed||!running||token!=generation)return;
        if(latency>1500){face.rules.reset();ui.post(()->{if(!destroyed&&running&&token==generation)status.setText("Обработка задерживается. Выключите дополнительные модели.");});return;}
        int saved=0;
        for(String event:result.events()){
            double value=switch(event){case "fatigue_perclos"->result.perclos()*100;case "fatigue_yawning","yawn"->result.yawnCount();case "head_nod"->result.headDownMs()/1000.0;default->result.closedMs()/1000.0;};
            try{store.add(event,src,owner,capturedAt,result.closedMs(),result.confidence(),value);saved++;}
            catch(Exception failure){ui.post(()->{if(!destroyed){savedEvents.setText("Событие не сохранено · проверьте свободное место");syncStatus.setText("Не удалось записать событие на телефон");}});}
        }
        final int persisted=saved;
        ui.post(()->{
            if(destroyed||token!=generation||!running)return;
            alerts.onFrame(frame,result);observedFrames++;
            String label=!result.faceVisible()?"Лицо не видно":result.closureAlarm()?"Откройте глаза · остановитесь":result.fatigueActive()?"Признаки усталости · нужен отдых":result.headDownMs()>=2000?"Поднимите голову":result.eyesClosed()?"Глаза закрыты":"Наблюдение активно";
            status.setText(label);status.setTextColor(result.closureAlarm()?Ui.RED:result.fatigueActive()||!result.faceVisible()?Ui.AMBER:Ui.GREEN);
            eyeMetric.setText(!result.faceVisible()?"ГЛАЗА    нет наблюдения":result.eyesClosed()?String.format(java.util.Locale.US,"ГЛАЗА    закрыты %.1f с",result.closedMs()/1000.0):"ГЛАЗА    открыты");
            eyeMetric.setTextColor(result.closureAlarm()?Ui.RED:Ui.TEXT);
            mouthMetric.setText("ВОЗМОЖНЫЕ ЗЕВКИ    "+result.yawnCount()+" / 10 мин"+(result.jawOpenMs()>0?" · рот открыт":""));
            fatigueMetric.setText(result.perclosReady()?"PERCLOS    "+Math.round(result.perclos()*100)+"% · закрытие глаз за окно 60 с":"PERCLOS    наблюдений "+result.validMs()/1000+" с / минимум 15 с");
            details.setText("На телефоне · "+latency+" мс/кадр · "+(result.headCalibrated()?"положение головы настроено":"смотрите прямо 3 секунды для настройки"));
            if(persisted>0){sessionEventCount+=persisted;savedEvents.setText("Сохранено за сеанс: "+sessionEventCount);}
        });
        if(extra){String candidateText;
            try{if(candidates==null)candidates=new CandidateEngine(getApplicationContext());candidateText=!result.faceVisible()?"Лицо не видно · дополнительные оценки недоступны":candidates.analyze(image);}
            catch(Exception optionalFailure){candidateText="Дополнительные модели недоступны · анализ глаз продолжается";}
            final String display=candidateText;
            ui.post(()->{if(!destroyed&&token==generation&&running&&researchEnabled)objects.setText(display);});
        }
    }
    private void resetSession(){sessionEventCount=0;observedFrames=0;monitorStarted=SystemClock.elapsedRealtime();savedEvents.setText("Сохранено за сеанс: 0");status.setTextColor(Ui.TEXT);inference.execute(()->lastPhoneSample=0);}
    private void playAlert(int duration){if(tone!=null)tone.startTone(ToneGenerator.TONE_PROP_BEEP2,duration);}
    private void testSound(){
        AudioManager audio=(AudioManager)getSystemService(AUDIO_SERVICE);
        String message=tone==null?"Звук недоступен. Перезапустите приложение.":audio.getStreamVolume(AudioManager.STREAM_MUSIC)==0?"Громкость мультимедиа — ноль. Увеличьте её кнопками телефона.":"Это проверка звука. Для проверки распознавания запустите камеру.";
        warningToneUntil=SystemClock.elapsedRealtime()+550;playAlert(500);Toast.makeText(this,message,Toast.LENGTH_LONG).show();
    }
    private void showJournal(){inference.execute(()->{String log=store.recent(activeOwner);ui.post(()->{if(!destroyed)new AlertDialog.Builder(this).setTitle("Журнал на телефоне").setMessage(log).setPositiveButton("Закрыть",null).show();});});}
    private void stop() {
        generation++;running=false;alerts.reset();warningToneUntil=0;if(tone!=null)tone.stopTone();ui.removeCallbacks(tick);newFrame.set(0);sampledFrame=0;
        if(clipRecorder!=null)clipRecorder.stop();
        if(cameras!=null)cameras.unbindAll();
        if(player!=null){player.release();player=null;}
        if(face!=null)inference.execute(()->face.rules.reset());
    }
    private void showClips() {
        List<File> files=clipRecorder.clips();
        if(files.isEmpty()){new AlertDialog.Builder(this).setMessage("Завершённых записей пока нет. Остановите наблюдение, чтобы завершить текущую запись.").setPositiveButton("Закрыть",null).show();return;}
        String[] labels=files.stream().limit(30).map(f->f.getName()+" · "+f.length()/1024+" KB").toArray(String[]::new);
        new AlertDialog.Builder(this).setTitle("Видеозаписи · выберите для отправки").setItems(labels,(d,i)->{
            Uri uri=androidx.core.content.FileProvider.getUriForFile(this,getPackageName()+".files",files.get(i));
            Intent send=new Intent(Intent.ACTION_SEND).setType("video/mp4").putExtra(Intent.EXTRA_STREAM,uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(Intent.createChooser(send,"Сохранить или поделиться видео"));
        }).setNegativeButton("Закрыть",null).show();
    }
    private void syncNow() {
        if(syncing||authBusy||destroyed)return;syncing=true;
        final boolean monitoring=running;final double fps=observedFrames*1000.0/Math.max(1,SystemClock.elapsedRealtime()-monitorStarted);
        network.execute(()->{
            String message;
            try {message=SyncCoordinator.events(this,store);if(monitoring)SyncCoordinator.heartbeat(this,fps);
                try(AuditStore audits=new AuditStore(this)){audits.flush(new DriverApi(this));}
            }
            catch(SecurityException e){message="Войдите снова · события остаются на телефоне";}
            catch(Exception e){message="Нет связи с сервером · события сохранены и ждут отправки";}
            final String result=message;ui.post(()->{syncing=false;if(!destroyed)syncStatus.setText(result);});
        });
    }
    private final Runnable syncTick=new Runnable(){public void run(){if(!foreground||destroyed)return;syncNow();ui.postDelayed(this,15_000);}};
    @Override protected void onResume(){super.onResume();foreground=true;ui.post(syncTick);ui.post(soundTick);}
    @Override protected void onPause(){super.onPause();foreground=false;ui.removeCallbacks(syncTick);ui.removeCallbacks(soundTick);stop();if(status!=null)status.setText("Наблюдение остановлено · нажмите «Начать наблюдение»");}
    @Override protected void onDestroy(){stop();destroyed=true;if(tone!=null)tone.release();
        inference.execute(()->{if(face!=null)face.close();if(candidates!=null)candidates.close();});inference.shutdown();
        network.execute(()->{try{if(inference.awaitTermination(30,java.util.concurrent.TimeUnit.SECONDS))store.close();}catch(InterruptedException e){Thread.currentThread().interrupt();}});
        network.shutdown();super.onDestroy();}
}
