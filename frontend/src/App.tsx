import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  regenerateJobs,
  fetchStatus,
  generateThumbnailsForJobs,
  getAuthToken,
  login,
  setAuthToken,
  stitchSelectedJobs,
  triggerTask,
  terminateTask,
  request,
  computeExpectedRatio,
} from "./api";
import type { BridgeSettings, StatusResponse, Job, TaskAction } from "./types";
import { JobTable } from "./components/JobTable";
import { BridgePanel } from "./components/BridgePanel";
import { BridgeJobDetails } from "./components/BridgeJobDetails";
import "./App.css";

const ACTIONS: Array<{
  action: TaskAction;
  label: string;
  description: string;
}> = [
  {
    action: "scan",
    label: "Scan",
    description: "Discover stable sources; does not start conversion",
  },
  {
    action: "deep_scan",
    label: "Deep Scan",
    description: "Full source reconciliation and remote receipt check",
  },
  {
    action: "stitch",
    label: "Stitch Pending",
    description: "Run stitcher for queued items only",
  },
  {
    action: "full_stitch",
    label: "Retry Failed",
    description: "Attempt stitching for failed jobs as well",
  },
  {
    action: "generate_thumbnails",
    label: "Generate Thumbnails",
    description: "Extract preview thumbnails for jobs missing them",
  },
];

const SELECTABLE_STATUSES = new Set<Job["status"]>([
  "unprocessed",
  "failed",
  "processed",
]);

const statusOrder: Record<TaskAction | "status", number> = {
  scan: 0,
  deep_scan: 1,
  stitch: 2,
  full_stitch: 3,
  generate_thumbnails: 4,
  stitch_selected: 5,
  full_run: 6,
  regenerate_selected: 7,
  test_connection: 8,
  status: 4,
};

