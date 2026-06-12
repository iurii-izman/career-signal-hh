from src.utils import html_to_text, normalize_text, salary_to_str


def test_html_to_text_removes_tags() -> None:
    assert html_to_text("<p>Hello <b>world</b></p>") == "Hello world"


def test_salary_to_str_formats_ranges() -> None:
    assert salary_to_str(100000, 150000, "RUR") == "100 000–150 000 RUR"
    assert salary_to_str(100000, None, "RUR") == "от 100 000 RUR"
    assert salary_to_str(None, None, None) == "Не указана"


def test_normalize_text() -> None:
    assert normalize_text("  ЁЖИК\n  Python  ") == "ежик python"
