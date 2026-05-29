// superpowers OpenCode plugin
// Reminds the agent to check for relevant skills before responding.
import { existsSync, readdirSync } from "fs";
import { join } from "path";

export const SuperpowersPlugin = async ({ directory }) => {
  let reminded = false;

  const superpowersDir = join(
    process.env.HOME || "/home/kali",
    ".agents",
    "skills"
  );

  const superpowerList = [
    "finding-duplicate-functions",
    "mcp-cli",
    "using-tmux-for-interactive-commands",
    "windows-vm",
    "using-superpowers",
    "superpowers-lab",
  ];

  return {
    "tool.execute.before": async (input, output) => {
      if (reminded) return;
      if (!existsSync(superpowersDir)) return;

      if (input.tool === "bash") {
        output.args.command =
          `echo "[superpowers] Skills available. Before responding check if one applies: ${superpowerList.join(", ")}" && ` +
          output.args.command;
        reminded = true;
      }
    },
  };
};
