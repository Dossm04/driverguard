package kz.driverguard.offline;

import android.content.Context;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.*;

/** Synchronous API: call from a background executor. Never logs credentials or response bodies. */
final class DriverApi {
    private static final Object AUTH_LOCK = new Object();
    private final SessionStore sessions;
    DriverApi(Context context) { sessions = new SessionStore(context.getApplicationContext()); }
    SessionStore.Session session() { return sessions.load(); }
    void logout() { sessions.clear(); }

    SessionStore.Session login(String rawBase, String phone, String pin) throws Exception {
        String base = SyncPolicy.base(rawBase);
        JSONObject reply = new JSONObject(exchange(base + "/auth/driver-login", "POST", null,
            new JSONObject().put("phone", LoginInput.phone(phone)).put("pin", LoginInput.pin(pin)).toString(), null));
        int id = reply.optInt("driver_id", 0);
        String token = reply.optString("access_token", "");
        if (id <= 0 || token.isBlank()) throw new IOException("У аккаунта нет профиля водителя. Обратитесь к координатору.");
        JSONObject profile = reply.optJSONObject("user");
        if (profile == null) profile = new JSONObject();
        SessionStore.Session session = new SessionStore.Session(base, SyncPolicy.owner(base, id), token, reply.optString("refresh_token", ""), profile);
        sessions.save(session);
        try { return refreshProfile(); } catch (IOException unavailable) { return session; }
    }

    SessionStore.Session refreshProfile() throws Exception {
        SessionStore.Session before = requireSession();
        JSONObject profile = get("/drivers/me");
        SessionStore.Session current = requireSession();
        if (!current.owner().equals(before.owner())) throw new SecurityException("Аккаунт изменился");
        SessionStore.Session updated = new SessionStore.Session(current.base(), current.owner(), current.accessToken(), current.refreshToken(), profile);
        sessions.replaceIfCurrent(current, updated);
        return requireSession();
    }

    JSONObject get(String path) throws Exception { return new JSONObject(request("GET", path, null)); }
    JSONArray getArray(String path) throws Exception { return new JSONArray(request("GET", path, null)); }
    JSONObject post(String path, JSONObject body) throws Exception { return new JSONObject(request("POST", path, body.toString())); }
    String request(String method, String path, String body) throws Exception {
        validatePath(path);
        SessionStore.Session session = requireSession();
        try { return ensureOwner(session, exchange(session.base() + path, method, session.accessToken(), body, null)); }
        catch (HttpError error) {
            if (error.code != 401) throw error;
            SessionStore.Session refreshed = refresh(session);
            return ensureOwner(refreshed, exchange(refreshed.base() + path, method, refreshed.accessToken(), body, null));
        }
    }

    JSONObject multipartAudit(AuditStore.Draft draft) throws Exception {
        SessionStore.Session session = requireSession();
        if (!session.owner().equals(draft.owner())) throw new SecurityException("Этот осмотр принадлежит другому аккаунту");
        try { return new JSONObject(ensureOwner(session, exchange(session.base() + "/checklists", "POST", session.accessToken(), null, draft))); }
        catch (HttpError error) {
            if (error.code != 401) throw error;
            session = refresh(session);
            return new JSONObject(ensureOwner(session, exchange(session.base() + "/checklists", "POST", session.accessToken(), null, draft)));
        }
    }

    private SessionStore.Session refresh(SessionStore.Session expected) throws Exception {
        synchronized (AUTH_LOCK) {
            SessionStore.Session current = requireSession();
            if (!current.owner().equals(expected.owner())) throw new SecurityException("Аккаунт изменился. Повторите действие.");
            if (!current.accessToken().equals(expected.accessToken())) return current;
            if (current.refreshToken().isBlank()) throw new SecurityException("Войдите снова. Данные сохранены на телефоне.");
            JSONObject reply = new JSONObject(exchange(current.base() + "/auth/refresh", "POST", null,
                new JSONObject().put("refresh_token", current.refreshToken()).toString(), null));
            String token = reply.optString("access_token", "");
            if (token.isBlank() || !SyncPolicy.owner(current.base(), reply.optInt("driver_id", 0)).equals(current.owner()))
                throw new SecurityException("Сервер не подтвердил аккаунт водителя");
            SessionStore.Session updated = new SessionStore.Session(current.base(), current.owner(), token, reply.optString("refresh_token", current.refreshToken()), current.profile());
            if (!sessions.replaceIfCurrent(current, updated)) throw new SecurityException("Аккаунт изменился. Повторите действие.");
            return updated;
        }
    }

