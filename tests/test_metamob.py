from cogs.metamob import (
    ArchMonster,
    MonsterSearchResult,
    TradeOpportunity,
    TradeSearchMatch,
    _choice_value,
    _normalize_quest_slug,
    _search_results_content,
    _trade_content,
    adjusted_quantity,
    resolve_archmonster,
    find_trade_opportunities,
)


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


def test_choice_value_keeps_monster_id_for_autocomplete():
    monster = MonsterSearchResult(id=123, name="Arachitik la Souffreteuse")

    assert _choice_value(monster) == "123:Arachitik la Souffreteuse"


def test_resolve_archmonster_from_autocomplete_value_or_name():
    monsters = {
        123: ArchMonster(id=123, name="Arachitik la Souffreteuse", owned=1, required=1),
        456: ArchMonster(id=456, name="Bambono le Divin", owned=0, required=1),
    }

    assert resolve_archmonster("123:Arachitik la Souffreteuse", monsters).id == 123
    assert resolve_archmonster("bambono le divin", monsters).id == 456
    assert resolve_archmonster("arachitik", monsters).id == 123
    assert resolve_archmonster("inconnu", monsters) is None


def test_adjusted_quantity_stays_within_metamob_bounds():
    assert adjusted_quantity(0, -1) == 0
    assert adjusted_quantity(4, -1) == 3
    assert adjusted_quantity(4, 1) == 5
    assert adjusted_quantity(30, 1) == 30


def test_trade_content_groups_items_by_giver():
    trade = {
        "id": 9,
        "status": "open",
        "starter_id": 10,
        "target_id": 20,
    }
    items = [
        {"giver_id": 10, "monster_name": "Arachitik", "quantity": 2},
        {"giver_id": 20, "monster_name": "Bambono", "quantity": 1},
    ]

    content = _trade_content(trade, items)

    assert "Échange Metamob #9" in content
    assert "<@10> donne à <@20>" in content
    assert "Arachitik x2" in content
    assert "<@20> donne à <@10>" in content
    assert "Bambono x1" in content


def test_search_results_content_summarizes_mutual_matches():
    arachitik = ArchMonster(id=123, name="Arachitik", owned=2, required=1)
    bambono = ArchMonster(id=456, name="Bambono", owned=2, required=1)
    match = TradeSearchMatch(
        user_id=20,
        label="Ilyzaelle",
        they_give=[TradeOpportunity(monster=arachitik, giver_extra=1, receiver_missing=1)],
        you_give=[TradeOpportunity(monster=bambono, giver_extra=1, receiver_missing=1)],
    )

    content = _search_results_content([match])

    assert "Ilyzaelle" in content
    assert "a **1** archi(s) que tu cherches" in content
    assert "Tu as **1** archi(s)" in content
