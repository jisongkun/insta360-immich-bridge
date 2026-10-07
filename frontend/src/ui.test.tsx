import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { BridgePanel } from "./components/BridgePanel";
import { getAuthToken, request, setAuthToken } from "./api";
import type { BridgeSettings, Job, StatusResponse } from "./types";

const profile = {
  output_size: "7680x3840",
  bitrate: "200000000",
  stitch_type: "aistitch",
  auto_resolution: false,
  original_bitrate: false,
  enable_h265: true,
  enable_flowstate: true,
  enable_directionlock: true,
  enable_stitchfusion: true,
  disable_cuda: false,
};
const initialSettings: BridgeSettings = {
  immich_url: "http://immich",
  api_key_env: "IMMICH_API_KEY",
  api_key_file: "/run/secrets/key",
  folders: [],
  mappings: [],
  exclusions: [],
  download_sources: false,
  automatic: false,
  automatic_photos: false,
  api_source_enabled: true,
  interval: 60,
  folder_interval: 600,
  stable_seconds: 60,
  full_interval: 86400,
  source_timezone: "Asia/Shanghai",
  profile,
};
const initialStatus: StatusResponse = {
  jobs: [],
  connection: { ok: true, server: "http://immich/api", version: "v3.2.4" },
  automatic: false,
  api_paused: false,
  next_api_scan: null,
  next_folder_scan: null,
  scan_summary: { groups: 0 },
  active_jobs: [],
  active_tasks: [],
  pending_jobs: 0,
  queued_jobs: 0,
  max_parallel_jobs: 1,
  expected_size_ratio: 1,
  stitch_settings: profile,
  concurrency: { stitch: 1, scan: 4, deep_scan: 1, thumbnails: 2 },
};
const job: Job = {
  id: "job-1",
  timestamp: "2026-10-07T12:00:00Z",
  final_file: "/work/test.mp4",
  source_files: [],
  status: "unprocessed",
  queue_state: "queued",
  pid: null,
  stitched_size: 0,
  process: 0,
  expected_size: 100,
  created_at: "2026-10-07T12:00:00Z",
  updated_at: "2026-10-07T12:00:00Z",
  thumbnail_url: null,
  stage: "pending",
  phase: "converting",
  verified: false,
  owned: false,
  remote_missing: false,
  local_deleted: false,
  recipe: "recipe",
};
let saved: BridgeSettings;
let status: StatusResponse;
let submissions: Array<{ path: string; body: Record<string, unknown> }>;
let stopFails = false;
function response(data: unknown, code = 200) {
  return new Response(JSON.stringify(data), { status: code });
}
function mount(panel = false) {
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={cache}>
      {panel ? <BridgePanel enabled status={status} /> : <App />}
    </QueryClientProvider>,
  );
  return cache;
}
beforeEach(() => {
  setAuthToken("test-bridge-token");
  saved = structuredClone(initialSettings);
  status = structuredClone(initialStatus);
  submissions = [];
  stopFails = false;
  vi.stubGlobal(
    "fetch",
    async (input: string | Request | URL, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body ?? "{}"));
        submissions.push({ path, body });
        if (path === "/settings/bridge") {
          if (body.profile?.output_size === "bad")
            return response({ error: "Invalid output_size" }, 400);
          saved = {
            ...saved,
            ...body,
            profile: { ...saved.profile, ...body.profile },
          };
          delete (saved as unknown as Record<string, unknown>).immich_api_key;
          return response(saved);
        }
        if (path === "/settings/stitch" && body.output_size === "bad")
          return response({ error: "Invalid output_size" }, 400);
        if (path === "/settings/parallelism")
          status.concurrency = {
            ...status.concurrency!,
            stitch: body.stitch_parallelism,
          };
        if (path === "/settings/ratio")
          status.expected_size_ratio = body.expected_size_ratio;
        if (path === "/settings/ratio/compute")
          return response({ expected_size_ratio: 2 });
        if (path === "/tasks/terminate" && stopFails)
          return response({ error: "Stop request failed" }, 500);
        return response({
          task_id: "task-new",
          scheduled: body.action,
          ...body,
        });
      }
      if (path === "/settings/bridge") return response(saved);
      if (path === "/status") return response(status);
      if (path.includes("/events")) return response({ events: [] });
      if (path.includes("/logs"))
        return response({ stage: "pending", phase: "converting", logs: [] });
      if (path.includes("/details")) return response({});
      throw new Error("Unexpected request " + path);
    },
  );
});
afterEach(() => {
  cleanup();
  setAuthToken(null);
  vi.unstubAllGlobals();
});

