import { defineConfig } from "@playwright/test";
import { loadEnv } from "vite";

/**
 * E2E runs against the real stack: the API is started with migrations + demo seed, and Vite proxies
 * /api to it. `E2E_SKIP_WEBSERVER=1` points the suite at services you started yourself (e.g. CI job
 * that boots docker compose first).
 */
const env = { ...loadEnv("", process.cwd(), ""), ...process.env };
const API_PORT = env.E2E_API_PORT ?? "8000";
const WEB_PORT = env.E2E_WEB_PORT ?? "5173";
const skip = env.E2E_SKIP_WEBSERVER === "1";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 8_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"], ["html", { open: "never" }]],
  outputDir: "test-results/e2e",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    locale: "ar-EG",
    timezoneId: "Africa/Cairo",
    browserName: "chromium",
  },
  projects: [
    // the screenshot sizes the spec asks for: 1440×900 desktop and 390×844 phone
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
  ],
  webServer: skip
    ? undefined
    : [
        {
          command: `bash -lc 'cd ../backend && (test -n "$DATABASE_URL" || export DATABASE_URL="sqlite+aiosqlite:///$(pwd)/e2e.db") && export ENV=dev INTEGRATIONS_DRIVER=sim CELERY_TASK_ALWAYS_EAGER=1 STORAGE_DIR="$(pwd)/../.e2e-storage" && rm -f e2e.db && python -m alembic -c alembic.ini upgrade head && python -m app.seed && python -m uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT}'`,
          cwd: process.cwd(),
          url: `http://127.0.0.1:${API_PORT}/healthz`,
          reuseExistingServer: true,
          timeout: 180_000,
          stdout: "pipe",
          stderr: "pipe",
          env: { PYTHONPATH: "backend" },
        },
        {
          command: `bash -lc 'VITE_API_ORIGIN=http://127.0.0.1:${API_PORT} npm run dev -- --port ${WEB_PORT} --strictPort'`,
          cwd: process.cwd(),
          url: `http://127.0.0.1:${WEB_PORT}`,
          reuseExistingServer: true,
          timeout: 120_000,
          stdout: "pipe",
          stderr: "pipe",
        },
      ],
});
