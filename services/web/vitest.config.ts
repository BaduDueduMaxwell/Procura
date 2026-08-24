import { defineConfig } from "vitest/config";
import { resolve } from "path";
import react from "@vitejs/plugin-react";
export default defineConfig({ plugins: [react()], test: { environment: "jsdom", setupFiles: ["./tests/setup.ts"] }, resolve: { alias: { "@": resolve(import.meta.dirname, ".") } } });
