import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const ngrokHost = process.env.NGROK_HOST;

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    allowedHosts: ngrokHost ? [ngrokHost] : [".ngrok-free.dev"],
    hmr: ngrokHost
      ? {
          protocol: "wss",
          host: ngrokHost,
          clientPort: 443,
        }
      : undefined,
  },
});
