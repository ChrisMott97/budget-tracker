import { useMutation } from "@tanstack/react-query";
import type { ParseResult } from "../types";
import { importCsv } from "../api/transactions";

export type ImportStatus = "idle" | "loading" | "error" | "success";

export function useCsvImport() {
    const mutation = useMutation<ParseResult, Error, File>({
        mutationFn: (file) => importCsv(file),
    });

    async function run(file: File) {
        try {
            await mutation.mutateAsync(file);
        } catch {
            // mutateAsync rejects on failure, but the failure is already held in
            // mutation.error and reported through `error` below. Swallowing the
            // rejection keeps `run` safe to await from a submit handler.
        }
    }

    // TanStack calls the in-flight state "pending"; the app's convention for
    // async state is idle | loading | error, so only this name is adapted.
    const status: ImportStatus = mutation.status === "pending" ? "loading" : mutation.status;

    return {
        transactions: mutation.data?.transactions ?? [],
        // The bank/payee -> preset mapping the rows' categories derive from.
        // Exposed here for slices 2-3 (per-row override, editable mapping table);
        // no consumer yet.
        categoryMap: mutation.data?.category_map ?? [],
        status,
        error: mutation.error?.message,
        run,
    };
}
