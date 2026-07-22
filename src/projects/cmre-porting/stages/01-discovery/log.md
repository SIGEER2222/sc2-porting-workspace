# Stage Log: CMRE Source Discovery

## Progress

- Bound the local CMRE package to logical source ID `cmre-dev-package`; the absolute path remains in
  ignored local configuration.
- Inventoried the complete source package: 1816 files, including 450 XML, 66 Galaxy, and 344 DDS.
- Ran dependency inspection from the CMRE package root against all mission maps and core Mods.
- Scanned Galaxy entry points and Catalog file clusters to establish the next analysis boundary.

## Evidence

- `static`: the package contains 15 unpacked mission maps, one launcher map, five CMRE/ArtPack Mods,
  and no source files were modified. Evidence: `evidence/static/package-inventory.json`.
- `static`: every mission map and the launcher directly depend on `CMRE_Core_Triggers`; its resolved
  parent order is ArtPack -> Base -> Mengsk/Stetmann -> Triggers -> map. Evidence:
  `evidence/static/dependency-graph.json` and toolkit `inspect --project-root <cmre-source>`.
- `static`: `CMRE_Core_Base` is not a minimal shared base. It contains broad Catalog files plus
  `GameData/Commanders/CommanderTychus.xml` and `FutureCommanders.xml`. Evidence:
  `evidence/static/split-candidates.json`.
- `static`: `CMRE_Core_Triggers` contains 47 Galaxy files, including 3.2 MB `LibCOMI.galaxy`, 1.05 MB
  `LibCOMU.galaxy`, UI scripts, AI libraries, and commander tactical AI. Evidence:
  `evidence/static/split-candidates.json`.
- `inference`: shared mission runtime, UI/console, AI, scoring, and commander runtime are viable
  package candidates, but exact extraction order requires include and symbol-call closure.

## Changes

- `src/projects/cmre-porting/**`: project manifest, discovery evidence, stage result, issues, and handoff.
- Workspace source-binding support: prevents committed absolute machine paths.

## Problems

- Toolkit inspection only resolved sibling dependencies when `--project-root` was the CMRE package
  root; running it from the parent SC2 repository produced false unresolved sibling dependencies.
- `Void.SC2Campaign` remains unresolved inside the development package and must be resolved from an
  installed/reference data source before composition validation.
- Regex counts identify candidate boundaries but do not prove symbol-level ownership or execution.

## Handoff

The next stage can rely on the declared load order, complete top-level inventory, and known monolith
hotspots. It must build symbol-level Galaxy and Catalog ownership graphs before any SC2 content is
copied or split.
