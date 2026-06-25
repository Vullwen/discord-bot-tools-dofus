from config import raid_cap


def test_default_caps():
    assert raid_cap("Gigalodon") == 12
    assert raid_cap("Jardins Éternels") == 16


def test_unknown_returns_none():
    assert raid_cap(None) is None
    assert raid_cap("Inconnu") is None
