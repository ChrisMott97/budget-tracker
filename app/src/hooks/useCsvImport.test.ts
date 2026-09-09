import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useCsvImport } from "./useCsvImport";
import { createQueryWrapper } from "../test/queryClientWrapper.tsx";

const csvFile = () => new File(["Date,Description,Amount\n"], "bank.csv", { type: "text/csv" });

const rows = [{ date: "2025-03-12", description: "TESCO STORES", amount: -12.5 }];

const ok = () => new Response(JSON.stringify(rows), { status: 200 });
const serverError = () => new Response("boom", { status: 500 });

// TanStack pushes mutation state to the component through its notify manager,
// which lands a tick after mutateAsync settles. Assertions therefore wait for
// the status rather than reading it straight after the act.
const expectStatus = (read: () => string, expected: string) =>
    waitFor(() => expect(read()).toBe(expected));

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("useCsvImport", () => {
    it("stores the returned transactions and reports success", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(ok()));
        const { result } = renderHook(() => useCsvImport(), { wrapper: createQueryWrapper() });

        await act(() => result.current.run(csvFile()));

        await expectStatus(() => result.current.status, "success");
        expect(result.current.transactions).toEqual(rows);
        expect(result.current.error).toBeUndefined();
    });

    it("exposes an error and clears transactions when the API fails", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(serverError()));
        const { result } = renderHook(() => useCsvImport(), { wrapper: createQueryWrapper() });

        await act(() => result.current.run(csvFile()));

        await expectStatus(() => result.current.status, "error");
        expect(result.current.error).toBe("Failed to import CSV");
        expect(result.current.transactions).toEqual([]);
    });

    it("posts the file as multipart form data to the transactions endpoint", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
        vi.stubGlobal("fetch", fetchMock);
        const { result } = renderHook(() => useCsvImport(), { wrapper: createQueryWrapper() });

        await act(() => result.current.run(csvFile()));

        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe("/api/transactions");
        expect(init.method).toBe("POST");
        expect(init.body).toBeInstanceOf(FormData);
    });

    it("clears a previous error when a later import succeeds", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValueOnce(serverError()).mockResolvedValueOnce(ok()),
        );
        const { result } = renderHook(() => useCsvImport(), { wrapper: createQueryWrapper() });

        await act(() => result.current.run(csvFile()));
        await expectStatus(() => result.current.status, "error");

        await act(() => result.current.run(csvFile()));

        await expectStatus(() => result.current.status, "success");
        expect(result.current.error).toBeUndefined();
        expect(result.current.transactions).toEqual(rows);
    });

    it("reports loading while the import is in flight", async () => {
        let release: (value: Response) => void = () => {};
        vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((resolve) => { release = resolve; })));
        const { result } = renderHook(() => useCsvImport(), { wrapper: createQueryWrapper() });

        let pending: Promise<void>;
        await act(() => { pending = result.current.run(csvFile()); });

        await expectStatus(() => result.current.status, "loading");

        await act(async () => {
            release(ok());
            await pending;
        });

        await expectStatus(() => result.current.status, "success");
    });
});
