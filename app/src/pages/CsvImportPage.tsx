import TransactionsTable from "../components/TransactionsTable.tsx";
import { useCsvImport } from "../hooks/useCsvImport";

export default function CsvImportPage() {
    const { transactions, status, error, run } = useCsvImport();

    async function submit(e: React.SubmitEvent<HTMLFormElement>) {
        e.preventDefault();
        const form = e.currentTarget;
        const formData = new FormData(form);
        const file = formData.get("csvFile") as File;
        if (!file || file.size === 0) {
            console.error("No file selected or file is empty");
            form.reset();
            return;
        }

        await run(file);
        form.reset();
    }

    return (
        <div className="flex flex-col gap-4 items-center">
            <h1 className="text-2xl font-bold mb-4">Import Transactions from CSV</h1>
            <form onSubmit={submit} className="flex flex-col gap-4 items-center">
                <input type="file" name="csvFile" accept=".csv" className="border border-gray-300 rounded p-3" />
                <button type="submit" disabled={status === "loading"} className="bg-blue-500 cursor-pointer text-white font-bold py-2 px-4 rounded">
                    {status === "loading" ? "Importing..." : "Import CSV"}
                </button>
            </form>
            {error && <p role="alert" className="text-red-600">{error}</p>}
            <TransactionsTable transactions={transactions} />
        </div>
    );
}
