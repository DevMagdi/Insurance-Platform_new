import { describe, expect, it } from "vitest";

import { ar } from "@/lib/i18n/ar";
import { en } from "@/lib/i18n/en";

function keys(value: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, nested]) =>
    nested && typeof nested === "object" && !Array.isArray(nested)
      ? keys(nested as Record<string, unknown>, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

/** Arabic is the source of truth; a missing English key is a bug, not a fallback (spec §11). */
describe("translation parity", () => {
  const arabic = keys(ar as unknown as Record<string, unknown>);
  const english = keys(en as unknown as Record<string, unknown>);

  it("has at least the screens' worth of keys", () => {
    expect(arabic.length).toBeGreaterThan(180);
  });

  it("mirrors every Arabic key in English", () => {
    expect(english.filter((key) => !arabic.includes(key))).toEqual([]);
    expect(arabic.filter((key) => !english.includes(key))).toEqual([]);
  });

  it("never leaves an empty string behind", () => {
    const empties = [...arabic, ...english].filter((key) => {
      const [namespace, ...rest] = key.split(".");
      const bag = (en as Record<string, unknown>)[namespace ?? ""] ?? (ar as Record<string, unknown>)[namespace ?? ""];
      let cursor: unknown = bag;
      for (const part of rest) cursor = (cursor as Record<string, unknown>)?.[part ?? ""];
      return typeof cursor === "string" && cursor.trim().length === 0;
    });
    expect(empties).toEqual([]);
  });
});
