# NOTICE — third-party and runtime references

FitLab's own source (everything under `fitlab_evaluation/`,
`fitlab_foundation/`, `examples/`, `fixtures/`, `tests/`, `scripts/`, and the
documentation) is MIT-licensed (see `LICENSE`). Provenance audit finding: all
product code is Python-standard-library-only; no third-party source was
incorporated, so no incompatible third-party source obligations exist.

The following artifacts are referenced by FitLab but are **not** part of this
repository and are **not redistributed** with it. Nothing here grants
redistribution rights for them.

| Artifact | Role | Distribution status |
|---|---|---|
| Lemonade runtime (AMD) | local OpenAI-compatible inference service used for evaluation | external; installed by the operator; never bundled |
| LiquidAI LFM2.5-1.2B-Instruct GGUF | model weights evaluated in the recorded LIVE-002 campaign | external; downloaded by the operator's runtime into its own cache; never bundled |
| llama.cpp backend | the CPU inference server Lemonade launches | external; shipped inside the Lemonade runtime; never bundled |
| Python standard library | the only code dependency of FitLab itself | PSF License (runtime, not redistributed here) |

Recorded campaign evidence (`evidence/phase-a/live-validation-001/`) was
produced on the author's machine with Lemonade 2026.43.3 executing
LFM2.5-1.2B-Instruct GGUF (Q4_K_M) through llama.cpp on CPU. The evidence
quotes the runtime's own launch metadata (with cache paths redacted to
placeholders); it contains no model data, no weights, and no runtime binaries.

"FitLab" and the Capability Passport documents produced by it are products of
this repository's authors. Runtime and model names remain the property of
their respective owners and are used here solely to describe honest
interoperability.