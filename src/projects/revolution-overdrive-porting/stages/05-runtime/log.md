# Stage 05 Runtime Log

## 2026-08-07

### Plan and scope

- Stage plan: `src/projects/revolution-overdrive-porting/stages/05-runtime/plan.md`.
- Write scope honored: Stage 05 records, Stage 05 artifacts, and the approved RO launcher only.
- The global workspace pointer still names `cmre-porting`; it was not changed because this task is governed by the explicit RO project manifest and changing it would affect another workflow.

### Dependency and launcher evidence

- Approved launcher command used the official campaign mirror with `-CampaignSourceRoot` and staged `Void.SC2Campaign`, `Liberty.SC2Campaign`, and `Swarm.SC2Campaign`.
- API launcher windows on ports `18121`, `18122`, `18123`, `18124`, `18125`, and `18126` reached `ready: true` through `tools/launchers/launch-revolution-overdrive.ps1`.
- Latest launcher evidence: `artifacts/projects/revolution-overdrive-porting/stage05-runtime/launcher-runtime.json`.
- Latest launcher window: port `18126`, map `traynor01.SC2Map`, faction `Iron`, no new ScriptError files.

### Runtime probes

1. StormLib archive: `direct-run-traynor01-iron/traynor01.stage05.stormlib-direct.SC2Map`.
   `RequestPing` passed, but `RequestCreateGame` returned `MissingMap` (`error=1`).
2. `map_data` plus `map_path` variants returned the same `MissingMap` response.
3. Existing `pack_mpq.py` output was reproduced byte-for-byte from the earlier `api18119` artifact (`SHA256 C357C29E7E3634E1F3D9DABD0D61D503318A9F53F79B4C2F33D58E0503E564FB`).
4. The pack-mpq map-data path was tested through the existing runner behavior: first JoinGame returned `CannotOpenMap` (`error=6`, details `无法打开地图`), and later retries correctly reported that no game had been created.
5. Because CreateGame/JoinGame did not establish a game, no runtime claim is made for advancing frames, P1 units, faction chat, or native AI allies.

Evidence files:

- `artifacts/projects/revolution-overdrive-porting/stage05-runtime/api-stormlib-traynor01-iron-18121.json`
- `artifacts/projects/revolution-overdrive-porting/stage05-runtime/api-stormlib-traynor01-iron-18122.json`
- `artifacts/projects/revolution-overdrive-porting/stage05-runtime/api-map-path-data-18123.json`
- `artifacts/projects/revolution-overdrive-porting/stage05-runtime/api-packmpq-traynor01-iron-18124.json`
- `artifacts/projects/revolution-overdrive-porting/stage05-runtime/api-baseline-cmre-18125.json`
- `artifacts/projects/revolution-overdrive-porting/stage05-runtime/api-mapdata-joinafter-error-18126.json`
- `artifacts/projects/revolution-overdrive-porting/stage05-runtime/script-error-verdict-18126.json`

### Root cause evidence

The user-provided read-only source was compared with the owned package:

- Source: 49 files, 14,691,558 bytes.
- Owned package: 47 files, 2,746,936 bytes.
- Missing owned entries: `t3TextureMasks` (9,797,696 bytes) and `Triggers` (2,146,926 bytes).
- All common files had matching SHA-256 hashes.

Evidence: `artifacts/projects/revolution-overdrive-porting/stage05-runtime/source-owned-map-closure-traynor01.json`.

This explains the native `CannotOpenMap` result more strongly than an MPQ writer hypothesis. The missing entries are package content, so they cannot be repaired under the current Stage 05 write scope.

### Regression validation

- `python -m unittest src/projects/revolution-overdrive-porting/stages/04-ai-ally/test_ai_ally_adapter.py -v`: 5 passed.
- `python -m unittest src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_runtime_matrix.py -v`: 9 passed.
- `python -m unittest tools/cmre-webui/test_revolution_overdrive.py -v`: 2 passed; the HTTP dry-run reached the owned launcher staging path.
- `python -m unittest src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py -v`: 27 passed, 1 failed after 120.5 seconds. The failure is the pre-existing CMRE visual fallback assertion `embedded_icon_count 0 != 1`; no RO file is implicated.

### Stage conclusion

Stage 05 is verified as `blocked`, not passed. The campaign dependency staging, launcher readiness, ScriptError gate, AI contract regressions, and WebUI route are green. Native map load, commander faction runtime state, and native AI ally runtime evidence remain unverified until the owned map closure is repaired.
