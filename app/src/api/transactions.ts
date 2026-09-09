import type { ParseResult } from "../types";


export async function importCsv(file: File, abort?: AbortSignal): Promise<ParseResult> {
    const body = new FormData();
    body.append("file", file);

    const res = await fetch("/api/transactions", {
        method: "POST",
        signal: abort,
        body,
    });
    if (!res.ok) throw new Error("Failed to import CSV");

    return res.json();
}
