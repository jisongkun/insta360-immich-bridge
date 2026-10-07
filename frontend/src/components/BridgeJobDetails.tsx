import { useQuery } from "@tanstack/react-query";
import { request } from "../api";
import type { BridgeEvent, Job } from "../types";

export function BridgeJobDetails({
  job,
  onClose,
}: {
  job: Job;
  onClose: () => void;
}) {
  const events = useQuery({
    queryKey: ["job-events", job.id],
    queryFn: () => request<{ events: BridgeEvent[] }>(`/jobs/${job.id}/events`),
    refetchInterval: 2000,
  });
  const logs = useQuery({
    queryKey: ["job-logs", job.id],
    queryFn: () =>
      request<{
        stage: string;
        phase: string;
        error?: string;
        logs: Array<{ name: string; text: string }>;
      }>(`/jobs/${job.id}/logs`),
    refetchInterval: 3000,
  });
  const details = useQuery({
    queryKey: ["job-details", job.id],
    queryFn: () => request<object>(`/jobs/${job.id}/details`),
  });
  return (
    <div className="modal-backdrop">
      <div className="modal job-details">
        <div className="actions-header">
          <h3>任务 {job.id}</h3>
          <button className="ghost" onClick={onClose}>
            关闭
          </button>
        </div>
        <p>
          当前阶段：{logs.data?.stage ?? job.stage} · 继续位置：
          {logs.data?.phase ?? job.phase}
        </p>
        <p>
          Immich asset：{job.asset_id ?? "未上传"} · 核验：
          {job.verified ? "通过" : "待核验"} · 本地成片：
          {job.local_deleted ? "已清理" : "保留／尚未生成"}
        </p>
        {(logs.data?.error || job.error) && (
          <p className="error">{logs.data?.error || job.error}</p>
        )}
        <details>
          <summary>原片、目标和有效参数</summary>
          <pre>{JSON.stringify(details.data, null, 2)}</pre>
        </details>
        <h4>阶段事件</h4>
        {events.data?.events.map((e) => (
          <div key={e.seq} className="mono">
            {new Date(e.at * 1000).toLocaleString()} [{e.stage}] {e.message}
          </div>
        ))}
        <h4>SDK／转换日志（每文件末尾 64 KiB）</h4>
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
