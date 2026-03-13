"""loom.contrib.rag.schemas — Pydantic models for every pipeline stage."""

from loom.contrib.rag.schemas.post import (
    ChannelBias,
    ChannelEditorProfile,
    Language,
    NormalizedPost,
)
from loom.contrib.rag.schemas.telegram import (
    RawTelegramMessage,
    ReactionCount,
    TelegramChannel,
    TelegramMediaType,
    TextEntity,
)
from loom.contrib.rag.schemas.mux import (
    MuxEntry,
    MuxedStream,
    MuxWindowConfig,
)
from loom.contrib.rag.schemas.chunk import (
    ChunkStrategy,
    TextChunk,
)
from loom.contrib.rag.schemas.analysis import (
    AnalysisBlock,
    AnalysisType,
    AnomalyFlag,
    AnomalyType,
    CorroborationMatch,
    ExtractedData,
    ExtractedDatum,
    ExtractedDataType,
    Severity,
    TrendSignal,
)
from loom.contrib.rag.schemas.embedding import (
    EmbeddedChunk,
    SimilarityResult,
)

__all__ = [
    # post
    "Language", "ChannelBias", "ChannelEditorProfile", "NormalizedPost",
    # telegram
    "TelegramMediaType", "TextEntity", "ReactionCount",
    "RawTelegramMessage", "TelegramChannel",
    # mux
    "MuxWindowConfig", "MuxEntry", "MuxedStream",
    # chunk
    "ChunkStrategy", "TextChunk",
    # analysis
    "AnalysisType", "Severity", "AnalysisBlock",
    "TrendSignal", "CorroborationMatch",
    "AnomalyType", "AnomalyFlag",
    "ExtractedDataType", "ExtractedDatum", "ExtractedData",
    # embedding
    "EmbeddedChunk", "SimilarityResult",
]
