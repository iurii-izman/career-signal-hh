from argparse import Namespace

from rich.console import Console

from src.commands import auth
from src.hh_client import HHClient


class FakeClient:
    auth_mode = "application_token"
    app_access_token = "super-secret-token-value"
    user_agent = "TestClient/1.0"

    def get_me(self) -> dict[str, str]:
        return {"id": "1"}

    def search_vacancies(self, text: str, per_page: int) -> dict[str, object]:
        return {"items": []}


def test_auth_check_does_not_print_token(monkeypatch) -> None:
    output = Console(record=True, width=120)
    monkeypatch.setattr(auth, "console", output)
    monkeypatch.setattr(auth, "load_dotenv", lambda: None)
    monkeypatch.setattr(auth, "HHClient", FakeClient)

    assert auth.command_auth_check(Namespace()) == 0

    rendered = output.export_text()
    assert "super-secret-token-value" not in rendered
    assert "HH_APP_ACCESS_TOKEN: указан" in rendered
