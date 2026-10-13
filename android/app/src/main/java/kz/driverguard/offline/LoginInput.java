package kz.driverguard.offline;

/** Normalize formatting only; never substitute another account or PIN. */
final class LoginInput {
    static String phone(String raw) {
        String value=raw==null?"":raw.replaceAll("[\\s\\p{Z}()\\-]", "");
        if(value.matches("8[0-9]{10}")) value="+7"+value.substring(1);
        else if(value.matches("7[0-9]{10}")) value="+"+value;
        if(!value.matches("\\+[1-9][0-9]{7,14}"))
            throw new IllegalArgumentException("Введите номер с кодом страны, например +70000000001. Без букв.");
        return value;
    }
    static String pin(String raw) {
        String value=raw==null?"":raw.strip();
        if(!value.matches("[0-9]{4,12}"))throw new IllegalArgumentException("Введите PIN из 4–12 цифр, выданный координатором.");
        return value;
    }
    static String error(Throwable error) {
        if(error instanceof java.net.UnknownHostException)return "Не найден адрес сервера. Проверьте интернет, адрес и временно отключите VPN или частный DNS для проверки.";
        if(error instanceof java.net.SocketTimeoutException)return "Сервер не ответил вовремя. Проверьте интернет и повторите вход.";
        if(error instanceof javax.net.ssl.SSLException)return "Не удалось установить защищённое соединение. Проверьте автоматические дату и время на телефоне и соединение с интернетом.";
        if(error instanceof java.net.ConnectException)return "Не удалось подключиться к серверу. Проверьте интернет и адрес сервера.";
        if(error instanceof IllegalArgumentException||error instanceof SecurityException)return error.getMessage();
        if(error instanceof DriverApi.HttpError h)return h.code==401?"Неверный номер телефона или PIN. В приложение нужен PIN водителя, а не пароль администратора.":h.getMessage();
        return "Вход не завершён ("+error.getClass().getSimpleName()+"). Проверьте интернет и повторите попытку. Сохранённые данные остаются на телефоне.";
    }
}
