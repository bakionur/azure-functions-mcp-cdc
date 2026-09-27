// Bundles everything into ONE index.html — the resource trigger returns this single file.
// target esnext: main.js uses top-level await (MCP App hosts are current Chromium/Electron webviews).
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";
export default defineConfig({ plugins: [viteSingleFile()], build: { outDir: "dist", emptyOutDir: true, target: "esnext" } });
