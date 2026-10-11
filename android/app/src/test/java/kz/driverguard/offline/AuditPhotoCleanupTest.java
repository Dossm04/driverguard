package kz.driverguard.offline;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.UUID;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import static org.junit.Assert.*;

public class AuditPhotoCleanupTest {
    private Path root;
    @Before public void prepare() throws Exception { root = Files.createTempDirectory("audit-photo-test"); Files.createDirectory(root.resolve("audit_photos")); }
    @After public void cleanup() throws Exception {
        if (root == null) return;
        Path verified = root.toRealPath(), temporary = Path.of(System.getProperty("java.io.tmpdir")).toRealPath();
        assertEquals(temporary,verified.getParent());
        assertTrue(verified.getFileName().toString().startsWith("audit-photo-test"));
        try (var files = Files.walk(verified)) { files.sorted(java.util.Comparator.reverseOrder()).forEach(file -> { try { Files.deleteIfExists(file); } catch (Exception ignored) { } }); }
    }
    private Path photo() throws Exception { Path file = root.resolve("audit_photos").resolve(UUID.randomUUID() + ".jpg"); Files.write(file,new byte[]{1,2,3}); return file; }
    @Test public void cancelledUnreferencedPhotoIsDeleted() throws Exception {
        Path file = photo();
        assertTrue(AuditStore.deletePhotoIfUnreferenced(root.toFile(),file.toString(),Set.of(),null));
        assertFalse(Files.exists(file));
    }
    @Test public void anyStoredReferenceProtectsPhotoRegardlessOfAuditState() throws Exception {
        Path file = photo();
        assertFalse(AuditStore.deletePhotoIfUnreferenced(root.toFile(),file.toString(),Set.of(file.toString()),null));
        assertTrue(Files.exists(file));
    }
    @Test public void pendingCaptureAndCompressionSurviveRecreation() throws Exception {
        Path file = photo(), temporary = Path.of(file + ".tmp"); Files.write(temporary,new byte[]{1});
        assertFalse(AuditStore.deletePhotoIfUnreferenced(root.toFile(),file.toString(),Set.of(),file.toString()));
        assertFalse(AuditStore.deletePhotoIfUnreferenced(root.toFile(),temporary.toString(),Set.of(),file.toString()));
        assertTrue(Files.exists(file)); assertTrue(Files.exists(temporary));
    }
    @Test public void failedCompressionTemporaryFileIsRemovedAfterCaptureFinishes() throws Exception {
        Path file = photo(), temporary = Path.of(file + ".tmp"); Files.write(temporary,new byte[]{1});
        assertTrue(AuditStore.deletePhotoIfUnreferenced(root.toFile(),temporary.toString(),Set.of(file.toString()),null));
        assertTrue(Files.exists(file)); assertFalse(Files.exists(temporary));
    }
    @Test public void cleanupCannotEscapeAuditPhotoDirectory() throws Exception {
        Path outside = root.resolve(UUID.randomUUID() + ".jpg"); Files.write(outside,new byte[]{1});
        String traversal = root.resolve("audit_photos").resolve("..").resolve(outside.getFileName()).toString();
        assertFalse(AuditStore.deletePhotoIfUnreferenced(root.toFile(),traversal,Set.of(),null));
        assertTrue(Files.exists(outside));
    }
    @Test public void unrelatedFilesAreNotTreatedAsAbandonedCaptures() throws Exception {
        Path file = root.resolve("audit_photos").resolve("keep.txt"); Files.write(file,new byte[]{1});
        assertFalse(AuditStore.deletePhotoIfUnreferenced(root.toFile(),file.toString(),Set.of(),null));
        assertTrue(Files.exists(file));
    }
}
