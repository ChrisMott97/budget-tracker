import { useState } from "react";
import type { Transaction } from "../types";
import { importCsv } from "../api/transactions";

type ImportState =
    | { status: "idle"; transactions: Transaction[] }
    | { status: "loading"; transactions: Transaction[] }
    | { status: "error"; error: string; transactions: Transaction[] }

export function useCsvImport() {
    const [state, setState] = useState<ImportState>({ status: "idle", transactions: [] });

    async function run(file: File) {
        setState({ status: "loading", transactions: [] });
        try {
            const transactions = await importCsv(file);
            setState({status: "idle", transactions});
        } catch (error) {
            setState({ status: "error", error: (error as Error).message, transactions: [] });
        }
    }

    return {
        transactions: state.transactions,
        status: state.status,
        error: state.status === "error" ? state.error : undefined,
        run,
    }
}
