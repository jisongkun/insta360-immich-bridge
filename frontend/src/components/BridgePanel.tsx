import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request, triggerTask } from "../api";
import type { BridgeSettings, BridgeEvent, StatusResponse } from "../types";

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
  const events = useQuery({
    queryKey: ["bridge-events"],
    queryFn: () => request<{ events: BridgeEvent[] }>("/events"),
    enabled,
    refetchInterval: 5000,
  });
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
  const recent = events.data?.events.slice(-10) ?? [];
  return (
    <section className="panel bridge-panel">
      <div className="actions-header">
        <h2>Immich 集成</h2>
        <button className="ghost" onClick={() => setOpen(!open)}>
          连接与扫描设置
        </button>
      </div>
      <p>
        {status?.connection.ok
          ? `已连接 ${status.connection.server} · ${status.connection.version}`
          : status?.connection.error || "尚未验证连接"}{" "}
        · 自动运行{" "}
        {status?.api_paused
          ? "因权限错误暂停"
          : status?.automatic
            ? "开启"
            : "关闭"}
      </p>
      <p className="muted">
        上次发现 {status?.scan_summary.groups ?? "—"} 组完整原片。API 下次运行：
        {status?.next_api_scan
          ? new Date(status.next_api_scan * 1000).toLocaleString()
          : "手动"}
        。原片保留；成片经服务器 SHA-256 核验后删除本地副本。
      </p>
      <div className="action-buttons">
        <button
          className="primary"
          onClick={() => action.mutate("test_connection")}
          disabled={action.isPending}
        >
          测试连接
        </button>
        <button
          className="primary"
          onClick={() => action.mutate("full_run")}
          disabled={action.isPending}
        >
          手动发现并处理
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
            停止 {t.action}
          </button>
        ))}
      </div>
      {action.isError && <p className="error">{action.error.message}</p>}
      {settings.isError && <p className="error">{settings.error.message}</p>}
      {open && draft && (
        <div className="bridge-settings">
          <label>
            Immich 地址
            <input
              value={draft.immich_url}
              onChange={(e) => change("immich_url", e.target.value)}
              placeholder="https://photos.example.com"
            />
          </label>
          <p className="muted">
            API Key
            从服务器环境变量或只读密钥文件读取，不会出现在网页设置和任务日志中。文件路径非空时优先使用文件。
          </p>
          <label>
            API Key 环境变量名称
            <input
              value={draft.api_key_env}
              onChange={(e) => change("api_key_env", e.target.value)}
            />
          </label>
          <label>
            API Key 文件路径
            <input
              value={draft.api_key_file}
              onChange={(e) => change("api_key_file", e.target.value)}
              placeholder="/run/secrets/immich-key"
            />
          </label>
          <label>
            <input
              type="checkbox"
              checked={draft.download_sources}
              onChange={(e) => change("download_sources", e.target.checked)}
            />
            通过 API 下载原片（关闭时使用只读路径映射）
          </label>
          <label>
            额外扫描目录（每行一个，包含子目录）
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
            排除路径通配符（每行一个）
            <textarea
              rows={2}
              value={draft.exclusions.join("\n")}
              onChange={(e) =>
                change("exclusions", e.target.value.split("\n").filter(Boolean))
              }
            />
          </label>
          <p>
            原片路径映射：左侧为 Immich originalPath
            前缀，右侧为本工具可读挂载目录。
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
                移除
              </button>
            </div>
          ))}
          <button
            className="ghost"
            onClick={() =>
              change("mappings", [...draft.mappings, { from: "", to: "" }])
            }
          >
            添加映射
          </button>
          <label>
            <input
              type="checkbox"
              checked={draft.automatic}
              onChange={(e) => change("automatic", e.target.checked)}
            />
            按间隔自动发现并处理
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
                  interval: "API 间隔",
                  folder_interval: "目录扫描间隔",
                  stable_seconds: "文件稳定等待",
                  full_interval: "全量核对间隔",
                }[key]
              }
              （秒）
              <input
                type="number"
                min={1}
                value={draft[key]}
                onChange={(e) => change(key, Number(e.target.value))}
              />
            </label>
          ))}
          <label>
            文件名拍摄时间所属时区
            <input
              value={draft.source_timezone}
              onChange={(e) => change("source_timezone", e.target.value)}
            />
          </label>
          <p>
            分辨率、码率和拼接算法在原 Settings
            中设置。以下开关沿用原转换器；保存不会自动替换已有导出。
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
                  enable_flowstate: "FlowState 防抖",
                  enable_directionlock: "方向锁定（需要防抖）",
                  enable_stitchfusion: "Stitch Fusion",
                  disable_cuda: "禁用 CUDA",
                }[key]
              }
            </label>
          ))}
          <button
            className="primary"
            disabled={save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? "保存中…" : "保存设置"}
          </button>
          {save.isError && <p className="error">{save.error.message}</p>}
        </div>
      )}
      <details>
        <summary>最近运行日志</summary>
        {recent.map((e) => (
          <div className="mono" key={e.seq}>
            {new Date(e.at * 1000).toLocaleString()} [{e.stage}] {e.message}
          </div>
        ))}
      </details>
    </section>
  );
}
