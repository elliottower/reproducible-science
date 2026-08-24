## What this changes

<!-- One or two sentences. What is different afterwards, not how. -->

## Why

<!-- The defect, the gap, or the request. Link the issue if there is one. -->

## Checks

- [ ] `make qa` passes
- [ ] a note under `changes/<package>/` if this is user-visible
- [ ] new behaviour has a test that fails without it

## If this touches evidence

<!-- Delete this section if it does not. -->

- [ ] `repro verify paper/repro.yaml --policy strict` passes
- [ ] derived artifacts regenerate clean (`make drift`)
- [ ] conformance fixtures are unchanged, or the change is deliberate and re-pinned
