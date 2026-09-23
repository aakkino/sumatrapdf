# Translation provider UI and docs

## Goal

Expose the new provider identities in configuration and document their endpoint status.

## Requirements

- Add canonical persisted names and clear credential requirements to the existing provider switcher.
- Preserve the official Google Cloud provider as a separate option.
- Document that `Google` and `GoogleAPI` use unofficial web endpoints whose availability and limits may change.

## Acceptance Criteria

- [ ] The provider menu independently selects all three Google options.
- [ ] Persisted names round-trip without ambiguity and existing settings remain compatible.
- [ ] User documentation distinguishes web endpoints from Cloud Translation v2.
