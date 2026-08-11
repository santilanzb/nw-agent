from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TextChunk:
    index: int
    text: str


def chunk_markdown(text: str, max_chars: int = 1200, overlap_chars: int = 180) -> list[TextChunk]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current.strip())
            overlap_seed = current[-overlap_chars:].strip()
            current = overlap_seed or ""
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if len(candidate) <= max_chars:
                current = candidate
                continue

        remaining = paragraph
        while len(remaining) > max_chars:
            chunks.append(remaining[:max_chars].strip())
            remaining = remaining[max_chars - overlap_chars :].strip()
        current = remaining

    if current:
        chunks.append(current.strip())

    return [TextChunk(index=index, text=chunk) for index, chunk in enumerate(chunks)]

