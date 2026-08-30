export const pages = [
    {
        title: "Categories",
        key: 'categories',
    },
    {
        title: "Transactions",
        key: 'transactions',
    },
    {
        title: "CSV",
        key: 'csv',
    }
] as const

export type PageKey = typeof pages[number]['key']