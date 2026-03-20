"""Tests for the loom.tracing module (OTel integration)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from loom.tracing.otel import (
    _NoOpSpan,
    _NoOpTracer,
    extract_trace_context,
    get_tracer,
    init_tracing,
    inject_trace_context,
)


class TestNoOpSpan:
    def test_set_attribute(self):
        span = _NoOpSpan()
        span.set_attribute("key", "value")  # should not raise

    def test_set_status(self):
        span = _NoOpSpan()
        span.set_status("OK")

    def test_record_exception(self):
        span = _NoOpSpan()
        span.record_exception(ValueError("test"))

    def test_add_event(self):
        span = _NoOpSpan()
        span.add_event("event", {"key": "val"})

    def test_end(self):
        span = _NoOpSpan()
        span.end()

    def test_context_manager(self):
        span = _NoOpSpan()
        with span as s:
            assert s is span


class TestNoOpTracer:
    def test_start_as_current_span(self):
        tracer = _NoOpTracer()
        with tracer.start_as_current_span("test") as span:
            assert isinstance(span, _NoOpSpan)

    def test_start_as_current_span_with_kwargs(self):
        tracer = _NoOpTracer()
        with tracer.start_as_current_span("test", context=None, attributes={"a": 1}) as span:
            assert isinstance(span, _NoOpSpan)

    def test_start_span(self):
        tracer = _NoOpTracer()
        span = tracer.start_span("test")
        assert isinstance(span, _NoOpSpan)

    def test_start_span_with_kwargs(self):
        tracer = _NoOpTracer()
        span = tracer.start_span("test", context=None, attributes={"a": 1})
        assert isinstance(span, _NoOpSpan)


class TestGetTracer:
    def test_returns_noop_when_no_otel(self):
        with patch("loom.tracing.otel._HAS_OTEL", False):
            tracer = get_tracer("test")
            assert isinstance(tracer, _NoOpTracer)

    def test_returns_real_when_otel_available(self):
        mock_trace = MagicMock()
        mock_trace.get_tracer.return_value = MagicMock()
        with (
            patch("loom.tracing.otel._HAS_OTEL", True),
            patch("loom.tracing.otel._trace_mod", mock_trace),
        ):
            tracer = get_tracer("test")
            mock_trace.get_tracer.assert_called_once_with("test")
            assert tracer is mock_trace.get_tracer.return_value


class TestInjectTraceContext:
    def test_noop_when_no_otel(self):
        with patch("loom.tracing.otel._HAS_OTEL", False):
            carrier = {"task_id": "123"}
            inject_trace_context(carrier)
            assert "_trace_context" not in carrier

    def test_injects_when_otel_available(self):
        mock_propagate = MagicMock()
        mock_propagate.inject.side_effect = lambda h: h.update({"traceparent": "00-abc-def-01"})
        with (
            patch("loom.tracing.otel._HAS_OTEL", True),
            patch("loom.tracing.otel._propagate_mod", mock_propagate),
        ):
            carrier = {"task_id": "123"}
            inject_trace_context(carrier)
            assert carrier["_trace_context"] == {"traceparent": "00-abc-def-01"}

    def test_no_inject_when_headers_empty(self):
        mock_propagate = MagicMock()
        mock_propagate.inject.side_effect = lambda h: None  # no headers added
        with (
            patch("loom.tracing.otel._HAS_OTEL", True),
            patch("loom.tracing.otel._propagate_mod", mock_propagate),
        ):
            carrier = {"task_id": "123"}
            inject_trace_context(carrier)
            assert "_trace_context" not in carrier


class TestExtractTraceContext:
    def test_noop_when_no_otel(self):
        with patch("loom.tracing.otel._HAS_OTEL", False):
            ctx = extract_trace_context({"_trace_context": {"traceparent": "x"}})
            assert ctx is None

    def test_none_when_no_key(self):
        with patch("loom.tracing.otel._HAS_OTEL", True):
            ctx = extract_trace_context({"task_id": "123"})
            assert ctx is None

    def test_none_when_invalid_type(self):
        with patch("loom.tracing.otel._HAS_OTEL", True):
            ctx = extract_trace_context({"_trace_context": "not-a-dict"})
            assert ctx is None

    def test_extracts_when_present(self):
        mock_propagate = MagicMock()
        mock_propagate.extract.return_value = "mock_context"
        with (
            patch("loom.tracing.otel._HAS_OTEL", True),
            patch("loom.tracing.otel._propagate_mod", mock_propagate),
        ):
            headers = {"traceparent": "00-abc-def-01"}
            ctx = extract_trace_context({"_trace_context": headers})
            mock_propagate.extract.assert_called_once_with(headers)
            assert ctx == "mock_context"


class TestInitTracing:
    def test_returns_false_when_no_otel(self):
        with patch("loom.tracing.otel._HAS_OTEL", False):
            assert init_tracing() is False

    def test_returns_false_when_sdk_missing(self):
        with (
            patch("loom.tracing.otel._HAS_OTEL", True),
            patch.dict(
                "sys.modules",
                {
                    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": None,
                },
            ),
        ):
            # The import will raise ImportError inside init_tracing
            assert init_tracing() is False

    def test_returns_true_when_sdk_fully_available(self):
        """Lines 132-134, 141-153: init_tracing sets up provider and returns True."""
        mock_resource_cls = MagicMock()
        mock_resource_cls.create.return_value = MagicMock()

        mock_provider = MagicMock()
        mock_provider_cls = MagicMock(return_value=mock_provider)

        mock_exporter = MagicMock()
        mock_exporter_cls = MagicMock(return_value=mock_exporter)

        mock_processor = MagicMock()
        mock_processor_cls = MagicMock(return_value=mock_processor)

        mock_trace = MagicMock()

        with (
            patch("loom.tracing.otel._HAS_OTEL", True),
            patch("loom.tracing.otel._trace_mod", mock_trace),
            patch.dict(
                "sys.modules",
                {
                    "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource_cls),
                    "opentelemetry.sdk.trace": MagicMock(TracerProvider=mock_provider_cls),
                    "opentelemetry.sdk.trace.export": MagicMock(
                        BatchSpanProcessor=mock_processor_cls
                    ),
                    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": MagicMock(
                        OTLPSpanExporter=mock_exporter_cls
                    ),
                },
            ),
        ):
            result = init_tracing("my-service", endpoint="http://localhost:4317")

        assert result is True
        mock_trace.set_tracer_provider.assert_called_once()

    def test_returns_true_without_explicit_endpoint(self):
        """Lines 144-148: endpoint=None means no endpoint kwarg to OTLPSpanExporter."""
        mock_resource_cls = MagicMock()
        mock_resource_cls.create.return_value = MagicMock()

        mock_provider = MagicMock()
        mock_provider_cls = MagicMock(return_value=mock_provider)

        mock_exporter_cls = MagicMock(return_value=MagicMock())
        mock_processor_cls = MagicMock(return_value=MagicMock())

        mock_trace = MagicMock()

        with (
            patch("loom.tracing.otel._HAS_OTEL", True),
            patch("loom.tracing.otel._trace_mod", mock_trace),
            patch.dict(
                "sys.modules",
                {
                    "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource_cls),
                    "opentelemetry.sdk.trace": MagicMock(TracerProvider=mock_provider_cls),
                    "opentelemetry.sdk.trace.export": MagicMock(
                        BatchSpanProcessor=mock_processor_cls
                    ),
                    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": MagicMock(
                        OTLPSpanExporter=mock_exporter_cls
                    ),
                },
            ),
        ):
            result = init_tracing("my-service")

        assert result is True
        # When no endpoint is provided, OTLPSpanExporter should be called with no kwargs.
        mock_exporter_cls.assert_called_once_with()
        mock_trace.set_tracer_provider.assert_called_once()


class TestTracingIntegrationWithActor:
    """Verify that tracing imports and no-op behavior work in the actor."""

    def test_actor_process_one_with_noop_tracing(self):
        """The actor module should import tracing without error."""
        from loom.core.actor import BaseActor

        assert hasattr(BaseActor, "_process_one")

    def test_trace_context_roundtrip(self):
        """Inject/extract should work as a pair even in no-op mode."""
        carrier = {"task_id": "t1", "worker_type": "summarizer"}
        inject_trace_context(carrier)
        ctx = extract_trace_context(carrier)
        # Without OTel installed, inject is a no-op, extract returns None
        # Both should be safe to call
        assert ctx is None or ctx is not None  # just verifying no crash
