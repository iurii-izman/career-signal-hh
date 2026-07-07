from __future__ import annotations

import logging
import os
import random
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


class HHBudgetExceeded(HHAPIError):
    """Raised when the request budget has been exhausted."""

    pass


class HHClient:
    base_url = "https://api.hh.ru"

    def __init__(
        self,
        user_agent: str | None = None,
        timeout: int = 20,
        auth_mode: str | None = None,
        app_access_token: str | None = None,
        user_access_token: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.auth_mode = (
            (auth_mode or os.getenv("HH_AUTH_MODE", "none")).strip().lower()
        )
        self.app_access_token = (
            app_access_token
            if app_access_token is not None
            else os.getenv("HH_APP_ACCESS_TOKEN", "")
        ).strip()
        self.user_access_token = (
            user_access_token
            if user_access_token is not None
            else os.getenv("HH_USER_ACCESS_TOKEN", "")
        ).strip()
        self.user_agent = user_agent or os.getenv("HH_USER_AGENT", "CareerSignalHH/0.1")
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        if self.auth_mode in {"application_token", "user_oauth"} and self.active_token:
            self.session.headers["Authorization"] = f"Bearer {self.active_token}"

        # Rate limiting configuration
        self.delay_min = self._env_float(
            ("HH_DELAY_MIN_SECONDS", "REQUEST_DELAY_MIN"),
            "0.7",
        )
        self.delay_max = self._env_float(
            ("HH_DELAY_MAX_SECONDS", "REQUEST_DELAY_MAX"),
            "1.5",
        )
        self.cooldown_429 = float(os.getenv("HH_COOLDOWN_ON_429_SECONDS", "120"))
        self.stop_on_429 = os.getenv("HH_STOP_ON_429", "true").strip().lower() == "true"

        # Budget tracking (set via set_budget before a run)
        self.budget: dict[str, int] | None = None

        # Run statistics
        self.stats_429: int = 0
        self.stats_errors: int = 0
        self.stats_search_requests: int = 0
        self.stats_detail_requests: int = 0
        self.stats_dict_requests: int = 0
        self.stats_attempted_requests: int = 0

    @staticmethod
    def _env_float(names: tuple[str, ...], default: str) -> float:
        """Read the first non-empty env var from *names* and parse it as float."""
        for name in names:
            raw = os.getenv(name, "").strip()
            if not raw:
                continue
            try:
                return float(raw)
            except ValueError:
                break
        return float(default)

    @property
    def active_token(self) -> str:
        """Return the token relevant for the current auth mode."""
        if self.auth_mode == "user_oauth":
            return self.user_access_token
        if self.auth_mode == "application_token":
            return self.app_access_token
        return ""

    @property
    def active_token_env_name(self) -> str:
        """Return the env var name for the current auth mode token."""
        if self.auth_mode == "user_oauth":
            return "HH_USER_ACCESS_TOKEN"
        return "HH_APP_ACCESS_TOKEN"

    @property
    def active_token_present(self) -> bool:
        """Return whether the token required by the current auth mode is present."""
        return bool(self.active_token)

    def _validate_auth(self) -> None:
        if self.auth_mode == "application_token" and not self.app_access_token:
            raise HHConfigurationError(
                "HH_AUTH_MODE=application_token, но HH_APP_ACCESS_TOKEN пуст. "
                "Добавьте токен приложения в .env."
            )
        if self.auth_mode == "user_oauth":
            if not self.user_access_token:
                raise HHConfigurationError(
                    "HH_AUTH_MODE=user_oauth, но HH_USER_ACCESS_TOKEN пуст. "
                    "Добавьте OAuth токен пользователя в .env."
                )
            return
        if self.auth_mode not in {"none", "application_token", "user_oauth"}:
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

    # ------------------------------------------------------------------
    # Budget API
    # ------------------------------------------------------------------

    def set_budget(self, max_requests: int, max_details: int) -> None:
        """Configure the request budget for the upcoming search run."""
        self.budget = {
            "max_requests": max_requests,
            "max_details": max_details,
            "total": 0,
            "search": 0,
            "detail": 0,
            "dict": 0,
        }
        self.stats_429 = 0
        self.stats_errors = 0
        self.stats_search_requests = 0
        self.stats_detail_requests = 0
        self.stats_dict_requests = 0
        self.stats_attempted_requests = 0

    def can_request(self, request_type: str = "other") -> bool:
        """Check whether a request of the given type is still within budget.

        Returns True if the request is allowed, False otherwise.
        """
        if self.budget is None:
            return True
        if self.budget["total"] >= self.budget["max_requests"]:
            return False
        if (
            request_type == "detail"
            and self.budget["detail"] >= self.budget["max_details"]
        ):
            return False
        return True

    def budget_summary(self) -> dict[str, int]:
        """Return a snapshot of current budget counters."""
        if self.budget is None:
            return {
                "total": 0,
                "search": 0,
                "detail": 0,
                "dict": 0,
                "max_requests": 0,
                "max_details": 0,
            }
        return {
            "total": self.budget["total"],
            "search": self.budget["search"],
            "detail": self.budget["detail"],
            "dict": self.budget["dict"],
            "max_requests": self.budget["max_requests"],
            "max_details": self.budget["max_details"],
        }

    def _record_request(self, request_type: str) -> None:
        if self.budget is None:
            return
        self.budget["total"] += 1
        self.budget[request_type] += 1
        if request_type == "search":
            self.stats_search_requests += 1
        elif request_type == "detail":
            self.stats_detail_requests += 1
        elif request_type == "dict":
            self.stats_dict_requests += 1

    def _apply_delay(self) -> None:
        """Sleep a random interval between delay_min and delay_max seconds."""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)

    def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        request_type: str = "other",
    ) -> Any:
        self._validate_auth()

        # --- budget guard ---
        if (
            self.budget is not None
            and self.budget["total"] >= self.budget["max_requests"]
        ):
            raise HHBudgetExceeded(
                "Request budget exceeded "
                f"({self.budget['total']}/{self.budget['max_requests']} total requests)."
            )
        if (
            request_type == "detail"
            and self.budget is not None
            and self.budget["detail"] >= self.budget["max_details"]
        ):
            raise HHBudgetExceeded(
                "Detail request budget exceeded "
                f"({self.budget['detail']}/{self.budget['max_details']} detail requests)."
            )

        # --- pre-request delay ---
        self._apply_delay()

        url = f"{self.base_url}{path}"
        for attempt in range(3):
            try:
                self.stats_attempted_requests += 1
                response = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == 2:
                    self.stats_errors += 1
                    raise HHAPIError(f"HH API недоступен: {exc}") from exc
                time.sleep(1.5 * (attempt + 1))
                continue

            # --- 429 handling ---
            if response.status_code == 429:
                self.stats_429 += 1
                if self.stop_on_429:
                    raise HHAPIError(
                        "HH API вернул 429 (rate limit). Остановка согласно HH_STOP_ON_429=true.",
                        status_code=429,
                        path=path,
                    )
                if attempt == 0:
                    delay = float(
                        response.headers.get("Retry-After", self.cooldown_429)
                    )
                    LOGGER.warning("HH API rate limit (429), ожидание %.1f сек.", delay)
                    time.sleep(delay)
                    continue
                # Second 429 in a row — stop
                raise HHAPIError(
                    "HH API повторно вернул 429 (rate limit). Остановка.",
                    status_code=429,
                    path=path,
                )

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
                    token_hint = (
                        "HH_USER_ACCESS_TOKEN указан в .env, а HH_AUTH_MODE=user_oauth"
                        if self.auth_mode == "user_oauth"
                        else "HH_APP_ACCESS_TOKEN указан в .env, а HH_AUTH_MODE=application_token"
                    )
                    raise HHAuthorizationRequired(
                        "HH API вернул 403. Для доступа к этому методу может "
                        "требоваться авторизованный токен. Проверьте, что доступ "
                        "к приложению одобрен и что "
                        f"{token_hint}. "
                        f"Ответ API: {detail}",
                        status_code=403,
                        body=body,
                        path=path,
                    )
                self.stats_errors += 1
                raise HHAPIError(
                    f"HH API вернул {response.status_code} для {path}: {detail}",
                    status_code=response.status_code,
                    body=body,
                    path=path,
                )

            # --- success: record and return ---
            self._record_request(request_type)
            return response.json()

        self.stats_errors += 1
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
        return self._request(
            "/vacancies",
            dict(params) if not extra_params else params,
            request_type="search",
        )

    def get_vacancy(self, vacancy_id: str) -> dict[str, Any]:
        return self._request(f"/vacancies/{vacancy_id}", request_type="detail")

    def get_me(self) -> dict[str, Any]:
        return self._request("/me", request_type="dict")

    def get_areas(self) -> list[dict[str, Any]]:
        return self._request("/areas", request_type="dict")

    def get_dictionaries(self) -> dict[str, Any]:
        return self._request("/dictionaries", request_type="dict")

    def get_professional_roles(self) -> dict[str, Any]:
        return self._request("/professional_roles", request_type="dict")
