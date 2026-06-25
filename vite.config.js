import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { handleVisionRequest, loadDotEnv } from "./server/groqVisionService.js";

function visionApiPlugin() {
  return {
    name: "slidevision-groq-vision-api",
    configureServer(server) {
      loadDotEnv();

      server.middlewares.use(async (request, response, next) => {
        if (!request.url?.startsWith("/api/vision")) {
          next();
          return;
        }

        await handleVisionRequest(request, response);
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), visionApiPlugin()],
  server: {
    proxy: {
      "/docling": {
        target: "http://localhost:5001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/docling/, ""),
      },
      "/gotenberg": {
        target: "http://localhost:3000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/gotenberg/, ""),
      },
      "/langchain-extractor": {
        target: "http://localhost:5051",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/langchain-extractor/, ""),
      },
    },
  },
});
