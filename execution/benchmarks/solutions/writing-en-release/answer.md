## What changed

REL-3.4.0 releases on 2026-08-18 and adds the ExportJob webhook event `export.completed`. The event gives integrators a defined signal for the completed export-job lifecycle. Existing CSV output is not being redesigned in this release: the CSV output format is unchanged.
This note is limited to the event name and version boundary supplied for this change.

## Compatibility

To receive `export.completed`, an integration must use API version `2026-06-01`. The existing `legacy_export` endpoint remains available in REL-3.4.0, so an immediate endpoint migration is not required by this release. However, `legacy_export` is scheduled for removal in 4.0.0. That stated removal version is the compatibility boundary; these notes do not assign a release date to 4.0.0 or claim compatibility outside the facts listed here.

## Upgrade

Before enabling the new webhook, update the version header to `2026-06-01` and test in staging. Confirm that the receiver handles `export.completed` as part of its normal event processing, then plan the eventual move away from `legacy_export`. Teams can retain their current CSV parsing expectations because the CSV format is unchanged. Record any integration-specific issues through the normal support channel.
