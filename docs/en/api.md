# Agent API

[简体中文](../zh/api.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

The [schema snapshot (JSON)](../../templates/layout-agent/docs/api-schema.json) records argument details. Use live discovery to check the running APP.

## Transport and discovery

The running APP exposes an authenticated HTTP service on 127.0.0.1. It publishes the current URL/token in agent-connection.json. This descriptor is private runtime data; use the generated client folder, not a fixed port. GET is not the tool protocol.

POST /call with Authorization: Bearer <local-token> and a JSON object containing exactly tool, arguments, request_id and client_id. The server bounds payload size and validates non-finite JSON. Use the bundled client to handle response envelopes and polling.

```json
{
  "tool": "workspace",
  "arguments": {"action": "status"},
  "request_id": "caller-generated-unique-id",
  "client_id": "layout-agent-1"
}
```

The special tools discovery call returns currently available schemas and is not a product tool. Ten tools are available by default; human process settings can additionally enable route_region. The static schema lists all possible tools; live discovery and permission checks take precedence. MCP is not a supported transport.

## Tools

| Tool | Purpose |
|---|---|
| workspace | Status and explicit archive save/load under configured roots |
| reference_cases | Read-only discovery and inspection of human-provided references |
| process_configuration | Setup-role requirements, proposal submission/query and configuration export; no API approval |
| claim_region | Exclusive ownership of one construction level |
| inspect_region | Scoped layout, rules, connectivity and schematic-reference projections |
| edit_region | Validated edit batches, including supported frames, PINs, guards and routing windows |
| route_region | Algorithm autorouting, disabled by default until enabled in the human process UI |
| check_region | Local supported DRC/connectivity jobs |
| capture_region | Scoped read-only images, independent of the human view |
| server_drc_region | Scoped server checks and result queries |
| release_region | Release/handoff or evidence-validated completion |

The API intentionally does not expose arbitrary Python/SKILL, direct Bridge access, arbitrary source import/sync, native PCell internals or human process approval.

The process editor's drawing/layers page has an unchecked-by-default “允许 Agent 使用算法自动布线” option; legacy configurations also default to disabled. It gates only route_region: disabled tools disappear from live discovery and generate/recheck/apply return AGENT_AUTOROUTE_DISABLED. Existing jobs may still use status/discard, and original idempotent receipts remain valid. Human UI autorouting and Agent arrange/align/auto-via/multilayer-path helpers remain available. inspect_region(kind=rules) reports agent_autoroute_enabled; routing layer/via data remains readable but is not permission. process_configuration.submit cannot change the flag: omission preserves the human choice, changes return AGENT_PERMISSION_UI_ONLY. Imported shared configurations default to disabled until a local human enables and saves them.

edit_region tighten_region/tighten_child_region share the human tightening implementation. Around contents and direct-child PIN extents, each axis reserves half the largest own/direct-child PIN dimension plus 10% (at least one manufacturing grid step), rounded outward. padding_um adds extra clearance; pin_clearance_um reports the automatic margin. Tightening only shrinks within the original frame, preserves native geometry and PIN mode, and adds no insufficient-margin warning for an already tight frame.

## Identity, revision and jobs

Claim first, retain the returned session token and use a separate client identity for each parallel worker. Inspect before editing; send expected_revision and actual object IDs. Global revisions are not a license to overwrite a scoped stale input.

A request is identified by client_id + request_id + the same body. Preserve this tuple across network timeouts. A different ID may create a second operation. Retain client pending files until reconciliation succeeds. Queued/running jobs are not success; poll their existing job ID. Respect stale/cancelled/failed outcomes and inspect before revising the operation.

Server DRC may start without a preceding local pass, but done requires both current full-region local and server evidence. Advisory warnings are separate from actual blocking errors. The approved report filter applies to UI, API and server completion, while raw waived records remain inspectable. It cannot override local physical failures.

## Client generation and schema maintenance

tools/create_layout_agent.py copies only executable templates, instructions and generated schema/SDK. It never copies another agent's tasks, identities or pending. Existing managed files are hash-checked before update. The external agent host must enforce folder permissions; documentation alone is not a security sandbox.

After changing agent_tools/contract.py, run:

```powershell
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit --check
```

Then update the intended idle live client's folder with --update. Do not silently widen a layout agent's role to maintenance/PDK access.

## Implementation ownership

http_api marshals calls into the owner thread. session/leases enforce claims and replay rules. region_edits/region_tasks coordinate domain services and immutable worker inputs. inspection/capture preserve scope; release_status checks evidence. Business rules belong in the shared Editor/region/physical/process services, not duplicated HTTP branches.

---

[简体中文](../zh/api.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)
