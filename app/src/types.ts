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
}
