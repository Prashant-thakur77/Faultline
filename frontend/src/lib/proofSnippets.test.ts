import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { ALGO_NAMES, SNIPPETS } from "./proofSnippets";

const TEMPLATES = path.resolve(__dirname, "../../../backend/faultline/graph/templates");
const REGISTRY = path.resolve(__dirname, "../../../backend/faultline/graph/algo/registry.py");

describe("proof story snippets", () => {
  it.each(Object.entries(SNIPPETS))("%s is verbatim from its template", (_, s) => {
    const src = readFileSync(path.join(TEMPLATES, s.file), "utf8");
    expect(src).toContain(`// id: ${s.id}`);
    const lines = src.split("\n").map((l) => l.trim());
    for (const shown of s.code.split("\n")) {
      let raw = shown.trim();
      for (const [key, name] of Object.entries(ALGO_NAMES)) raw = raw.replaceAll(`${name}(`, `{algo:${key}}(`);
      expect(lines).toContain(raw);
    }
  });

  it("names each procedure as the registry resolves it", () => {
    const reg = readFileSync(REGISTRY, "utf8");
    for (const [key, name] of Object.entries(ALGO_NAMES)) expect(reg).toMatch(new RegExp(`"${key}": \\["${name.replace(".", "\\.")}"`));
  });
});

describe("API tabs", () => {
  const ROOT = path.resolve(__dirname, "../../..");
  it("MCP tab runs the repo's own published npm bridge", async () => {
    const { API_TABS } = await import("./proofSnippets");
    const shown = JSON.parse(API_TABS.find((t) => t.id === "mcp")!.code);
    const pkg = JSON.parse(readFileSync(path.join(ROOT, "packages/faultline-mcp/package.json"), "utf8"));
    expect(shown.mcpServers.faultline).toEqual({ command: "npx", args: ["-y", pkg.name] });
  });
  it("REST tab calls a real route with fields its request model declares", async () => {
    const { API_TABS } = await import("./proofSnippets");
    const code = API_TABS.find((t) => t.id === "rest")!.code;
    const api = readFileSync(path.join(ROOT, "backend/faultline/api.py"), "utf8");
    expect(api).toContain('@app.post("/api/context_pack")');
    const body = JSON.parse(code.match(/-d '(.*)'/)![1]);
    const model = api.slice(api.indexOf("class ContextPackReq"), api.indexOf('@app.post("/api/context_pack")'));
    for (const k of Object.keys(body)) expect(model).toMatch(new RegExp(`\\b${k}:`));
  });
});
