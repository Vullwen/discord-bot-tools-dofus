from PIL import Image

from utils.stuff_card import build_stuff_fallback_card, parse_dofusbook_url


def test_parse_private_dofusbook_url():
    link = parse_dofusbook_url(
        "https://www.dofusbook.net/fr/equipement/private/"
        "22758146-eau-air-ret-pm-dist/objets"
    )

    assert link.host == "www.dofusbook.net"
    assert link.reference == "22758146"
    assert link.label == "Eau Air Ret Pm Dist"


def test_parse_short_dofusbook_url_without_scheme():
    link = parse_dofusbook_url("d-bk.net/fr/d/1XUQs")

    assert link.url == "https://d-bk.net/fr/d/1XUQs"
    assert link.reference == "1XUQs"
    assert link.label == "Stuff 1XUQs"


def test_rejects_other_hosts():
    try:
        parse_dofusbook_url("https://example.com/stuff")
    except ValueError as exc:
        assert "dofusbook.net" in str(exc)
    else:
        raise AssertionError("invalid host should fail")


def test_build_fallback_card_is_png():
    link = parse_dofusbook_url("https://d-bk.net/fr/d/1XUQs")

    card = build_stuff_fallback_card(link, "test")

    with Image.open(card) as image:
        assert image.format == "PNG"
        assert image.size == (900, 420)
