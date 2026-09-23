# Technical Design

## Architecture

TranslationConfig owns provider labels, visibility, persistence, and configuration tests; service code owns network behavior.

## Lifecycle and State

The provider catalog drives the menu and selected configuration group; canonical names round-trip through the existing setting.

## Compatibility and Ownership

Google and GoogleAPI share the Google configuration group but retain distinct canonical provider names and no-key behavior.
