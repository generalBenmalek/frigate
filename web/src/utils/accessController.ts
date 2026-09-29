import { fromZonedTime } from "date-fns-tz";
import type { AccessEvent, AccessEventFilters } from "@/types/accessController";

export function accessFilterTimestamp(value: string, timezone: string): number | undefined {
  if (!value) return undefined;
  const timestamp = fromZonedTime(value, timezone.replace(/^UTC(?=[+-])/, "")).getTime() / 1000;
  if (!Number.isFinite(timestamp)) throw new RangeError("Invalid timestamp");
  return timestamp;
}

export function matchesAccessEvent(
  event: AccessEvent, deviceId: string, filters: AccessEventFilters, timezone: string,
): boolean {
  if (deviceId !== "all" && event.device_id !== deviceId) return false;
  const start = accessFilterTimestamp(filters.start, timezone);
  const end = accessFilterTimestamp(filters.end, timezone);
  if (start !== undefined && event.timestamp < start) return false;
  if (end !== undefined && event.timestamp > end) return false;
  if (filters.status && event.status !== filters.status) return false;
  return [
    [filters.name, event.user_name], [filters.userId, event.user_id],
    [filters.cardNo, event.card_number],
  ].every(([filter, value]) => !String(filter ?? "").trim() ||
    String(value ?? "").toLowerCase().includes(String(filter).trim().toLowerCase()));
}

export function mergeAccessEvents(...collections: AccessEvent[][]): AccessEvent[] {
  const events = new Map<string, AccessEvent>();
  for (const collection of collections) {
    for (const event of collection) events.set(event.id, event);
  }
  return [...events.values()].sort((a, b) => b.timestamp - a.timestamp || a.id.localeCompare(b.id)).slice(0, 500);
}
