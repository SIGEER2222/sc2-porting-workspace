# conftest.py — 起义狂潮移植项目 (revolution-overdrive-porting)
#
# Stage 09 (stages/09-ai-ally-runtime-retry) 是一次探索性延续，尝试用 *运行时观测*
# 联盟契约去补证 RO-AI-001 的 18 条 residual。该思路已被显式废弃，改为「根因钉死 +
# 审计闭环」方案（RO-AI-001：182 进合约 + 18 fail-closed = runtime_leader_identity，
# 静态不可约，运行时观测无法补证）。
#
# 其写入 vibe/ai_ally.py 的实现在 C-lite 历史收口（git reset --hard origin/master）时被
# 回退，但此未追踪测试文件幸存，且引用已不存在的符号，导致整项目 pytest collection 崩溃。
#
# 保留该文件留档，但将其排除出自动 collection，使正当的 Stage 04/08 回归套件保持绿色且诚实。
collect_ignore_glob = [
    "stages/09-ai-ally-runtime-retry/test_runtime_observed_contract.py",
]
