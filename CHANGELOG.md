# Changelog

## Unreleased

- Complete the five-category Phase 2 reference implementation with policy routing
  connected to persistent jobs, exact-action approvals, resumed workers, and verified reviews.
- Add an optional Ollama inference adapter and explicit deterministic fixture mode.
- Preserve existing jobs and reviews through additive migration 006.
- Add end-to-end approval/rejection/no-match examples and failure-path integration checks.
- Configure deployed smoke tests and CI for sentiment and policy workflows.

- Organise Phase 1 concept-learning and Phase 2 production-behaviour tracks.
- Add learning path, explicit coverage status, and a future-domain roadmap.
- Remove verified-empty domain/configuration/evaluation/core scaffolding.
- Preserve the working sentiment application, shared utilities, CLI, data, tests,
  and historical v0.1.0 tag. The cleanup preserved the historical application; the concept track now contains 15 exercises.

## 0.1.0 — 2026-11-06

First sentiment-focused release.

- Shared agent contracts, bounded orchestration, and action verification.
- ML training interface, CSV/JSONL loading, seeded splits, classification metrics,
  and model-independent artifact persistence.
- Sentiment lexicon baseline and TF-IDF/logistic regression training/inference.
- Explicit neutral and uncertain behaviour with verifiable in-memory feedback actions.
- Validation comparison, optional final test evaluation, and trusted model save/load.
- Unified run/train/evaluate CLI with module and console entry points.
- Setup/architecture/evaluation documentation, complete test discovery, package
  builds, and clean wheel smoke checks configured in CI.

The other five agents remain planned. Synthetic data is demonstration-only; no
production accuracy, calibration, persistent review queue, or deployment is claimed.
