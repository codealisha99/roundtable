import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Web on 4500; the token API (4501) is reached through the dev proxy so the browser sees one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4500,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:4501" },
  },
  preview: {
    host: "127.0.0.1",
    port: 4500,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:4501" },
  },
});
