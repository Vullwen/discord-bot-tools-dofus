from config import raid_cap, raid_low_level_cap


def test_default_caps():
    assert raid_cap("Gigalodon") == 12
    assert raid_cap("Jardins Éternels") == 16


def test_unknown_returns_none():
    assert raid_cap(None) is None
    assert raid_cap("Inconnu") is None


def test_low_level_caps():
    assert raid_low_level_cap("Gigalodon") == 2
    assert raid_low_level_cap("Jardins Éternels") == 0
    assert raid_low_level_cap(None) == 0
    assert raid_low_level_cap("Inconnu") == 0
