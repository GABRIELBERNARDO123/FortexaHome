import { describe, expect, it } from "vitest";

import { idempotencyHeaders, newIdempotencyKey } from "../lib/api";

describe("idempotency key do cliente", () => {
  it("gera chaves diferentes para operações diferentes", () => {
    const first = newIdempotencyKey();
    const second = newIdempotencyKey();
    expect(first).not.toBe(second);
    expect(first.length).toBeGreaterThanOrEqual(8);
    expect(first).toMatch(/^[A-Za-z0-9._:-]+$/);
  });

  it("envia a chave no cabeçalho Idempotency-Key", () => {
    expect(idempotencyHeaders("chave-123")).toEqual({ "Idempotency-Key": "chave-123" });
  });
});
