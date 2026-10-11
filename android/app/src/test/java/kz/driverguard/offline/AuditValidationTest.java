package kz.driverguard.offline;

import org.junit.Test;
import static org.junit.Assert.*;
import org.json.*;
import java.nio.file.Files;
import java.nio.file.Path;

public class AuditValidationTest {
    private JSONArray items() throws Exception {
        return new JSONArray().put(new JSONObject().put("id","auto").put("base",true).put("method","auto"))
            .put(new JSONObject().put("id","distance").put("base",true).put("method","input"))
            .put(new JSONObject().put("id","brakes").put("base",true).put("method","answer").put("na_allowed",false))
            .put(new JSONObject().put("id","trailer").put("base",false).put("method","answer").put("na_allowed",true));
    }
    @Test public void requiredAnswersCannotBeSkippedButAutomaticItemsAreNotEntered() throws Exception {
        var missing = AuditValidation.missing(items(), new JSONArray(), new JSONObject(), new JSONObject());
        assertEquals(2,missing.size()); assertTrue(missing.contains("distance")); assertTrue(missing.contains("brakes"));
    }
    @Test public void negativeAnswerIsValidAndMustReachCoordinator() throws Exception {
        var answers = new JSONObject().put("distance","4510").put("brakes","нет");
        assertTrue(AuditValidation.missing(items(),new JSONArray(),answers,new JSONObject()).isEmpty());
    }
    @Test public void notApplicableIsAllowedOnlyByTemplate() throws Exception {
        var answers = new JSONObject().put("distance","4510").put("brakes","н-п").put("trailer","н-п");
        assertEquals(java.util.List.of("brakes"),AuditValidation.missing(items(),new JSONArray(),answers,new JSONObject()));
    }
    @Test public void customPhotoSlotsAreRequiredAndMissingFilesCannotBeQueued() throws Exception {
        var slots = new JSONArray().put(new JSONObject().put("slot","custom_cargo").put("label","Груз"));
        var missing = AuditValidation.missing(new JSONArray(),slots,new JSONObject(),new JSONObject().put("custom_cargo","does-not-exist.jpg"));
        assertEquals(java.util.List.of("Груз"),missing);
    }
    @Test public void realSavedPhotoSatisfiesSlot() throws Exception {
        Path photo = Files.createTempFile("audit-test", ".jpg");
        try {
            Files.write(photo,new byte[]{1,2,3});
            var slots = new JSONArray().put(new JSONObject().put("slot","tires").put("label","Шины"));
            assertTrue(AuditValidation.missing(new JSONArray(),slots,new JSONObject(),new JSONObject().put("tires",photo.toString())).isEmpty());
        } finally { Files.deleteIfExists(photo); }
    }
}
