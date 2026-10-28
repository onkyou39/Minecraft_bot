from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import handlers.handlers as handlers

ADMIN_ID = 111


def make_update(user_id=ADMIN_ID):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()
    return update


def make_context(*args):
    return SimpleNamespace(args=list(args))


@pytest.fixture
def users():
    # Порядок вставки намеренно НЕ совпадает с порядком по ID:
    # нумерация должна идти именно по порядку вставки
    return {789: "bob", 123: "alice", 456: None}


@pytest.fixture(autouse=True)
def patched(users):
    service = MagicMock()
    service.authorized_users = users
    config = SimpleNamespace(admin_chat_id=ADMIN_ID)
    # noinspection PyUnresolvedReferences
    with patch.object(handlers, "bot_service", service), \
         patch.object(handlers, "bot_config", config):
        yield service


def reply_text(update):
    return update.message.reply_text.call_args.args[0]


# ---------- права ----------
@pytest.mark.asyncio
async def test_non_admin_denied(patched, users):
    update = make_update(user_id=999)
    await handlers.removeuser(update, make_context("1"))

    assert "Только администратор" in reply_text(update)
    assert len(users) == 3
    patched.save_auth_data.assert_not_called()


# ---------- аргументы ----------
@pytest.mark.asyncio
@pytest.mark.parametrize("args", [(), ("1", "2")])
async def test_wrong_args_count(patched, users, args):
    update = make_update()
    await handlers.removeuser(update, make_context(*args))

    assert "Использование" in reply_text(update)
    assert len(users) == 3
    patched.save_auth_data.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("arg", ["abc", "1.5", "--5", "@alice"])
async def test_non_numeric_arg(patched, users, arg):
    update = make_update()
    await handlers.removeuser(update, make_context(arg))

    assert "должен быть числом" in reply_text(update)
    assert len(users) == 3
    patched.save_auth_data.assert_not_called()


# ---------- удаление по номеру ----------
@pytest.mark.asyncio
@pytest.mark.parametrize("number, removed", [(1, 789), (2, 123), (3, 456)])
async def test_remove_by_number_uses_insertion_order(patched, users, number, removed):
    """Нумерация идёт по порядку добавления, а не по возрастанию ID."""
    update = make_update()
    await handlers.removeuser(update, make_context(str(number)))

    assert removed not in users
    assert len(users) == 2
    patched.save_auth_data.assert_called_once()


@pytest.mark.asyncio
async def test_reply_contains_id_and_username(patched, users):
    update = make_update()
    await handlers.removeuser(update, make_context("2"))

    text = reply_text(update)
    assert "123" in text and "@alice" in text


@pytest.mark.asyncio
async def test_reply_without_username(patched, users):
    update = make_update()
    await handlers.removeuser(update, make_context("3"))

    text = reply_text(update)
    assert "456" in text and "@" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("number", ["0", "4", "-1", "100"])
async def test_number_out_of_range(patched, users, number):
    update = make_update()
    await handlers.removeuser(update, make_context(number))

    assert "не найден" in reply_text(update)
    assert len(users) == 3
    patched.save_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_user_id_is_not_accepted_anymore(patched, users):
    """Удаление по ID убрано: реальный ID не должен ничего удалять."""
    update = make_update()
    await handlers.removeuser(update, make_context("123"))

    assert "не найден" in reply_text(update)
    assert 123 in users
    patched.save_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_numbering_shifts_after_removal(patched, users):
    """Фиксирует поведение: после удаления номера сдвигаются."""
    update = make_update()
    await handlers.removeuser(update, make_context("1"))
    await handlers.removeuser(update, make_context("1"))

    assert list(users) == [456]