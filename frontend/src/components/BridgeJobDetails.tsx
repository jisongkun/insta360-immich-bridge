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
        <div className="action-buttons">
          <button
            className="ghost"
            onClick={() => events.setPaused(!events.paused)}
          >
            {events.paused ? "继续日志" : "暂停日志"}
          </button>
          <select
            aria-label="事件级别"
            value={level}
            onChange={(e) => setLevel(e.target.value)}
          >
            <option value="all">全部级别</option>
            <option value="error">错误</option>
            <option value="warn">警告</option>
            <option value="info">信息</option>
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
            下载已加载日志
          </button>
        </div>
        <h4>阶段事件（最多保留 5000 条；级别按事件阶段分类）</h4>
        {events.data
          ?.filter((e) => level === "all" || eventLevel(e) === level)
          .map((e) => (
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
