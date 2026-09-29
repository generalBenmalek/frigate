# Standalone Dahua access-controller tools

These tools run separately from Frigate's employee portal and database. The
simulator owns a SQLite file; the debugger holds a device password only for the
request in progress. Both bind to localhost by default.

From the repository root, install the small tool dependency set and start each
service in a separate terminal:

```bash
python3 -m pip install -r dahua_tools/requirements.txt
python3 -m dahua_tools.simulator
python3 -m dahua_tools.debugger
```

Open `http://127.0.0.1:8080` for the simulator and
`http://127.0.0.1:8081` for the debugger. To run both containers independently
of the portal, use `docker compose -f dahua_tools/compose.yml up --build`.
Container ports publish only on localhost. For a deliberate LAN deployment,
change the host binding in `compose.yml`; for direct Python launches, set
`DAHUA_SIM_HOST` or `DAHUA_DEBUG_HOST`. Protect either service before exposing
it to other users: the simulator management API and debugger are not
authenticated.

## Simulator

The first launch creates `dahua_simulator.db` with two online, closed doors.
Set `DAHUA_SIM_DB` to choose a different file. The management page supports
controller settings, door status, user and card editing, many-to-many card
ownership, access scans, explicit grants and denials, historical events, and
live events. A successful live card scan opens its door. A remote open command
opens it; close relocks it. Historical generation records an event without
changing door state or sending a live notification.

Connect through `DahuaAccessController(ip="127.0.0.1", port=8080,
provider="cgi", use_auth=False)`. The simulator implements the exact CGI
routes used by the existing adapter: `magicBox.cgi`, `configManager.cgi`,
`accessControl.cgi`, `recordFinder.cgi`, `eventManager.cgi`, and
`snapshot.cgi`. The snapshot is visibly labeled simulated. Preview clips
remain unavailable. Existing `/sim/status`, `/sim/online`, `/sim/offline`, and
`/sim/event` paths remain for the former desktop utility.

CGI access records use the ASI2201H-W field shapes: zero-based `Door`, numeric
`Status` and `Method`, `ReaderID`, `Type`, `ErrorCode`, and Unix timestamps.
The access form selects card, multi-card, fingerprint, face, or password
methods. Live CGI events contain multiline JSON and honor `codes=[All]` or
selected codes. Historical CGI queries honor the time bounds, count, and
`condition.UserID`, `condition.CardNo`, `condition.Door`, `condition.ReaderID`,
and `condition.Type`. Device identity actions also include `getMachineName`,
`getSerialNo`, `getSoftwareVersion`, and `getHardwareVersion`.
CGI wall-clock search bounds use `Africa/Algiers` by default; set
`DAHUA_SIM_TIMEZONE` to match a controller in another timezone.

Frigate's access-controller Events tab loads controller history on demand and
receives subsequent access and verification updates over its existing
WebSocket connection. The twelve reference columns and six filters share the
configured UI timezone. Select a row to see camera verification and footage
in the separate selected-event section. Device failures retain stored history;
unsupported or incomplete CGI pagination produces a visible history warning.

## Camera verification and footage

Associate a Frigate camera with the controller. Successful access scans for
every authentication method are verified against overlapping person events,
the detection timeline, and live person objects. For live scans, Frigate caches
three camera screenshots at two-second intervals, including denied scans for
footage, and tries its existing face
recognizer on unidentified person crops. Recognition respects global and
per-camera face settings, the recognition score threshold, and `min_faces`.
Retrying the same image does not increase the recognition count.
Live object identities continue to be sampled through the camera window,
including objects whose events are not retained as snapshots or recordings.
Register faces using names matching the controller's card owners.

An identified owner produces `valid`; another identified person produces
`warning`. Unidentified people or missing identity evidence produce `unknown`,
with the reason shown in the selected-event section. Recordings and face
training folders are not prerequisites for an already identified detection.
Scans remain `pending` through their configured camera window plus a 30-second
grace period for delayed recognition. Denied access remains `unverified`.
Recent inconclusive scans are checked for updated detection identities for
five minutes; older scans can be retried from the selected-event section.

If a live controller timestamp differs from Frigate by more than 30 seconds,
camera evidence and footage use event receipt time. The displayed controller
timestamp remains unchanged. Historical-only events use their stored time and
are never compared to an unrelated current live frame. Retry verification
checks updated history, cached screenshots, saved person snapshots, and frames
from recording history. Automatic historical image work runs at most two jobs
concurrently. Screenshot files in `/tmp/cache/access_snapshots` expire after
24 hours and are served only to administrators.

Footage uses the media API and tries preview MP4, recording/object clips, then
cached or object snapshots. The source selector also permits a manual choice.
The Provider capabilities UI and its request are commented out for later
re-enablement; backend capability endpoints remain available.

## Debugger

Enter a device address, credentials, provider, and CGI event endpoint. Each
button sends one request through the shared application-facing adapter and
shows `SUCCESS`, `FAILED`, or `NOT SUPPORTED`, the duration, HTTP status when
available, normalized data, safe raw response, and detailed diagnostics. The
live event button opens a cancellable stream. The JSON export contains only
redacted results. The `netsdk` choice reports unavailable until a compatible
provider plugin is installed; no native SDK binaries are bundled.

Use the simulator as a no-device target by entering `127.0.0.1`, port `8080`,
provider `cgi`, and clearing the authentication checkbox. From a debugger
container targeting the simulator container, use host `simulator` and port
`8080`. Real-device CGI support depends on the controller firmware; an HTTP
failure remains visible rather than switching providers automatically.
