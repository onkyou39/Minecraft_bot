from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from handlers import handlers

ADMIN_ID = 111


def make_update(user_id=ADMIN_ID, chat_type="supergroup", chat_id=-1001, title="Alpha"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.type = chat_type
    update.effective_chat.id = chat_id
    update.effective_chat.title = title
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
def groups():
    return {}


@pytest.fixture(autouse=True)
def patched(groups):
    service = MagicMock()
    service.authorized_groups = groups
    config = SimpleNamespace(admin_chat_id=ADMIN_ID)
    with patch.object(handlers, "bot_service", service), \
         patch.object(handlers, "bot_config", config):
        yield service


def reply_text(update):
    return update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_only_in_group(patched, groups):
    update = make_update(chat_type="private", chat_id=ADMIN_ID)
    await handlers.addgroup(update, SimpleNamespace(args=[]))

    assert "только в группе" in reply_text(update)
    assert groups == {}
    patched.save_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_non_admin_denied(patched, groups):
    update = make_update(user_id=999)
    await handlers.addgroup(update, SimpleNamespace(args=[]))

    assert "Только администратор" in reply_text(update)
    assert groups == {}
    patched.save_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_add_new_group_stores_title(patched, groups):
    update = make_update(chat_id=-1001, title="Alpha")
    await handlers.addgroup(update, SimpleNamespace(args=[]))

    assert groups == {-1001: "Alpha"}
    assert "успешно добавлена" in reply_text(update)
    patched.save_auth_data.assert_called_once()


@pytest.mark.asyncio
async def test_title_none_falls_back_to_id(patched, groups):
    update = make_update(chat_id=-1001, title=None)
    await handlers.addgroup(update, SimpleNamespace(args=[]))

    assert groups == {-1001: "-1001"}


@pytest.mark.asyncio
async def test_already_added_same_title(patched, groups):
    groups[-1001] = "Alpha"
    update = make_update(chat_id=-1001, title="Alpha")
    await handlers.addgroup(update, SimpleNamespace(args=[]))

    assert "уже добавлена" in reply_text(update)
    assert groups == {-1001: "Alpha"}
    patched.save_auth_data.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_placeholder_name_is_updated(patched, groups):
    """Группа из старого файла хранится с ID вместо названия."""
    groups[-1001] = "-1001"
    update = make_update(chat_id=-1001, title="Alpha")
    await handlers.addgroup(update, SimpleNamespace(args=[]))

    assert groups == {-1001: "Alpha"}
    assert "обновлено" in reply_text(update)
    patched.save_auth_data.assert_called_once()


@pytest.mark.asyncio
async def test_renamed_group_is_updated(patched, groups):
    groups[-1001] = "Old name"
    update = make_update(chat_id=-1001, title="New name")
    await handlers.addgroup(update, SimpleNamespace(args=[]))

    assert groups == {-1001: "New name"}
    patched.save_auth_data.assert_called_once()