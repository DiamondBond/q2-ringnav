# V1.5R — shared wheel/touch menu selection

Implemented as a release candidate; real Q2 validation remains pending.

- Correct centre selection to stock screen-toggle key 218. Keep key 171 as native Play/Pause.
- Store logical selection on each surface; draw a white outline without changing native focus.
- Observe actual touch clicks before app callbacks, so centre opens the item just touched.
- Preserve native taps, drags and momentum. Touch interrupts wheel glide; wheel interrupts touch
  momentum. Ignore centre/wheel while a finger is down. Reconcile offscreen selection after settle.
- Resolve recycled table rows by logical index and deliver centre clicks synchronously.
- Initialize on paint, preserve surviving-menu selection, reset on count changes, and cancel a
  stale glide when a wheel reversal brings selection back into the current viewport.
- Build V1.5R from audited stock V1.32, execute regression scenarios and compare two fresh packages.

See README.md for controls, hook addresses, validation boundaries and the device acceptance check.