export default function App() {
  const [detailsJobId, setDetailsJobId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const [pollingFast, setPollingFast] = useState(false);
  const statusQuery = useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: pollingFast ? 1000 : 15000,
  });

  const mutation = useMutation({
    mutationFn: (action: TaskAction) => triggerTask(action),
    onSuccess: (data, action) => {
      setActiveTask({ id: data.task_id, action });
      setLastTaskTriggeredAt(Date.now());
      setConfirmStop(false);
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });

  const jobs = statusQuery.data?.jobs ?? [];
  const detailsJob = jobs.find((job) => job.id === detailsJobId);
  const [selectedJobs, setSelectedJobs] = useState<Set<string>>(new Set());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsGeneration = useRef(0);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginTokenValue, setLoginTokenValue] = useState("");
  const [activeTask, setActiveTask] = useState<{
    id: string;
    action: TaskAction;
  } | null>(null);
  const [lastTaskTriggeredAt, setLastTaskTriggeredAt] = useState(0);
  const [confirmStop, setConfirmStop] = useState(false);
  const [stitchConcurrencyValue, setStitchConcurrencyValue] = useState<
    number | string
  >(1);
  const [scanConcurrencyValue, setScanConcurrencyValue] = useState<
    number | string
  >(25);
  const [deepScanConcurrencyValue, setDeepScanConcurrencyValue] = useState<
    number | string
  >(1);
  const [thumbnailConcurrencyValue, setThumbnailConcurrencyValue] = useState<
    number | string
  >(4);
  const [ratioValue, setRatioValue] = useState<number | string>(1);
  const [outputSizeValue, setOutputSizeValue] = useState("");
  const [bitrateValue, setBitrateValue] = useState("");
  const [stitchTypeValue, setStitchTypeValue] = useState("");
  const [autoResolution, setAutoResolution] = useState(false);
  const [originalBitrate, setOriginalBitrate] = useState(false);

  useEffect(() => {
    setSelectedJobs((prev) => {
      const validIds = new Set(
        jobs
          .filter((job) => SELECTABLE_STATUSES.has(job.status))
          .map((job) => job.id),
      );
      const next = new Set<string>();
      prev.forEach((id) => {
        if (validIds.has(id)) {
          next.add(id);
        }
      });
      return next.size === prev.size ? prev : next;
    });
  }, [jobs]);

  const settingsMutation = useMutation({
    mutationFn: async () => {
      const sanitizedStitchConcurrency = Number(stitchConcurrencyValue);
      const sanitizedScanConcurrency = Number(scanConcurrencyValue);
      const sanitizedDeepConcurrency = Number(deepScanConcurrencyValue);
      const sanitizedThumbnailConcurrency = Number(thumbnailConcurrencyValue);
      const sanitizedOutput = outputSizeValue.trim();
      const sanitizedBitrate = bitrateValue.trim();
      const sanitizedStitchType = stitchTypeValue.trim();
      const saved = await request<BridgeSettings>("/settings/bridge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stitch_parallelism: sanitizedStitchConcurrency,
          scan_parallelism: sanitizedScanConcurrency,
          deep_scan_parallelism: sanitizedDeepConcurrency,
          thumbnail_parallelism: sanitizedThumbnailConcurrency,
          expected_size_ratio: Number(ratioValue),
          profile: {
            output_size: sanitizedOutput,
            bitrate: sanitizedBitrate,
            stitch_type: sanitizedStitchType,
            auto_resolution: autoResolution,
            original_bitrate: originalBitrate,
          },
        }),
      });
      return {
        saved,
        ratio: Number(ratioValue),
        concurrency: {
          stitch: sanitizedStitchConcurrency,
          scan: sanitizedScanConcurrency,
          deep_scan: sanitizedDeepConcurrency,
          thumbnails: sanitizedThumbnailConcurrency,
        },
      };
    },
    onSuccess: ({ saved, ratio, concurrency }) => {
      queryClient.setQueryData(["bridge-settings"], saved);
      queryClient.setQueryData<StatusResponse>(["status"], (previous) =>
        previous
          ? {
              ...previous,
              stitch_settings: saved.profile,
              expected_size_ratio: ratio,
              concurrency,
              max_parallel_jobs: concurrency.stitch,
            }
          : previous,
      );
      queryClient.invalidateQueries({ queryKey: ["status"] });
      closeSettings();
    },
  });

  const computeRatioMutation = useMutation({
    mutationFn: (_generation: number) => computeExpectedRatio(),
    onSuccess: (data, generation) => {
      if (generation === settingsGeneration.current)
        setRatioValue(data.expected_size_ratio);
    },
  });

  const stitchSelectedMutation = useMutation({
    mutationFn: (jobIds: string[]) => stitchSelectedJobs(jobIds),
    onSuccess: () => {
      setSelectedJobs(new Set());
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const regenerateMutation = useMutation({
    mutationFn: regenerateJobs,
    onSuccess: () => {
      setSelectedJobs(new Set());
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const thumbnailsSelectedMutation = useMutation({
    mutationFn: (jobIds: string[]) => generateThumbnailsForJobs(jobIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
  const summary = useMemo(() => summarizeJobs(jobs), [jobs]);
  const activeJobs = statusQuery.data?.active_jobs ?? [];
  const queuedJobs =
    statusQuery.data?.queued_jobs ?? statusQuery.data?.pending_jobs ?? 0;
  const pendingJobs = statusQuery.data?.pending_jobs ?? 0;
  const maxParallelJobs = statusQuery.data?.max_parallel_jobs ?? 1;
  const expectedRatio = statusQuery.data?.expected_size_ratio ?? 1;
  const stitchSettings = statusQuery.data?.stitch_settings;
  const concurrency = statusQuery.data?.concurrency;
  const stitchConcurrency = concurrency?.stitch ?? maxParallelJobs;
  const scanConcurrency = concurrency?.scan ?? 25;
  const deepConcurrency = concurrency?.deep_scan ?? 1;
  const thumbnailConcurrency = concurrency?.thumbnails ?? 4;

  function closeSettings() {
    settingsGeneration.current += 1;
    setSettingsOpen(false);
  }
  function openSettings() {
    settingsGeneration.current += 1;
    settingsMutation.reset();
    computeRatioMutation.reset();
    setStitchConcurrencyValue(stitchConcurrency);
    setScanConcurrencyValue(scanConcurrency);
    setDeepScanConcurrencyValue(deepConcurrency);
    setRatioValue(expectedRatio);
    setOutputSizeValue(stitchSettings?.output_size ?? "");
    setBitrateValue(stitchSettings?.bitrate ?? "");
    setStitchTypeValue(stitchSettings?.stitch_type ?? "");
    setAutoResolution(stitchSettings?.auto_resolution ?? false);
    setThumbnailConcurrencyValue(thumbnailConcurrency);
    setOriginalBitrate(stitchSettings?.original_bitrate ?? false);
    setSettingsOpen(true);
  }
  const lastUpdated = statusQuery.dataUpdatedAt
    ? new Date(statusQuery.dataUpdatedAt).toLocaleTimeString("en-US")
    : "—";
  const activeTasks = statusQuery.data?.active_tasks ?? [];
  const controlsLocked =
    mutation.isPending ||
    !!activeTask ||
    activeTasks.length > 0 ||
    loginOpen ||
    stitchSelectedMutation.isPending ||
    regenerateMutation.isPending ||
    thumbnailsSelectedMutation.isPending;
  const showTaskControl = mutation.isPending || !!activeTask;

  useEffect(() => {
    const token = getAuthToken();
    if (token && !loginTokenValue) {
      setLoginTokenValue(token);
    }
  }, [loginTokenValue]);

  useEffect(() => {
    const error = statusQuery.error as (Error & { status?: number }) | null;
    if (statusQuery.isError && error?.status === 401) {
      setAuthToken(null);
      setLoginOpen(true);
    }
  }, [statusQuery.isError, statusQuery.error]);

  useEffect(() => {
    if (!activeTask || !statusQuery.data?.active_tasks) {
      return;
    }
    if (statusQuery.dataUpdatedAt < lastTaskTriggeredAt) {
      return;
    }
    const stillRunning = activeTasks.some((task) => task.id === activeTask.id);
    if (!stillRunning) {
      setActiveTask(null);
      setConfirmStop(false);
    }
  }, [
    activeTasks,
    activeTask,
    statusQuery.data?.active_tasks,
    statusQuery.dataUpdatedAt,
    lastTaskTriggeredAt,
  ]);

  const terminateMutation = useMutation({
    mutationFn: (taskId: string) => terminateTask(taskId),
    onSuccess: () => {
      setConfirmStop(false);
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });

  const loginMutation = useMutation({
    mutationFn: (token: string) => login(token),
    onSuccess: (_data, token) => {
      setAuthToken(token);
      setLoginOpen(false);
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });

  const trigger = (action: TaskAction) => {
    mutation.mutate(action);
  };

  useEffect(() => {
    setPollingFast(controlsLocked || terminateMutation.isPending);
  }, [controlsLocked, terminateMutation.isPending]);

  return (
    <div className="app-container">
      <header className="panel hero">
        <div>
          <h1>Insta360 Immich Bridge</h1>
          <p className="muted">
            Discover originals, stitch 360 media, and deliver verified exports
            to Immich.
          </p>
        </div>
        <div className="hero-stats">
          <div>
            <span className="stat-label">Total Jobs</span>
            <span className="stat-value">{summary.total}</span>
          </div>
          <div>
            <span className="stat-label">Active Threads</span>
            <span className="stat-value">{activeJobs.length}</span>
          </div>
          <div>
            <span className="stat-label">Stitching Jobs</span>
            <span className="stat-value">{maxParallelJobs}</span>
          </div>
          <div>
            <span className="stat-label">Last Updated</span>
            <span className="stat-value mono">{lastUpdated}</span>
          </div>
        </div>
      </header>

      <BridgePanel status={statusQuery.data} enabled={!loginOpen} />
      {detailsJob && (
        <BridgeJobDetails
          job={detailsJob}
          onClose={() => setDetailsJobId(null)}
        />
      )}
      <section className="panel actions">
        <div className="actions-header">
          <h2>Controls</h2>
          <div className="action-buttons">
            {showTaskControl && (
              <div className="task-control">
                {confirmStop && activeTask ? (
                  <button
                    type="button"
                    className="confirm-stop"
                    onClick={() =>
                      activeTask && terminateMutation.mutate(activeTask.id)
                    }
                    disabled={terminateMutation.isPending}
                  >
                    {terminateMutation.isPending ? "Stopping…" : "Confirm?"}
                  </button>
                ) : (
                  <button
                    type="button"
                    className="task-spinner"
                    onClick={() => setConfirmStop(true)}
                    disabled={!activeTask || terminateMutation.isPending}
                    aria-label="Stop running task"
                  >
                    <span className="spinner-ring" aria-hidden="true" />
                    <span className="spinner-stop" aria-hidden="true" />
                  </button>
                )}
              </div>
            )}
            <button
              className="ghost"
              type="button"
              onClick={() => statusQuery.refetch()}
              disabled={statusQuery.isFetching || controlsLocked}
            >
              Refresh
            </button>
            <button
              className="ghost"
              type="button"
              onClick={openSettings}
              disabled={controlsLocked}
            >
              Settings
            </button>
          </div>
        </div>
        <div className="action-grid">
          {ACTIONS.map(({ action, label, description }) => (
            <button
              key={action}
              type="button"
              className="action-card"
              disabled={controlsLocked}
              onClick={() => trigger(action)}
            >
              <div className="action-card-content">
                <span className="action-label">{label}</span>
                <span className="action-description">{description}</span>
              </div>
            </button>
          ))}
        </div>
        {controlsLocked && <p className="muted">Command running…</p>}
        {mutation.isError && (
          <p className="error">{(mutation.error as Error)?.message}</p>
        )}
      </section>

      <section className="panel summary">
        <h2>Job Summary</h2>
        <p className="muted">
          Shows stages, elapsed time, and size estimates. Completion requires
          verification of the Immich original.
        </p>
        <div className="summary-grid">
          <SummaryCard label="Queued" value={queuedJobs} tone="queued" />
          <SummaryCard label="Pending" value={pendingJobs} tone="pending" />
          <SummaryCard
            label="Processing"
            value={summary.processing}
            tone="running"
          />
          <SummaryCard
            label="Finished"
            value={summary.processed}
            tone="success"
          />
          <SummaryCard label="Failed" value={summary.failed} tone="failed" />
        </div>
      </section>

      {statusQuery.isError && (
        <div className="panel error">
          Failed to load status: {(statusQuery.error as Error)?.message}
        </div>
      )}

      <SelectionActions
        selectedCount={selectedJobs.size}
        pendingJobs={pendingJobs}
        queuedJobs={queuedJobs}
        onGenerate={() =>
          thumbnailsSelectedMutation.mutate(Array.from(selectedJobs))
        }
        onStitch={() => stitchSelectedMutation.mutate(Array.from(selectedJobs))}
        isGenerating={thumbnailsSelectedMutation.isPending}
        isStitching={stitchSelectedMutation.isPending}
        disabled={selectedJobs.size === 0 || controlsLocked}
      />
      <div className="selection-actions">
        <span>
          New settings apply to new jobs. Select completed exports to regenerate
          and replace them; previous exports move to Immich trash.
        </span>
        <button
          type="button"
          className="primary"
          disabled={
            controlsLocked ||
            regenerateMutation.isPending ||
            !jobs.some(
              (j) =>
                selectedJobs.has(j.id) &&
                j.status === "processed" &&
                j.owned &&
                !j.replaced_by,
            )
          }
          onClick={() =>
            regenerateMutation.mutate(
              jobs
                .filter(
                  (j) =>
                    selectedJobs.has(j.id) &&
                    j.status === "processed" &&
                    j.owned &&
                    !j.replaced_by,
                )
                .map((j) => j.id),
            )
          }
        >
          Regenerate and Replace Selected Exports
        </button>
        {regenerateMutation.isError && (
          <p className="error">{regenerateMutation.error.message}</p>
        )}
      </div>
      <JobTable
        onDetails={(job) => setDetailsJobId(job.id)}
        jobs={jobs}
        isLoading={statusQuery.isLoading}
        selectedJobs={selectedJobs}
        selectableStatuses={SELECTABLE_STATUSES}
        onToggleJob={(jobId, selected) =>
          setSelectedJobs((prev) => {
            const next = new Set(prev);
            if (selected) {
              next.add(jobId);
            } else {
              next.delete(jobId);
            }
            return next;
          })
        }
        onTogglePage={(jobIds, selected) =>
          setSelectedJobs((prev) => {
            const next = new Set(prev);
            jobIds.forEach((id) => {
              if (selected) {
                next.add(id);
              } else {
                next.delete(id);
              }
            });
            return next;
          })
        }
      />
      <SelectionActions
        selectedCount={selectedJobs.size}
        pendingJobs={pendingJobs}
        queuedJobs={queuedJobs}
        onGenerate={() =>
          thumbnailsSelectedMutation.mutate(Array.from(selectedJobs))
        }
        onStitch={() => stitchSelectedMutation.mutate(Array.from(selectedJobs))}
        isGenerating={thumbnailsSelectedMutation.isPending}
        isStitching={stitchSelectedMutation.isPending}
        disabled={selectedJobs.size === 0 || controlsLocked}
      />
      {thumbnailsSelectedMutation.isError && (
        <div className="panel error">
          Failed to generate thumbnails:{" "}
          {(thumbnailsSelectedMutation.error as Error)?.message}
        </div>
      )}
      {stitchSelectedMutation.isError && (
        <div className="panel error">
          Failed to stitch selected:{" "}
          {(stitchSelectedMutation.error as Error)?.message}
        </div>
      )}
      {settingsOpen && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3>Settings</h3>
            <label htmlFor="parallel-input">Stitching jobs</label>
            <input
              id="parallel-input"
              type="number"
              min={1}
              value={stitchConcurrencyValue}
              onChange={(event) =>
                setStitchConcurrencyValue(event.target.value)
              }
              disabled={settingsMutation.isPending}
            />
            <label htmlFor="scan-concurrency-input">Scan jobs</label>
            <input
              id="scan-concurrency-input"
              type="number"
              min={1}
              value={scanConcurrencyValue}
              onChange={(event) => setScanConcurrencyValue(event.target.value)}
              disabled={settingsMutation.isPending}
            />
            <label htmlFor="deep-scan-concurrency-input">Deep scan jobs</label>
            <input
              id="deep-scan-concurrency-input"
              type="number"
              min={1}
              value={deepScanConcurrencyValue}
              onChange={(event) =>
                setDeepScanConcurrencyValue(event.target.value)
              }
              disabled={settingsMutation.isPending}
            />
            <label htmlFor="thumbnail-concurrency-input">Thumbnail jobs</label>
            <input
              id="thumbnail-concurrency-input"
              type="number"
              min={1}
              value={thumbnailConcurrencyValue}
              onChange={(event) =>
                setThumbnailConcurrencyValue(event.target.value)
              }
              disabled={settingsMutation.isPending}
            />
            <label htmlFor="ratio-input">Expected size ratio</label>
            <div className="ratio-controls">
              <input
                id="ratio-input"
                type="number"
                min={0.01}
                step={0.01}
                value={ratioValue}
                onChange={(event) => setRatioValue(event.target.value)}
                disabled={
                  settingsMutation.isPending || computeRatioMutation.isPending
                }
              />
              <button
                type="button"
                className="ghost"
                onClick={() =>
                  computeRatioMutation.mutate(settingsGeneration.current)
                }
                disabled={
                  computeRatioMutation.isPending || settingsMutation.isPending
                }
              >
                {computeRatioMutation.isPending
                  ? "Computing…"
                  : "Compute Ratio"}
              </button>
            </div>
            <div className="checkbox-row">
              <label htmlFor="auto-resolution">
                <input
                  id="auto-resolution"
                  type="checkbox"
                  checked={autoResolution}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setAutoResolution(checked);
                  }}
                  disabled={settingsMutation.isPending}
                />
                Use default resolution (derive from input)
              </label>
            </div>
            <label htmlFor="resolution-input">Output resolution</label>
            <input
              id="resolution-input"
              type="text"
              value={autoResolution ? "" : outputSizeValue}
              onChange={(event) => setOutputSizeValue(event.target.value)}
              disabled={settingsMutation.isPending || autoResolution}
              placeholder={
                autoResolution
                  ? "Auto: 2×input width × input height"
                  : "e.g. 5760x2880"
              }
            />
            <label htmlFor="bitrate-input">Bitrate (bits per second)</label>
            <input
              id="bitrate-input"
              type="text"
              value={bitrateValue}
              onChange={(event) => setBitrateValue(event.target.value)}
              disabled={settingsMutation.isPending || originalBitrate}
            />
            <div className="checkbox-row">
              <label htmlFor="original-bitrate">
                <input
                  id="original-bitrate"
                  type="checkbox"
                  checked={originalBitrate}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setOriginalBitrate(checked);
                  }}
                  disabled={settingsMutation.isPending}
                />
                Use original bitrate (match input file)
              </label>
            </div>
            <label htmlFor="stitch-type-input">Stitch type</label>
            <input
              id="stitch-type-input"
              type="text"
              value={stitchTypeValue}
              onChange={(event) => setStitchTypeValue(event.target.value)}
              disabled={settingsMutation.isPending}
            />
            <div className="modal-actions">
              <button
                type="button"
                className="ghost"
                onClick={closeSettings}
                disabled={settingsMutation.isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                className="primary"
                onClick={() => settingsMutation.mutate()}
                disabled={settingsMutation.isPending}
              >
                {settingsMutation.isPending ? "Saving…" : "Save"}
              </button>
            </div>
            {computeRatioMutation.isError && (
              <p className="error">
                Failed to compute ratio:{" "}
                {(computeRatioMutation.error as Error)?.message}
              </p>
            )}
            {settingsMutation.isError && (
              <p className="error">
                Failed to update settings:{" "}
                {(settingsMutation.error as Error)?.message}
              </p>
            )}
          </div>
        </div>
      )}
      {loginOpen && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3>Login</h3>
            <p className="muted">Enter the access token to continue.</p>
            <input
              type="password"
              value={loginTokenValue}
              onChange={(event) => setLoginTokenValue(event.target.value)}
              placeholder="Access token"
              disabled={loginMutation.isPending}
            />
            <div className="modal-actions">
              <button
                type="button"
                className="primary"
                onClick={() => loginMutation.mutate(loginTokenValue.trim())}
                disabled={!loginTokenValue.trim() || loginMutation.isPending}
              >
                {loginMutation.isPending ? "Logging in…" : "Login"}
              </button>
            </div>
            {loginMutation.isError && (
              <p className="error">
                Login failed: {(loginMutation.error as Error)?.message}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function summarizeJobs(jobs: Job[]) {
  return jobs.reduce(
    (acc, job) => {
      acc.total += 1;
      acc[job.status] += 1;
      return acc;
    },
    { total: 0, unprocessed: 0, processing: 0, processed: 0, failed: 0 },
  );
}

interface SummaryCardProps {
  label: string;
  value: number;
  tone: "queued" | "pending" | "running" | "success" | "failed";
}

function SummaryCard({ label, value, tone }: SummaryCardProps) {
  return (
    <div className={clsx("summary-card", tone)}>
      <span className="muted">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}

interface SelectionActionsProps {
  selectedCount: number;
  pendingJobs: number;
  queuedJobs: number;
  onGenerate: () => void;
  onStitch: () => void;
  isGenerating: boolean;
  isStitching: boolean;
  disabled: boolean;
}

function SelectionActions({
  selectedCount,
  pendingJobs,
  queuedJobs,
  onGenerate,
  onStitch,
  isGenerating,
  isStitching,
  disabled,
}: SelectionActionsProps) {
  return (
    <div className="selection-actions">
      <span>
        {selectedCount} selected · {queuedJobs} queued · {pendingJobs} pending
      </span>
      <div className="selection-buttons">
        <button
          type="button"
          className="ghost"
          onClick={onGenerate}
          disabled={disabled || isGenerating}
        >
          {isGenerating ? "Generating…" : "Thumbnails Selected"}
        </button>
        <button
          type="button"
          className="primary"
          onClick={onStitch}
          disabled={disabled || isStitching}
        >
          {isStitching ? "Stitching…" : "Stitch Selected"}
        </button>
      </div>
    </div>
  );
}
