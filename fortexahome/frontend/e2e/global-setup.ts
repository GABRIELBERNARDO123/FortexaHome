import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { request } from "@playwright/test";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const composeFile = "docker-compose.e2e.yml";
const project = "fortexahome_e2e";

function compose(args: string[], options: { allowFailure?: boolean } = {}) {
  try {
    execFileSync(
      "docker",
      ["compose", "-f", composeFile, "-p", project, ...args],
      { cwd: repoRoot, stdio: "inherit", env: process.env },
    );
  } catch (error) {
    if (!options.allowFailure) throw error;
  }
}

async function waitFor(url: string, timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Serviço ainda iniciando.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timeout aguardando ${url}`);
}

async function createStorageState() {
  const authDir = path.join(path.dirname(fileURLToPath(import.meta.url)), ".auth");
  fs.mkdirSync(authDir, { recursive: true });
  const api = await request.newContext({ baseURL: "http://127.0.0.1:8011" });
  const customer = await api.post("/api/v1/auth/login", {
    data: { email: "cliente.e2e@example.com", password: "E2eSenha#2026" },
  });
  if (!customer.ok()) throw new Error(`E2E customer login failed: ${customer.status()}`);
  await api.storageState({ path: path.join(authDir, "customer.json") });
  const member = await api.post("/api/v1/auth/login", {
    data: { email: "membro.e2e@example.com", password: "E2eSenha#2026" },
  });
  if (!member.ok()) throw new Error(`E2E member login failed: ${member.status()}`);
  await api.storageState({ path: path.join(authDir, "member.json") });
  const customer2 = await api.post("/api/v1/auth/login", {
    data: { email: "cliente2.e2e@example.com", password: "E2eSenha#2026" },
  });
  if (!customer2.ok()) throw new Error(`E2E second customer login failed: ${customer2.status()}`);
  await api.storageState({ path: path.join(authDir, "customer2.json") });
  const privacyOwner = await api.post("/api/v1/auth/login", {
    data: { email: "privacidade.owner.e2e@example.com", password: "E2eSenha#2026" },
  });
  if (!privacyOwner.ok()) throw new Error(`E2E privacy owner login failed: ${privacyOwner.status()}`);
  await api.storageState({ path: path.join(authDir, "privacy-owner.json") });
  const privacyMember = await api.post("/api/v1/auth/login", {
    data: { email: "privacidade.member.e2e@example.com", password: "E2eSenha#2026" },
  });
  if (!privacyMember.ok()) throw new Error(`E2E privacy member login failed: ${privacyMember.status()}`);
  await api.storageState({ path: path.join(authDir, "privacy-member.json") });
  const support = await api.post("/api/v1/support/auth/login", {
    data: { email: "suporte.e2e@example.com", password: "SuporteE2e#2026" },
  });
  if (!support.ok()) throw new Error(`E2E support login failed: ${support.status()}`);
  await api.storageState({ path: path.join(authDir, "support.json") });
  await api.dispose();
}

export default async function globalSetup() {
  if (process.env.E2E_EXTERNAL === "1") return;
  compose(["down", "--remove-orphans"], { allowFailure: true });
  compose(["up", "-d", "--build", "e2e-db", "e2e-api", "e2e-web"]);
  compose(["run", "--rm", "--no-deps", "--build", "e2e-seed"]);
  await waitFor(`${process.env.E2E_BASE_URL || "http://127.0.0.1:3011"}/`);
  await waitFor("http://127.0.0.1:8011/api/v1/health");
  await createStorageState();
}
