"""
Golden replay test corpus.

This package contains recorded trading sessions used for:
- Regression testing
- Determinism verification
- Performance benchmarking

Each session directory contains:
- events.jsonl: Recorded EventEnvelope messages
- expected_decisions.jsonl: Expected DecisionRecord outputs
- metadata.json: Session metadata and configuration
"""
