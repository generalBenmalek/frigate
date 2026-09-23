import json
from collections.abc import Callable
from datetime import datetime

import requests
from requests.auth import HTTPDigestAuth


class DahuaAccessController:

    def __init__(
        self,
        ip: str,
        username: str = "admin",
        password: str = "",
        port: int = 80,
        timeout: int = 5,
        use_auth: bool = True,
    ):
        self.ip = ip
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.use_auth = use_auth

        self.base_url = f"http://{ip}:{port}"

        self.session = requests.Session()

        if use_auth:
            self.session.auth = HTTPDigestAuth(
                username,
                password,
            )

    # =========================================================
    # SYSTEM INFORMATION
    # =========================================================

    def get_system_info(self) -> dict:

        url = (
            f"{self.base_url}/cgi-bin/magicBox.cgi"
            "?action=getSystemInfo"
        )

        response = self.session.get(
            url,
            timeout=self.timeout,
        )

        response.raise_for_status()

        info = {}

        for line in response.text.splitlines():

            if "=" not in line:
                continue

            key, value = line.split("=", 1)

            info[key] = value

        return info

    # =========================================================
    # STATUS
    # =========================================================

    def is_online(self) -> bool:

        try:
            self.get_system_info()
            return True

        except requests.RequestException:
            return False

    # =========================================================
    # HISTORICAL RECORDS
    # =========================================================

    def get_access_records(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:

        start = int(start_time.timestamp())
        end = int(end_time.timestamp())

        url = (
            f"{self.base_url}"
            "/cgi-bin/recordFinder.cgi"
            "?action=find"
            "&name=AccessControlCardRec"
            f"&StartTime={start}"
            f"&EndTime={end}"
        )

        response = self.session.get(
            url,
            timeout=self.timeout,
        )

        response.raise_for_status()

        return self._parse_records(
            response.text
        )

    def get_card_owners(self, card_number: str) -> list[str]:
        """Read the names attached to a card from the controller's card records."""
        response = self.session.get(
            f"{self.base_url}/cgi-bin/recordFinder.cgi",
            params={
                "action": "find",
                "name": "AccessControlCard",
                "condition.CardNo": card_number,
                "count": 1024,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        records = self._parse_records(response.text)
        return sorted(
            {
                name
                for record in records
                if str(record.get("CardNo", "")).strip() == card_number
                for name in self.record_names(record)
            }
        )

    @staticmethod
    def record_names(record: dict) -> list[str]:
        """Extract single or indexed names from Dahua record fields."""
        names: list[str] = []
        for key, value in record.items():
            if key not in {"CardName", "CardNames", "UserName", "UserNames", "Names"} and not key.startswith(
                ("CardName[", "CardNames[", "UserName[", "UserNames[", "Names[")
            ):
                continue
            if isinstance(value, str) and value.startswith("["):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
        return list(dict.fromkeys(names))

    # =========================================================
    # LIVE EVENTS
    # =========================================================

    def listen_events(
        self,
        callback: Callable[[dict], None],
    ):

        url = (
            f"{self.base_url}"
            "/cgi-bin/eventManager.cgi"
            "?action=attach"
            "&codes=[All]"
        )

        with self.session.get(
            url,
            stream=True,
            timeout=None,
        ) as response:

            response.raise_for_status()

            buffer = []

            for line in response.iter_lines(
                chunk_size=1,
                decode_unicode=True
            ):

                if not line:
                    continue

                line = line.strip()

                buffer.append(line)

                if line.startswith("data="):

                    event_text = "\n".join(
                        buffer
                    )

                    event = (
                        self._parse_live_event(
                            event_text
                        )
                    )

                    buffer.clear()

                    if event:
                        callback(event)

    # =========================================================
    # LIVE EVENT PARSER
    # =========================================================

    @staticmethod
    def _parse_live_event(
        text: str,
    ) -> dict | None:

        event = {
            "code": None,
            "action": None,
            "index": None,
            "data": {},
        }

        for line in text.splitlines():

            if "=" not in line:
                continue

            key, value = line.split(
                "=",
                1,
            )

            if key == "Code":

                event["code"] = value

            elif key == "action":

                event["action"] = value

            elif key == "index":

                event["index"] = value

            elif key == "data":

                try:

                    event["data"] = json.loads(
                        value
                    )

                except json.JSONDecodeError:

                    event["data"] = {
                        "raw": value
                    }

        if not event["code"]:
            return None

        return event

    # =========================================================
    # HISTORICAL RECORD PARSER
    # =========================================================

    @staticmethod
    def _parse_records(
        text: str,
    ) -> list[dict]:

        records = {}

        for line in text.splitlines():

            if "=" not in line:
                continue

            key, value = line.split(
                "=",
                1,
            )

            if not key.startswith(
                "records["
            ):
                continue

            try:

                end = key.index("]")

                index = int(
                    key[
                        len("records["):
                        end
                    ]
                )

                field = key[
                    end + 2:
                ]

                if index not in records:
                    records[index] = {}

                records[index][field] = value

            except (
                ValueError,
                IndexError,
            ):
                continue

        return [
            records[index]
            for index in sorted(records)
        ]
