package kz.driverguard.offline;

import android.Manifest;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.*;
import android.media.ExifInterface;
import android.net.Uri;
import android.os.Bundle;
import android.text.*;
import android.view.View;
import android.widget.*;
import androidx.activity.ComponentActivity;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.core.content.FileProvider;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

/** Native pre-trip inspection: the same server template, photos and review contract as the web app. */
public final class AuditActivity extends ComponentActivity {
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private DriverApi api;
    private AuditStore store;
    private AuditStore.Draft draft;
    private TextView stateLabel;
    private int step;
    private boolean optional, busy;
    private String message = "Ответы и фотографии сохраняются на телефоне автоматически.";
    private String captureSlot, capturePath, captureDraft, captureOwner;
    private ActivityResultLauncher<Uri> takePhoto;
    private ActivityResultLauncher<String> permission;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        api = new DriverApi(this); store = new AuditStore(this);
        network.execute(() -> store.prunePhotos(getFilesDir()));
        takePhoto = registerForActivityResult(new ActivityResultContracts.TakePicture(), ok -> captured(Boolean.TRUE.equals(ok)));
        permission = registerForActivityResult(new ActivityResultContracts.RequestPermission(), ok -> {
            if (ok && captureSlot != null) launchPhoto(); else toast("Для фотографий разрешите доступ к камере");
        });
        if (state != null) { step = state.getInt("step", 0); optional = state.getBoolean("optional", false); }
        restoreCapture();
        SessionStore.Session session = api.session();
        if (session == null) { render(); return; }
        draft = store.current(session.owner());
        if (draft != null && !draft.state().equals("draft")) step = 2;
        render();
        loadTemplate();
    }
    @Override protected void onSaveInstanceState(Bundle state) { super.onSaveInstanceState(state); state.putInt("step",step); state.putBoolean("optional",optional); }
    @Override protected void onDestroy() { network.execute(store::close); network.shutdown(); super.onDestroy(); }

    private void loadTemplate() {
        if (api.session() == null) return;
        busy = true;
        network.execute(() -> {
            try {
                SessionStore.Session before = api.session();
                JSONArray items = api.getArray("/checklists/items"), slots = api.getArray("/checklists/slots");
                SessionStore.Session now = api.session();
                if (now == null || !now.owner().equals(before.owner())) throw new SecurityException("Аккаунт изменился");
                store.cacheTemplate(before.owner(), items, slots);
                runOnUiThread(() -> {
                    if (isDestroyed()) return;
                    busy = false;
                    if (draft == null) createDraft();
                    else { message = "Шаблон компании обновлён. Текущий осмотр сохранён."; updateState(); }
                });
            } catch (Exception failure) {
                runOnUiThread(() -> {
                    if (isDestroyed()) return;
                    busy = false;
                    if (draft == null && api.session() != null && store.template(api.session().owner()) != null) createDraft();
                    message = draft == null ? "Чтобы открыть осмотр, один раз подключитесь к серверу и загрузите шаблон." : "Нет связи с сервером. Осмотр можно заполнить и сохранить на телефоне.";
                    updateState();
                });
            }
        });
    }
    private void createDraft() {
        try {
            SessionStore.Session session = api.session();
            if (session == null) throw new IOException("Войдите в аккаунт водителя");
            draft = store.create(session); step = 0;
            message = "Новый осмотр. Ответы и фото сохраняются автоматически.";
            render();
        } catch (Exception error) { message = error.getMessage(); render(); }
    }
    private void render() {
        LinearLayout page = Ui.page(this, "Осмотр перед рейсом", "Проверьте автомобиль. Отметьте состояние. Добавьте фотографии.");
        Ui.secondary(this, page, "‹  На главную", this::finish);
        LinearLayout info = Ui.card(this, page);
        stateLabel = Ui.text(this, info, message, 14, Ui.MUTED);
        SessionStore.Session session = api.session();
        if (session == null) { Ui.text(this, info, "Войдите в аккаунт на главной странице, чтобы связать осмотр с водителем и машиной.", 17, Ui.TEXT); return; }
        if (draft == null) { Ui.button(this, page, "Загрузить шаблон", () -> { if (!busy) loadTemplate(); }); return; }
        if (!draft.owner().equals(session.owner())) { Ui.text(this, info, "Аккаунт изменился. Вернитесь на главную.", 17, Ui.AMBER); return; }
        String[] names = {"1 · Анкета", "2 · Фото", "3 · Итог"};
        LinearLayout tabs = new LinearLayout(this); page.addView(tabs);
        for (int n = 0; n < names.length; n++) {
            int next = n;
            Button tab = new Button(this); tab.setText(names[n]); tab.setAllCaps(false); tab.setTextSize(12); tab.setTextColor(Ui.TEXT);
            tab.setBackgroundTintList(ColorStateList.valueOf(step == n ? Ui.BLUE : Ui.CARD));
            tabs.addView(tab, new LinearLayout.LayoutParams(0, Ui.dp(this, 54), 1));
            tab.setOnClickListener(v -> { step = next; render(); });
        }
        try { if (step == 0) answers(page); else if (step == 1) photos(page); else summary(page); }
        catch (Exception failure) { Ui.text(this, page, "Не удалось открыть осмотр: " + failure.getMessage(), 16, Ui.RED); }
    }

    private void answers(LinearLayout page) throws Exception {
        boolean editable = draft.state().equals("draft");
        Ui.text(this, page, "Обязательные пункты отмечены •", 14, Ui.MUTED);
        String section = "";
        for (int n = 0; n < draft.items().length(); n++) {
            JSONObject item = draft.items().getJSONObject(n);
            String method = item.optString("method"), id = item.getString("id");
            if (method.equals("auto") || (!optional && !item.optBoolean("base"))) continue;
            if (!section.equals(item.optString("section"))) {
                section = item.optString("section"); Ui.text(this, page, item.optString("section_title", section), 21, Ui.TEXT);
            }
            LinearLayout card = Ui.card(this, page);
            Ui.text(this, card, (item.optBoolean("base") ? "• " : "") + item.getString("text"), 16, Ui.TEXT);
            if (method.equals("input")) {
                EditText input = Ui.field(this, card, "Введите значение", draft.answers().optString(id, ""), false);
                if (id.equals("А5")) input.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
                input.setEnabled(editable);
                input.addTextChangedListener(new TextWatcher() {
                    public void beforeTextChanged(CharSequence text, int start, int count, int after) { }
                    public void onTextChanged(CharSequence text, int start, int before, int count) { saveAnswer(id, text.toString()); }
                    public void afterTextChanged(Editable text) { }
                });
            } else {
                RadioGroup group = new RadioGroup(this); group.setOrientation(RadioGroup.HORIZONTAL); card.addView(group);
                String[] values = item.optBoolean("na_allowed") ? new String[]{"да", "нет", "н-п"} : new String[]{"да", "нет"};
                for (String value : values) {
                    RadioButton answer = new RadioButton(this); answer.setId(View.generateViewId());
                    answer.setText(value.equals("да") ? "Да" : value.equals("нет") ? "Нет" : "Н/П"); answer.setTextColor(Ui.TEXT);
                    answer.setButtonTintList(ColorStateList.valueOf(Ui.BLUE)); answer.setMinHeight(Ui.dp(this,48)); answer.setEnabled(editable);
                    group.addView(answer, new RadioGroup.LayoutParams(0, -2, 1));
                    if (draft.answers().optString(id).equals(value)) answer.setChecked(true);
                    answer.setOnClickListener(v -> saveAnswer(id, value));
                }
                if (method.equals("photo_ai")) Ui.text(this, card, "Ответ будет сопоставлен с фотографией при проверке осмотра.", 12, Ui.MUTED);
            }
        }
        Ui.secondary(this, page, optional ? "Показать обязательные пункты" : "Показать все пункты осмотра", () -> { optional = !optional; render(); });
        Ui.button(this, page, "Далее: фотографии →", () -> { step = 1; render(); });
    }
    private void saveAnswer(String id, String value) {
        try {
            if (draft == null || !draft.state().equals("draft")) return;
            JSONObject answers = new JSONObject(draft.answers().toString());
            if (value.trim().isEmpty()) answers.remove(id); else answers.put(id, value.trim());
            draft = AuditStore.changed(draft, answers, draft.photos()); store.save(draft);
        } catch (Exception failure) { toast("Ответ не сохранён: " + failure.getMessage()); }
    }
    private void photos(LinearLayout page) throws Exception {
        Ui.text(this, page, "Снимайте на стоянке. В кадре должен быть весь проверяемый участок.", 14, Ui.MUTED);
        for (int n = 0; n < draft.slots().length(); n++) {
            JSONObject slot = draft.slots().getJSONObject(n); String id = slot.getString("slot");
            LinearLayout card = Ui.card(this, page);
            Ui.text(this, card, (n + 1) + " / " + draft.slots().length() + "   " + slot.getString("label"), 19, Ui.TEXT);
            String hint = slot.optString("hint", ""); if (!hint.isBlank()) Ui.text(this, card, hint, 13, Ui.MUTED);
            String path = draft.photos().optString(id, ""); boolean exists = !path.isBlank() && new File(path).isFile();
            if (exists) {
                Bitmap image = thumbnail(path, 480);
                if (image != null) { ImageView preview = new ImageView(this); preview.setImageBitmap(image); preview.setScaleType(ImageView.ScaleType.FIT_CENTER); card.addView(preview, new LinearLayout.LayoutParams(-1, Ui.dp(this,160))); }
                Ui.text(this, card, "✓ Фото сохранено на телефоне", 13, Ui.GREEN);
            } else if (draft.state().equals("sent")) Ui.text(this, card, "Фото передано в осмотр на сервере. Локальная копия очищена.", 13, Ui.MUTED);
            if (draft.state().equals("draft")) Ui.button(this, card, exists ? "Переснять" : "Сделать фото", () -> beginPhoto(id));
        }
        Ui.button(this, page, "Проверить осмотр →", () -> { step = 2; render(); });
    }
    private void summary(LinearLayout page) throws Exception {
        LinearLayout result = Ui.card(this, page);
        if (draft.state().equals("sent")) {
            JSONObject response = draft.result();
            Ui.text(this, result, "Осмотр №" + response.optInt("id") + " передан", 23, Ui.GREEN);
            String status = response.optString("status", "pending");
            Ui.text(this, result, switch (status) {
                case "approved" -> "Координатор согласовал выезд";
                case "approved_with_note" -> "Выезд согласован с замечанием";
                case "rejected", "repair", "sent_to_repair" -> "Требуется устранить замечания";
                default -> "Ожидает решения координатора";
            }, 18, Ui.TEXT);
            JSONObject meta = response.optJSONObject("ai_meta");
            String provider = meta == null ? "" : meta.optString("provider");
            if (provider.equals("mock")) Ui.text(this, result, "Фото получены. Автоматический анализ на сервере работает в демонстрационном режиме; необходима проверка координатора.", 14, Ui.AMBER);
            else if (provider.equals("unavailable") || provider.isBlank()) Ui.text(this, result, "Фото получены. Автоматическая проверка недоступна — ожидайте проверки координатора.", 14, Ui.AMBER);
            else Ui.text(this, result, "Результат проверки: " + response.optString("verdict", "").replace('_',' '), 16, Ui.TEXT);
            String note = response.optString("note", ""); if (!note.isBlank() && !note.equals("null")) Ui.text(this, result, note, 15, Ui.TEXT);
            JSONArray issues = response.optJSONArray("answer_issues");
            if (issues != null) for (int n = 0; n < Math.min(issues.length(), 5); n++) Ui.text(this, result, "• " + issues.getJSONObject(n).optString("text"), 14, Ui.AMBER);
            Ui.button(this, page, "Обновить решение", this::refreshResult);
            Ui.secondary(this, page, "Начать новый осмотр", this::createDraft);
        } else if (draft.state().equals("correction")) {
            Ui.text(this, result, "Нужно исправить осмотр", 23, Ui.AMBER);
            Ui.text(this, result, draft.lastError(), 16, Ui.TEXT);
            Ui.text(this, result, "Сервер подтвердил, что осмотр не принят. Обновите форму и исправьте отмеченные пункты.", 14, Ui.MUTED);
            Ui.button(this, page, "Обновить форму и исправить", this::correctRejected);
        } else if (draft.state().equals("queued")) {
            Ui.text(this, result, "Сохранено для отправки", 23, Ui.AMBER);
            Ui.text(this, result, "Осмотр и фотографии находятся на телефоне. После соединения они будут переданы в панель координатора. Выезд ещё не согласован.", 16, Ui.TEXT);
            if (!draft.lastError().isBlank()) Ui.text(this, result, draft.lastError(), 13, Ui.MUTED);
            Ui.button(this, page, busy ? "Отправляем…" : "Отправить сейчас", this::flush);
        } else {
            List<String> missing = AuditValidation.missing(draft.items(), draft.slots(), draft.answers(), draft.photos());
            Ui.text(this, result, missing.isEmpty() ? "Осмотр готов к отправке" : "Осталось заполнить", 23, missing.isEmpty() ? Ui.GREEN : Ui.AMBER);
            if (!missing.isEmpty()) Ui.text(this, result, String.join(" · ", missing), 15, Ui.TEXT);
            Ui.text(this, result, "Ответов: " + draft.answers().length() + "  ·  Фото: " + draft.photos().length() + " / " + draft.slots().length(), 16, Ui.TEXT);
            Ui.text(this, result, "После отправки осмотр проверяет координатор. При отсутствии сети он сохранится на телефоне.", 14, Ui.MUTED);
            Button submit = Ui.button(this, page, "Сохранить и передать осмотр", () -> {
                try { store.queue(draft); draft = store.get(draft.id(), draft.owner()); render(); flush(); }
                catch (Exception failure) { toast(failure.getMessage()); }
            });
            submit.setEnabled(missing.isEmpty());
            Ui.secondary(this, page, "Вернуться к анкете", () -> { step = 0; render(); });
        }
    }
    private void flush() {
        if (busy) return; busy = true; message = "Передаём осмотр и фото…"; updateState();
        String id = draft.id(), owner = draft.owner();
        network.execute(() -> {
            String status;
            try { status = store.flush(api); } catch (Exception error) { status = "Осмотр сохранён. " + error.getMessage(); }
            String finalStatus = status;
            runOnUiThread(() -> { if (isDestroyed()) return; busy = false; message = finalStatus; draft = store.get(id, owner); render(); });
        });
    }
    private void refreshResult() {
        if (busy || draft == null) return; busy = true;
        String id = draft.id(), owner = draft.owner(); int remoteId = draft.result().optInt("id");
        network.execute(() -> {
            String status;
            try { store.updateResult(id, owner, api.get("/checklists/" + remoteId)); status = "Решение обновлено"; }
            catch (Exception error) { status = "Не удалось обновить решение. " + error.getMessage(); }
            String finalStatus = status;
            runOnUiThread(() -> { if (isDestroyed()) return; busy = false; message = finalStatus; draft = store.get(id, owner); render(); });
        });
    }
    private void correctRejected() {
        if (busy) return; busy = true;
        String owner = draft.owner(); AuditStore.Draft rejected = draft;
        network.execute(() -> {
            try {
                SessionStore.Session session = api.session();
                if (session == null || !session.owner().equals(owner)) throw new SecurityException("Войдите в исходный аккаунт");
                JSONArray items = api.getArray("/checklists/items"), slots = api.getArray("/checklists/slots");
                SessionStore.Session current = api.session();
                if (current == null || !current.owner().equals(owner)) throw new SecurityException("Аккаунт изменился");
                store.cacheTemplate(owner,items,slots); AuditStore.Draft editable = store.reopenRejected(rejected);
                runOnUiThread(() -> { if (isDestroyed()) return; busy=false; draft=editable; step=0; message="Форма обновлена. Ваши ответы и фото сохранены, проверьте новые обязательные пункты."; render(); });
            } catch (Exception error) { runOnUiThread(() -> { busy=false; toast("Нужна связь с сервером: " + error.getMessage()); }); }
        });
    }

    private void beginPhoto(String slot) {
        if (draft == null || !draft.state().equals("draft")) return;
        captureSlot = slot;
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) permission.launch(Manifest.permission.CAMERA);
        else launchPhoto();
    }
    private void launchPhoto() {
        String startedPath = null;
        try {
            File folder = new File(getFilesDir(), "audit_photos");
            if (!folder.isDirectory() && !folder.mkdirs()) throw new IOException("Нет места для фотографии");
            if (folder.getUsableSpace() < 128L * 1024 * 1024) throw new IOException("Освободите место на телефоне: для фото нужно 128 МБ");
            File file = new File(folder, UUID.randomUUID() + ".jpg");
            capturePath = file.getAbsolutePath(); captureDraft = draft.id(); captureOwner = draft.owner();
            startedPath = capturePath;
            store.rememberCapture(captureSlot,capturePath,captureDraft,captureOwner);
            takePhoto.launch(FileProvider.getUriForFile(this, getPackageName() + ".files", file));
        } catch (Exception error) {
            if (startedPath != null) {
                String failedPath = startedPath; store.clearCapture(failedPath);
                network.execute(() -> store.cleanupUnreferencedPhoto(getFilesDir(),failedPath));
            }
            toast("Не удалось открыть камеру: " + error.getMessage());
        }
    }
    private void restoreCapture() {
        var preferences = getSharedPreferences("audit_capture", MODE_PRIVATE);
        captureSlot = preferences.getString("slot", null); capturePath = preferences.getString("path", null);
        captureDraft = preferences.getString("draft", null); captureOwner = preferences.getString("owner", null);
    }
    private void captured(boolean success) {
        restoreCapture();
        if (!success || capturePath == null || captureSlot == null || captureDraft == null || captureOwner == null) {
            String cancelledPath = capturePath; store.clearCapture(cancelledPath);
            network.execute(() -> {
                store.cleanupUnreferencedPhoto(getFilesDir(),cancelledPath);
                if (cancelledPath != null) store.cleanupUnreferencedPhoto(getFilesDir(),cancelledPath + ".tmp");
            });
            return;
        }
        String slot = captureSlot, path = capturePath, id = captureDraft, owner = captureOwner;
        network.execute(() -> {
            try {
                File photo = new File(path);
                if (!photo.getCanonicalFile().getParentFile().equals(new File(getFilesDir(), "audit_photos").getCanonicalFile())) throw new IOException("Неверный путь фото");
                compress(photo);
                AuditStore.Draft target = store.get(id, owner);
                if (target == null || !target.state().equals("draft")) throw new IOException("Осмотр уже отправлен");
                JSONObject photos = new JSONObject(target.photos().toString()); String previous = photos.optString(slot, ""); photos.put(slot, path);
                target = AuditStore.changed(target, target.answers(), photos); store.save(target);
                if (!previous.isBlank()) store.cleanupUnreferencedPhoto(getFilesDir(),previous);
                runOnUiThread(() -> { if (isDestroyed()) return; if (draft != null && draft.id().equals(id)) draft = store.get(id, owner); step = 1; message = "Фото сохранено. Можно продолжать без интернета."; render(); });
            } catch (Exception error) { runOnUiThread(() -> toast("Фото не сохранено: " + error.getMessage())); }
            finally {
                store.clearCapture(path);
                store.cleanupUnreferencedPhoto(getFilesDir(),path);
                store.cleanupUnreferencedPhoto(getFilesDir(),path + ".tmp");
            }
        });
    }
    private static Bitmap thumbnail(String path, int longest) {
        BitmapFactory.Options options = new BitmapFactory.Options(); options.inJustDecodeBounds = true; BitmapFactory.decodeFile(path, options);
        options.inSampleSize = 1; while (Math.max(options.outWidth, options.outHeight) / options.inSampleSize > longest * 2) options.inSampleSize *= 2;
        options.inJustDecodeBounds = false; return BitmapFactory.decodeFile(path, options);
    }
    private static void compress(File file) throws Exception {
        if (!file.isFile() || file.length() == 0 || file.length() > 40L * 1024 * 1024) throw new IOException("Камера не сохранила корректное фото");
        Bitmap source = thumbnail(file.getAbsolutePath(), 1600);
        if (source == null) throw new IOException("Не удалось прочитать фото");
        Bitmap resized = source, oriented = null;
        try {
            float ratio = Math.min(1f, 1600f / Math.max(source.getWidth(), source.getHeight()));
            if (ratio < 1) resized = Bitmap.createScaledBitmap(source, Math.max(1,Math.round(source.getWidth()*ratio)), Math.max(1,Math.round(source.getHeight()*ratio)), true);
            int orientation = new ExifInterface(file.getAbsolutePath()).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL);
            Matrix matrix = new Matrix();
            switch (orientation) {
                case ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1,1);
                case ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180);
                case ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1,-1);
                case ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.setRotate(90); matrix.postScale(-1,1); }
                case ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90);
                case ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.setRotate(270); matrix.postScale(-1,1); }
                case ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(270);
                default -> { }
            }
            oriented = Bitmap.createBitmap(resized, 0, 0, resized.getWidth(), resized.getHeight(), matrix, true);
            File temporary = new File(file.getParentFile(), file.getName() + ".tmp");
            try (FileOutputStream output = new FileOutputStream(temporary)) { if (!oriented.compress(Bitmap.CompressFormat.JPEG, 85, output)) throw new IOException("Не удалось сжать фото"); }
            java.nio.file.Files.move(temporary.toPath(), file.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        } finally { if (oriented != null && oriented != resized && oriented != source) oriented.recycle(); if (resized != source) resized.recycle(); source.recycle(); }
    }
    private void updateState() { if (stateLabel != null) stateLabel.setText(message); }
    private void toast(String text) { if (!isDestroyed()) Toast.makeText(this, text == null ? "Не удалось выполнить действие" : text, Toast.LENGTH_LONG).show(); }
}