describe("bridge authentication", () => {
  it("locks already open settings and Stop controls when login expires", async () => {
    const user = userEvent.setup();
    const cache = mount();
    await screen.findByText(/Connected to/);
    await user.click(screen.getByRole("button", { name: "Connection and Discovery Settings" }));
    await screen.findByLabelText("Immich URL", { exact: true });
    await user.click(screen.getByRole("button", { name: "Settings", exact: true }));
    await act(async () => cache.setQueryData(["status"], {
      ...status,
      active_tasks: [{ id: "running", action: "scan", started_at: "2026-10-07T12:00:00Z" }],
    }));
    const originalFetch = fetch;
    vi.stubGlobal("fetch", (input: string | Request | URL, init?: RequestInit) =>
      String(input) === "/status"
        ? Promise.resolve(response({ error: "Login required" }, 401))
        : originalFetch(input, init),
    );
    await act(async () => { await cache.invalidateQueries({ queryKey: ["status"] }); });
    await screen.findByRole("heading", { name: "Bridge Login" });
    for (const name of ["Save", "Compute Ratio", "Stop scan"]) {
      expect((screen.getByRole("button", { name, exact: true }) as HTMLButtonElement).disabled).toBe(true);
    }
    // The connection editor's native disabled fieldset blocks its Save too.
    expect(screen.getByRole("group", { name: "Connection and Discovery Settings" }).getAttribute("disabled")).not.toBeNull();
  });
  it("a late unauthorized response cannot clear a newer browser login", async () => {
    let release!: (value: Response) => void;
    vi.stubGlobal("fetch", () => new Promise<Response>((resolve) => {
      release = resolve;
    }));
    const pending = request("/status").catch(
      (error: Error & { status?: number }) => error.status,
    );
    setAuthToken("newer-bridge-token");
    release(response({ error: "Login required" }, 401));
    expect(await pending).toBe(401);
    expect(getAuthToken()).toBe("newer-bridge-token");
  });
  it("opens login immediately on a new browser and blocks protected actions", () => {
    setAuthToken(null);
    vi.stubGlobal("fetch", () => new Promise<Response>(() => {}));
    mount();
    expect(screen.getByRole("heading", { name: "Bridge Login" })).toBeTruthy();
    expect(screen.queryByText("Command running…")).toBeNull();
    expect(
      (screen.getByRole("button", { name: "Test Connection" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("a rejected Test Connection opens login and can recover with the bridge token", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText(/Connected to/);
    const originalFetch = fetch;
    let taskAuthorized = false;
    vi.stubGlobal("fetch", (input: string | Request | URL, init?: RequestInit) => {
      if (String(input) === "/tasks") {
        taskAuthorized = (init?.headers as Record<string, string>).Authorization ===
          "Bearer replacement-bridge-token";
        return Promise.resolve(taskAuthorized
          ? response({ task_id: "connection-task", scheduled: "test_connection" })
          : response({ error: "Login required" }, 401));
      }
      if (String(input) === "/login") {
        return Promise.resolve(JSON.parse(String(init?.body)).token === "replacement-bridge-token"
          ? response({ ok: true }) : response({ error: "Invalid token" }, 401));
      }
      return originalFetch(input, init);
    });
    await user.click(screen.getByRole("button", { name: "Test Connection" }));
    await screen.findByRole("heading", { name: "Bridge Login" });
    expect(getAuthToken()).toBeNull();
    const token = screen.getByLabelText("Bridge access token");
    await user.clear(token);
    await user.type(token, "wrong-token");
    await user.click(screen.getByRole("button", { name: "Login", exact: true }));
    await screen.findByText(/Invalid token/);
    expect((token as HTMLInputElement).value).toBe("wrong-token");
    await user.clear(token);
    await user.type(token, "replacement-bridge-token");
    await user.click(screen.getByRole("button", { name: "Login", exact: true }));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Bridge Login" })).toBeNull(),
    );
    await user.click(screen.getByRole("button", { name: "Test Connection" }));
    await waitFor(() => expect(taskAuthorized).toBe(true));
    expect(getAuthToken()).toBe("replacement-bridge-token");
  });
});

describe("configuration and task usability", () => {
  it("Cancel discards connection edits and clears the one-way API key input", async () => {
    const user = userEvent.setup();
    mount(true);
    await user.click(
      screen.getByRole("button", { name: "Connection and Discovery Settings" }),
    );
    const url = await screen.findByRole("textbox", { name: "Immich URL" });
    await user.clear(url);
    await user.type(url, "http://abandoned");
    await user.type(
      screen.getByLabelText("Immich API Key", { exact: true }),
      "discard-me",
    );
    await user.click(
      screen.getByRole("button", { name: "Cancel", exact: true }),
    );
    await user.click(
      screen.getByRole("button", { name: "Connection and Discovery Settings" }),
    );
    expect(
      (screen.getByRole("textbox", { name: "Immich URL" }) as HTMLInputElement)
        .value,
    ).toBe("http://immich");
    expect(
      (
        screen.getByLabelText("Immich API Key", {
          exact: true,
        }) as HTMLInputElement
      ).value,
    ).toBe("");
    expect(submissions).toEqual([]);
  });
  it("saving a key submits it once and never refills the password field", async () => {
    const user = userEvent.setup();
    mount(true);
    await user.click(
      screen.getByRole("button", { name: "Connection and Discovery Settings" }),
    );
    await user.type(
      await screen.findByLabelText("Immich API Key", { exact: true }),
      "new-private-key",
    );
    await user.click(
      screen.getByRole("button", { name: "Save Settings", exact: true }),
    );
    await waitFor(() =>
      expect(
        screen.queryByLabelText("Immich API Key", { exact: true }),
      ).toBeNull(),
    );
    expect(submissions[0].body.immich_api_key).toBe("new-private-key");
    await user.click(
      screen.getByRole("button", { name: "Connection and Discovery Settings" }),
    );
    expect(
      (
        screen.getByLabelText("Immich API Key", {
          exact: true,
        }) as HTMLInputElement
      ).value,
    ).toBe("");
  });
  it("status polling does not overwrite an unsaved converter draft", async () => {
    const user = userEvent.setup();
    const cache = mount();
    await screen.findByText(/Connected to/);
    await user.click(
      screen.getByRole("button", { name: "Settings", exact: true }),
    );
    const input = screen.getByLabelText("Output resolution");
    await user.clear(input);
    await user.type(input, "3840x1920");
    await act(async () => {
      cache.setQueryData(["status"], {
        ...status,
        jobs: [job],
        stitch_settings: { ...profile, bitrate: "100000000" },
      });
    });
    await screen.findByRole("button", { name: job.timestamp });
    expect((input as HTMLInputElement).value).toBe("3840x1920");
  });
  it("a rejected Save uses one request and leaves unrelated settings unchanged", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText(/Connected to/);
    await user.click(
      screen.getByRole("button", { name: "Settings", exact: true }),
    );
    await user.clear(screen.getByLabelText("Output resolution"));
    await user.type(screen.getByLabelText("Output resolution"), "bad");
    const concurrency = screen.getByLabelText("Stitching jobs");
    await user.clear(concurrency);
    await user.type(concurrency, "3");
    await user.click(screen.getByRole("button", { name: "Save", exact: true }));
    await screen.findByText(/Invalid output_size/);
    expect(status.concurrency!.stitch).toBe(1);
    expect(
      submissions.filter((x) => x.path.startsWith("/settings/")),
    ).toHaveLength(1);
  });
  it("successful Save reopens with accepted values while status refresh is delayed", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText(/Connected to/);
    const originalFetch = fetch;
    vi.stubGlobal(
      "fetch",
      (input: string | Request | URL, init?: RequestInit) =>
        String(input) === "/status"
          ? new Promise<Response>(() => {})
          : originalFetch(input, init),
    );
    await user.click(
      screen.getByRole("button", { name: "Settings", exact: true }),
    );
    const output = screen.getByLabelText("Output resolution");
    await user.clear(output);
    await user.type(output, "3840x1920");
    await user.click(screen.getByRole("button", { name: "Save", exact: true }));
    await waitFor(() =>
      expect(screen.queryByLabelText("Output resolution")).toBeNull(),
    );
    await user.click(
      screen.getByRole("button", { name: "Settings", exact: true }),
    );
    expect(
      (screen.getByLabelText("Output resolution") as HTMLInputElement).value,
    ).toBe("3840x1920");
  });
  it("numeric settings allow clearing and replacing a value", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText(/Connected to/);
    await user.click(
      screen.getByRole("button", { name: "Settings", exact: true }),
    );
    for (const label of [
      "Stitching jobs",
      "Scan jobs",
      "Deep scan jobs",
      "Thumbnail jobs",
      "Expected size ratio",
    ]) {
      const input = screen.getByLabelText(label);
      await user.clear(input);
      expect((input as HTMLInputElement).value).toBe("");
      await user.type(input, "3");
      expect((input as HTMLInputElement).value).toBe("3");
    }
  });
  it("a late Compute Ratio response cannot modify a reopened settings draft", async () => {
    const user = userEvent.setup();
    const cache = mount();
    await screen.findByText(/Connected to/);
    const originalFetch = fetch;
    let release!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      (input: string | Request | URL, init?: RequestInit) =>
        String(input) === "/settings/ratio/compute"
          ? new Promise<Response>((resolve) => {
              release = resolve;
            })
          : originalFetch(input, init),
    );
    await user.click(
      screen.getByRole("button", { name: "Settings", exact: true }),
    );
    await user.click(screen.getByRole("button", { name: "Compute Ratio" }));
    await waitFor(() => expect(release).toBeTypeOf("function"));
    await user.click(
      screen.getByRole("button", { name: "Cancel", exact: true }),
    );
    await user.click(
      screen.getByRole("button", { name: "Settings", exact: true }),
    );
    const ratio = screen.getByLabelText("Expected size ratio");
    await user.clear(ratio);
    await user.type(ratio, "3");
    release(response({ expected_size_ratio: 2 }));
    await waitFor(() =>
      expect(
        cache
          .getMutationCache()
          .getAll()
          .some(
            (m) =>
              (m.state.data as { expected_size_ratio?: number } | undefined)
                ?.expected_size_ratio === 2,
          ),
      ).toBe(true),
    );
    expect((ratio as HTMLInputElement).value).toBe("3");
  });
  it("locks processing controls for tasks started outside this tab", async () => {
    status.active_tasks = [
      {
        id: "remote-task",
        action: "full_run",
        started_at: "2026-10-07T12:00:00Z",
      },
    ];
    mount();
    await screen.findByText(/Connected to/);
    expect(
      (
        screen.getByRole("button", {
          name: /Stitch Pending/,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: "Discover and Process Now",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
  it("open job details update delivery receipts when status changes", async () => {
    status.jobs = [job];
    const user = userEvent.setup();
    const cache = mount();
    await user.click(
      await screen.findByRole("button", { name: job.timestamp }),
    );
    const done = {
      ...job,
      stage: "done",
      status: "processed",
      asset_id: "uploaded-asset",
      verified: true,
      local_deleted: true,
    };
    await act(async () => {
      cache.setQueryData(["status"], { ...status, jobs: [done] });
    });
    const receipt = await screen.findByText(/Immich asset: uploaded-asset/);
    expect(receipt.textContent).toContain("Verification: passed");
    expect(receipt.textContent).toContain("Local export: deleted");
  });
  it("shows a failed stop request instead of an unhandled rejection", async () => {
    status.active_tasks = [
      { id: "remote-task", action: "scan", started_at: "2026-10-07T12:00:00Z" },
    ];
    stopFails = true;
    const user = userEvent.setup();
    mount(true);
    await user.click(
      screen.getByRole("button", { name: "Stop scan", exact: true }),
    );
    await screen.findByText("Stop request failed");
  });
});
