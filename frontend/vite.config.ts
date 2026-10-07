import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const target = process.env.BRIDGE_DEV_API ?? "http://127.0.0.1:8008";
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      [
        "status",
        "tasks",
        "login",
        "settings",
        "jobs",
        "events",
        "thumbnails",
      ].map((path) => [`/${path}`, { target, changeOrigin: true }]),
    ),
  },
});
