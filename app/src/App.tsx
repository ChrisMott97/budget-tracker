import NavBar from "./components/NavBar.tsx";
import * as React from "react";
import {useState} from "react";
import CsvImportPage from "./pages/CsvImportPage.tsx";
import type {pages} from "./types.ts";

export const pageComponentByKey: Record<typeof pages[number]['key'], () => React.JSX.Element> = {
    'csv': CsvImportPage
}

function App() {
    const [activePage, setActivePage] = useState<typeof pages[number]['key']>('csv');
    const ActiveComponent = pageComponentByKey[activePage];
    // Hide navigation while it's not required yet in the project
    const showNavigation = false;

    return (
        <div className="p-10">
            {showNavigation && <NavBar selected={activePage} onSelect={(page) => setActivePage(page)}/>}
            <ActiveComponent/>
        </div>
    )
}

export default App
