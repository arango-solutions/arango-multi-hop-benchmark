import { describe, expect, it } from "vitest";
import { apiBase } from "./client";

describe("apiBase", () => {
  it("returns empty string at the AMP /frontend root", () => {
    expect(apiBase("/frontend/")).toBe("");
  });

  it("returns empty string at the legacy /ui root", () => {
    expect(apiBase("/ui/")).toBe("");
  });

  it("strips the platform proxy prefix before /frontend", () => {
    expect(apiBase("/_service/uds/_global/multihop-eval/frontend/")).toBe(
      "/_service/uds/_global/multihop-eval",
    );
  });

  it("strips a db-scoped platform proxy prefix before /frontend", () => {
    expect(
      apiBase("/_service/uds/_db/mydb/myinstance/frontend/index.html"),
    ).toBe("/_service/uds/_db/mydb/myinstance");
  });

  it("prefers /frontend over /ui when both could match", () => {
    expect(apiBase("/base/frontend/ui/thing")).toBe("/base");
  });

  it("returns empty string when no known prefix is present", () => {
    expect(apiBase("/")).toBe("");
    expect(apiBase("/something/else")).toBe("");
  });
});
