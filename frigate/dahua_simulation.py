import json
import threading
import time
from datetime import datetime
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from urllib.parse import (
    parse_qs,
    urlparse,
)


# ============================================================
# CONTROLLER STATE
# ============================================================

class ControllerState:

    def __init__(self):

        self.lock = threading.Lock()

        self.online = True

        self.name = "SIM-AC-001"
        self.model = "DHI-ASI2201H-W"
        self.serial = "SIM123456789"

        self.ip = "127.0.0.1"

        self.channel_count = 1

        self.events = []

        self.listeners = []

    # --------------------------------------------------------
    # ADD EVENT
    # --------------------------------------------------------

    def add_event(
        self,
        event_data,
    ):

        event = {
            "timestamp": time.time(),

            "datetime": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

            **event_data,
        }

        with self.lock:

            self.events.append(
                event
            )

            listeners = list(
                self.listeners
            )

        for listener in listeners:

            try:
                listener(event)

            except Exception:
                pass

        return event

    # --------------------------------------------------------
    # LISTENERS
    # --------------------------------------------------------

    def add_listener(
        self,
        listener,
    ):

        with self.lock:

            self.listeners.append(
                listener
            )

    def remove_listener(
        self,
        listener,
    ):

        with self.lock:

            if listener in self.listeners:

                self.listeners.remove(
                    listener
                )


STATE = ControllerState()


# ============================================================
# HTTP SERVER
# ============================================================

