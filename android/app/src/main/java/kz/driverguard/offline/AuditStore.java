package kz.driverguard.offline;

import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import java.io.File;
import java.io.IOException;
import java.time.Instant;
import java.time.Duration;
import java.util.*;
import org.json.*;

/** Durable, owner-scoped audit drafts and upload outbox. Submitted drafts are immutable. */
final class AuditStore extends SQLiteOpenHelper {
    private static final Object FLUSH_LOCK = new Object();
    private static final Object PHOTO_LOCK = new Object();
    private final SharedPreferences capture;
    record Template(JSONArray items, JSONArray slots) {}
    record Draft(String id, String owner, String base, JSONObject answers, JSONObject photos, String state,
                 String createdAt, JSONObject result, JSONArray items, JSONArray slots, String lastError) {}
    AuditStore(Context context) {
        super(context.getApplicationContext(), "audits.db", null, 1);
        capture = context.getApplicationContext().getSharedPreferences("audit_capture", Context.MODE_PRIVATE);
    }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE templates(owner TEXT PRIMARY KEY, items TEXT NOT NULL, slots TEXT NOT NULL)");
        db.execSQL("CREATE TABLE audits(id TEXT PRIMARY KEY, owner TEXT NOT NULL, base TEXT NOT NULL, answers TEXT NOT NULL, photos TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, result TEXT NOT NULL, items TEXT NOT NULL, slots TEXT NOT NULL, last_error TEXT NOT NULL)");
        db.execSQL("CREATE INDEX audit_owner_state ON audits(owner,state)");
    }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { }

    synchronized void cacheTemplate(String owner, JSONArray items, JSONArray slots) throws JSONException {
        if (items.length() == 0 || slots.length() == 0) throw new JSONException("Пустой шаблон осмотра");
        ContentValues row = new ContentValues(); row.put("owner", owner); row.put("items", items.toString()); row.put("slots", slots.toString());
        getWritableDatabase().insertWithOnConflict("templates", null, row, SQLiteDatabase.CONFLICT_REPLACE);
    }
    synchronized Template template(String owner) {
        try (Cursor cursor = getReadableDatabase().rawQuery("SELECT items,slots FROM templates WHERE owner=?", new String[]{owner})) {
            if (!cursor.moveToFirst()) return null;
            try { return new Template(new JSONArray(cursor.getString(0)), new JSONArray(cursor.getString(1))); }
            catch (JSONException invalid) { return null; }
        }
    }
    synchronized Draft create(SessionStore.Session session) throws Exception {
        Template template = template(session.owner());
        if (template == null) throw new IOException("Подключитесь один раз, чтобы загрузить шаблон осмотра вашей компании.");
        Draft draft = new Draft(UUID.randomUUID().toString(), session.owner(), session.base(), new JSONObject(), new JSONObject(), "draft", Instant.now().toString(), new JSONObject(), template.items(), template.slots(), "");
        ContentValues values = values(draft);
        if (getWritableDatabase().insertOrThrow("audits", null, values) == -1) throw new IOException("Не удалось сохранить осмотр");
        return draft;
    }
    synchronized Draft current(String owner) {
        try (Cursor cursor = getReadableDatabase().rawQuery("SELECT * FROM audits WHERE owner=? ORDER BY created_at DESC LIMIT 1", new String[]{owner})) {
            return cursor.moveToFirst() ? read(cursor) : null;
        }
    }
    synchronized Draft get(String id, String owner) {
        try (Cursor cursor = getReadableDatabase().rawQuery("SELECT * FROM audits WHERE id=? AND owner=?", new String[]{id, owner})) {
            return cursor.moveToFirst() ? read(cursor) : null;
        }
    }
    synchronized void save(Draft draft) {
        if (!draft.state().equals("draft")) throw new IllegalStateException("Отправленный осмотр нельзя изменять");
        synchronized (PHOTO_LOCK) {
            ContentValues row = new ContentValues(); row.put("answers", draft.answers().toString()); row.put("photos", draft.photos().toString());
            if (getWritableDatabase().update("audits", row, "id=? AND owner=? AND state='draft'", new String[]{draft.id(), draft.owner()}) != 1)
                throw new IllegalStateException("Осмотр уже отправлен или удалён");
        }
    }
    synchronized void queue(Draft draft) throws Exception {
        List<String> missing = AuditValidation.missing(draft.items(), draft.slots(), draft.answers(), draft.photos());
        if (!missing.isEmpty()) throw new IOException("Заполните обязательные пункты и фото: " + String.join(", ", missing));
        save(draft);
        ContentValues row = new ContentValues(); row.put("state", "queued"); row.put("last_error", "");
        if (getWritableDatabase().update("audits", row, "id=? AND owner=? AND state='draft'", new String[]{draft.id(), draft.owner()}) != 1)
            throw new IOException("Состояние осмотра изменилось. Откройте его заново.");
    }
    synchronized List<Draft> pending(String owner) {
        List<Draft> values = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().rawQuery("SELECT * FROM audits WHERE owner=? AND state='queued' ORDER BY created_at LIMIT 10", new String[]{owner})) {
            while (cursor.moveToNext()) values.add(read(cursor));
        }
        return values;
    }
    synchronized int countPending(String owner) {
        if (owner == null) return 0;
        try (Cursor cursor = getReadableDatabase().rawQuery("SELECT COUNT(*) FROM audits WHERE owner=? AND state='queued'", new String[]{owner})) { cursor.moveToFirst(); return cursor.getInt(0); }
    }
    /** Remove only confirmed-uploaded photos, never draft/queued evidence. Server copies remain. */
    synchronized void prunePhotos(File filesDirectory) {
        synchronized (PHOTO_LOCK) { prunePhotosLocked(filesDirectory); }
    }
    private void prunePhotosLocked(File filesDirectory) {
        File folder = new File(filesDirectory, "audit_photos");
        if (!folder.isDirectory()) return;
        Set<String> protectedFiles = new HashSet<>();
        Set<String> allReferences = new HashSet<>();
        List<Draft> sent = new ArrayList<>();
        try (Cursor cursor = getReadableDatabase().rawQuery("SELECT * FROM audits ORDER BY created_at", null)) {
            while (cursor.moveToNext()) {
                Draft row = read(cursor);
                if (row.state().equals("sent")) sent.add(row);
                else row.photos().keys().forEachRemaining(key -> protectedFiles.add(row.photos().optString(key)));
                row.photos().keys().forEachRemaining(key -> allReferences.add(row.photos().optString(key)));
            }
        }
        File[] files = folder.listFiles(); if (files == null) return;
        long total = 0; for (File file : files) if (file.isFile()) total += file.length();
        Instant cutoff = Instant.now().minus(Duration.ofDays(7));
        for (Draft row : sent) {
            boolean expired;
            try { expired = Instant.parse(row.createdAt()).isBefore(cutoff); } catch (Exception ignored) { expired = false; }
            if (!expired && total <= 256L * 1024 * 1024) continue;
            Iterator<String> slots = row.photos().keys();
            while (slots.hasNext()) {
                File photo = new File(row.photos().optString(slots.next()));
                long bytes = photo.length();
                if (deletePhotoIfUnreferenced(filesDirectory,photo.getPath(),protectedFiles,capture.getString("path",null))) total -= bytes;
            }
        }
        // Previous versions left cancelled captures and failed compression files behind.
        // A capture awaiting an Activity result is protected even across process recreation.
        for (File file : files) deletePhotoIfUnreferenced(filesDirectory,file.getPath(),allReferences,capture.getString("path",null));
    }
    void rememberCapture(String slot, String path, String draft, String owner) throws IOException {
        synchronized (PHOTO_LOCK) {
            if (!capture.edit().putString("slot",slot).putString("path",path).putString("draft",draft).putString("owner",owner).commit())
                throw new IOException("Не удалось сохранить незавершённое фото");
        }
    }
    void clearCapture(String expectedPath) {
        synchronized (PHOTO_LOCK) {
            if (Objects.equals(expectedPath,capture.getString("path",null))) capture.edit().clear().commit();
        }
    }
    synchronized void cleanupUnreferencedPhoto(File filesDirectory, String path) {
        synchronized (PHOTO_LOCK) {
            Set<String> references = new HashSet<>();
            try (Cursor cursor = getReadableDatabase().rawQuery("SELECT photos FROM audits",null)) {
                while (cursor.moveToNext()) {
                    JSONObject photos = new JSONObject(cursor.getString(0));
                    photos.keys().forEachRemaining(key -> references.add(photos.optString(key)));
                }
            } catch (JSONException damaged) { return; }
            deletePhotoIfUnreferenced(filesDirectory,path,references,capture.getString("path",null));
        }
    }
    /** Filesystem guard shared by immediate cancellation and periodic orphan cleanup. */
    static boolean deletePhotoIfUnreferenced(File filesDirectory, String path, Set<String> references, String activeCapture) {
        if (path == null || path.isBlank()) return false;
        try {
            File root = filesDirectory.getCanonicalFile(), folder = new File(root,"audit_photos").getCanonicalFile();
            if (!root.equals(folder.getParentFile())) return false;
            File photo = new File(path).getCanonicalFile();
            if (!folder.equals(photo.getParentFile()) || !photo.isFile()
                || !photo.getName().matches("[0-9a-fA-F-]{36}\\.jpg(?:\\.tmp)?")) return false;
            for (String reference : references) if (!reference.isBlank() && photo.equals(new File(reference).getCanonicalFile())) return false;
            if (activeCapture != null && !activeCapture.isBlank()) {
                if (photo.equals(new File(activeCapture).getCanonicalFile()) || photo.equals(new File(activeCapture + ".tmp").getCanonicalFile())) return false;
            }
            return photo.delete();
        } catch (IOException | SecurityException failure) { return false; }
    }
    synchronized void markSent(String id, String owner, JSONObject response) {
        ContentValues row = new ContentValues(); row.put("state", "sent"); row.put("result", response.toString()); row.put("last_error", "");
        getWritableDatabase().update("audits", row, "id=? AND owner=? AND state='queued'", new String[]{id, owner});
    }
    synchronized void updateResult(String id, String owner, JSONObject response) {
        ContentValues row = new ContentValues(); row.put("result", response.toString());
        getWritableDatabase().update("audits", row, "id=? AND owner=? AND state='sent'", new String[]{id, owner});
    }
    private synchronized void error(Draft draft, String text) {
        ContentValues row = new ContentValues(); row.put("last_error", text == null ? "Ошибка соединения" : text);
        getWritableDatabase().update("audits", row, "id=? AND owner=? AND state='queued'", new String[]{draft.id(), draft.owner()});
    }
    private synchronized void reject(Draft draft) {
        ContentValues row = new ContentValues(); row.put("state", "correction");
        getWritableDatabase().update("audits", row, "id=? AND owner=? AND state='queued'", new String[]{draft.id(), draft.owner()});
    }
    synchronized Draft reopenRejected(Draft draft) throws Exception {
        Template template = template(draft.owner());
        if (template == null) throw new IOException("Сначала обновите шаблон осмотра");
        JSONObject answers = new JSONObject(), photos = new JSONObject();
        for (int n=0; n<template.items().length(); n++) {
            JSONObject item = template.items().getJSONObject(n); String id = item.getString("id");
            if (!item.optString("method").equals("auto") && draft.answers().has(id)) answers.put(id,draft.answers().get(id));
        }
        for (int n=0; n<template.slots().length(); n++) {
            String id = template.slots().getJSONObject(n).getString("slot");
            if (draft.photos().has(id)) photos.put(id,draft.photos().get(id));
        }
        ContentValues row = new ContentValues(); row.put("state","draft"); row.put("answers",answers.toString()); row.put("photos",photos.toString());
        row.put("items",template.items().toString()); row.put("slots",template.slots().toString()); row.put("last_error","");
        if (getWritableDatabase().update("audits",row,"id=? AND owner=? AND state='correction'",new String[]{draft.id(),draft.owner()})!=1) throw new IOException("Состояние осмотра изменилось");
        return get(draft.id(),draft.owner());
    }

    String flush(DriverApi api) throws Exception {
        synchronized (FLUSH_LOCK) {
            SessionStore.Session session = api.session();
            if (session == null) return "Войдите для отправки осмотра";
            List<Draft> drafts = pending(session.owner());
            if (drafts.isEmpty()) return "Осмотры синхронизированы";
            JSONObject capabilities = api.get("/checklists/mobile-capabilities");
            if (!capabilities.optBoolean("idempotent_uploads")) throw new IOException("Обновите сервер DriverGuard для надёжной отправки осмотров.");
            int count = 0;
            for (Draft draft : drafts) {
                try {
                    JSONObject response = api.multipartAudit(draft);
                    if (response.optInt("id", 0) <= 0) throw new IOException("Сервер не подтвердил осмотр");
                    markSent(draft.id(), draft.owner(), response);
                    count++;
                } catch (Exception failure) {
                    error(draft, failure.getMessage());
                    if (failure instanceof DriverApi.HttpError && (((DriverApi.HttpError) failure).code == 422 || ((DriverApi.HttpError) failure).code == 409)) reject(draft);
                    throw failure;
                }
            }
            return "Передано осмотров: " + count;
        }
    }

    static Draft changed(Draft draft, JSONObject answers, JSONObject photos) {
        return new Draft(draft.id(), draft.owner(), draft.base(), answers, photos, draft.state(), draft.createdAt(), draft.result(), draft.items(), draft.slots(), draft.lastError());
    }
    private static ContentValues values(Draft draft) {
        ContentValues row = new ContentValues(); row.put("id", draft.id()); row.put("owner", draft.owner()); row.put("base", draft.base());
        row.put("answers", draft.answers().toString()); row.put("photos", draft.photos().toString()); row.put("state", draft.state()); row.put("created_at", draft.createdAt());
        row.put("result", draft.result().toString()); row.put("items", draft.items().toString()); row.put("slots", draft.slots().toString()); row.put("last_error", draft.lastError()); return row;
    }
    private static String s(Cursor cursor, String name) { return cursor.getString(cursor.getColumnIndexOrThrow(name)); }
    private static Draft read(Cursor cursor) {
        try { return new Draft(s(cursor,"id"),s(cursor,"owner"),s(cursor,"base"),new JSONObject(s(cursor,"answers")),new JSONObject(s(cursor,"photos")),s(cursor,"state"),s(cursor,"created_at"),new JSONObject(s(cursor,"result")),new JSONArray(s(cursor,"items")),new JSONArray(s(cursor,"slots")),s(cursor,"last_error")); }
        catch (JSONException invalid) { throw new IllegalStateException("Сохранённый осмотр повреждён", invalid); }
    }
}
