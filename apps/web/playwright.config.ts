import { defineConfig, devices } from "@playwright/test";

/**
 * E2E tests run against the Next.js dev server.
 * Tests use network interception (page.route) so no real local-worker process is required.
 * Set E2E_BASE_URL to target a running server; otherwise the config starts one automatically.
 *
 * To run:
 *   npm --prefix apps/web run test:e2e
 *
 * If browsers are not installed:
 *   npx playwright install --with-deps chromium
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    trace: "on-first-retry",
    // Grant clipboard permissions so localStorage helpers work cleanly.
    permissions: ["clipboard-read", "clipboard-write"],
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // Start the Next.js dev server automatically when no external URL is provided.
  ...(process.env.E2E_BASE_URL
    ? {}
    : {
        webServer: {
          command: "npm run dev",
          url: "http://localhost:3000",
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      }),
});
