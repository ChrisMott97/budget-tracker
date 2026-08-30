import { useState } from "react";

interface Transaction {
    date: string;
    description: string;
    amount: number;
}

export default function CsvImportPage() {
    const [transactions, setTransactions] = useState<Transaction[]>([]);

    function submit(formData: FormData) {
        const file = formData.get("csvFile") as File;
        if (!file) {
            throw new Error("No file selected");
        }

        const body = new FormData();
        body.append("file", file);

        fetch("/api/transactions", {
            method: "POST",
            body,
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error("Failed to import CSV");
                }
                return response.json();
            })
            .then((data) => {
                setTransactions(data);
            })
            .catch((error) => {
                console.error("Error importing CSV:", error);
            });
    }

    const rows = transactions.map(transaction => (
        <tr key={transaction.date + transaction.description}>
            <td>{transaction.date}</td>
            <td>{transaction.description}</td>
            <td>£{transaction.amount.toFixed(2)}</td>
        </tr>
    ))

    return (
        <>
            <form action={submit} className="flex flex-col gap-4 items-start">
                <input type="file" name="csvFile" accept=".csv" />
                <button type="submit">Import CSV</button>
            </form>
            <table className="table-fixed w-150">
                <thead>
                    <tr className="text-left">
                        <th>Date</th>
                        <th>Description</th>
                        <th>Amount</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </>
    );
}
