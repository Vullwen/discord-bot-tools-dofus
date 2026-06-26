from utils import names

RAIDS = ["Gigalodon", "Jardins Éternels"]


def test_exact_case_insensitive_and_accents():
    assert names.match_raid_name("Gigalodon", RAIDS) == "Gigalodon"
    assert names.match_raid_name("gigalodon", RAIDS) == "Gigalodon"
    assert names.match_raid_name("Jardins Éternels", RAIDS) == "Jardins Éternels"
    assert names.match_raid_name("JARDINS ETERNELS", RAIDS) == "Jardins Éternels"


def test_missing_accents_and_plural():
    assert names.match_raid_name("jardin eternel", RAIDS) == "Jardins Éternels"
    assert names.match_raid_name("jardins eternels", RAIDS) == "Jardins Éternels"
    assert names.match_raid_name("jardin eternell", RAIDS) == "Jardins Éternels"


def test_prefix_and_substring():
    assert names.match_raid_name("jardin", RAIDS) == "Jardins Éternels"
    assert names.match_raid_name("giga", RAIDS) == "Gigalodon"
    assert names.match_raid_name("eternel", RAIDS) == "Jardins Éternels"


def test_typo_tolerance():
    assert names.match_raid_name("gigalodn", RAIDS) == "Gigalodon"  # 1 lettre oubliée


def test_empty_and_unknown():
    assert names.match_raid_name("", RAIDS) is None
    assert names.match_raid_name("   ", RAIDS) is None
    # Trop éloigné d'un nom connu -> None
    assert names.match_raid_name("volcan cosmique", RAIDS) is None
