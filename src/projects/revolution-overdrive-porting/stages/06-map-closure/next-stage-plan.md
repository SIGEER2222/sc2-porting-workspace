# Next Stage Plan: Commander Closure

Stage 07 will compare the source Revolution Overdrive Mod and all declared dependency Mods with
the owned commander package plus the existing `assets/` mirror. It will copy or stage only source
files whose hashes match, fail on changed common files, and then rerun the approved native MVP.

The asset mirror is an existing local repository input and remains unmodified. Native runtime
claims still require CreateGame/JoinGame, advancing frames, observations, and a same-window
ScriptError verdict.
