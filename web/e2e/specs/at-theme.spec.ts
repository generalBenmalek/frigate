import { test, expect } from "../fixtures/frigate-test";

test.describe("AT theme @mobile", () => {
  for (const mode of ["light", "dark"] as const) {
    test(`${mode} settings have readable text and visible controls`, async ({
      frigateApp,
    }, testInfo) => {
      const page = frigateApp.page;
      await page.addInitScript((theme) => {
        localStorage.setItem("frigate-ui-theme", JSON.stringify({ theme }));
      }, mode);
      await frigateApp.goto("/settings");
      await expect(page.locator("html")).toHaveClass(/theme-AT/);
      await expect(page.locator("html")).toHaveClass(new RegExp(mode));
      if (frigateApp.isMobile) {
        await page.getByText("UI settings", { exact: true }).click();
      }
      await expect(
        page.getByRole("heading", { name: /UI settings/i, level: 4 }),
      ).toBeInViewport({ ratio: 1 });
      await expect(
        page.locator("#pageRoot").getByRole("switch").first(),
      ).toBeVisible();
      const ratios = await page.evaluate(() => {
        const color = (token: string) => {
          const probe = document.createElement("span");
          probe.style.color = `hsl(var(--${token}))`;
          document.body.appendChild(probe);
          const rgb = getComputedStyle(probe)
            .color.match(/[\d.]+/g)!
            .slice(0, 3)
            .map(Number);
          probe.remove();
          return rgb;
        };
        const luminance = (rgb: number[]) =>
          rgb
            .map((channel) => channel / 255)
            .map((channel) =>
              channel <= 0.04045
                ? channel / 12.92
                : ((channel + 0.055) / 1.055) ** 2.4,
            )
            .reduce(
              (sum, channel, index) =>
                sum + channel * [0.2126, 0.7152, 0.0722][index],
              0,
            );
        const contrast = (a: string, b: string) => {
          const values = [luminance(color(a)), luminance(color(b))].sort(
            (x, y) => y - x,
          );
          return (values[0] + 0.05) / (values[1] + 0.05);
        };
        return {
          text: [
            "foreground",
            "secondary-foreground",
            "muted-foreground",
            "neutral",
            "neutral_variant",
          ].map((token) => contrast(token, "background")),
          pairs: [
            ["primary", "primary-foreground"],
            ["selected", "selected-foreground"],
            ["accent", "accent-foreground"],
            ["popover", "popover-foreground"],
            ["warning", "warning-foreground"],
            ["destructive", "destructive-foreground"],
            ["secondary", "primary"],
          ].map(([a, b]) => contrast(a, b)),
          borders: ["background", "background-alt", "card"].map((token) =>
            contrast("input", token),
          ),
        };
      });
      for (const ratio of [...ratios.text, ...ratios.pairs])
        expect(ratio).toBeGreaterThanOrEqual(4.5);
      for (const ratio of ratios.borders)
        expect(ratio).toBeGreaterThanOrEqual(3);
      await page.screenshot({
        path: testInfo.outputPath(`at-${mode}-settings.png`),
        fullPage: true,
      });
    });
  }

  test("fresh preferences default to AT and explicit choices survive reload", async ({
    frigateApp,
  }) => {
    const page = frigateApp.page;
    await frigateApp.goto("/settings");
    await expect(page.locator("html")).toHaveClass(/theme-AT/);
    await page.evaluate(() => {
      localStorage.setItem(
        "frigate-ui-theme",
        JSON.stringify({
          theme: "light",
          colorScheme: "theme-green",
        }),
      );
    });
    await page.reload();
    await expect(page.locator("html")).toHaveClass(/theme-green/);
    await expect(page.locator("html")).not.toHaveClass(/theme-AT/);
  });
});
