from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont


ALLOWED_DOFUSBOOK_HOSTS = {"dofusbook.net", "www.dofusbook.net", "d-bk.net"}


@dataclass(frozen=True)
class StuffLink:
    url: str
    host: str
    label: str
    reference: str


def parse_dofusbook_url(raw_url: str) -> StuffLink:
    value = raw_url.strip()
    if not value:
        raise ValueError("Lien Dofusbook vide.")

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host not in ALLOWED_DOFUSBOOK_HOSTS:
        raise ValueError("Le lien doit venir de dofusbook.net ou d-bk.net.")

    parts = [part for part in parsed.path.split("/") if part]
    reference = _extract_reference(host, parts)
    label = _extract_label(host, parts, reference)

    return StuffLink(url=value, host=host, label=label, reference=reference)


def _extract_reference(host: str, parts: list[str]) -> str:
    if host == "d-bk.net":
        return parts[-1] if parts else "lien court"

    for part in parts:
        if part and part[0].isdigit():
            return part.split("-", 1)[0]
    return "equipement"


def _extract_label(host: str, parts: list[str], reference: str) -> str:
    if host == "d-bk.net":
        return f"Stuff {reference}"

    for part in parts:
        if part.startswith(reference) and "-" in part:
            slug = part.split("-", 1)[1]
            words = [word for word in slug.replace("_", "-").split("-") if word]
            if words:
                return " ".join(words).title()
    return "Stuff Dofusbook"


def build_stuff_fallback_card(link: StuffLink, reason: str | None = None) -> BytesIO:
    width, height = 900, 420
    image = Image.new("RGB", (width, height), "#332f28")
    draw = ImageDraw.Draw(image)

    fonts = _load_fonts()
    title_font, label_font, body_font, small_font = fonts

    _rounded(draw, (18, 18, width - 18, height - 18), "#3f3930", "#5b5145", 8)
    _rounded(draw, (36, 36, 550, 100), "#2d2924", "#655a4b", 6)
    draw.text((54, 48), link.label, fill="#ffffff", font=title_font)
    draw.text((54, 76), f"Ref: {link.reference}", fill="#d2c3aa", font=small_font)

    _rounded(draw, (590, 36, 846, 100), "#2d2924", "#655a4b", 6)
    draw.text((612, 50), "Dofusbook", fill="#ffffff", font=label_font)
    draw.text((612, 76), link.host, fill="#d2c3aa", font=small_font)

    panels = [
        ((36, 126, 270, 320), "Stats", ["Capture auto en attente", "Stats detaillees via page", "Mode image Discord"]),
        ((296, 126, 530, 320), "Items", ["Slots du stuff", "Icones et objets", "Depuis le lien DB"]),
        ((556, 126, 790, 320), "Visuel", ["Screenshot navigateur", "Crop compact", "Fallback si bloque"]),
    ]
    for box, title, lines in panels:
        _rounded(draw, box, "#37322b", "#51483d", 8)
        draw.text((box[0] + 18, box[1] + 16), title, fill="#f2d28a", font=label_font)
        for idx, line in enumerate(lines):
            y = box[1] + 58 + idx * 34
            draw.text((box[0] + 18, y), line, fill="#ffffff", font=body_font)

    _rounded(draw, (36, 344, 846, 384), "#292620", "#655a4b", 6)
    status = reason or "Carte generee depuis le lien Dofusbook."
    draw.text((54, 354), _ellipsize(status, 94), fill="#f1eadf", font=small_font)

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def _load_fonts() -> tuple[ImageFont.ImageFont, ...]:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        return (
            ImageFont.truetype(bold_path, 24),
            ImageFont.truetype(bold_path, 18),
            ImageFont.truetype(font_path, 17),
            ImageFont.truetype(font_path, 14),
        )
    except OSError:
        fallback = ImageFont.load_default()
        return fallback, fallback, fallback, fallback


def _rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    outline: str,
    radius: int,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)


def _ellipsize(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
