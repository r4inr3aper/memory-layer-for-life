import { exportFileName } from "@/lib/dataExport";

jest.mock("expo-file-system", () => ({ File: jest.fn(), Paths: {} }));
jest.mock("expo-sharing", () => ({}));
jest.mock("@/lib/api/me", () => ({ getMyExport: jest.fn() }));

describe("exportFileName", () => {
  it("names the file after the day the backend made the export", () => {
    expect(exportFileName("2026-10-24T18:30:00+00:00")).toBe(
      "zoop-export-2026-10-24.json",
    );
  });

  it("falls back to today's date", () => {
    const now = new Date("2026-01-05T08:00:00Z");
    expect(exportFileName(undefined, now)).toBe("zoop-export-2026-01-05.json");
    expect(exportFileName("not a date", now)).toBe(
      "zoop-export-2026-01-05.json",
    );
  });
});
