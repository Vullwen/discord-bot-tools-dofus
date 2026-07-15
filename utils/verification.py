"""Analyse et scoring des captures de vérification Dofus."""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass

from PIL import Image, ImageOps
import pytesseract


@dataclass(frozen=True)
class VerificationResult:
    status: str
    score: int
    reasons: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return self.status == "validated"


def extract_text_from_image_bytes(data: bytes) -> str:
    """Extrait le texte d'une image avec Tesseract.

    Le pré-traitement reste volontairement léger pour supporter les thèmes Dofus
    variés sans dégrader les captures déjà lisibles.
    """
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image).convert("L")
        image = ImageOps.autocontrast(image)
        return pytesseract.image_to_string(image, lang="fra+eng")


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("’", "'")
    return " ".join(value.split())


def compact_code(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _contains(haystack: str, needle: str) -> bool:
    normalized_needle = normalize_text(needle)
    if not normalized_needle:
        return False
    return normalized_needle in haystack


def _code_present(text: str, code: str) -> bool:
    return compact_code(code) in compact_code(text)


def _has_whoami_block(text: str, character_name: str, server: str, guild_name: str) -> bool:
    character = normalize_text(character_name)
    expected_server = normalize_text(server)
    expected_guild = normalize_text(guild_name)
    normalized = normalize_text(text)
    return (
        "se trouve" in normalized
        and "serveur" in normalized
        and "guilde" in normalized
        and character in normalized
        and expected_server in normalized
        and expected_guild in normalized
    )


def _has_guild_chat_line(text: str, character_name: str, code: str) -> bool:
    character = normalize_text(character_name)
    expected_code = compact_code(code)
    for line in text.splitlines():
        normalized = normalize_text(line)
        if character not in normalized or expected_code not in compact_code(line):
            continue
        if "guilde" in normalized:
            return True
        # Dofus peut afficher le message courant sans préfixe "(Guilde)".
        # On refuse en revanche les lignes explicitement marquées groupe/équipe/etc.
        if re.search(r"\((?!guilde\))[^)]*\)", normalized):
            continue
        if re.search(rf"\b{re.escape(character)}\s*:", normalized):
            return True
    return False


def _has_time_line(text: str) -> bool:
    for line in text.splitlines():
        normalized = normalize_text(line)
        if re.search(r"\b\d{1,2}\s+[a-z]{4,}\s+6\d{2}\b", normalized):
            return True
        if re.search(r"\b\d{1,2}:\d{2}\b", normalized) and "-" in normalized:
            return True
    return False


def evaluate_ocr_text(
    text: str,
    *,
    code: str,
    character_name: str,
    server: str,
    guild_name: str,
) -> VerificationResult:
    normalized = normalize_text(text)
    reasons: list[str] = []
    score = 0

    code_ok = _code_present(text, code)
    character_ok = _contains(normalized, character_name)
    server_ok = _contains(normalized, server)
    guild_ok = _contains(normalized, guild_name)
    whoami_ok = _has_whoami_block(text, character_name, server, guild_name)
    guild_chat_ok = _has_guild_chat_line(text, character_name, code)
    time_ok = _has_time_line(text)

    checks = (
        (code_ok, 30, "code unique trouvé"),
        (character_ok, 15, "pseudo perso trouvé"),
        (server_ok, 15, "serveur trouvé"),
        (guild_ok, 20, "guilde trouvée"),
        (whoami_ok, 10, "ligne /whoami reconnue"),
        (guild_chat_ok, 15, "message avec le code reconnu"),
        (time_ok, 5, "ligne /time reconnue"),
    )
    for ok, points, reason in checks:
        if ok:
            score += points
            reasons.append(reason)

    if not code_ok:
        return VerificationResult("rejected", score, tuple(reasons + ["code absent"]))
    if character_ok and server_ok and guild_ok and guild_chat_ok and score >= 80:
        return VerificationResult("validated", score, tuple(reasons))
    return VerificationResult("needs_review", score, tuple(reasons))
