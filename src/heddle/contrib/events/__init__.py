"""heddle.contrib.events — event-sourcing patterns on top of Heddle.

Wire-contract layer:

- :mod:`heddle.contrib.events.envelopes` — ``Event`` / ``Command`` and
  their metadata models, riding :class:`heddle.core.envelope.WireEnvelope`
  as ``events.Event`` / ``events.Command`` (wire-envelope S3a).
- :mod:`heddle.contrib.events.rejection_log` — ``Rejection``, riding
  the envelope as ``events.Rejection``.
- :mod:`heddle.contrib.events.subjects` — NATS subject + stream-name
  helpers for the event-sourcing wire contract.
- :mod:`heddle.contrib.events.issuer_conventions` — reserved
  ``issued_by`` prefixes and the framework-issuer predicate.

Also ships aggregate base classes, event/rejection logs, command
handler, dispatcher, and framework projectors.

See ``heddle-contrib-events-m2-architecture-v7.md`` for the original
plan (its concrete-aggregate/application layer was not built; the
generic framework layer described above is what shipped).
"""
