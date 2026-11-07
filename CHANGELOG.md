# Changelog

## Unreleased

- Organise Phase 1 concept-learning and Phase 2 production-behaviour tracks.
- Add learning path, explicit coverage status, and a future-domain roadmap.
- Remove verified-empty domain/configuration/evaluation/core scaffolding.
- Preserve the working sentiment application, shared utilities, CLI, data, tests,
  and historical v0.1.0 tag. No concept examples are implemented in this cleanup.

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
