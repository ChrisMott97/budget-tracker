import type { Transaction } from "../types";


export async function importCsv(file: File, abort?: AbortSignal): Promise<Transaction[]> {
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
