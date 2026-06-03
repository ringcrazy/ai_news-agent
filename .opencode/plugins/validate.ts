import type { Plugin } from "@opencode-ai/plugin";
import { appendFileSync } from "node:fs";
import { join } from "node:path";

type ToolArgs = {
  file_path?: string;
  filePath?: string;
};

const ARTICLE_PATH_PATTERN = /(^|[\\/])knowledge[\\/]articles[\\/].+\.json$/i;

function getFilePath(args: ToolArgs | undefined): string | undefined {
  return args?.file_path ?? args?.filePath;
}

const DEBUG_LOG_PATH = join(import.meta.dir, "..", "validate-json-debug.log");

function dlog(message: string): void {
  try {
    appendFileSync(
      DEBUG_LOG_PATH,
      `[${new Date().toISOString()}] ${message}\n`,
      "utf8",
    );
  } catch {
    // debug logging must never crash the plugin
  }
}

dlog("plugin module loaded");

export const validatePlugin: Plugin = async ({ $ }) => {
  dlog("plugin initialized");

  return {
    async "tool.execute.after"(input) {
      try {
        const toolName = input.tool;
        dlog(`hook fired: tool=${toolName}`);

        if (toolName !== "write" && toolName !== "edit") {
          return;
        }

        const filePath = getFilePath(input.args);
        if (!filePath || !ARTICLE_PATH_PATTERN.test(filePath)) {
          return;
        }

        dlog(`path matched: ${filePath}`);

        const result =
          await $`python hooks/validate_json.py ${filePath}`.nothrow();

        if (!result.ok) {
          console.error(`[validate-json] validation failed for ${filePath}`);
          console.error(String(result.stderr ?? result.stdout ?? ""));
          dlog(`validation FAILED: ${filePath}`);
        } else {
          dlog(`validation passed: ${filePath}`);
        }
      } catch (error) {
        console.error("[validate-json] unexpected plugin error");
        console.error(error);
        dlog(`unexpected error: ${String(error)}`);
      }
    },
  };
};

export default validatePlugin;
