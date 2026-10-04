import type { AccessReviewFilters } from "@/types/accessController";
import { accessFilterTimestamp } from "@/utils/accessController";

export function accessReviewParams(
  filters: AccessReviewFilters,
  timezone: string,
  page: number,
) {
  const start = accessFilterTimestamp(filters.start, timezone);
  const end = accessFilterTimestamp(filters.end, timezone);
  if (start !== undefined && end !== undefined && start > end) {
    throw new Error("invalid_time_range");
  }
  return {
    start:
      start === undefined ? undefined : new Date(start * 1000).toISOString(),
    end: end === undefined ? undefined : new Date(end * 1000).toISOString(),
    name: filters.name || undefined,
    user_id: filters.userId || undefined,
    card_no: filters.cardNo || undefined,
    device_id: filters.deviceId || undefined,
    door_id: filters.doorId || undefined,
    camera: filters.camera || undefined,
    source: filters.source || undefined,
    reviewed: filters.reviewed,
    classification: filters.classification || undefined,
    page,
    page_size: 50,
  };
}
