import logging

import pytest
from pydantic import SecretStr, ValidationError

from opensource_scout.config import Settings
from opensource_scout.logging import JsonFormatter, RedactionFilter, redact


def test_secret_values_never_appear_in_repr() -> None:
    settings = Settings(
        GITHUB_TOKEN=SecretStr("ghp_" + "a" * 36),
        OPENAI_API_KEY=SecretStr("sk-" + "b" * 40),
    )
    rendered = repr(settings)
    assert "ghp_" not in rendered
    assert "sk-" not in rendered


def test_secret_values_are_recoverable_at_point_of_use() -> None:
    token = "ghp_" + "a" * 36
    settings = Settings(GITHUB_TOKEN=SecretStr(token))
    assert settings.github_token_value() == token


def test_missing_secrets_return_none() -> None:
    settings = Settings(GITHUB_TOKEN=None, OPENAI_API_KEY=None)
    assert settings.github_token_value() is None
    assert settings.openai_api_key_value() is None


def test_negative_concurrency_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(GITHUB_CONCURRENCY=0)


def test_negative_budget_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(DAILY_OPENAI_BUDGET_USD=-1.0)


def test_database_url_derives_from_data_dir(tmp_path) -> None:  # noqa: ANN001
    settings = Settings(OSS_DATA_DIR=tmp_path)
    assert settings.database_path == tmp_path / "opensource_scout.db"
    assert str(settings.database_path) in settings.database_url


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_" + "a" * 36,
        "github_pat_" + "b" * 30,
        "sk-" + "c" * 40,
    ],
)
def test_redact_scrubs_known_secret_shapes(secret: str) -> None:
    text = f"using token {secret} for the request"
    assert secret not in redact(text)


def test_redact_scrubs_bearer_header_but_keeps_prefix() -> None:
    text = "Authorization: Bearer ghp_" + "d" * 36
    result = redact(text)
    assert "ghp_" not in result
    assert result.startswith("Authorization: Bearer ")


def test_redact_is_a_noop_on_ordinary_text() -> None:
    text = "this log line has no secrets in it"
    assert redact(text) == text


def test_redaction_filter_scrubs_percent_style_log_args() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token is %s",
        args=("ghp_" + "e" * 36,),
        exc_info=None,
    )
    assert RedactionFilter().filter(record) is True
    assert "ghp_" not in record.msg
    assert record.args is None


def test_json_formatter_produces_valid_json_line() -> None:
    import json

    record = logging.LogRecord(
        name="opensource_scout.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=None,
        exc_info=None,
    )
    line = JsonFormatter().format(record)
    payload = json.loads(line)
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
