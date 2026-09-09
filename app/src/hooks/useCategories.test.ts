import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useCategories } from "./useCategories";
import { createQueryWrapper } from "../test/queryClientWrapper.tsx";

const presets = ["Groceries", "Bills", "Income"];

const ok = () =>
    new Response(JSON.stringify({ categories: presets }), { status: 200 });

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("useCategories", () => {
    it("exposes the fetched preset list", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok()));
        const { result } = renderHook(() => useCategories(), { wrapper: createQueryWrapper() });

        await waitFor(() => expect(result.current.categories).toEqual(presets));
    });

    it("returns an empty list while the request is in flight", () => {
        vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>(() => {})));
        const { result } = renderHook(() => useCategories(), { wrapper: createQueryWrapper() });

        expect(result.current.categories).toEqual([]);
    });
});
