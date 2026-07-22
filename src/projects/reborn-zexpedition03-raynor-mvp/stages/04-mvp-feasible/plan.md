# MVP Feasibility Plan

## Objective

Prove that zexpedition03 can run with TerranRaynor for a sustained smoke window without ScriptError,
while producing machine-readable commander, production, panel, and mission evidence.

## Validation

1. Acquire the repository test lock before all live SC2 changes.
2. Launch through the Reborn commander launcher and complete the readiness wait.
3. Observe RuntimeProbe for 90 seconds.
4. Fail if any ScriptError exists after the probe window.
5. Record process, mission, Raynor, production, GP panel, and log evidence.

## Stop condition

Stop when the smoke scenario passes with no ScriptError and all critical runtime assertions pass.
