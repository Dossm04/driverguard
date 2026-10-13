package kz.driverguard.offline;
import org.junit.Test;
import static org.junit.Assert.*;
public class LoginInputTest {
    @Test public void normalizesFormattedNumber(){assertEquals("+77011234567",LoginInput.phone(" +7 (701) 123-45-67 "));}
    @Test public void supportsLocalPrefix(){assertEquals("+77011234567",LoginInput.phone("87011234567"));}
    @Test public void acceptsNonbreakingSpaces(){assertEquals("+70000000001",LoginInput.phone("+7\u00a00000000001"));}
    @Test public void preservesLeadingZeroPin(){assertEquals("002351",LoginInput.pin(" 002351 "));}
    @Test(expected=IllegalArgumentException.class) public void rejectsLetters(){LoginInput.phone("+7OOOOOOOOO1");}
    @Test(expected=IllegalArgumentException.class) public void rejectsAdminPassword(){LoginInput.pin("admin-password");}
}
