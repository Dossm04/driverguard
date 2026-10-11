package kz.driverguard.offline;

import java.io.File;
import java.util.ArrayList;
import java.util.List;
import org.json.*;

final class AuditValidation {
    private AuditValidation() {}
    static List<String> missing(JSONArray items, JSONArray slots, JSONObject answers, JSONObject photos) throws JSONException {
        List<String> missing = new ArrayList<>();
        for (int n = 0; n < items.length(); n++) {
            JSONObject item = items.getJSONObject(n);
            String id = item.getString("id"), method = item.optString("method", "answer");
            if (method.equals("auto")) continue;
            String answer = answers.optString(id, "").trim();
            if (answer.isEmpty()) { if (item.optBoolean("base")) missing.add(id); continue; }
            if (!method.equals("input") && !answer.equals("да") && !answer.equals("нет") && !(answer.equals("н-п") && item.optBoolean("na_allowed"))) missing.add(id);
        }
        for (int n = 0; n < slots.length(); n++) {
            JSONObject slot = slots.getJSONObject(n);
            String path = photos.optString(slot.getString("slot"), "");
            File file = new File(path);
            if (path.isBlank() || !file.isFile() || file.length() == 0 || file.length() > 4 * 1024 * 1024) missing.add(slot.optString("label", slot.getString("slot")));
        }
        return missing;
    }
}
