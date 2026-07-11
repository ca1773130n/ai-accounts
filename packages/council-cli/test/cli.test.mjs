import { describe, expect, it } from "vitest";
import { drainSse, main, progressLine } from "../bin/aia-council.mjs";

describe("drainSse", () => {
  it("extracts data payloads and keeps the partial tail", () => {
    const [events, rest] = drainSse(
      'event: council\ndata: {"kind":"council_start","payload":{"members":[]}}\n\n' +
        ": heartbeat 1\ndata: not-json\n" +
        'data: {"kind":"decision","payload":{"choice":1}}\ndata: {"kind":"par',
    );
    expect(events.map((e) => e.kind)).toEqual(["council_start", "decision"]);
    expect(rest).toBe('data: {"kind":"par');
  });
});

describe("progressLine", () => {
  it("formats interesting kinds and stays silent on decision", () => {
    expect(
      progressLine({
        kind: "council_start",
        payload: { members: [{ role: "architect", account_label: "A1" }] },
      }),
    ).toContain("council convened");
    expect(progressLine({ kind: "position", role: "architect", option: 2 })).toBe(
      "position [architect] votes 2",
    );
    expect(progressLine({ kind: "decision", payload: {} })).toBeNull();
  });
});

describe("main argument validation", () => {
  it("exits 2 without two options", async () => {
    expect(await main(["-q", "which?", "-o", "only one"])).toBe(2);
  });

  it("exits 0 on --help", async () => {
    expect(await main(["--help"])).toBe(0);
  });
});
