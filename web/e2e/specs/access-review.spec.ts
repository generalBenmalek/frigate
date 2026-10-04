import { test, expect, type FrigateApp } from "../fixtures/frigate-test";
import type { AccessEvent } from "../../src/types/accessController";

function accessEvent(
  id: string,
  status: "valid" | "warning" | "unknown" | "pending",
): AccessEvent {
  return {
    id,
    device_id: "gate",
    device_name: "Main gate",
    timestamp: 1791024118,
    user_name: id === "valid" ? "Mohamed" : id,
    user_id: "1",
    door_id: "0",
    status: "OK",
    type: "Entry",
    verification_status: status,
    machine_status: status,
    effective_status: status,
    reviewed: false,
    review_revision: 0,
    source: "employee_portal",
    camera: "front_door",
    clip_start: 1791024108,
    clip_end: 1791024128,
  };
}

async function installAccessMocks(app: FrigateApp) {
  const state = {
    events: ["valid", "warning", "unknown", "pending"].map((status) =>
      accessEvent(
        status,
        status as "valid" | "warning" | "unknown" | "pending",
      ),
    ),
    failSubmission: false,
    submissions: [] as {
      action: string;
      classification?: string;
      expected_revision: number;
    }[],
  };
  await app.page.route("**/api/access-controllers**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/events/review")) {
      const params = url.searchParams;
      const filtered = state.events.filter(
        (event) =>
          (params.get("reviewed") === "all" ||
            !!event.reviewed === (params.get("reviewed") === "reviewed")) &&
          (!params.get("name") ||
            event.user_name
              ?.toLowerCase()
              .includes(params.get("name")!.toLowerCase())),
      );
      const counts = {
        all: filtered.length,
        valid: 0,
        warning: 0,
        unknown: 0,
        pending: 0,
      };
      for (const event of filtered)
        counts[
          event.effective_status as "valid" | "warning" | "unknown" | "pending"
        ]++;
      const events = filtered.filter(
        (event) =>
          !params.get("classification") ||
          event.effective_status === params.get("classification"),
      );
      await route.fulfill({
        json: { events, total: events.length, counts, page: 1, page_size: 50 },
      });
    } else if (url.pathname.endsWith("/reviews")) {
      await route.fulfill({ json: [] });
    } else if (url.pathname.endsWith("/review")) {
      if (state.failSubmission) {
        await route.fulfill({
          status: 409,
          json: { reason: "review_conflict" },
        });
        return;
      }
      const body = route.request().postDataJSON();
      state.submissions.push(body);
      const id = url.pathname.split("/").at(-2);
      const event = state.events.find((item) => item.id === id)!;
      event.reviewed = true;
      event.review_revision = (event.review_revision ?? 0) + 1;
      event.effective_status =
        body.action === "confirm" ? event.machine_status : body.classification;
      event.review_status = event.effective_status as
        | "valid"
        | "warning"
        | "unknown";
      event.reviewed_by = "admin";
      await route.fulfill({ json: event });
    } else if (url.pathname.endsWith("/sync")) {
      await route.fulfill({ json: { results: [] } });
    } else if (url.pathname.endsWith("/events")) {
      await route.fulfill({ json: state.events });
    } else {
      await route.fulfill({
        json: [
          {
            id: "gate",
            name: "Main gate",
            ip_address: "127.0.0.1",
            port: 80,
            provider: "cgi",
            sdk_port: 37777,
            use_https: false,
            type: "Dahua",
            model: "Test",
            serial_number: "",
            status: "online",
            associated_camera: "front_door",
            seconds_before: 10,
            seconds_after: 10,
          },
        ],
      });
    }
  });
  await app.goto("/access-controller");
  await app.page.getByRole("tab", { name: "Review", exact: true }).click();
  await expect(
    app.page.getByRole("row").filter({ hasText: "Mohamed" }),
  ).toBeVisible();
  return state;
}

