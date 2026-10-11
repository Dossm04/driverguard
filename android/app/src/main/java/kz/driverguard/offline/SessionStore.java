package kz.driverguard.offline;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** Account credentials stay encrypted in the device keystore. The PIN is never persisted. */
final class SessionStore {
    private static final Object LOCK = new Object();
    private static final String KEY = "driverguard.session.v1";
    record Session(String base, String owner, String accessToken, String refreshToken, JSONObject profile) {}
    private final SharedPreferences preferences;
    SessionStore(Context context) { preferences = context.getSharedPreferences("secure_session", Context.MODE_PRIVATE); }

    Session load() {
        synchronized (LOCK) {
            String encoded = preferences.getString("session", null);
            if (encoded == null) return null;
            try {
                JSONObject wrapper = new JSONObject(encoded);
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(wrapper.getString("iv"), Base64.NO_WRAP)));
                JSONObject value = new JSONObject(new String(cipher.doFinal(Base64.decode(wrapper.getString("data"), Base64.NO_WRAP)), StandardCharsets.UTF_8));
                return new Session(value.getString("base"), value.getString("owner"), value.getString("access"), value.optString("refresh", ""), value.optJSONObject("profile") == null ? new JSONObject() : value.getJSONObject("profile"));
            } catch (Exception unavailable) {
                // A replaced keystore or damaged credential must never expose plaintext credentials.
                return null;
            }
        }
    }

    void save(Session session) throws Exception {
        synchronized (LOCK) {
            JSONObject value = new JSONObject().put("base", session.base()).put("owner", session.owner())
                .put("access", session.accessToken()).put("refresh", session.refreshToken()).put("profile", session.profile());
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            String data = new JSONObject().put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
                .put("data", Base64.encodeToString(cipher.doFinal(value.toString().getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP)).toString();
            if (!preferences.edit().putString("session", data).commit()) throw new java.io.IOException("Не удалось сохранить вход на телефоне");
        }
    }

    boolean replaceIfCurrent(Session expected, Session updated) throws Exception {
        synchronized (LOCK) {
            Session current = load();
            if (current == null || !current.owner().equals(expected.owner()) || !current.accessToken().equals(expected.accessToken())) return false;
            save(updated);
            return true;
        }
    }

    void clear() { synchronized (LOCK) { preferences.edit().remove("session").commit(); } }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY)) return (SecretKey) store.getKey(KEY, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
        return generator.generateKey();
    }
}
