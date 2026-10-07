import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request } from "../api";
import type { BridgeEvent } from "../types";

// Query errors keep the cursor; resuming/reconnecting reads every undelivered page.
export function useEventLog(path: string, enabled = true) {
  const cursor = useRef<number>();
  const retained = useRef<BridgeEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const query = useQuery({
    queryKey: ["incremental-events", path],
    queryFn: async () => {
      let page: BridgeEvent[];
      do {
        const response = await request<{ events: BridgeEvent[] }>(
          cursor.current === undefined
            ? path
            : `${path}?after=${cursor.current}`,
        );
        page = response.events;
        if (page.length) {
          retained.current = [...retained.current, ...page].slice(-5000);
          cursor.current = page[page.length - 1].seq;
        }
      } while (page.length === 500);
      return retained.current;
    },
    enabled: enabled && !paused,
    refetchInterval: paused ? false : 2000,
  });
  return { ...query, paused, setPaused };
}

export function eventLevel(event: BridgeEvent) {
  if (/failed|error|conflict|unsupported/.test(event.stage)) return "error";
  if (/cancel|waiting|blocked|missing/.test(event.stage)) return "warn";
  return "info";
}

export function saveLog(name: string, text: string) {
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/plain;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}
