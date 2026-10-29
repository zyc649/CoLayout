---
name: colayout-layout-agent
description: Create or update a separate, client-only CoLayout layout-agent folder and publish its live APP connection. Use during onboarding or when replacing a layout conversation; not for editing layout or changing a PDK.
---

# Create a layout-agent workspace

Use this from the setup/maintenance conversation, with repository access. The new layout conversation receives only its own folder, not this repository, SSH credentials or the Virtuoso skill.

1. Ensure setup.ps1 succeeded and the Windows APP is running. Read its status with the project Python:
   `python -m colayout_lite.bootstrap status`.
2. Choose a user-approved folder. The default is a sibling named after the checkout plus `-layout-agent`, so it does not inherit the source project's maintenance skills. A nonempty unmanaged folder must not be overwritten.
3. Run `python tools/create_layout_agent.py --folder <folder>`. Use `--update` only for an existing managed client folder. It preserves identities, requests, pending outcomes, outputs and customized managed files; inspect any reported custom-file conflicts.
4. Check `ready`, not merely process exit success. If the archive path changed, wait for all agents/jobs to finish, save and close the APP normally, start it through tools/project.ps1 and publish the connection. Verify `workspace status` reports that folder's workspaces directory before declaring it ready. Never kill Virtuoso or discard pending transactions.
5. Verify from the new folder with its own `python.cmd service.py connect` and `api.py --client onboarding tools`. Do not claim or edit a user's region just to check connectivity.
6. Tell the user to open a new conversation, grant access only to this folder, read its AGENTS.md, and give it the intended region ID and task. Keep software fixes and PDK onboarding in the setup/maintenance conversation.

The generated folder contains the standard-library SDK/CLI, a snapshot of the live API contract, role instructions, and empty directories for requests, outputs, workspaces and feedback. It must not contain another agent's work, the APP source, Bridge scripts, .env, private keys or the maintenance chat.

`--offline` prepares files only and does not claim a working connection. Re-run with `--update` after the APP is available.

Folder permissions must be enforced in the host agent application. The client and AGENTS.md are not an OS sandbox. All clients still obey APP region leases and revision checks; a timeout requires reconciliation of the original request ID/body.
