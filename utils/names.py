"""Matching flou de noms (pure logic, sans Discord ni DB, testable).

Permet de reconnaître un nom de raid saisi approximativement : tolère la casse,
les accents, les pluriels, les abréviations/préfixes et quelques fautes de frappe.
"""
from __future__ import annotations

import unicodedata
from typing import Optional, Sequence


def _normalize(s: str) -> str:
    """Minuscules + sans accents + espaces normalisés."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _strip_plural(token: str) -> str:
    """Retire un 's' final (pluriel français). 'jardins' -> 'jardin'."""
    return token[:-1] if len(token) > 1 and token.endswith("s") else token


def _singularize(phrase: str) -> str:
    return " ".join(_strip_plural(t) for t in phrase.split())


def _levenshtein(a: str, b: str) -> int:
    """Distance d'édition entre deux chaînes."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                prev[j] + 1,            # suppression
                cur[j - 1] + 1,         # insertion
                prev[j - 1] + (ca != cb),  # substitution
            ))
        prev = cur
    return prev[-1]


def _token_prefix_match(needle: str, haystack: str) -> bool:
    """Vrai si chaque mot de `needle` est préfixe d'un mot de `haystack`.

    "jardin" couvre "jardins", "giga" couvre "gigalodon".
    """
    needles = needle.split()
    hay = haystack.split()
    if not needles:
        return False
    return all(any(hw.startswith(nw) for hw in hay) for nw in needles)


def match_raid_name(raw: str, names: Sequence[str]) -> Optional[str]:
    """Reconnaît un nom de raid saisi approximativement -> nom canonique, ou None.

    Ordre de tolérance (du plus précis au plus permissif) :
    1. égalité normalisée (casse/accents) ;
    2. égalité après retrait des pluriels ;
    3. sous-chaîne (l'un contient l'autre) ;
    4. chaque mot de la saisie est préfixe d'un mot du nom ;
    5. distance d'édition faible (fautes de frappe).
    """
    if not raw:
        return None
    needle = _normalize(raw)
    if not needle:
        return None

    norms = [(name, _normalize(name)) for name in names]

    # 1) Égalité normalisée.
    for name, norm in norms:
        if needle == norm:
            return name

    needle_s = _singularize(needle)
    # 2) Égalité sans pluriels.
    for name, norm in norms:
        if needle_s == _singularize(norm):
            return name

    # 3) Sous-chaîne.
    for name, norm in norms:
        if len(needle) >= 3 and (needle in norm or norm in needle):
            return name

    # 4) Préfixe par mot.
    for name, norm in norms:
        if _token_prefix_match(needle, norm):
            return name

    # 5) Fautes de frappe : meilleure distance d'édition sous un seuil.
    best_name, best_dist = None, None
    for name, norm in norms:
        d = _levenshtein(needle, norm)
        if best_dist is None or d < best_dist:
            best_name, best_dist = name, d
    threshold = max(1, len(needle) // 4)
    if best_dist is not None and best_dist <= threshold:
        return best_name

    return None
