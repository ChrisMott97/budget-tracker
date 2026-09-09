import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useCategoryOverrides } from "./useCategoryOverrides";

describe("useCategoryOverrides", () => {
    it("records an override for a row index", () => {
        const { result } = renderHook(() => useCategoryOverrides());

        act(() => result.current.setOverride(2, "Bills"));

        expect(result.current.overrides).toEqual({ 2: "Bills" });
    });

    it("replacing an override for the same row keeps only the latest", () => {
        const { result } = renderHook(() => useCategoryOverrides());

        act(() => result.current.setOverride(2, "Bills"));
        act(() => result.current.setOverride(2, "Groceries"));

        expect(result.current.overrides).toEqual({ 2: "Groceries" });
    });

    it("reset clears all overrides", () => {
        const { result } = renderHook(() => useCategoryOverrides());

        act(() => result.current.setOverride(0, "Income"));
        act(() => result.current.setOverride(3, ""));
        act(() => result.current.reset());

        expect(result.current.overrides).toEqual({});
    });
});
