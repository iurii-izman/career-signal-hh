from __future__ import annotations

import logging
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class HHAPIError(RuntimeError):
    pass


class HHClient:
    base_url = "https://api.hh.ru"

    def __init__(self, user_agent: str, timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept": "application/json"}
        )

    def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
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
            if response.status_code in {400, 403, 404, 429} or response.status_code >= 500:
                detail = response.text[:300]
                hint = ""
                if response.status_code == 403 and path.startswith("/vacancies"):
                    hint = (
                        " Поиск/получение вакансий может требовать авторизацию "
                        "приложения согласно текущей политике HH API."
                    )
                raise HHAPIError(
                    f"HH API вернул {response.status_code} для {path}: {detail}{hint}"
                )
            response.raise_for_status()
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

    def get_areas(self) -> list[dict[str, Any]]:
        return self._request("/areas")

    def get_dictionaries(self) -> dict[str, Any]:
        return self._request("/dictionaries")

    def get_professional_roles(self) -> dict[str, Any]:
        return self._request("/professional_roles")
