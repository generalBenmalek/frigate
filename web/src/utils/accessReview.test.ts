import { describe, expect, it } from "vitest";
import { emptyAccessReviewFilters } from "@/types/accessController";
import { accessReviewParams } from "@/utils/accessReview";

describe("access review search parameters", () => {
  it("defaults to unreviewed grants with server-side pagination", () => {
    expect(
      accessReviewParams(emptyAccessReviewFilters, "Africa/Algiers", 2),
    ).toMatchObject({
      reviewed: "unreviewed",
      page: 2,
      page_size: 50,
      classification: undefined,
    });
  });

  it("converts the configured timezone and preserves controller door zero", () => {
    expect(
      accessReviewParams(
        {
          ...emptyAccessReviewFilters,
          start: "2026-10-03T11:41:58",
          end: "2026-10-03T12:41:58",
          doorId: "0",
          reviewed: "all",
          classification: "warning",
          source: "employee_portal",
          name: "Mohamed",
          userId: "1",
          cardNo: "1200",
          deviceId: "gate",
          camera: "camera",
        },
        "Africa/Algiers",
        1,
      ),
    ).toEqual({
      start: "2026-10-03T10:41:58.000Z",
      end: "2026-10-03T11:41:58.000Z",
      door_id: "0",
      reviewed: "all",
      classification: "warning",
      source: "employee_portal",
      name: "Mohamed",
      user_id: "1",
      card_no: "1200",
      device_id: "gate",
      camera: "camera",
      page: 1,
      page_size: 50,
    });
  });

  it("rejects invalid or reversed time ranges", () => {
    expect(() =>
      accessReviewParams(
        { ...emptyAccessReviewFilters, start: "bad" },
        "UTC",
        1,
      ),
    ).toThrow();
    expect(() =>
      accessReviewParams(
        {
          ...emptyAccessReviewFilters,
          start: "2026-10-04T12:00",
          end: "2026-10-03T12:00",
        },
        "UTC",
        1,
      ),
    ).toThrow("invalid_time_range");
  });
});
