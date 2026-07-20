from cogs.metamob import ArchMonster, _normalize_quest_slug, find_trade_opportunities


def test_find_trade_opportunities_uses_parallel_requirements():
    giver = {
        1: ArchMonster(id=1, name="Arachitik la Souffreteuse", owned=3, required=1),
        2: ArchMonster(id=2, name="Bambono le Divin", owned=2, required=2),
        3: ArchMonster(id=3, name="Champayr le Disjoncté", owned=5, required=1),
    }
    receiver = {
        1: ArchMonster(id=1, name="Arachitik la Souffreteuse", owned=0, required=1),
        2: ArchMonster(id=2, name="Bambono le Divin", owned=0, required=2),
        3: ArchMonster(id=3, name="Champayr le Disjoncté", owned=2, required=1),
    }

    opportunities = find_trade_opportunities(giver, receiver)

    assert [item.monster.id for item in opportunities] == [1]
    assert opportunities[0].giver_extra == 2
    assert opportunities[0].receiver_missing == 1


def test_find_trade_opportunities_sorts_by_name():
    giver = {
        1: ArchMonster(id=1, name="Z", owned=2, required=1),
        2: ArchMonster(id=2, name="A", owned=2, required=1),
    }
    receiver = {
        1: ArchMonster(id=1, name="Z", owned=0, required=1),
        2: ArchMonster(id=2, name="A", owned=0, required=1),
    }

    opportunities = find_trade_opportunities(giver, receiver)

    assert [item.monster.name for item in opportunities] == ["A", "Z"]


def test_normalize_quest_slug_accepts_full_url():
    assert _normalize_quest_slug("abc123") == "abc123"
    assert _normalize_quest_slug("https://www.metamob.fr/quests/abc123/") == "abc123"
