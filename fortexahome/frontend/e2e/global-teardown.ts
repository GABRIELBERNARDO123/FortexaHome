import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export default async function globalTeardown() {
  if (process.env.E2E_EXTERNAL === "1" || process.env.E2E_KEEP === "1") return;
  const authDir = path.join(path.dirname(fileURLToPath(import.meta.url)), ".auth");
  fs.rmSync(authDir, { recursive: true, force: true });
  try {
    execFileSync(
      "docker",
      ["compose", "-f", "docker-compose.e2e.yml", "-p", "fortexahome_e2e", "down", "--remove-orphans"],
      { cwd: repoRoot, stdio: "inherit", env: process.env },
    );
  } catch {
    // O ambiente é descartável; falhas de teardown não escondem o resultado dos testes.
  }
}
