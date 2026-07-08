import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react({ jsxRuntime: "automatic" })],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalized = id.replace(/\\/g, "/");
          if (normalized.includes("/node_modules/react")) {
            return "vendor-react";
          }
          if (normalized.includes("/src/api/")) {
            return "app-api";
          }
          if (normalized.includes("/src/views/DebugWorkspace.jsx")) {
            return "view-debug";
          }
          if (normalized.includes("/src/views/SceneWorkspace.jsx")) {
            return "view-scene";
          }
          if (normalized.includes("/src/views/FrameworkWorkbenchWorkspace.jsx")) {
            return "view-framework";
          }
          if (normalized.includes("/src/views/")) {
            return "views-core";
          }
        },
      },
    },
  },
});
