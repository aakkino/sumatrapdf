# Backend Development Guidelines

This directory is intentionally project-neutral. The bootstrap-guidelines task
must replace these placeholders with conventions derived from the target
project before backend implementation begins.

## Pre-Development Checklist

- Inspect the target repository and its existing convention documents.
- Replace each generic guide below with evidence-backed project rules.
- Keep Harness-owned contracts in `harness-migration.md` and
  `model-routing-and-dispatch.md` intact.

## Guides

| Guide                                                         | Bootstrap question                                    |
| ------------------------------------------------------------- | ----------------------------------------------------- |
| [Directory Structure](./directory-structure.md)               | Where do backend modules, services, and routes live?  |
| [Database Guidelines](./database-guidelines.md)               | What persistence and migration conventions exist?     |
| [Error Handling](./error-handling.md)                         | How are failures represented and propagated?          |
| [Logging Guidelines](./logging-guidelines.md)                 | What may be logged, at which levels, and where?       |
| [Quality Guidelines](./quality-guidelines.md)                 | Which checks and review rules are required?           |
| [Native Translation Service](./translation-service.md)        | Native provider-neutral translation contract          |
| [Model Routing And Dispatch](./model-routing-and-dispatch.md) | Harness-owned Trellis dispatch contract               |
| [Harness Migration](./harness-migration.md)                   | Harness-owned migration contract                      |
| [Windows Build](./windows-build.md)                           | How MSVC and the Windows SDK compile base code safely |
