# Formula, Assumption, and Limitation Register

All quantities use exact integer or `decimal.Decimal` values. Operations are performed through exact rational/integer arithmetic and converted to finite base-10 Decimal representations without consulting the caller's ambient Decimal precision, rounding mode, or traps. A numeric result is reproducible from the documented expression and declared inputs; that does not make the underlying idealization a physical measurement.

## `fitlab.weights.idealized_payload` — v1.0.0

Expression:

`P_total × bits_per_weight ÷ 8`

Classification: `ESTIMATED`.

Uses total parameters, including all experts for MoE. Supported weight precisions are 1, 2, 3, 4, 5, 6, 8, 16, and 32 bits. Fractional idealized bytes are preserved exactly rather than rounded.

Excludes container metadata, tensor alignment, quantization scales/zero points, tokenizer, runtime buffers, KV cache, allocator behavior, file compression, and implementation overhead. It is not GGUF size, loaded RAM, RSS, or proof of fit.

Hand fixture: `1,000 × 4 ÷ 8 = 500 bytes` exactly.

## `fitlab.kv.standard_full_cache` — v1.0.0

Expression:

`2 × L × H_kv × D_head × B_seq × S × bytes_per_KV_element`

Classification: `CALCULATED` under declared metadata.

`H_kv` is the KV-head count, not query-head count. `B_seq` is applied once. KV precision is independent of weight precision.

Supported only when the caller explicitly declares a supported decoder architecture and standard full-attention/full-cache behavior. Architecture and attention default to `UNKNOWN`. Sliding-window, MLA, paged, offloaded, other incompatible architectures, or unverified architecture return `UNKNOWN`; missing metadata also returns `UNKNOWN`.

Hand fixture: `2 × 2 × 2 × 4 × 1 × 10 × 2 = 640 bytes`. Two resident sequences yield `1,280 bytes`.

Excludes cache allocator overhead, paging metadata, alignment, and runtime-specific cache layout.

## `fitlab.compute.dense_ar_decoder_heuristic` — v1.0.0

Expression:

`approximately 2 × active_parameters FLOP/generated_token`

Classification: `ESTIMATED`.

For dense decoders, total parameters are used unless an explicit active count is declared. For MoE, `active_parameters` is mandatory. The weight formula still uses total parameters.

This simplified decode heuristic excludes prefill, full attention cost, embeddings, sampling, communication, routing overhead, training, and other runtime work. It does not predict achieved throughput.

## `fitlab.compute.target_throughput` — v1.0.0

Expression:

`decoder_FLOP_per_token × target_tokens_per_second`

Classification: `ESTIMATED`.

Target throughput is a caller-declared requirement, not an observed or predicted achievement. The operand must be the versioned `fitlab.compute.dense_ar_decoder_heuristic` result with unit `FLOP/generated_token`; byte-valued or otherwise incompatible results return `UNKNOWN`. Unknown decoder work propagates to `UNKNOWN`.

## `fitlab.bandwidth.conditional_decode` — v1.0.0

Expression:

`declared_bytes_reloaded_per_token × target_tokens_per_second`

Classification: `ESTIMATED`.

Requires both quantities and an explicit residency/cache assumption. The engine does not substitute model weight size, vendor peak bandwidth, or a hidden cache-hit ratio. It does not infer achievable throughput.

## `fitlab.memory.known_baseline` — v1.0.0

Expression:

`idealized_weight_payload + supported_standard_full_KV_cache`

Classification: `ESTIMATED`.

If either dependency is unknown, the aggregate is `UNKNOWN`. Runtime overhead stays separately `UNKNOWN`. The baseline is never a whole-system-fit result.

## `fitlab.memory.independent_physical_capacity` — v1.0.0

Expression:

`host_RAM + accelerator_dedicated_memory`

Unified shared memory is a subset of host RAM and is not added. Capacity is not measured free headroom and does not establish fit.

## Deliberately absent formulas

F1 provides no formula for runtime overhead, operating-system reserve, fragmentation, actual model-load RSS, vendor-bandwidth efficiency, achieved tokens/s, thermal behavior, power behavior, or whole-system physical feasibility. Those conclusions remain `UNKNOWN` or observations remain `UNAVAILABLE` until later stages obtain valid evidence.

An externally supplied effective-bandwidth number without a verified measurement source and definition remains `UNAVAILABLE` with `UNVERIFIED_PROVENANCE`. F1 never converts a caller-supplied number into a calculated or measured claim.
