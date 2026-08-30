import NavBar from "./components/NavBar.tsx";
import * as React from "react";
import {useState} from "react";
import CategoriesPage from "./pages/CategoriesPage.tsx";
import TransactionsPage from "./pages/TransactionsPage.tsx";
import CsvImportPage from "./pages/CsvImportPage.tsx";
import type {pages} from "./types.ts";

export const pageComponentByKey: Record<typeof pages[number]['key'], () => React.JSX.Element> = {
    'categories': CategoriesPage,
    'transactions': TransactionsPage,
    'csv': CsvImportPage
}

function App() {
    const [activePage, setActivePage] = useState<typeof pages[number]['key']>('categories');
    const ActiveComponent = pageComponentByKey[activePage];

    return (
        <div className="p-10">
            <NavBar selected={activePage} onSelect={(page) => setActivePage(page)}/>
            <ActiveComponent/>
        </div>
    )
}

export default App
