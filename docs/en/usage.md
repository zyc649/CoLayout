# Using CoLayout

[简体中文](../zh/usage.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

## The workspace

The APP keeps one authoritative local document. Humans and API clients see the same objects, region hierarchy, UID identities and undo semantics. A local operation region is an organizational boundary, not a new Virtuoso cell.

After the process has been approved, use the File menu to import the intended native Layout and its corresponding schematic reference. Native Layout PIN/network data defines physical targets; schematic information helps understand topology, matching and design intent. Import is explicit.

Create an operation region around the objects to work on, inspect its interfaces and give its ID to a layout agent. An interface missing physical access can remain a declared obligation; drawing a guard or connection later must satisfy it. A virtual marker does not create metal.

## A typical collaboration

1. A human selects the source design and partitions local work.
2. Each layout agent claims one assigned region. Sibling agents can proceed in parallel; a parent manages only direct child shells and interfaces.
3. Build the interior, using directional PIN mode where appropriate. Complete device access, routing and sampled guard structures.
4. Tighten the operation region with the property-panel action/API, select fixed PIN mode and complete real boundary exits.
5. Run local checks frequently and inspect warnings. Run server DRC when appropriate, review active errors and finish only with valid whole-region evidence from both.
6. The human explicitly writes the reviewed workspace to Virtuoso, then performs the required full-chip checks/LVS and final sign-off.

During agent occupancy, physical human edits are locked for that construction level. Navigation remains available; positioning guides are the limited collaboration exception. Do not terminate another client's session to bypass a lock.

## Hierarchy and routing windows

Ordinary leaf PCells participate in local/server checks. True native hierarchical objects remain blackboxes. Their public PINs may be inside their footprint: object-specific, layer-specific routing windows can open a limited corridor. These do not reveal/edit internal geometry or waive another object's keepout.

Local child operation regions are separate from native hierarchy. Their internal work is controlled by their own agent. Moving a parent-managed child shell transforms its contents coherently and invalidates dependent work as required.

## Checks have different meanings

- Local connectivity checks exposed targets and supported material connectivity, not the full extracted device circuit.
- Local DRC includes configured simple geometry, design advice, cross-device Poly conflict checks, configured MIM-region via protection and internal-metal contact advice. Unsupported width geometries are skipped.
- The internal-metal contact warning is nonblocking advice. Known local physical errors and incomplete/stale/truncated results still prevent completion.
- Server DRC uses a private native copy containing the current local edits. It applies the approved process report policy and retains the original records.
- Passing both region checks is not full-chip DRC or LVS sign-off.

Do not change device parameters to hide a mismatch or invent a waiver. If a native-source baseline check fails, stop and reconcile the actual source/dependency change before synchronizing.

When reviewing local rules, source/note are evidence and descriptions, not executable regional exceptions or electrical conditions. Keep rules with unrepresentable conditions disabled with a reason; a note alone does not implement the condition.

## Save, reopen and recovery

The APP automatically maintains its internal working document and recovery records. Explicit Save / Save As creates or updates the user's portable JSON archive. Later editing does not continuously rewrite that archive.

The Agent workspace save API creates a standalone snapshot; load follows the same semantics as opening a saved workspace in the UI, with a backup first. Loading replaces the whole current document and requires idle sessions/jobs and no unresolved native transaction. It does not synchronize to Virtuoso.

For an unknown request outcome, preserve the original request ID/body and pending file. Query/reconcile it; do not send a new create request. For an uncertain native write, preserve the receipt and use the recovery flow. Never remove evidence to make an error disappear.

## Common controls

| Default | Action |
|---|---|
| F | Fit the view |
| Ctrl+E | Return to the parent level |
| Ctrl+R | Rotate selected supported objects by 90° |
| Ctrl+Z or U | Undo |
| Ctrl+Y or Ctrl+Shift+Z | Redo |
| Ctrl + wheel | Change the hierarchy peek level |
| Esc | Cancel the current interaction |

Shortcuts are configurable in the UI. Text fields keep text-editing behavior. Panel buttons toggle their corresponding panels; auto-routing is available through View rather than the main toolbar.

---

[简体中文](../zh/usage.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)
