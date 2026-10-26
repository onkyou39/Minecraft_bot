from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import handlers.handlers as handlers


ADMIN_ID = 111


def make_update(user_id=ADMIN_ID, chat_type="private", chat_id=ADMIN_ID):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.type = chat_type
    update.effective_chat.id = chat_id
    update.effective_message.reply_text = AsyncMock()
    return update


def make_context(*args):
    return SimpleNamespace(args=list(args))


@pytest.fixture
def groups():
    return {-1001: "Alpha", -1002: "Beta", -1003: "Gamma"}


@pytest.fixture(autouse=True)
def patched(groups):
    service = MagicMock()
    service.authorized_groups = groups
    config = SimpleNamespace(admin_chat_id=ADMIN_ID)
    # noinspection PyUnresolvedReferences
    with patch.object(handlers, "bot_service", service), \
         patch.object(handlers, "bot_config", config):
        yield service


def reply_text(update):
    return update.effective_message.reply_text.call_args.args[0]


# ---------- права ----------
@pytest.mark.asyncio
async def test_non_admin_denied(patched, groups):
    update = make_update(user_id=999)
    await handlers.removegroup(update, make_context())

    assert "Только администратор" in reply_text(update)
    assert len(groups) == 3
    patched.save_auth_data.assert_not_called()


# ---------- удаление текущей группы ----------
@pytest.mark.asyncio
async def test_remove_current_group(patched, groups):
    update = make_update(chat_type="supergroup", chat_id=-1002)
    await handlers.removegroup(update, make_context())

    assert -1002 not in groups
    assert "Beta" in reply_text(update)
    patched.save_auth_data.assert_called_once()

@pytest.mark.asyncio
async def test_current_group_not_in_list(patched, groups):
    update = make_update(chat_type="group", chat_id=-9999)
    await handlers.removegroup(update, make_context())

    assert "не была в списке" in reply_text(update)
    assert len(groups) == 3
    patched.save_auth_data.assert_not_called()

@pytest.mark.asyncio
async def test_group_with_args_shows_usage(patched, groups):
    update = make_update(chat_type="group", chat_id=-1002)
    await handlers.removegroup(update, make_context("1"))

    assert "Используйте" in reply_text(update)
    assert len(groups) == 3
    patched.save_auth_data.assert_not_called()


# ---------- личка: ввод ----------
@pytest.mark.asyncio
async def test_private_without_args_shows_usage(patched, groups):
    update = make_update()
    await handlers.removegroup(update, make_context())

    assert "Использование" in reply_text(update)
    assert len(groups) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("arg", ["abc", "--5", "1.5", ""])
async def test_non_numeric_arg(patched, groups, arg):
    update = make_update()
    await handlers.removegroup(update, make_context(arg))

    assert "должны быть числом" in reply_text(update)
    assert len(groups) == 3
    patched.save_auth_data.assert_not_called()



# ---------- личка: удаление по ID ----------
@pytest.mark.asyncio
async def test_remove_by_id(patched, groups):
    update = make_update()
    await handlers.removegroup(update, make_context("-1003"))

    assert -1003 not in groups
    assert "Gamma" in reply_text(update)
    patched.save_auth_data.assert_called_once()


@pytest.mark.asyncio
async def test_remove_by_unknown_id(patched, groups):
    update = make_update()
    await handlers.removegroup(update, make_context("-5555"))

    assert "не найдена" in reply_text(update)
    assert len(groups) == 3
    patched.save_auth_data.assert_not_called()



# ---------- личка: удаление по номеру ----------
@pytest.mark.asyncio
@pytest.mark.parametrize("number, removed", [(1, -1001), (2, -1002), (3, -1003)])
async def test_remove_by_number(patched, groups, number, removed):
    update = make_update()
    await handlers.removegroup(update, make_context(str(number)))

    assert removed not in groups
    assert len(groups) == 2
    patched.save_auth_data.assert_called_once()



@pytest.mark.asyncio
@pytest.mark.parametrize("number", ["0", "4", "100"])
async def test_number_out_of_range(patched, groups, number):
    update = make_update()
    await handlers.removegroup(update, make_context(number))

    assert "не найдена" in reply_text(update)
    assert len(groups) == 3
    patched.save_auth_data.assert_not_called()



@pytest.mark.asyncio
async def test_numbering_shifts_after_removal(patched, groups):
    """Фиксирует поведение: после удаления номера сдвигаются."""
    update = make_update()
    await handlers.removegroup(update, make_context("1"))
    await handlers.removegroup(update, make_context("1"))

    assert list(groups) == [-1003]