from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class HHAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: Any = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.path = path


class HHConfigurationError(HHAPIError):
    pass


class HHAuthorizationRequired(HHAPIError):
    pass


class HHClient:
    base_url = "https://api.hh.ru"

    def __init__(
        self,
        user_agent: str | None = None,
        timeout: int = 20,
        auth_mode: str | None = None,
        app_access_token: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.auth_mode = (auth_mode or os.getenv("HH_AUTH_MODE", "none")).strip().lower()
        self.app_access_token = (
            app_access_token
            if app_access_token is not None
            else os.getenv("HH_APP_ACCESS_TOKEN", "")
        ).strip()
        self.user_agent = user_agent or os.getenv(
            "HH_USER_AGENT", "CareerSignalHH/0.1"
        )
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        if self.auth_mode == "application_token" and self.app_access_token:
            self.session.headers["Authorization"] = (
                f"Bearer {self.app_access_token}"
            )

    def _validate_auth(self) -> None:
        if self.auth_mode == "application_token" and not self.app_access_token:
            raise HHConfigurationError(
                "HH_AUTH_MODE=application_token, но HH_APP_ACCESS_TOKEN пуст. "
                "Добавьте токен приложения в .env."
            )
        if self.auth_mode == "user_oauth":
            raise NotImplementedError(
                "HH_AUTH_MODE=user_oauth зарезервирован на будущее и пока не реализован."
            )
        if self.auth_mode not in {"none", "application_token"}:
            raise HHConfigurationError(
                f"Неизвестный HH_AUTH_MODE={self.auth_mode!r}. "
                "Допустимы none, application_token и user_oauth."
            )

    @staticmethod
    def _response_body(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text[:1000]

    @staticmethod
    def _body_text(body: Any) -> str:
        if isinstance(body, str):
            return body
        import json

        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._validate_auth()
        url = f"{self.base_url}{path}"
        for attempt in range(3):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == 2:
                    raise HHAPIError(f"HH API недоступен: {exc}") from exc
                time.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code == 429 and attempt < 2:
                delay = float(response.headers.get("Retry-After", 1.5 * (attempt + 1)))
                LOGGER.warning("HH API rate limit, повтор через %.1f сек.", delay)
                time.sleep(delay)
                continue
            if response.status_code >= 400:
                body = self._response_body(response)
                detail = self._body_text(body)
                if (
                    response.status_code == 400
                    and '"type":"bad_user_agent"' in detail.replace(" ", "")
                ):
                    raise HHConfigurationError(
                        "HH отклонил HH_USER_AGENT. Укажите уникальное название "
                        "приложения и реальный контакт или URL проекта в .env. "
                        f"Ответ API: {detail}",
                        status_code=400,
                        body=body,
                        path=path,
                    )
                if response.status_code == 401:
                    raise HHAuthorizationRequired(
                        "HH API вернул 401. Токен отсутствует, истёк, отозван "
                        "или неверно передан.",
                        status_code=401,
                        body=body,
                        path=path,
                    )
                if response.status_code == 403:
                    raise HHAuthorizationRequired(
                        "HH API вернул 403. Для доступа к этому методу может "
                        "требоваться токен приложения. Проверьте, что заявка "
                        "одобрена, HH_APP_ACCESS_TOKEN указан в .env, а "
                        "HH_AUTH_MODE=application_token. "
                        f"Ответ API: {detail}",
                        status_code=403,
                        body=body,
                        path=path,
                    )
                raise HHAPIError(
                    f"HH API вернул {response.status_code} для {path}: {detail}",
                    status_code=response.status_code,
                    body=body,
                    path=path,
                )
            return response.json()
        raise HHAPIError(f"HH API не ответил после повторов: {path}")

    def search_vacancies(
        self,
        text: str,
        area: str | int | None = None,
        page: int = 0,
        per_page: int = 50,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: list[tuple[str, Any]] = [
            ("text", text),
            ("page", page),
            ("per_page", per_page),
        ]
        if area is not None:
            params.append(("area", area))
        for key, value in (extra_params or {}).items():
            if isinstance(value, list):
                params.extend((key, item) for item in value)
            elif value is not None:
                params.append((key, value))
        return self._request("/vacancies", dict(params) if not extra_params else params)

    def get_vacancy(self, vacancy_id: str) -> dict[str, Any]:
        return self._request(f"/vacancies/{vacancy_id}")

    def get_me(self) -> dict[str, Any]:
        return self._request("/me")

    def get_areas(self) -> list[dict[str, Any]]:
        return self._request("/areas")

    def get_dictionaries(self) -> dict[str, Any]:
        return self._request("/dictionaries")

    def get_professional_roles(self) -> dict[str, Any]:
        return self._request("/professional_roles")
