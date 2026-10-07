import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request, triggerTask } from "../api";
import { useEventLog } from "../hooks/useEventLog";
import type { BridgeSettings, StatusResponse } from "../types";

export function BridgePanel({
  status,
  enabled,
}: {
  status?: StatusResponse;
  enabled: boolean;
}) {
  const cache = useQueryClient();
  const settings = useQuery({
    queryKey: ["bridge-settings"],
    queryFn: () => request<BridgeSettings>("/settings/bridge"),
    enabled,
  });
  const events = useEventLog("/events", enabled);
  const [draft, setDraft] = useState<BridgeSettings>();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (settings.data) setDraft(structuredClone(settings.data));
  }, [settings.data]);
  const save = useMutation({
    mutationFn: async () => {
      if (!draft) return;
      // Submit only fields editable here, never state/work paths or actual credentials.
      const {
        immich_url,
        api_key_env,
        api_key_file,
        folders,
        mappings,
        exclusions,
        download_sources,
        automatic,
        automatic_photos,
        api_source_enabled,
        interval,
        folder_interval,
        stable_seconds,
        full_interval,
        source_timezone,
        profile,
      } = draft;
      return request("/settings/bridge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          immich_url,
          api_key_env,
          api_key_file,
          folders,
          mappings,
          exclusions,
          download_sources,
          automatic,
          automatic_photos,
          api_source_enabled,
          interval,
          folder_interval,
          stable_seconds,
          full_interval,
          source_timezone,
          profile: {
            enable_h265: profile.enable_h265,
            enable_flowstate: profile.enable_flowstate,
            enable_directionlock: profile.enable_directionlock,
            enable_stitchfusion: profile.enable_stitchfusion,
            disable_cuda: profile.disable_cuda,
          },
        }),
      });
    },
    onSuccess: () => {
      setOpen(false);
      cache.invalidateQueries({ queryKey: ["bridge-settings"] });
      cache.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const action = useMutation({
    mutationFn: triggerTask,
    onSuccess: () => cache.invalidateQueries({ queryKey: ["status"] }),
  });
  function change<K extends keyof BridgeSettings>(
    key: K,
    value: BridgeSettings[K],
  ) {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
  }
  const recent = events.data?.slice(-10) ?? [];
  return (
    <section className="panel bridge-panel">
      <div className="actions-header">
        <h2>Immich Integration</h2>
        <button className="ghost" onClick={() => setOpen(!open)}>
          Connection and Discovery Settings
        </button>
      </div>
      <p>
        {status?.connection.ok
          ? `Connected to ${status.connection.server} · ${status.connection.version}`
          : status?.connection.error || "Connection not verified"}{" "}
        · Automatic processing{" "}
        {status?.api_paused
          ? "paused due to an authorization error"
          : status?.automatic
            ? "on"
            : "off"}
      </p>
      <p className="muted">
        Last discovery: {status?.scan_summary.groups ?? "—"} complete source
        groups. Next API scan:{" "}
        {status?.next_api_scan
          ? new Date(status.next_api_scan * 1000).toLocaleString("en-US")
          : "manual"}
        . Originals are retained. Local exports are deleted after server SHA-256
        verification.
      </p>
      <div className="action-buttons">
        <button
          className="primary"
          onClick={() => action.mutate("test_connection")}
          disabled={action.isPending}
        >
          Test Connection
        </button>
        <button
          className="primary"
          onClick={() => action.mutate("full_run")}
          disabled={action.isPending}
        >
          Discover and Process Now
        </button>
        {status?.active_tasks?.map((t) => (
          <button
            className="ghost"
            key={t.id}
            onClick={() =>
              request("/tasks/terminate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ task_id: t.id }),
              }).then(() => cache.invalidateQueries({ queryKey: ["status"] }))
            }
          >
            Stop {t.action}
          </button>
        ))}
      </div>
      {action.isError && <p className="error">{action.error.message}</p>}
      {settings.isError && <p className="error">{settings.error.message}</p>}
      {open && draft && (
        <div className="bridge-settings">
          <label>
            Immich URL
            <input
              value={draft.immich_url}
              onChange={(e) => change("immich_url", e.target.value)}
              placeholder="https://photos.example.com"
            />
          </label>
          <p className="muted">
            The API key is read from a server environment variable or a
            read-only secret file. Its value is excluded from settings responses
            and job logs. A configured file takes priority.
          </p>
          <label>
            API Key Environment Variable
            <input
              value={draft.api_key_env}
              onChange={(e) => change("api_key_env", e.target.value)}
            />
          </label>
          <label>
            API Key File Path
            <input
              value={draft.api_key_file}
              onChange={(e) => change("api_key_file", e.target.value)}
              placeholder="/run/secrets/immich-key"
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={draft.api_source_enabled}
              onChange={(e) => change("api_source_enabled", e.target.checked)}
            />
            Discover originals through the Immich API (disable for folder-only
            discovery)
          </label>
          <label>
            <input
              type="checkbox"
              checked={draft.download_sources}
              onChange={(e) => change("download_sources", e.target.checked)}
            />
            Download originals through the API (otherwise use read-only path
            mappings)
          </label>
          <label>
            Additional source folders (one per line, including subfolders)
            <textarea
              rows={3}
              value={draft.folders.join("\n")}
              onChange={(e) =>
                change("folders", e.target.value.split("\n").filter(Boolean))
              }
              placeholder="/sources/insta360"
            />
          </label>
          <label>
            Excluded path patterns (one per line)
            <textarea
              rows={2}
              value={draft.exclusions.join("\n")}
              onChange={(e) =>
                change("exclusions", e.target.value.split("\n").filter(Boolean))
              }
            />
          </label>
          <p>
            Source mappings: Immich originalPath prefix on the left; the
            bridge's readable mount on the right.
          </p>
          {draft.mappings.map((m, i) => (
            <div className="mapping-row" key={i}>
              <input
                aria-label={`Immich path ${i + 1}`}
                value={m.from}
                onChange={(e) =>
                  change(
                    "mappings",
                    draft.mappings.map((x, n) =>
                      n === i ? { ...x, from: e.target.value } : x,
                    ),
                  )
                }
              />
              <span>→</span>
              <input
                aria-label={`Mounted path ${i + 1}`}
                value={m.to}
                onChange={(e) =>
                  change(
                    "mappings",
                    draft.mappings.map((x, n) =>
                      n === i ? { ...x, to: e.target.value } : x,
                    ),
                  )
                }
              />
              <button
                className="ghost"
                onClick={() =>
                  change(
                    "mappings",
                    draft.mappings.filter((_, n) => n !== i),
                  )
                }
              >
                Remove
              </button>
            </div>
          ))}
          <button
            className="ghost"
            onClick={() =>
              change("mappings", [...draft.mappings, { from: "", to: "" }])
            }
          >
            Add Mapping
          </button>
          <label>
            <input
              type="checkbox"
              checked={draft.automatic}
              onChange={(e) => change("automatic", e.target.checked)}
            />
            Automatically discover and process at configured intervals
          </label>
          <label>
            <input
              type="checkbox"
              checked={draft.automatic_photos}
              onChange={(e) => change("automatic_photos", e.target.checked)}
            />
            Automatically process INSP photos (off by default; requires separate
            sample validation)
          </label>
          {(
            [
              "interval",
              "folder_interval",
              "stable_seconds",
              "full_interval",
            ] as const
          ).map((key) => (
            <label key={key}>
              {
                {
                  interval: "API Scan Interval",
                  folder_interval: "Folder Scan Interval",
                  stable_seconds: "File Stability Wait",
                  full_interval: "Full Reconciliation Interval",
                }[key]
              }{" "}
              (seconds)
              <input
                type="number"
                min={1}
                value={draft[key]}
                onChange={(e) => change(key, Number(e.target.value))}
              />
            </label>
          ))}
          <label>
            Time Zone for Filename Capture Dates
            <input
              value={draft.source_timezone}
              onChange={(e) => change("source_timezone", e.target.value)}
            />
          </label>
          <p>
            Set resolution, bitrate, and stitching algorithm in Settings. The
            switches below use the existing converter. Saving does not
            automatically replace existing exports.
          </p>
          {(
            [
              "enable_h265",
              "enable_flowstate",
              "enable_directionlock",
              "enable_stitchfusion",
              "disable_cuda",
            ] as const
          ).map((key) => (
            <label key={key}>
              <input
                type="checkbox"
                checked={draft.profile[key]}
                onChange={(e) =>
                  change("profile", {
                    ...draft.profile,
                    [key]: e.target.checked,
                  })
                }
              />
              {
                {
                  enable_h265: "H.265",
                  enable_flowstate: "FlowState Stabilization",
                  enable_directionlock: "Direction Lock (requires FlowState)",
                  enable_stitchfusion: "Stitch Fusion",
                  disable_cuda: "Disable CUDA",
                }[key]
              }
            </label>
          ))}
          <button
            className="primary"
            disabled={save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "Saving…" : "Save Settings"}
          </button>
          {save.isError && <p className="error">{save.error.message}</p>}
        </div>
      )}
      <details>
        <summary>Recent Activity</summary>
        {recent.map((e) => (
          <div className="mono" key={e.seq}>
            {new Date(e.at * 1000).toLocaleString("en-US")} [{e.stage}]{" "}
            {e.message}
          </div>
        ))}
      </details>
    </section>
  );
}
