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
}
