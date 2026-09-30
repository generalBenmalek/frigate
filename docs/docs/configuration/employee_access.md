---
id: employee_access
title: Employee cardless access
---

The employee portal is a separate website in the Frigate deployment, on port
8972 by default. It uses local employee accounts, Frigate camera frames and
face-recognition models, and the existing controller remote-unlock operation.

## Setup

Publish port `8972:8972` in the Frigate Docker port mappings. The portal uses
Frigate's TLS setting and certificate. To change its listening port, set
`networking.listen.employee` and restart Frigate, updating the Docker mapping.

```yaml
networking:
  listen:
    employee: 8972
```

Open **Employees** in the main Frigate website as an administrator. Cardless
access starts disabled. Create employee accounts or refresh controller users,
assign unique names and usernames, and set passwords of at least 12 characters.
Employees are separate from the accounts that log in to the main Frigate website.

Register face images with **Upload face image**, or select an existing registered
face. The face-library label must equal the assigned employee name. Uploads must
contain exactly one face. Renaming a bound identity also renames its face library.

Assign allowed doors per controller. Each controller must already have an
associated Frigate camera. Enable global face recognition, face recognition on
that camera, and camera detection before enabling cardless access.

## Controller imports

Directories refresh at startup, when a controller is saved, and every five minutes.
Administrators can also refresh them immediately. Imported
accounts remain pending until an administrator confirms a unique name and sets
their login credentials. Passwords and PINs from controllers are never used for
employee login.

Records are identified by controller and controller user ID. Administrators must
explicitly link records for the same employee across controllers. The surviving
account keeps its name, login credentials, face, and local overrides.

Imported doors follow active controller records until an administrator saves a
local override for that employee and controller. **Restore controller permissions**
removes the override. Changes in this page do not modify physical card permissions
or controller users. Cardless access uses door lists, without importing physical
controller time sections or holiday schedules.

Import status distinguishes complete directories, limited legacy card-record
enumeration, unsupported providers, and failed imports. Failed or incomplete
directory retrieval retains the preceding permissions. NetSDK plugins must expose
`get_users()` returning `users` with `user_id`, `name`, `active`, and normalized
one-based `doors`, plus a `limited` flag. No native SDK is installed by this feature.

Deleting a local employee retains existing face-library images and suppresses
reimport of that employee's controller records.

## Employee workflow

Open the employee website and sign in with the assigned username and password.
Select **I forgot my card**, a camera, an associated controller, and a permitted
door. Face the selected camera before starting verification.

The backend captures a new frame, detects persons across the entire image, and
requires exactly one person. It compares a usable face only against the identity
of the authenticated employee, using the configured face recognition threshold.
Missing, too-small, or severely blurred faces are retried for up to ten seconds.
Zero or multiple persons, identity failures, and capture failures do not unlock.

A successful verification automatically sends one unlock command. The website
reports command acceptance rather than asserting that a physical door opened.
Unknown controller outcomes are not retried automatically. Snapshots stay in
memory; audit metadata is retained for thirty days and is visible to administrators.

Disabling cardless access affects only this employee workflow. Disabling an account
or changing its password revokes employee sessions. Employee authentication remains
mandatory even when main Frigate authentication is disabled or the API is reached
through the internal port.
