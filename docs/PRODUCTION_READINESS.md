# Production Readiness — v1.0.0

## Supported production target

**Windows 11 x64-compatible** is the production target for v1.0.0.

The Android application is a companion preview. It intentionally does not claim parity for audited QRZ mutation.

## Release gates

A production candidate must pass:
- full backend regression suite;
- immutable acceptance suite;
- integration safety verification;
- product capability contract;
- production metadata/version verification;
- frontend production build;
- packaged executable self-test;
- packaged executable GUI smoke test;
- silent installer smoke test;
- installed-copy self-test;
- installed-copy GUI smoke test.

## Data-integrity guarantees

The application is designed to fail closed around remote writes.

For eQSL → QRZ:
- preview is generated before mutation;
- candidates are strict 1:1 matches;
- full live preflight runs before the first mutation;
- live ADIF is backed up;
- one candidate is used as a canary;
- every write is re-fetched and verified;
- protected fields cannot silently change;
- ambiguous cards remain review-only.

## Known operational limitation

The Windows installer is not currently code-signed. Windows SmartScreen may identify the publisher as unknown. Validate installer origin and checksum from the GitHub Actions artifact.

## Release checklist

- [ ] `VERSION` and all package/install metadata agree.
- [ ] All CI gates are green on the release commit.
- [ ] Windows installer artifact is produced.
- [ ] Installer hash is recorded in release notes.
- [ ] Fresh install passes startup and health checks.
- [ ] Upgrade install preserves user data.
- [ ] eQSL Inbox reports a realistic full record count.
- [ ] eQSL → QRZ dry plan is reviewed before applying.
- [ ] No secrets are present in repository content or release logs.
