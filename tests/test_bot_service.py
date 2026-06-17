import services.bot_service as bot_service


def test_is_authorized_user():
    bot_service.authorized_users = {123: "test"}
    bot_service.authorized_groups = set()
    assert bot_service.is_authorized(123) is True

def test_is_authorized_group():
    bot_service.authorized_users = {}
    bot_service.authorized_groups = {-100123}

    assert bot_service.is_authorized(-100123) is True

def test_is_authorized_unknown():
    bot_service.authorized_users = {}
    bot_service.authorized_groups = set()

    assert bot_service.is_authorized(999999) is False