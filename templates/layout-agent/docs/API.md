# Client workflow

All coordinates for edit calls are workspace-absolute micrometres unless the tool says otherwise. Native via definitions expose DBU dimensions; use dbu_per_micron to convert them. Do not treat same-name net labels or highlighted pixels as proof of physical connection.

1. `tools`: inspect the live tools/actions. A schema file is a snapshot, not authority over a newer server.
2. `claim_region`: use the exact region ID from the user. Keep the returned session token private.
3. `inspect_region`: layout/rules/reference/net projections are scoped to the claimed construction level.
4. `edit_region`: supply expected_revision and a reviewed operation batch. Atomic validation must succeed before edits are adopted.
5. `check_region`: asynchronous local connectivity, supported geometric rules and advisory checks. Poll the same job ID.
6. `server_drc_region`: asynchronous server DRC using an isolated native copy. It can start independently of local DRC; both must pass for completion.
7. `capture_region`: scoped screenshots for review. These do not move the human camera.
8. `release_region`: done requires valid complete-region evidence; handoff preserves intermediate work.

`route_region` is disabled by default and absent from live tools until a human enables Agent autorouting in the process UI. Disabled generate/recheck/apply calls fail with AGENT_AUTOROUTE_DISABLED; existing jobs still allow status/discard for cleanup. Agents cannot change this permission, including through process proposals. Human UI routing and all other edit helpers remain available. `inspect rules` reports `agent_autoroute_enabled`; readable routing layer/via data does not grant access. `reference_cases` manages references, and `workspace` handles explicit snapshots. `process_configuration` is for the separate setup role; ordinary layout agents do not change global process settings.

Useful conventions:

- First build the interior with directional PINs where suitable, then tighten the region, select fixed PIN mode and route to real boundary access.
- Tightening automatically leaves half the largest own/direct-child PIN dimension per axis plus 10% (at least one grid step), rounded outward, around contents and child PIN extents. `padding_um` adds to this margin. It only shrinks inside the original frame, preserves native geometry/PIN mode and does not warn when the original frame is already too tight.
- Native guard paths/rings are available only from approved sampled capabilities. Double rows cannot be inferred from a single-row sample.
- The internal-metal contact design warning flags possible accidental contact with a leaf device's non-PIN metal; it is advice, not an LVS verdict.
- Cross-device Poly conflicts and configured MIM-region via errors are local physical checks and are not waived by server report filters.
- Local `spacing` is geometric: it does not distinguish same-net/different-net geometry or compare net names. Enabled spacing rules on the same layer all apply; rule IDs, notes and sources do not implement conditional branches. Read the approved simplification and omitted cases, retain server checks, and report configuration concerns to the setup role instead of changing rules to bypass failures.
- Server report filtering follows the human-approved process policy. `include_waived=true` shows preserved filtered records without altering passed.
- Unknown outcome: retain pending and use the same request ID/body. `queued/running` is not success; inspect current/passed/completion_eligible/coverage.
- A port returning connection refused is a maintenance issue. Do not scan for another service or connect directly to Virtuoso.

Read `api.py --help` for CLI names. Send raw tool arguments with the existing CLI call facility or use colayout_client.py; do not import APP implementation modules.

## Preparing a raw edit

Run `api.py --client <name> inspect layout` and use the response's top-level revision as expected_revision. Discover the exact action with `tools --tool edit_region --action create_path90` (or another action). Save the arguments JSON under requests/, then call `api.py --client <same-name> call edit_region --args requests/edit.json --wait-seconds 20`.

The CLI injects its private session_token; do not copy the redacted token from output. It does not invent expected_revision or coordinates for you. Use actual scoped IDs/PIN coordinates and the current process definitions. Inspect edits after application; for an asynchronous result, keep its job_id and query status until edit_applied is established. Never repeat a submitted edit just because waiting ended.
