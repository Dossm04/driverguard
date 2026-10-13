package kz.driverguard.offline;
import org.junit.Test;
import java.util.HashSet;
import static org.junit.Assert.*;
public class LessonCatalogTest {
    @Test public void uniqueValidatedLessons(){var ids=new HashSet<String>();for(var l:LessonCatalog.ALL){assertTrue(ids.add(l.id()));assertTrue(l.steps().size()>=3);assertTrue(l.correct()>=0&&l.correct()<l.answers().size());assertFalse(l.source().isBlank());}assertEquals(6,ids.size());}
    @Test public void unknownAssignmentHasNoSubstitute(){assertNull(LessonCatalog.title("Специальный урок компании"));}
    @Test public void knownServerAssignmentMatchesExactContent(){assertEquals("fatigue",LessonCatalog.title("Управление усталостью").id());}
    @Test public void csvPreservesJsonQuotesAndNewlines(){assertEquals("\"{\"\"ear\"\":0.2}\"",EventText.csv("{\"ear\":0.2}"));assertEquals("\"a\nb\"",EventText.csv("a\nb"));}
}
