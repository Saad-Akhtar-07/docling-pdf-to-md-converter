import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function getPythonExecutable(loadedEnv) {
  if (loadedEnv.LOCAL_EXTRACTOR_PYTHON || process.env.LOCAL_EXTRACTOR_PYTHON) {
    return loadedEnv.LOCAL_EXTRACTOR_PYTHON || process.env.LOCAL_EXTRACTOR_PYTHON;
  }

  const venvPython =
    process.platform === "win32"
      ? resolve(process.cwd(), ".venv", "Scripts", "python.exe")
      : resolve(process.cwd(), ".venv", "bin", "python");

  return existsSync(venvPython) ? venvPython : "python";
}

function localExtractorPlugin(loadedEnv, extractorPort) {
  let extractorProcess = null;

  function stopExtractor() {
    if (!extractorProcess || extractorProcess.killed) return;
    extractorProcess.kill();
    extractorProcess = null;
  }

  return {
    name: "slidevision-local-extractor",
    configureServer(server) {
      if (process.env.SLIDEVISION_MANAGE_LOCAL_EXTRACTOR === "false") {
        return;
      }

      const pythonExecutable = getPythonExecutable(loadedEnv);
      extractorProcess = spawn(
        pythonExecutable,
        [
          "-m",
          "uvicorn",
          "server.localExtractorService:app",
          "--host",
          "127.0.0.1",
          "--port",
          String(extractorPort),
        ],
        {
          cwd: process.cwd(),
          env: {
            ...process.env,
            ...loadedEnv,
            PYTHONUNBUFFERED: "1",
          },
          stdio: ["ignore", "pipe", "pipe"],
          windowsHide: true,
        },
      );

      extractorProcess.stdout.on("data", (chunk) => {
        process.stdout.write(`[local-extractor] ${chunk}`);
      });

      extractorProcess.stderr.on("data", (chunk) => {
        process.stderr.write(`[local-extractor] ${chunk}`);
      });

      extractorProcess.on("exit", (code, signal) => {
        if (code || signal) {
          console.warn(`[local-extractor] stopped with code ${code ?? "null"} signal ${signal ?? "null"}`);
        }
        extractorProcess = null;
      });

      server.httpServer?.once("close", stopExtractor);
    },
  };
}

export default defineConfig(({ mode }) => {
  const loadedEnv = loadEnv(mode, process.cwd(), "");
  const localExtractorPort = Number(loadedEnv.LOCAL_EXTRACTOR_PORT || process.env.LOCAL_EXTRACTOR_PORT || 5052);

  return {
    plugins: [react(), localExtractorPlugin(loadedEnv, localExtractorPort)],
    server: {
      proxy: {
        "/local-extractor": {
          target: `http://127.0.0.1:${localExtractorPort}`,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/local-extractor/, ""),
        },
      },
    },
  };
});
