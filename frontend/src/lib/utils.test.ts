import { describe, expect, it } from "vitest";
import { safeHttpUrl } from "./utils";

describe("safeHttpUrl", () => {
  it("allows only absolute http(s) URLs as links", () => {
    expect(safeHttpUrl("https://github.com/acme/adr/blob/main/004.md")).toBe(true);
    expect(safeHttpUrl("http://example.org/x")).toBe(true);
    expect(safeHttpUrl("javascript:alert(1)")).toBe(false);
    expect(safeHttpUrl("JaVaScRiPt:alert(1)")).toBe(false);
    expect(safeHttpUrl("data:text/html,<script>alert(1)</script>")).toBe(false);
    expect(safeHttpUrl("docs/adr/004.md")).toBe(false);
    expect(safeHttpUrl("")).toBe(false);
  });
});
