import { afterEach, expect, it, vi } from "vitest";
import { request, ApiError } from "./client";
afterEach(() => vi.unstubAllGlobals());
it("refuses outbound and protocol-relative endpoints", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  await expect(request("https://outside.example/api")).rejects.toThrow();
  await expect(request("//outside.example/api")).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
it("preserves successful selections in a partial 409 response", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "role_conflict",
          details: {
            updated: [{ role_version: 2 }],
            failed: [{ code: "role_version_conflict" }],
          },
        }),
        { status: 409 },
      ),
    ),
  );
  try {
    await request("/api/contacts/roles");
    throw Error("expected error");
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).details.updated).toHaveLength(1);
  }
});
