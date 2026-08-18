# Stage50 Tactical Report v1

- schema_version: `tactical_report.v1`
- scenario_id: `Stage50-timing-push-setback`
- scenario_version: `2f23732c66656ab8`
- run_mode: `seed_batch`
- seeds: `[42, 43, 44]`
- strategy_a: `aggressive_timing_push` success_rate=1.0
- strategy_b: `delayed_defensive_baseline` success_rate=1.0
- confidence: `low`
- result_reliability: `degraded`
- compare_rule: 先按 success_rate 分组，仅在双方均成功的样本内比较 completion_time；若成功率不同，先报告成功率差异，不直接比较时间
- determinism: `True`
