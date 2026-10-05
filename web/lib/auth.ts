import { api, ApiError, setTokens } from "./api";
import { t } from "@/lib/i18n";

interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: { id: number; name: string; role: string } | null;
}

export async function login(email: string, password: string) {
  try {
    const data = await api<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setTokens(data.access_token, data.refresh_token);
    return data.user;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    // сетевые сбои браузер описывает по-английски — переводим (правило 7 CLAUDE.md)
    throw new Error(t("Сервер недоступен. Проверьте, что backend запущен на порту 8000"));
  }
}

/** Вход водителя в PWA (APP-1): телефон + PIN; токены сохраняются — «запомнить устройство». */
export async function driverLogin(phone: string, pin: string) {
  try {
    const data = await api<LoginResponse & { driver_id: number | null }>("/auth/driver-login", {
      method: "POST",
      body: JSON.stringify({ phone, pin }),
    });
    setTokens(data.access_token, data.refresh_token);
    return data.driver_id;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new Error(t("Нет связи с сервером. Проверьте интернет и попробуйте снова"));
  }
}

export function logout() {
  logoutTo("/login");
}

/** Выход с переходом на нужный экран входа (PWA водителя — /driver/login). */
export function logoutTo(to: string) {
  setTokens(null, null);
  window.location.href = to;
}
