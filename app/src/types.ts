export const pages = [
    {
        title: "Home",
        key: 'csv',
    }
] as const

export type PageKey = typeof pages[number]['key']

export interface Transaction {
    date: string;
    description: string;
    amount: number;
    // Present only when the bank's file carries the fact: filled from a layer-A
    // `exact` column, or (reference / txn_type) from a layer-B slot.
    balance?: number | null;
    category?: string | null;
    reference?: string | null;
    txn_type?: string | null;
    currency?: string | null;
    // The bank category label or payee string that produced `category`. Lets the
    // table regroup rows under an edited mapping entry (slices 2-3) without a
    // re-upload.
    category_source?: string | null;
}

// One row of the bank/payee -> preset mapping the API returns alongside the
// transactions. `kind` is the provenance: a bank category column mapped
// set-to-set, or the payee fallback.
export interface CategoryMapEntry {
    source: string;
    target: string | null;
    kind: "bank" | "payee";
}

export interface ParseResult {
    transactions: Transaction[];
    category_map: CategoryMapEntry[];
}
