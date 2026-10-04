import { test, expect } from "../fixtures/frigate-test";
import type { EmployeeRecord } from "../../src/types/employee";

test.describe("Super employee @mobile", () => {
  test("all-door flag persists and restores assignment controls", async ({
    frigateApp,
  }, testInfo) => {
    const employee: EmployeeRecord = {
      id: "mohamed",
      name: "Mohamed",
      display_name: "Mohamed",
      username: "mohamed",
      enabled: true,
      super_employee: false,
      pending: false,
      has_face: true,
      face_name: "Mohamed",
      sources: [],
      permissions: [],
    };
    const submissions: boolean[] = [];
    await frigateApp.page.route("**/api/employees**", async (route) => {
      if (route.request().method() === "PUT") {
        const body = route.request().postDataJSON();
        submissions.push(body.super_employee);
        employee.super_employee = body.super_employee;
        await route.fulfill({ json: employee });
      } else {
        await route.fulfill({ json: [employee] });
      }
    });
    await frigateApp.page.route("**/api/employee-access/**", async (route) => {
      await route.fulfill({
        json: route.request().url().endsWith("/audit")
          ? []
          : { enabled: true, port: 8972, sync: [] },
      });
    });
    await frigateApp.page.route("**/api/faces", (route) =>
      route.fulfill({ json: {} }),
    );
    await frigateApp.page.route("**/api/access-controllers", (route) =>
      route.fulfill({ json: [] }),
    );
    await frigateApp.goto("/employees");
    const page = frigateApp.page;
    await page
      .getByRole("button", { name: "Edit employee", exact: true })
      .click();
    const flag = page.getByRole("switch", {
      name: "Super Employee",
      exact: true,
    });
    await expect(flag).not.toBeChecked();
    await flag.click();
    await expect(flag).toBeChecked();
    await page.screenshot({
      path: testInfo.outputPath("super-employee.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByText("All doors", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Assign doors", exact: true }),
    ).toBeDisabled();
    expect(submissions).toEqual([true]);
    await page
      .getByRole("button", { name: "Edit employee", exact: true })
      .click();
    await expect(flag).toBeChecked();
    await flag.click();
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByText("All doors", { exact: true })).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Assign doors", exact: true }),
    ).toBeEnabled();
    expect(submissions).toEqual([true, false]);
    await page
      .getByRole("button", { name: "Create employee", exact: true })
      .click();
    await expect(flag).not.toBeChecked();
  });
});
