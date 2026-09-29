import { describe, expect, it } from "vitest";
import { accessFilterTimestamp, matchesAccessEvent, mergeAccessEvents } from "./accessController";
import { emptyAccessEventFilters, type AccessEvent } from "@/types/accessController";

const event: AccessEvent = {
  id: "scan", device_id: "controller", timestamp: 1790665389,
  user_name: "Alice", user_id: "001", card_number: "000ABC", status: "OK",
};

describe("access event history and live merging", () => {
  it("uses the configured timezone for date bounds", () => {
    expect(accessFilterTimestamp("2026-09-29T09:00", "Africa/Algiers"))
      .toBe(Date.parse("2026-09-29T08:00:00Z") / 1000);
  });

  it("applies text, status, device, and date bounds to live rows", () => {
    expect(matchesAccessEvent(event, "controller", {
      ...emptyAccessEventFilters, name: "AL", userId: "00", cardNo: "abc", status: "OK",
    }, "Africa/Algiers")).toBe(true);
    expect(matchesAccessEvent(event, "other", emptyAccessEventFilters, "Africa/Algiers")).toBe(false);
    expect(matchesAccessEvent(event, "all", { ...emptyAccessEventFilters, status: "Failed" }, "Africa/Algiers")).toBe(false);
    expect(matchesAccessEvent(event, "all", { ...emptyAccessEventFilters, end: "2026-09-28T23:59" }, "Africa/Algiers")).toBe(false);
  });

  it("retains live rows arriving during history and applies verification updates", () => {
    const live = { ...event, id: "newer", timestamp: event.timestamp + 1 };
    const updated = { ...event, verification_status: "valid" as const };
    const merged = mergeAccessEvents([event], [live, updated]);
    expect(merged.map((item) => item.id)).toEqual(["newer", "scan"]);
    expect(merged[1].verification_status).toBe("valid");
  });
});
