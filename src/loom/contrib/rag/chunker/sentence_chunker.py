r"""Persian-aware sentence-boundary chunker for RAG text splitting.

Persian sentence endings:
  - U+06D4 (Arabic full stop -- rare but present)
  - . followed by space/newline (common in mixed text)
  - \\n\\n (paragraph break -- very common in Telegram posts)
  - ! ?
  - U+061F (Arabic question mark)

Strategy: split on paragraph breaks first, then on sentence-terminal
punctuation. Merge short sentences up to target_chars. Always respect
max_chars hard ceiling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..schemas.chunk import ChunkStrategy, TextChunk

if TYPE_CHECKING:
    from ..schemas.mux import MuxEntry
    from ..schemas.post import NormalizedPost

# Paragraph boundary -- two or more newlines
_PARA_SPLIT = re.compile(r"\n{2,}")

# Bullet prefix common in Telegram
_BULLET_SPLIT = re.compile(
    r"(?=\U0001f539|\U0001f538|\u2022|\u25aa|\U0001f534|\U0001f535)", re.UNICODE
)


@dataclass
class ChunkConfig:
    """Configuration for text chunking."""

    strategy: ChunkStrategy = ChunkStrategy.SENTENCE
    target_chars: int = 400  # soft target per chunk
    max_chars: int = 600  # hard ceiling
    overlap_chars: int = 50  # overlap between consecutive chunks
    min_chars: int = 20  # don't emit chunks shorter than this


def chunk_post(
    post: NormalizedPost,
    config: ChunkConfig | None = None,
) -> list[TextChunk]:
    """Split a NormalizedPost into TextChunk objects.

    Returns at least one chunk (the full text) even if < min_chars.
    """
    cfg = config or ChunkConfig()
    text = post.text_clean

    if not text.strip():
        return []

    if cfg.strategy == ChunkStrategy.WHOLE_POST:
        return [_make_chunk(post, text, 0, len(text), 0, 1, cfg)]

    # Split into candidate segments
    if cfg.strategy == ChunkStrategy.PARAGRAPH:
        segments = _para_split(text)
    elif cfg.strategy == ChunkStrategy.SENTENCE:
        segments = _sentence_split(text)
    elif cfg.strategy == ChunkStrategy.FIXED_CHAR:
        segments = _fixed_char_split(text, cfg.max_chars)
    else:
        segments = [text]

    # Merge short segments and enforce max_chars
    merged = _merge_segments(segments, cfg.target_chars, cfg.max_chars)

    # Build TextChunk objects with cumulative character position tracking
    chunks: list[TextChunk] = []
    cumulative_offset = 0
    for seg in merged:
        if len(seg.strip()) < cfg.min_chars and len(merged) > 1:
            # Still advance offset past this segment so positions stay correct
            seg_idx = text.find(seg, cumulative_offset)
            if seg_idx != -1:
                cumulative_offset = seg_idx + len(seg)
            continue

        # Locate segment in original text using cumulative offset
        seg_idx = text.find(seg, cumulative_offset)
        if seg_idx == -1:
            seg_idx = cumulative_offset  # fallback
        char_start = seg_idx
        char_end = seg_idx + len(seg)
        cumulative_offset = char_end
        chunks.append(_make_chunk(post, seg, char_start, char_end, len(chunks), -1, cfg))

    # Rebuild with correct total_chunks (Pydantic models are immutable)
    total = len(chunks)
    final: list[TextChunk] = []
    for i, chunk in enumerate(chunks):
        final.append(
            TextChunk(
                chunk_id=f"{post.global_id}:{i}",
                source_global_id=post.global_id,
                source_channel_id=post.source_channel_id,
                source_channel_name=post.source_channel_name,
                timestamp_unix=post.timestamp_unix,
                text=chunk.text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                chunk_index=i,
                total_chunks=total,
                strategy=cfg.strategy,
                overlap_chars=cfg.overlap_chars,
            )
        )

    return final


def chunk_mux_entry(entry: MuxEntry, config: ChunkConfig | None = None) -> list[TextChunk]:
    """Convenience wrapper for MuxEntry."""
    return chunk_post(entry.post, config)


# ---------------------------------------------------------------------------
# Internal splitting helpers
# ---------------------------------------------------------------------------


def _para_split(text: str) -> list[str]:
    """Split on paragraph breaks (double newlines)."""
    parts = _PARA_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _sentence_split(text: str) -> list[str]:
    """Split on paragraph breaks first, then on sentence terminals.

    Also splits on bullet markers common in Telegram.
    """
    paragraphs = _para_split(text)
    sentences: list[str] = []
    for para in paragraphs:
        # Try bullet split first
        if re.search(r"[\U0001f539\U0001f538\u2022\u25aa\U0001f534\U0001f535]", para):
            parts = _BULLET_SPLIT.split(para)
            sentences.extend(p.strip() for p in parts if p.strip())
        else:
            # Basic sentence split on terminal punctuation
            # We split and recombine to keep the delimiter
            raw = re.split(r"([.!?\u061f\u06d4])", para)
            buf = ""
            for chunk in raw:
                buf += chunk
                if chunk in ".!?\u061f\u06d4" and buf.strip():
                    sentences.append(buf.strip())
                    buf = ""
            if buf.strip():
                sentences.append(buf.strip())

    return sentences if sentences else [text]


def _fixed_char_split(text: str, max_chars: int) -> list[str]:
    """Hard split every max_chars characters."""
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _merge_segments(segments: list[str], target: int, max_chars: int) -> list[str]:
    """Merge short consecutive segments up to target; hard-split if > max_chars."""
    merged: list[str] = []
    buf = ""

    for seg in segments:
        candidate = (buf + "\n" + seg).strip() if buf else seg
        if len(candidate) <= max_chars:
            buf = candidate
            if len(buf) >= target:
                merged.append(buf)
                buf = ""
        else:
            if buf:
                merged.append(buf)
            if len(seg) > max_chars:
                # Hard split
                merged.extend(_fixed_char_split(seg, max_chars))
                buf = ""
            else:
                buf = seg

    if buf:
        merged.append(buf)

    return merged if merged else segments


def _make_chunk(
    post: NormalizedPost,
    text: str,
    char_start: int,
    char_end: int,
    index: int,
    total: int,
    cfg: ChunkConfig,
) -> TextChunk:
    return TextChunk(
        chunk_id=f"{post.global_id}:{index}",
        source_global_id=post.global_id,
        source_channel_id=post.source_channel_id,
        source_channel_name=post.source_channel_name,
        timestamp_unix=post.timestamp_unix,
        text=text,
        char_start=char_start,
        char_end=char_end,
        chunk_index=index,
        total_chunks=total,
        strategy=cfg.strategy,
        overlap_chars=cfg.overlap_chars,
    )
