"""Клиент backend DriverGuard: логин по email/паролю служебной учётки, повтор при 401.

Бот ходит только в существующие ручки (docs/api.md): /events, /events/{uuid}/review,
/settings/notifications, /dashboard/summary, /devices, /leaderboard, /events/{uuid}/clip-url.
"""

import logging
from typing import Any

import httpx

log = logging.getLogger("driverguard.bot.api")


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class DgApi:
    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self._client = client or httpx.AsyncClient(timeout=10)
        self._token: str | None = None
        # в compose backend зовётся http://backend:8000 — значит, мы внутри docker-сети
        self.internal_clips = (
            "://backend" in self.base_url or "://host.docker.internal" in self.base_url
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _login(self) -> None:
        try:
            resp = await self._client.post(
                f"{self.base_url}/auth/login",
                json={"email": self.email, "password": self.password},
            )
        except httpx.HTTPError as exc:  # backend недоступен — ошибка, а не падение обработчика
            raise ApiError(503, f"Backend недоступен: {exc.__class__.__name__}") from exc
        if resp.status_code != 200:
            raise ApiError(resp.status_code, _detail(resp))
        self._token = resp.json()["access_token"]

    async def request(self, method: str, path: str, *, retried: bool = False, **kw) -> Any:
        if self._token is None:
            await self._login()
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            resp = await self._client.request(
                method, f"{self.base_url}{path}", headers=headers, **kw
            )
        except httpx.HTTPError as exc:
            raise ApiError(503, f"Backend недоступен: {exc.__class__.__name__}") from exc
        if resp.status_code == 401 and not retried:
            self._token = None  # токен протух — перелогин и один повтор
            return await self.request(method, path, retried=True, **kw)
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, _detail(resp))
        return resp.json()

    async def new_events(self, ts_from: str, page_size: int = 200) -> list[dict]:
        data = await self.request(
            "GET",
            "/events",
            params={"status": "new", "ts_from": ts_from, "page_size": page_size},
        )
        return data["items"]

    async def notifications(self) -> dict:
        return (await self.request("GET", "/settings/notifications"))["value"]

    async def review(self, event_uuid: str, status: str, comment: str | None) -> dict:
        body: dict[str, Any] = {"status": status}
        if comment:
            body["comment"] = comment
        return await self.request("POST", f"/events/{event_uuid}/review", json=body)

    async def summary(self) -> dict:
        return await self.request("GET", "/dashboard/summary", params={"period": "today"})

    async def devices(self) -> list[dict]:
        return await self.request("GET", "/devices")

    async def leaderboard(self) -> dict:
        return await self.request("GET", "/leaderboard", params={"period": "7"})

    async def clip_bytes(self, event_uuid: str) -> bytes | None:
        """Кадр/клип события, если он есть и доступен; любая ошибка — просто без кадра."""
        try:
            # internal=true — presigned-ссылка на minio внутри docker-сети (localhost:9000 из
            # контейнера бота недостижим); при локальном запуске оба адреса одинаковы
            url = (
                await self.request(
                    "GET",
                    f"/events/{event_uuid}/clip-url",
                    params={"internal": self.internal_clips},
                )
            )["url"]
            resp = await self._client.get(url, timeout=8)
            if resp.status_code == 200 and resp.content:
                return resp.content
        except (ApiError, httpx.HTTPError) as exc:
            log.info("Кадр события %s недоступен: %s", event_uuid, exc)
        return None


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        if isinstance(body.get("detail"), str):
            return body["detail"]
    except ValueError:
        pass
    return f"Ошибка {resp.status_code}"
