export type JobStatus = "unprocessed" | "processing" | "processed" | "failed";

export interface Job {
  id: string;
  timestamp: string;
  final_file: string;
  source_files: string[];
  status: JobStatus;
  queue_state?: "queued" | "pending" | null;
  pid: number | null;
  stitched_size: number;
  process: number;
  expected_size: number;
  created_at: string;
  updated_at: string;
  thumbnail_url: string | null;
  stage: string;
  phase?: string;
  error?: string;
  asset_id?: string;
  verified: boolean;
  owned: boolean;
  remote_missing: boolean;
  replaced_by?: string;
  local_deleted: boolean;
  recipe: string;
}

export interface StatusResponse {
  jobs: Job[];
  connection: {
    ok?: boolean;
    version?: string;
    error?: string;
    server?: string;
    user_id?: string;
  };
  automatic: boolean;
  api_paused: boolean;
  next_api_scan: number | null;
  next_folder_scan: number | null;
  scan_summary: { groups?: number; at?: number; full?: boolean };
  active_jobs: string[];
  active_tasks?: Array<{ id: string; action: TaskAction; started_at: string }>;
  pending_jobs: number;
  queued_jobs: number;
  max_parallel_jobs: number;
  expected_size_ratio: number;
  stitch_settings: {
    output_size: string;
    bitrate: string;
    stitch_type: string;
    auto_resolution: boolean;
    original_bitrate: boolean;
  };
  concurrency?: {
    stitch: number;
    scan: number;
    deep_scan: number;
    thumbnails: number;
  };
}

export type TaskAction =
  | "scan"
  | "deep_scan"
  | "stitch"
  | "full_stitch"
  | "generate_thumbnails"
  | "stitch_selected"
  | "full_run"
  | "regenerate_selected"
  | "test_connection";

export interface BridgeSettings {
  immich_url: string;
  api_key_env: string;
  api_key_file: string;
  folders: string[];
  mappings: Array<{ from: string; to: string }>;
  exclusions: string[];
  download_sources: boolean;
  automatic: boolean;
  interval: number;
  folder_interval: number;
  stable_seconds: number;
  full_interval: number;
  source_timezone: string;
  profile: StatusResponse["stitch_settings"] & {
    enable_h265: boolean;
    enable_flowstate: boolean;
    enable_directionlock: boolean;
    enable_stitchfusion: boolean;
    disable_cuda: boolean;
  };
}
export interface BridgeEvent {
  seq: number;
  stage: string;
  message: string;
  at: number;
}
