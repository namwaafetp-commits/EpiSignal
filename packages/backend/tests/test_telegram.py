import json
import logging
from unittest.mock import Mock

import pytest
from episignal_backend.config import Settings
from pydantic import SecretStr


def settings(**overrides: object) -> Settings:
    values = dict(
        database_url="postgresql://test:test@localhost/test",
        telegram_bot_token=SecretStr("12345:secret-token"),
        telegram_chat_id=SecretStr("-10042"),
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_send_telegram_message_uses_bounded_plain_text_https(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from episignal_backend import telegram

    connection = Mock()
    response = connection.getresponse.return_value
    response.status = 200
    response.read.return_value = b'{"ok":true}'
    factory = Mock(return_value=connection)
    monkeypatch.setattr(telegram, "HTTPSConnection", factory)
    assert (
        telegram.send_telegram_message("health report", settings=settings())
        is telegram.DeliveryResult.DELIVERED
    )
    factory.assert_called_once_with("api.telegram.org", timeout=10)
    args, kwargs = connection.request.call_args
    assert args == ("POST", "/bot12345:secret-token/sendMessage")
    body = json.loads(kwargs["body"])
    assert body == {
        "chat_id": "-10042",
        "text": "health report",
        "link_preview_options": {"is_disabled": True},
    }
    assert "parse_mode" not in body
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "status,payload",
    [
        (400, b"secret-token"),
        (429, b"limited"),
        (503, b"unavailable"),
        (200, b'{"ok":false,"description":"secret-token"}'),
        (200, b"not JSON"),
        (200, b"[]"),
    ],
)
def test_http_and_api_failures_are_sanitized(monkeypatch, caplog, status, payload):
    from episignal_backend import telegram

    connection = Mock()
    connection.getresponse.return_value.status = status
    connection.getresponse.return_value.read.return_value = payload
    monkeypatch.setattr(telegram, "HTTPSConnection", Mock(return_value=connection))
    with caplog.at_level(logging.DEBUG):
        assert (
            telegram.send_telegram_message("payload-secret", settings=settings())
            is telegram.DeliveryResult.FAILED
        )
    assert "telegram_delivery_failed" in caplog.text
    assert "secret-token" not in caplog.text
    assert "payload-secret" not in caplog.text
    assert "-10042" not in caplog.text
    assert "/bot" not in caplog.text
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("secret-token"),
        OSError("https://api.telegram.org/bot12345:secret-token/sendMessage"),
    ],
)
def test_network_failure_is_nonfatal_and_sanitized(monkeypatch, caplog, error):
    from episignal_backend import telegram

    connection = Mock()
    connection.request.side_effect = error
    monkeypatch.setattr(telegram, "HTTPSConnection", Mock(return_value=connection))
    assert (
        telegram.send_telegram_message("health", settings=settings())
        is telegram.DeliveryResult.FAILED
    )
    assert "secret-token" not in caplog.text
    assert "/bot" not in caplog.text
    connection.close.assert_called_once()


@pytest.mark.parametrize("token,chat", [("", "-10042"), ("123:secret-token", ""), (" ", " ")])
def test_missing_configuration_disables_without_network(monkeypatch, caplog, token, chat):
    from episignal_backend import telegram

    factory = Mock()
    monkeypatch.setattr(telegram, "HTTPSConnection", factory)
    with caplog.at_level(logging.INFO):
        result = telegram.send_telegram_message(
            "health", settings=settings(telegram_bot_token=token, telegram_chat_id=chat)
        )
    assert result is telegram.DeliveryResult.DISABLED
    assert "telegram_notifications_disabled" in caplog.text
    factory.assert_not_called()


def test_settings_read_prefixed_secrets_and_mask_repr(monkeypatch, tmp_path):
    monkeypatch.setenv("EPISIGNAL_TELEGRAM_BOT_TOKEN", "123:environment-secret")
    monkeypatch.setenv("EPISIGNAL_TELEGRAM_CHAT_ID", "-100999")
    path = tmp_path / "notifications.sqlite3"
    monkeypatch.setenv("EPISIGNAL_TELEGRAM_STATE_PATH", str(path))
    value = Settings(_env_file=None, database_url="postgresql://test:test@localhost/test")
    assert value.telegram_bot_token.get_secret_value() == "123:environment-secret"
    assert value.telegram_chat_id.get_secret_value() == "-100999"
    assert value.telegram_state_path == path
    assert "environment-secret" not in repr(value)
    assert "-100999" not in repr(value)


@pytest.mark.parametrize("message", ["", "\U0001f7e2" * 2049])
def test_invalid_message_length_does_not_contact_telegram(monkeypatch, message):
    from episignal_backend import telegram

    factory = Mock()
    monkeypatch.setattr(telegram, "HTTPSConnection", factory)
    assert (
        telegram.send_telegram_message(message, settings=settings())
        is telegram.DeliveryResult.FAILED
    )
    factory.assert_not_called()


def test_blank_state_path_is_unconfigured(monkeypatch):
    monkeypatch.setenv("EPISIGNAL_TELEGRAM_STATE_PATH", "")
    value = Settings(_env_file=None, database_url="postgresql://test:test@localhost/test")
    assert value.telegram_state_path is None


@pytest.mark.parametrize("path", ["notifications.sqlite3", "../state.sqlite3"])
def test_relative_state_path_is_rejected(path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="absolute"):
        settings(telegram_state_path=path)
