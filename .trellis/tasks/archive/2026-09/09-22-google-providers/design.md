# Technical Design

## Architecture

TranslationService owns provider IDs, URL construction, token generation, parsing, bounds, and redaction. Debug control only injects local fixture endpoints.

## Lifecycle and State

Selection translation passes normalized request data to the service worker; the service performs bounded HTTP GET and returns normalized results.

## Compatibility and Ownership

Google web endpoints are isolated from the existing Cloud Translation adapter so persisted provider selection and credentials remain compatible.
