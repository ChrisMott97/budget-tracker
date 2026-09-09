import { useCallback, useState } from "react";

// Manual per-row category edits, keyed by row index into the current import's
// transaction list. Client-only until persistence lands (milestone 2). Lifted
// into its own hook so slice 3 can read which rows are overridden and skip them
// when re-applying an edited mapping entry.
export function useCategoryOverrides() {
    const [overrides, setOverrides] = useState<Record<number, string>>({});

    // `value` of "" is meaningful: it sends the row back to Uncategorised.
    const setOverride = useCallback((index: number, value: string) => {
        setOverrides((current) => ({ ...current, [index]: value }));
    }, []);

    // Called after a new import: row indices from the previous file would
    // otherwise point at unrelated rows.
    const reset = useCallback(() => setOverrides({}), []);

    return { overrides, setOverride, reset };
}