class DahuaSimulatorHandler(
    BaseHTTPRequestHandler
):

    protocol_version = "HTTP/1.1"

    def log_message(
        self,
        format,
        *args,
    ):

        print(
            f"[HTTP] {format % args}"
        )

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    def send_text(
        self,
        text,
        status=200,
    ):

        body = text.encode()

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Connection",
            "close"
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        path = parsed.path

        params = parse_qs(
            parsed.query
        )

        if path == "/cgi-bin/magicBox.cgi":

            self.system_info()

        elif path == "/cgi-bin/eventManager.cgi":

            self.live_events()

        elif path == "/cgi-bin/recordFinder.cgi":

            self.records(params)

        # ----------------------------------------------------
        # SIMULATOR CONTROL API
        # ----------------------------------------------------

        elif path == "/sim/status":

            self.sim_status()

        elif path == "/sim/online":

            STATE.online = True

            self.send_text(
                "ONLINE"
            )

        elif path == "/sim/offline":

            STATE.online = False

            self.send_text(
                "OFFLINE"
            )

        elif path == "/sim/event":

            self.sim_event(
                params
            )

        else:

            self.send_text(
                "Not Found",
                404
            )

    # ========================================================
    # SYSTEM INFO
    # ========================================================

    def system_info(self):

        if not STATE.online:

            self.send_text(
                "Controller offline",
                503
            )

            return

        response = "\n".join(
            [
                f"deviceType={STATE.model}",
                f"serialNumber={STATE.serial}",
                f"deviceName={STATE.name}",
                f"channelNumber={STATE.channel_count}",
                "firmwareVersion=SIM-1.0.0",
            ]
        )

        self.send_text(
            response
        )

    # ========================================================
    # SIM STATUS
    # ========================================================

    def sim_status(self):

        status = {
            "online": STATE.online,
            "name": STATE.name,
            "model": STATE.model,
            "serial": STATE.serial,
            "ip": STATE.ip,
            "channel_count": STATE.channel_count,
        }

        self.send_json(
            status
        )

    # ========================================================
    # SEND JSON
    # ========================================================

    def send_json(
        self,
        data,
        status=200,
    ):

        body = json.dumps(
            data
        ).encode()

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.send_header(
            "Connection",
            "close"
        )

        self.end_headers()

        self.wfile.write(
            body
        )

    # ========================================================
    # SIMULATE EVENT
    # ========================================================

    def sim_event(
        self,
        params,
    ):

        if not STATE.online:

            self.send_text(
                "Controller offline",
                503
            )

            return

        event_type = params.get(
            "type",
            ["grant"]
        )[0]

        user = params.get(
            "user",
            [""]
        )[0]

        names = [name.strip() for name in params.get("name", [user]) if name.strip()]

        card = params.get(
            "card",
            [""]
        )[0]

        door = params.get(
            "door",
            ["0"]
        )[0]

        if event_type == "grant":

            data = {
                "EventType":
                    "AccessGranted",

                "UserID":
                    user,

                "CardName":
                    names[0] if names else "",

                **{f"CardNames[{index}]": name for index, name in enumerate(names)},

                "CardNo":
                    card,

                "Door":
                    door,

                "Status":
                    1,
            }

        elif event_type == "deny":

            data = {
                "EventType":
                    "AccessDenied",

                "UserID":
                    user,

                "CardNo":
                    card,

                "Door":
                    door,

                "Status":
                    0,
            }

        elif event_type == "open":

            data = {
                "EventType":
                    "DoorOpened",

                "Door":
                    door,
            }

        elif event_type == "close":

            data = {
                "EventType":
                    "DoorClosed",

                "Door":
                    door,
            }

        else:

            self.send_text(
                "Unknown event",
                400
            )

            return

        event = STATE.add_event(
            data
        )

        self.send_json(
            event
        )

    # ========================================================
    # LIVE EVENTS
    # ========================================================

    def live_events(self):

        if not STATE.online:

            self.send_text(
                "Controller offline",
                503
            )

            return

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.send_header(
            "Cache-Control",
            "no-cache"
        )

        self.send_header(
            "Connection",
            "keep-alive"
        )

        self.end_headers()

        stopped = threading.Event()

        def send_event(event):

            try:

                message = (
                    "Code=AccessControl\n"
                    "action=Pulse\n"
                    "index=0\n"
                    "data="
                    + json.dumps(
                        event,
                        separators=(",", ":")
                    )
                    + "\n\n"
                )

                self.wfile.write(
                    message.encode()
                )

                self.wfile.flush()

            except Exception:

                stopped.set()

        STATE.add_listener(
            send_event
        )

        print(
            "[LIVE] Client connected"
        )

        try:

            while not stopped.is_set():

                time.sleep(2)

                try:

                    self.wfile.write(
                        b"\n"
                    )

                    self.wfile.flush()

                except Exception:

                    break

        finally:

            STATE.remove_listener(
                send_event
            )

            print(
                "[LIVE] Client disconnected"
            )

    # ========================================================
    # HISTORICAL RECORDS
    # ========================================================

    def records(self, params):

        if not STATE.online:

            self.send_text(
                "Controller offline",
                503
            )

            return

        output = []

        with STATE.lock:

            events = list(
                STATE.events
            )

        record_name = params.get("name", ["AccessControlCardRec"])[0]
        card_number = params.get("condition.CardNo", [None])[0]
        start = int(params.get("StartTime", [0])[0])
        end = int(params.get("EndTime", [time.time()])[0])

        events = [
            event for event in events
            if (not card_number or event.get("CardNo") == card_number)
            and (record_name == "AccessControlCard" or start <= event["timestamp"] <= end)
        ]
        if record_name == "AccessControlCard":
            events = [
                {
                    "CardNo": event["CardNo"],
                    "CardName": event.get("CardName", ""),
                    "UserID": event.get("UserID", ""),
                    **{
                        key: value for key, value in event.items()
                        if key.startswith("CardNames[")
                    },
                }
                for event in events
                if event.get("CardNo")
            ]

        for index, event in enumerate(
            events
        ):

            for key, value in event.items():

                output.append(
                    f"records[{index}]."
                    f"{key}={value}"
                )

        self.send_text(
            "\n".join(output)
        )


# ============================================================
# SERVER
# ============================================================

def start_server():

    server = ThreadingHTTPServer(
        (
            "127.0.0.1",
            8080,
        ),
        DahuaSimulatorHandler,
    )

    print(
        "Dahua AC simulator running:"
    )

    print(
        "http://127.0.0.1:8080"
    )

    server.serve_forever()


if __name__ == "__main__":

    start_server()
