# Technical Design

## Architecture

Create a dedicated `TranslationConfig` window rather than keeping configuration
inside popup code. It reads editable copies of generated settings and consumes
provider metadata/validation/Test Connection through `TranslationService`.

Add one provider-neutral, read-only language-catalog accessor to
`TranslationService`. Reuse its existing labels and mapping data; do not change
HTTP transport, provider adapters, result parsing, or error redaction.

Use a captioned `WindowBase`, a native or accessibility-preserving three-item
provider selector, native Edit/DropDown controls, and themed buttons. Use small
custom dividers/icons only where they do not replace native input semantics.

## Lifecycle and State

One window exists at a time. Opening brings the window forward, then uses the
window's forced-focus helper to focus the provider selector even when Windows
foreground activation is rejected. Edits remain local until Save. Provider
switching swaps visible fields without discarding local values. Test Connection
snapshots current fields, creates a request ID, runs off the UI thread, and
applies completion only to the live matching window.

## Compatibility and Ownership

This child depends on the checked API-core contract. It adds the configuration
command through `cmd/gen-commands.ts` and generated sources. The popup child
owns removal of the old dialog implementation; the parent owns obsolete command
cleanup and final alias integration. Every intermediate unit must build.
Register the new source files in premake, MinGW, and generated Visual Studio
project lists in the same child.
