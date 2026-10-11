import { expect, test } from "@playwright/test";

import { measurementRows } from "../../lib/event-measurements";

test("absent measurements do not become zero readings", () => {
  expect(measurementRows(null)).toEqual([]);
  expect(measurementRows(undefined)).toEqual([]);
  expect(measurementRows({ rule_version: "dms-0.6", ear: null })).toEqual([]);
});

test("measured zero remains visible alongside valid readings", () => {
  const rows = measurementRows({ closed_ms: 0, ear: 0.234, blink_count_60s: 0 });
  expect(rows).toHaveLength(3);
  expect(rows.find((row) => row.key === "closed_ms")?.value).toBe("0.0 с");
  expect(rows.find((row) => row.key === "blink_count_60s")?.value).toBe("0");
});

test("native relative head ratios are never represented as calibrated degrees", () => {
  const rows = measurementRows({ head_delta: 0.063, yaw_delta: -0.082, away_ms: 2700 });
  expect(rows.find((row) => row.key === "head_delta")?.value).toBe("0.063");
  expect(rows.find((row) => row.key === "yaw_delta")?.value).toBe("-0.082");
  expect(rows.find((row) => row.key === "away_ms")?.value).toBe("2.7 с");
  expect(rows.some((row) => row.value.includes("°"))).toBe(false);
});

test("non-finite readings are not shown even with a malformed response", () => {
  expect(measurementRows({ ear: Number.NaN, perclos_pct: Infinity })).toEqual([]);
});
