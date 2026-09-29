"""Tests for Dahua provider parsing and normalized access events."""

import unittest
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from frigate.dahua_adapter import (
    CgiProvider,
    CgiEventParser,
    DahuaAccessController,
    DahuaConnection,
    DahuaNotSupported,
    DahuaOperationError,
    _safe_body,
)


class TestDahuaAdapter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = CgiProvider(DahuaConnection(ip="192.0.2.10"))

    async def test_system_info_normalizes_reported_fields_only(self):
        with patch.object(
            self.provider,
            "_text",
            new=AsyncMock(
                return_value=(
                    "deviceType=DHI-ASI2201-H-W\n"
                    "serialNumber=SN-1\n"
                    "version=1.2.3\n"
                    "deviceName=Lobby\n"
                    "IPAddress=192.0.2.10"
                )
            ),
        ):
            info = await self.provider.get_system_info()

        self.assertEqual(info["model"], "DHI-ASI2201-H-W")
        self.assertEqual(info["serial_number"], "SN-1")
        self.assertEqual(info["firmware_version"], "1.2.3")
        self.assertEqual(info["device_name"], "Lobby")
        self.assertEqual(info["ip_address"], "192.0.2.10")
        self.assertNotIn("manufacturer", info)

    async def test_history_fetches_each_page_and_keeps_record_fields(self):
        calls: list[int] = []

        async def page(_operation, _path, params):
            start_index = params.get("StartIndex", 0)
            calls.append(start_index)
            text = ["totalCount=250", "found=100"]
            count = min(100, 250 - start_index)
            for index in range(count):
                row_index = start_index + index
                text.append(f"records[{index}].RecNo={row_index}")
                text.append(f"records[{index}].CardNo=00{row_index}")
            return "\n".join(text)

        with patch.object(self.provider, "_text", side_effect=page):
            records = await self.provider.get_access_records(
                datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
            )

        self.assertEqual(calls, [0, 100, 200])
        self.assertEqual(len(records), 250)
        self.assertEqual(records[0]["CardNo"], "000")
        self.assertEqual(records[-1]["RecNo"], "249")

    async def test_history_repeated_page_preserves_records_and_marks_incomplete(self):
        repeated_fields = ["totalCount=150", "found=100"]
        for index in range(100):
            repeated_fields.append(f"records[{index}].RecNo={index}")
        repeated = "\n".join(repeated_fields)
        with patch.object(self.provider, "_text", new=AsyncMock(return_value=repeated)):
            records = await self.provider.get_access_records(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 2, tzinfo=UTC),
            )
        self.assertEqual(len(records), 100)
        self.assertTrue(self.provider.history_incomplete)

    async def test_asi_system_info_uses_separate_identity_actions(self):
        responses = {
            "getSystemInfo": "deviceType=DHI-ASI2201H-W\nserialNumber=SN-1",
            "getMachineName": "name=Lobby",
            "getSerialNo": "sn=SN-1",
            "getSoftwareVersion": "version=1.000.R,build:2022-07-27",
            "getHardwareVersion": "version=1.00",
        }

        async def response(_operation, _path, params):
            return responses[params["action"]]

        with patch.object(self.provider, "_text", side_effect=response):
            info = await self.provider.get_system_info()
        self.assertEqual(info["device_name"], "Lobby")
        self.assertEqual(info["firmware_version"], "1.000.R,build:2022-07-27")
        self.assertEqual(info["hardware_version"], "1.00")

    async def test_unbounded_history_uses_observed_find_request(self):
        with patch.object(self.provider, "_text", new=AsyncMock(return_value="found=0")) as request:
            await self.provider.get_access_records(None, None, count=500)
        self.assertEqual(request.call_args.args[2], {
            "action": "find", "name": "AccessControlCardRec", "count": 500,
        })

    def test_live_parser_keeps_multiline_nested_json_across_every_chunk_boundary(self):
        data = {
            "CardName": 'Alice; {quoted} "name"', "CardNo": "000ABC", "Door": 0,
            "nested": {"values": [{"text": "escaped \\ brace }"}]},
        }
        frame = "Code=AccessControl;action=Pulse;index=0;data=" + json.dumps(data, indent=2)
        for split in range(1, len(frame)):
            parser = CgiEventParser()
            self.assertEqual(parser.feed(frame[:split]), [])
            parsed = parser.feed(frame[split:])
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["data"], data)

    def test_live_parser_handles_headers_heartbeats_and_multiple_frames(self):
        frame = 'Code=AccessControl;action=Pulse;index=0;data={"Door":0}'
        parser = CgiEventParser()
        result = parser.feed("--boundary\r\nContent-Type: text/plain\r\nheartbeat\r\n" + frame + "\n" + frame)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["data"]["Door"], 0)

    def test_live_parser_recovers_after_an_unclosed_frame(self):
        parser = CgiEventParser()
        frame = 'Code=AccessControl;action=Pulse;index=0;data={"Door":0}'
        result = parser.feed('Code=AccessControl;action=Pulse;index=0;data={"Door":\n' + frame)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["data"], {"Door": 0})

    def test_normalization_preserves_zeroes_identifiers_and_error_precedence(self):
        event = DahuaAccessController.normalize_event({"code": "AccessControl", "data": {
            "RealUTC": 1790665389000, "CardNo": "000ABC", "UserID": "001",
            "Door": 0, "ReaderID": "1", "Method": 11, "Status": 1,
            "ErrorCode": 16, "Type": "Entry",
        }}, "controller")
        self.assertEqual(event["timestamp"], 1790665389)
        self.assertEqual(event["door_id"], 0)
        self.assertEqual(event["user_id"], "001")
        self.assertEqual(event["card_number"], "000ABC")
        self.assertEqual(event["authentication_method"], 11)
        self.assertEqual(event["status"], "Failed")
        self.assertEqual(event["error_code"], 16)

    def test_normalization_uses_utc_when_create_time_is_invalid(self):
        event = DahuaAccessController.normalize_event({
            "CreateTime": "invalid", "RealUTC": 1790665389,
        }, "controller")
        self.assertEqual(event["timestamp"], 1790665389)

    async def test_card_owner_lookup_preserves_card_number_and_names(self):
        response = (
            "records[0].CardNo=000123\n"
            "records[0].CardName=Alice\n"
            "records[0].UserNames[0]=Alex"
        )
        with patch.object(self.provider, "_text", new=AsyncMock(return_value=response)):
            owners = await self.provider.get_card_owners("000123")

        self.assertEqual(owners, ["Alex", "Alice"])

    async def test_door_discovery_does_not_invent_a_single_door(self):
        with (
            patch.object(
                self.provider, "_get_door_config", new=AsyncMock(return_value={})
            ),
            self.assertRaises(DahuaNotSupported),
        ):
            await self.provider.get_doors()

    async def test_door_discovery_keeps_each_reported_door(self):
        config = {
            "AccessControl[0].DoorName": "Main",
            "AccessControl[1].DoorName": "Garage",
        }
        with patch.object(
            self.provider, "_get_door_config", new=AsyncMock(return_value=config)
        ):
            doors = await self.provider.get_doors()

        self.assertEqual([door["id"] for door in doors], ["1", "2"])
        self.assertEqual([door["name"] for door in doors], ["Main", "Garage"])
        self.assertTrue(all("raw" in door for door in doors))

    async def test_door_commands_require_a_discovered_id(self):
        with (
            patch.object(
                self.provider,
                "_get_door_config",
                new=AsyncMock(return_value={"AccessControl[0].DoorName": "Main"}),
            ),
            patch.object(
                self.provider, "_text", new=AsyncMock(return_value="OK")
            ) as request,
        ):
            result = await self.provider.open_door("1")

        self.assertTrue(result["accepted"])
        self.assertEqual(result["door_id"], "1")
        self.assertEqual(request.await_args.args[0], "open_door")

    async def test_event_parser_keeps_access_control_data(self):
        event = CgiProvider._event_from_fields(
            {
                "Code": "AccessControl",
                "action": "Pulse",
                "Data.CardNo": "000123",
                "Data.Status": "0",
                "Data.Method": "1",
            }
        )
        self.assertIsNotNone(event)
        normalized = DahuaAccessController.normalize_event(event, "front-door")
        self.assertEqual(normalized["device_id"], "front-door")
        self.assertEqual(normalized["card_number"], "000123")
        self.assertEqual(normalized["access_status"], "0")
        self.assertEqual(normalized["authentication_method"], "1")

    async def test_raw_provider_event_redacts_secrets(self):
        event = DahuaAccessController.sanitize_raw_event(
            {"CardNo": "000123", "Password": "secret", "nested": {"PIN": "1234"}}
        )
        self.assertEqual(event["CardNo"], "000123")
        self.assertEqual(event["Password"], "<redacted>")
        self.assertEqual(event["nested"]["PIN"], "<redacted>")
        self.assertNotIn("secret", _safe_body('{"Password":"secret"}'))

    async def test_preview_clip_is_explicitly_unsupported_for_cgi(self):
        with self.assertRaises(DahuaNotSupported):
            await self.provider.get_preview_clip()


if __name__ == "__main__":
    unittest.main()
