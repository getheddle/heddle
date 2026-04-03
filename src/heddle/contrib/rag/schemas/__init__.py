"""heddle.contrib.rag.schemas — Pydantic models for every pipeline stage."""

from heddle.contrib.rag.schemas.analysis import (
    AnalysisBlock,
    AnalysisType,
    AnomalyFlag,
    AnomalyType,
    CorroborationMatch,
    ExtractedData,
    ExtractedDataType,
    ExtractedDatum,
    Severity,
    TrendSignal,
)
from heddle.contrib.rag.schemas.chunk import (
    ChunkStrategy,
    TextChunk,
)
from heddle.contrib.rag.schemas.embedding import (
    EmbeddedChunk,
    SimilarityResult,
)
from heddle.contrib.rag.schemas.mux import (
    MuxedStream,
    MuxEntry,
    MuxWindowConfig,
)
from heddle.contrib.rag.schemas.post import (
    ChannelBias,
    ChannelEditorProfile,
    Language,
    NormalizedPost,
)
from heddle.contrib.rag.schemas.telegram import (
    RawTelegramMessage,
    ReactionCount,
    TelegramChannel,
    TelegramMediaType,
    TextEntity,
)

__all__ = [
    "AnalysisBlock",
    # analysis
    "AnalysisType",
    "AnomalyFlag",
    "AnomalyType",
    "ChannelBias",
    "ChannelEditorProfile",
    # chunk
    "ChunkStrategy",
    "CorroborationMatch",
    # embedding
    "EmbeddedChunk",
    "ExtractedData",
    "ExtractedDataType",
    "ExtractedDatum",
    # post
    "Language",
    "MuxEntry",
    # mux
    "MuxWindowConfig",
    "MuxedStream",
    "NormalizedPost",
    "RawTelegramMessage",
    "ReactionCount",
    "Severity",
    "SimilarityResult",
    "TelegramChannel",
    # telegram
    "TelegramMediaType",
    "TextChunk",
    "TextEntity",
    "TrendSignal",
]
