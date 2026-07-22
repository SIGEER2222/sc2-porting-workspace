# Workspace Bootstrap Plan

## Objective

Create an independent Git repository that defines the initial tool boundary, AI constraints, Skills,
schemas, stage templates, and validation entry point without modifying existing SC2 assets.

## Inputs

- Existing SC2 workspace tool and source locations.
- User requirements for static analysis, dynamic analysis, adapter discovery, AI loops, noise control,
  external tool repositories, and stage records.

## Write scope

- The new `sc2-porting-workspace` repository only.

## Tasks

1. Initialize the repository.
2. Register external tools and source roots.
3. Define agent and package constraints.
4. Create static analysis, runtime analysis, adapter design, and development loop Skills.
5. Add project and stage schemas and templates.
6. Add a dependency-free workspace validation and project initialization command.
7. Validate the repository and Skills.

## Validation

- `node tools/workspace.mjs validate`
- Run the Skill Creator validator against all project-local Skills.
- Run and clean up a generated smoke project.

## Stop conditions

- Stop if existing maps, mods, external repositories, or parent-repository files would need mutation.