test.describe("Access review @mobile", () => {
  test.use({
    expectedErrors: [
      /status of 409|status of 404.*front_door|front_door.*net::ERR/,
    ],
  });
  test("counts, filters, pending controls and responsive layout", async ({
    frigateApp,
  }, testInfo) => {
    await installAccessMocks(frigateApp);
    const page = frigateApp.page;
    await expect(
      page.getByRole("button", { name: /Warning\s+1/ }),
    ).toBeVisible();
    await page.getByRole("row").filter({ hasText: "Mohamed" }).click();
    await expect(
      page.getByRole("button", { name: "Confirm machine status" }),
    ).toBeEnabled();
    await page.screenshot({
      path: testInfo.outputPath("access-review.png"),
      fullPage: true,
    });
    await expect(page.locator("#review-start")).toBeVisible();
    await expect(page.locator("#review-end")).toBeVisible();
    await page.getByRole("button", { name: /Pending\s+1/ }).click();
    await page.getByRole("row").filter({ hasText: "pending" }).click();
    await expect(
      page.getByRole("button", { name: "Confirm machine status" }),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Submit review" }),
    ).toBeDisabled();
    await page.locator("#review-name").fill("Mohamed");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(
      page.getByText("No access grants match these filters."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /Valid\s+1/ })).toBeVisible();
  });

  test("confirmation and correction mark grants reviewed", async ({
    frigateApp,
  }) => {
    const state = await installAccessMocks(frigateApp);
    const page = frigateApp.page;
    await page.getByRole("row").filter({ hasText: "Mohamed" }).click();
    await page.getByRole("button", { name: "Confirm machine status" }).click();
    await expect(
      page.getByRole("row").filter({ hasText: "Mohamed" }),
    ).toHaveCount(0);
    expect(state.submissions[0]).toEqual({
      action: "confirm",
      expected_revision: 0,
    });
    await page.getByRole("row").filter({ hasText: "warning" }).click();
    await page.locator("#review-classification").click();
    await page.getByRole("option", { name: "Valid", exact: true }).click();
    await page.getByRole("button", { name: "Submit review" }).click();
    await expect(
      page.getByRole("row").filter({ hasText: "warning" }),
    ).toHaveCount(0);
    expect(state.submissions[1]).toEqual({
      action: "correct",
      classification: "valid",
      expected_revision: 0,
    });
    await page.locator("#review-reviewed").click();
    await page.getByRole("option", { name: "Reviewed", exact: true }).click();
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(
      page.getByRole("row").filter({ hasText: "Mohamed" }),
    ).toBeVisible();
    await page.getByRole("row").filter({ hasText: "Mohamed" }).click();
    await expect(page.getByText("admin", { exact: true })).toBeVisible();
  });

  test("conflict is reported and realtime counts refresh", async ({
    frigateApp,
  }) => {
    const state = await installAccessMocks(frigateApp);
    state.failSubmission = true;
    await frigateApp.page
      .getByRole("row")
      .filter({ hasText: "Mohamed" })
      .click();
    await frigateApp.page
      .getByRole("button", { name: "Confirm machine status" })
      .click();
    await expect(frigateApp.page.getByRole("alert")).toContainText(
      "reviewed by another administrator",
    );
    state.events.push(accessEvent("new", "warning"));
    frigateApp.ws.send(
      "access_controller_events",
      JSON.stringify(state.events.at(-1)),
    );
    await expect(
      frigateApp.page.getByRole("button", { name: /Warning\s+2/ }),
    ).toBeVisible();
    await expect(
      frigateApp.page.getByRole("row").filter({ hasText: "new" }),
    ).toBeVisible();
  });

  test("footage unavailable fallback leaves review accessible", async ({
    frigateApp,
  }) => {
    await installAccessMocks(frigateApp);
    await frigateApp.page.route("**/api/front_door/start/**", async (route) => {
      await route.fulfill({ status: 404, body: "" });
    });
    await frigateApp.page
      .getByRole("row")
      .filter({ hasText: "Mohamed" })
      .click();
    await frigateApp.page
      .getByRole("button", { name: "View footage", exact: true })
      .click();
    await expect(frigateApp.page.getByRole("dialog")).toBeVisible();
    await expect(
      frigateApp.page.getByRole("dialog").getByRole("status"),
    ).toHaveText("No camera footage is available for this event.");
    await frigateApp.page.keyboard.press("Escape");
    await expect(
      frigateApp.page.getByRole("button", { name: "Confirm machine status" }),
    ).toBeEnabled();
  });
});
