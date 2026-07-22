# MVP Feasibility Log

## Runtime iterations

1. The first launch exposed missing CampaignLib dependencies and failed compilation.
2. The second launch exposed invalid map-init player context and an uninitialized runtime trigger.
3. The third launch exposed a delayed neutral-player TechTree query after readiness.
4. A later 90-second run exposed an official StarCoop achievement trigger calling the restricted
   `AchievementTermQuantitySet` native after the original observation window.
5. The Reborn adapter disabled all six offline-incompatible official achievement triggers, and the
   Galaxy checker gained restricted-achievement regression coverage.
6. Plan-mode execution then exposed duplicate `Mods/` path handling; the sync layer was normalized
   and a regression test now proves all ten effective local Mods are synchronized from source.
7. Player-1 campaign Zerg objects were removed at the map boundary for this Raynor-specific MVP,
   while the original non-Zerg mission unit remains. The adapter uses the original Lair coordinate
   as the deterministic commander base anchor.
8. The final locked launch completed readiness and a 300-second observer window with six passing
   critical assertions, no ScriptError, and a responsive SC2 process at the post-probe gate.

Each new Galaxy failure was converted into checker coverage or a launcher/runtime gate before the
next launch.

## Final observation

- SC2 remained alive and responsive through the complete 300-second observer window.
- RuntimeProbe reported `in_mission` and all six critical assertions passed.
- Raynor replacement reported `SUCCESS` with 16 Terran units and no player-1 Zerg/Protoss units.
- Raynor units, build abilities, commander upgrade, producer wiring, and GP panels were observed.
- The post-probe ScriptError scan and process-response gate both passed.
