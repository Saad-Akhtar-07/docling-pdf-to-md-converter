import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/docling": {
        target: "http://localhost:5001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/docling/, ""),
      },
<<<<<<< HEAD
      "/api": {
        target: "http://localhost:3001",
        changeOrigin: true,
      },
=======
>>>>>>> 3a405dd557e8516741103ff68021fac68d9494dd
    },
  },
});
