export const pages = [
    {
        title: "Home",
        key: 'csv',
    }
] as const

export type PageKey = typeof pages[number]['key']