    private String ensureOwner(SessionStore.Session expected, String result) {
        SessionStore.Session current = requireSession();
        if (!current.owner().equals(expected.owner())) throw new SecurityException("Аккаунт изменился. Данные останутся сохранёнными.");
        return result;
    }
    private SessionStore.Session requireSession() {
        SessionStore.Session session = session();
        if (session == null) throw new SecurityException("Сначала войдите в аккаунт водителя");
        return session;
    }
    private static void validatePath(String path) {
        if (path == null || !path.startsWith("/") || path.startsWith("//") || path.contains("://") || path.contains("..") || path.indexOf('\r') >= 0 || path.indexOf('\n') >= 0)
            throw new IllegalArgumentException("Неверный путь API");
    }
    static final class HttpError extends IOException {
        final int code;
        HttpError(int code, String message) { super(message); this.code = code; }
    }

    private static String exchange(String address, String method, String token, String body, AuditStore.Draft draft) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(draft == null ? 15000 : 120000);
            connection.setRequestMethod(method);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("ngrok-skip-browser-warning", "DriverGuard-Android");
            if (token != null) connection.setRequestProperty("Authorization", "Bearer " + token);
            if (draft != null) {
                String boundary = "DriverGuard" + UUID.randomUUID().toString().replace("-", "");
                connection.setDoOutput(true);
                connection.setChunkedStreamingMode(16384);
                connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
                try (OutputStream output = connection.getOutputStream()) { writeAudit(output, boundary, draft); }
            } else if (body != null) {
                byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
                connection.setDoOutput(true);
                connection.setFixedLengthStreamingMode(bytes.length);
                connection.setRequestProperty("Content-Type", "application/json");
                try (OutputStream output = connection.getOutputStream()) { output.write(bytes); }
            }
            int code = connection.getResponseCode();
            String response = readBounded(code >= 400 ? connection.getErrorStream() : connection.getInputStream());
            if (code < 200 || code >= 300) {
                String message = code == 401 ? "Срок входа истёк. Войдите снова." : "Сервер ответил " + code + ". Данные сохранены.";
                if (code == 422 || code == 409 || code == 403 || code == 429) {
                    try { Object detail = new JSONObject(response).opt("detail"); if (detail instanceof String) message = ((String) detail).substring(0, Math.min(((String) detail).length(), 350)); } catch (Exception ignored) { }
                }
                throw new HttpError(code, message);
            }
            return response;
        } finally { connection.disconnect(); }
    }
    private static String readBounded(InputStream source) throws IOException {
        if (source == null) return "";
        try (InputStream input = source; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192]; int count;
            while ((count = input.read(buffer)) >= 0) { if (output.size() + count > 2_097_152) throw new IOException("Слишком большой ответ сервера"); output.write(buffer, 0, count); }
            return output.toString(StandardCharsets.UTF_8.name());
        }
    }
    private static final Set<String> STANDARD_SLOTS = Set.of("front_lights", "rear_lights", "left_side", "right_side", "tires", "windshield", "under_engine");
    private static void writeAudit(OutputStream output, String boundary, AuditStore.Draft draft) throws Exception {
        field(output, boundary, "answers", draft.answers().toString());
        field(output, boundary, "client_uuid", draft.id());
        JSONArray extra = new JSONArray();
        Iterator<String> names = draft.photos().keys();
        List<String> ordered = new ArrayList<>();
        while (names.hasNext()) ordered.add(names.next());
        Collections.sort(ordered);
        for (String slot : ordered) if (!STANDARD_SLOTS.contains(slot)) extra.put(slot);
        field(output, boundary, "extra_slots", extra.toString());
        for (String slot : ordered) {
            File file = new File(draft.photos().getString(slot));
            if (!file.isFile() || file.length() == 0 || file.length() > 4 * 1024 * 1024) throw new IOException("Фото отсутствует или слишком большое: " + slot);
            String formName = STANDARD_SLOTS.contains(slot) ? slot : "extra";
            write(output, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + formName + "\"; filename=\"photo.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n");
            try (InputStream input = new FileInputStream(file)) { byte[] bytes = new byte[16384]; int count; while ((count = input.read(bytes)) != -1) output.write(bytes, 0, count); }
            write(output, "\r\n");
        }
        write(output, "--" + boundary + "--\r\n");
    }
    private static void field(OutputStream output, String boundary, String name, String value) throws IOException {
        write(output, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + name + "\"\r\n\r\n" + value + "\r\n");
    }
    private static void write(OutputStream output, String value) throws IOException { output.write(value.getBytes(StandardCharsets.UTF_8)); }
}
