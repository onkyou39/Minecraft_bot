"""Контракт между bot_service (хранилище) и хендлерами /authorized, /removeuser, /removegroup.

Целевой контракт:
- load_auth_data() -> (users: dict[int, str | None], groups: dict[int, str])
- ключи обоих словарей — int;
- порядок записей сохраняется (на нём держится нумерация);
- названия групп и username=None переживают save -> load;
- удаление (pop + save_auth_data) не откатывается после перезагрузки;
- старый файл, где "groups" — список ID, продолжает читаться.

"""
import json
from types import SimpleNamespace

import pytest

from services import bot_service

USERS = {789: "bob", 123: "alice", 456: None}
# Порядок вставки намеренно не совпадает с порядком по ID
GROUPS = {-1003: "Группа Gamma", -1001: "Alpha", -1002: "Beta"}


@pytest.fixture
def auth_file(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    # noinspection PyUnresolvedReferences
    monkeypatch.setattr(
        bot_service, "bot_config", SimpleNamespace(authorized_file=str(path))
    )
    return path


def save_state(monkeypatch, users, groups):
    monkeypatch.setattr(bot_service, "authorized_users", dict(users))
    monkeypatch.setattr(bot_service, "authorized_groups", dict(groups))
    bot_service.save_auth_data()


@pytest.fixture
def populated(auth_file, monkeypatch):
    save_state(monkeypatch, USERS, GROUPS)
    return auth_file


# ---------- круг save -> load ----------

def test_roundtrip_users(populated):
    users, _ = bot_service.load_auth_data()

    assert users == USERS


def test_roundtrip_groups_keep_names(populated):
    _, groups = bot_service.load_auth_data()

    assert groups == GROUPS


def test_groups_is_dict_not_set(populated):
    """Хендлеры делают authorized_groups.pop(id) -> name и .items()."""
    _, groups = bot_service.load_auth_data()

    assert isinstance(groups, dict)


def test_keys_are_int(populated):
    users, groups = bot_service.load_auth_data()

    assert all(isinstance(k, int) for k in users)
    assert all(isinstance(k, int) for k in groups)


def test_order_is_preserved(populated):
    """Нумерация в /authorized и /remove* идёт по порядку словаря."""
    users, groups = bot_service.load_auth_data()

    assert list(users) == [789, 123, 456]
    assert list(groups) == [-1003, -1001, -1002]


def test_none_username_survives(populated):
    users, _ = bot_service.load_auth_data()

    assert users[456] is None


def test_numbering_is_stable_across_restart(populated):
    first = bot_service.load_auth_data()
    second = bot_service.load_auth_data()

    assert [list(d.items()) for d in first] == [list(d.items()) for d in second]


# ---------- удаление ----------

def test_removal_is_persisted(populated, monkeypatch):
    """То, что делают removeuser/removegroup: pop + save_auth_data."""
    users, groups = bot_service.load_auth_data()
    users.pop(123)
    groups.pop(-1001)
    save_state(monkeypatch, users, groups)

    users, groups = bot_service.load_auth_data()

    assert list(users) == [789, 456]
    assert list(groups) == [-1003, -1002]
    assert groups[-1003] == "Группа Gamma"


# ---------- совместимость и ошибки ----------

def test_legacy_file_with_group_ids_list(auth_file):
    """Старый формат: "groups": [id, id, ...] без названий."""
    auth_file.write_text(
        json.dumps(
            {
                "users": [{"id": 1, "username": "alice"}],
                "groups": [-1002, -1001],
            }
        ),
        encoding="utf-8",
    )

    users, groups = bot_service.load_auth_data()

    assert users == {1: "alice"}
    assert list(groups) == [-1002, -1001]
    # Название для старых записей — любая строка (решите, какая: "" или str(id))
    assert all(isinstance(name, str) for name in groups.values())


def test_missing_file_gives_empty_state(auth_file):
    users, groups = bot_service.load_auth_data()

    assert users == {}
    assert groups == {}


def test_corrupted_file_gives_empty_state(auth_file):
    auth_file.write_text("{not json", encoding="utf-8")

    users, groups = bot_service.load_auth_data()

    assert users == {}
    assert groups == {}