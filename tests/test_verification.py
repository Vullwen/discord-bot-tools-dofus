from datetime import timedelta

import db
from config import now_paris
from utils.verification import evaluate_ocr_text


def test_evaluate_ocr_text_validates_expected_dofus_lines():
    text = """
    [09:41] ccpp#4778 (Vullwan) se trouve en Île de Grobe sur le serveur Dakal. Guilde [Bagarres et Belettes]
    [09:41] 15 Joullier 656 - 09:41
    [09:41] (Guilde) Vullwan:  BEB-492817
    """

    result = evaluate_ocr_text(
        text,
        code="BEB-492817",
        character_name="Vullwan",
        server="Dakal",
        guild_name="Bagarres et Belettes",
    )

    assert result.status == "validated"
    assert "code unique trouvé" in result.reasons
    assert "message avec le code reconnu" in result.reasons


def test_evaluate_ocr_text_validates_wrapped_whoami_and_plain_code_line():
    text = """
    [10:07] ccpp#4778 (Vullwan) se trouve en Île de Grobe sur le
    serveur Dakal. Guilde [Bagarres et Belettes]
    [10:07] 15 Joullier 656 - 10:07
    [10:07] Vullwan : BEB-901932
    """

    result = evaluate_ocr_text(
        text,
        code="BEB-901932",
        character_name="Vullwan",
        server="Dakal",
        guild_name="Bagarres et Belettes",
    )

    assert result.status == "validated"
    assert result.score == 110


def test_evaluate_ocr_text_needs_review_when_context_is_partial():
    text = "[09:41] (Guilde) Vullwan: BEB-492817"

    result = evaluate_ocr_text(
        text,
        code="BEB-492817",
        character_name="Vullwan",
        server="Dakal",
        guild_name="Bagarres et Belettes",
    )

    assert result.status == "needs_review"


def test_evaluate_ocr_text_rejects_missing_code():
    result = evaluate_ocr_text(
        "Vullwan se trouve sur le serveur Dakal. Guilde [Bagarres et Belettes]",
        code="BEB-492817",
        character_name="Vullwan",
        server="Dakal",
        guild_name="Bagarres et Belettes",
    )

    assert result.status == "rejected"


def test_verification_request_and_character_storage(tmp_path):
    db.reset_for_tests(str(tmp_path / "t.db"))
    request_id = db.create_verification_request(
        guild_id=2,
        discord_id=10,
        channel_id=500,
        character_name="Vullwan",
        server="Dakal",
        code="BEB-492817",
        expires_at=now_paris() + timedelta(minutes=15),
    )

    request = db.get_verification_request(request_id)
    assert request["status"] == "pending"
    assert db.get_pending_verification_for_user(guild_id=2, discord_id=10) is not None

    db.save_verified_character(
        guild_id=2,
        discord_id=10,
        character_name="Vullwan",
        server="Dakal",
        verified_by=None,
        is_main=True,
    )

    chars = db.list_user_characters(guild_id=2, discord_id=10)
    assert [(row["character_name"], row["is_main"]) for row in chars] == [("Vullwan", 1)]
    assert db.find_character(guild_id=2, character_name="vullwan")["discord_id"] == 10

    assert db.delete_user_characters(guild_id=2, discord_id=10) == 1
    assert db.list_user_characters(guild_id=2, discord_id=10) == []
    assert db.find_character(guild_id=2, character_name="Vullwan") is None
