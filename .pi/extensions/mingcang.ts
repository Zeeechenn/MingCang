import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

type CommandResult = {
  stdout: string;
  stderr: string;
};

function pythonFor(cwd: string): string {
  const venvPython = join(cwd, ".venv", "bin", "python");
  if (existsSync(venvPython)) return venvPython;
  return process.env.PYTHON || "python3";
}

function runMingCang(cwd: string, args: string[], signal?: AbortSignal): Promise<CommandResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      pythonFor(cwd),
      ["-m", "backend.agent.cli", ...args],
      {
        cwd,
        env: {
          ...process.env,
          PYTHONPATH: cwd,
          MINGCANG_AGENT_MODE: process.env.MINGCANG_AGENT_MODE || "local",
        },
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    signal?.addEventListener("abort", () => child.kill("SIGTERM"), { once: true });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
        return;
      }
      reject(new Error(stderr.trim() || `MingCang CLI exited with ${code}`));
    });
  });
}

function textResult(text: string, details: Record<string, unknown> = {}) {
  return {
    content: [{ type: "text" as const, text: text.trim() || "{}" }],
    details,
  };
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "mingcang_health",
    label: "MingCang Health",
    description: "Read MingCang agent health, database counts, watchlist, positions, and memory counts.",
    promptSnippet: "Use mingcang_health before answering MingCang runtime, setup, or health questions.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal, _onUpdate, ctx) {
      const result = await runMingCang(ctx.cwd, ["health", "--pretty"], signal);
      return textResult(result.stdout, { command: "health" });
    },
  });

  pi.registerTool({
    name: "mingcang_project_context",
    label: "MingCang Project Context",
    description: "Read MingCang startup context, project memory summary, active watchlist, and positions.",
    promptSnippet: "Use mingcang_project_context before project-level MingCang research or review.",
    parameters: Type.Object({
      symbol: Type.Optional(Type.String({ description: "Optional stock symbol to include focused context." })),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const args = ["project-context", "--pretty"];
      if (params.symbol) args.push("--symbol", params.symbol);
      const result = await runMingCang(ctx.cwd, args, signal);
      return textResult(result.stdout, { command: "project-context" });
    },
  });

  pi.registerTool({
    name: "mingcang_stock_context",
    label: "MingCang Stock Context",
    description: "Read one stock's latest signal, position, long-term label, copilot shadow opinion, and memory context.",
    promptSnippet: "Use mingcang_stock_context before single-stock MingCang research.",
    parameters: Type.Object({
      symbol: Type.String({ description: "Stock symbol, for example 000001." }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const result = await runMingCang(ctx.cwd, ["stock-context", params.symbol, "--pretty"], signal);
      return textResult(result.stdout, { command: "stock-context", symbol: params.symbol });
    },
  });

  pi.registerTool({
    name: "mingcang_memory_snapshot",
    label: "MingCang Memory Snapshot",
    description: "Read MingCang project-owned memory counts, recent memory rows, layered memory, and audit summaries.",
    promptSnippet: "Use mingcang_memory_snapshot for memory-sensitive MingCang work.",
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, signal, _onUpdate, ctx) {
      const result = await runMingCang(ctx.cwd, ["memory-snapshot", "--pretty"], signal);
      return textResult(result.stdout, { command: "memory-snapshot" });
    },
  });

  pi.registerTool({
    name: "mingcang_action_dry_run",
    label: "MingCang Action Dry Run",
    description: "Inspect a MingCang action schema, risk level, and payload without executing it.",
    promptSnippet: "Use mingcang_action_dry_run before any MingCang mutation.",
    parameters: Type.Object({
      name: Type.String({ description: "Registered action name, for example watchlist.add." }),
      payloadJson: Type.String({ description: "Action payload as a JSON object string." }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      const result = await runMingCang(ctx.cwd, ["action", params.name, "--payload-json", params.payloadJson, "--pretty"], signal);
      return textResult(result.stdout, { command: "action", action: params.name, dryRun: true });
    },
  });

  pi.registerTool({
    name: "mingcang_action_confirm",
    label: "MingCang Confirmed Action",
    description: "Execute a confirmed MingCang action. Use only after the user explicitly approves the exact payload.",
    promptSnippet: "Use mingcang_action_confirm only after the user explicitly confirms a MingCang action payload.",
    parameters: Type.Object({
      name: Type.String({ description: "Registered action name." }),
      payloadJson: Type.String({ description: "Action payload as a JSON object string." }),
      confirm: Type.Boolean({ description: "Must be true to execute." }),
    }),
    async execute(_toolCallId, params, signal, _onUpdate, ctx) {
      if (!params.confirm) throw new Error("Set confirm=true only after explicit user approval.");
      if (ctx.hasUI) {
        const ok = await ctx.ui.confirm("Execute MingCang action?", `${params.name}\n\n${params.payloadJson}`);
        if (!ok) throw new Error("MingCang action was cancelled by the user.");
      }
      const result = await runMingCang(ctx.cwd, ["action", params.name, "--payload-json", params.payloadJson, "--confirm", "--pretty"], signal);
      return textResult(result.stdout, { command: "action", action: params.name, dryRun: false });
    },
  });

  pi.registerCommand("mingcang-health", {
    description: "Run MingCang health check.",
    handler: async (_args, ctx) => {
      const result = await runMingCang(ctx.cwd, ["health", "--pretty"]);
      ctx.ui.notify(result.stdout.trim(), "info");
    },
  });
}
