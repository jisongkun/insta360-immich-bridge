import { useState } from "react";
import { useEventLog, eventLevel, saveLog } from "../hooks/useEventLog";
import { useQuery } from "@tanstack/react-query";
import { request } from "../api";
import type { Job } from "../types";

export function BridgeJobDetails({
  job,
  onClose,
}: {
  job: Job;
  onClose: () => void;
}) {
  const events = useEventLog(`/jobs/${job.id}/events`);
  const [level, setLevel] = useState("all");
  const logs = useQuery({
    queryKey: ["job-logs", job.id],
    queryFn: () =>
      request<{
        stage: string;
        phase: string;
        error?: string;
        logs: Array<{ name: string; text: string }>;
      }>(`/jobs/${job.id}/logs`),
    enabled: !events.paused,
    refetchInterval: events.paused ? false : 3000,
  });
  const details = useQuery({
    queryKey: ["job-details", job.id],
    queryFn: () => request<object>(`/jobs/${job.id}/details`),
  });
  return (
    <div className="modal-backdrop">
      <div
        className="modal job-details"
        role="dialog"
        aria-modal="true"
        aria-label="Job details"
      >
        <div className="actions-header">
          <h3>Job {job.id}</h3>
          <button className="ghost" onClick={onClose}>
            Close
          </button>
        </div>
        <p>
          Current stage: {job.stage} · Resume phase: {job.phase}
        </p>
        <p>
          Immich asset: {job.asset_id ?? "not uploaded"} · Verification:{" "}
          {job.verified ? "passed" : "pending"} · Local export:{" "}
          {job.local_deleted ? "deleted" : "retained / not generated yet"}
        </p>
        {job.error && <p className="error">{job.error}</p>}
        <details>
          <summary>Sources, Target, and Effective Settings</summary>
          <pre>{JSON.stringify(details.data, null, 2)}</pre>
        </details>
        <div className="action-buttons">
          <button
            className="ghost"
            onClick={() => events.setPaused(!events.paused)}
          >
            {events.paused ? "Resume Logs" : "Pause Logs"}
          </button>
          <select
            aria-label="Event level"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          >
            <option value="all">All Levels</option>
            <option value="error">Error</option>
            <option value="warn">Warning</option>
            <option value="info">Info</option>
          </select>
          <button
            className="ghost"
            onClick={() =>
              saveLog(
                `bridge-${job.id}.log`,
                (events.data ?? [])
                  .map(
                    (e) =>
                      `${new Date(e.at * 1000).toISOString()} [${eventLevel(e)}] [${e.stage}] ${e.message}`,
                  )
                  .join("\n") +
                  "\n\n" +
                  (logs.data?.logs ?? [])
                    .map((l) => `${l.name}\n${l.text}`)
                    .join("\n\n"),
              )
            }
          >
            Download Loaded Logs
          </button>
        </div>
        <h4>Stage Events (up to 5,000 retained; levels derived from stages)</h4>
        {events.data
          ?.filter((e) => level === "all" || eventLevel(e) === level)
          .map((e) => (
            <div key={e.seq} className="mono">
              {new Date(e.at * 1000).toLocaleString("en-US")} [{e.stage}]{" "}
              {e.message}
            </div>
          ))}
        <h4>SDK / Conversion Logs (last 64 KiB per file)</h4>
        {logs.data?.logs.map((l) => (
          <details key={l.name} open>
            <summary>{l.name}</summary>
            <pre>{l.text}</pre>
          </details>
        ))}
        {[events.error, logs.error, details.error]
          .filter(Boolean)
          .map((e, i) => (
            <p key={i} className="error">
              {(e as Error).message}
            </p>
          ))}
      </div>
    </div>
  );
}
