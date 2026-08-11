# conftest.py — 起义狂潮移植项目 (revolution-overdrive-porting)
#
# 治理判据（勿删）：**测试被配置静默排除 == 静默变绿**。
#
# 历史教训（2026-08-09）：Stage 09 曾走「运行时观测联盟契约」路线，向 vibe/ai_ally.py 写入
# RuntimeAllianceObservation / build_runtime_observed_ally_contract。该实现在 C-lite 收口
# (git reset --hard origin/master) 时被回退，但其未跟踪的测试文件幸存并引用了已不存在的符号，
# 导致整项目 pytest collection 崩溃。当时用 collect_ignore_glob 把它排除以恢复绿色——
# 副作用是此后每一轮门禁都"32 passed"，而没有任何信号提示 Stage 09 的守卫其实压根没跑。
#
# 现已删除该孤儿测试文件，排除列表清空。若未来再需要排除任何测试，必须同时：
#   1. 在此列出路径与理由；
#   2. 放宽下方 test_no_silent_test_exclusion 元守卫（迫使排除成为一次显式、可见的决定）。
collect_ignore_glob: list[str] = []
