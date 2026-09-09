import type { Transaction } from "../types";

// Facts that only some banks carry. Rendered as a column only when the current
// result populates it, so a sparse export (Amex: date, description, amount) does
// not grow empty columns. Category is not here: its cell is an always-present
// override control, so the column shows on every result.
const OPTIONAL_COLUMNS = [
    { key: "txn_type", label: "Type" },
    { key: "reference", label: "Reference" },
] as const;

function hasValue(transactions: Transaction[], key: keyof Transaction): boolean {
    return transactions.some((transaction) => {
        const value = transaction[key];
        return value !== null && value !== undefined && value !== "";
    });
}

function money(value: number, currency?: string | null): string {
    const amount = value.toFixed(2);
    return currency ? `${currency} ${amount}` : `£${amount}`;
}

interface TransactionsTableProps {
    transactions: Transaction[];
    categories: string[];
    overrides: Record<number, string>;
    onOverride: (index: number, value: string) => void;
}

export default function TransactionsTable({
    transactions,
    categories,
    overrides,
    onOverride,
}: TransactionsTableProps) {
    const optionalColumns = OPTIONAL_COLUMNS.filter((column) => hasValue(transactions, column.key));
    const showBalance = hasValue(transactions, "balance");

    return (
        <table className="w-full max-w-4xl mt-4 text-sm">
            <thead>
                <tr className="text-left border-b border-gray-300">
                    <th className="p-2">Date</th>
                    <th className="p-2">Description</th>
                    <th className="p-2">Category</th>
                    {optionalColumns.map((column) => (
                        <th key={column.key} className="p-2">{column.label}</th>
                    ))}
                    <th className="p-2 text-right">Amount</th>
                    {showBalance && <th className="p-2 text-right">Balance</th>}
                </tr>
            </thead>
            <tbody>
                {transactions.map((transaction, index) => (
                    <tr key={`${transaction.date}-${index}`} className="border-t border-gray-200">
                        <td className="p-2 whitespace-nowrap">{transaction.date}</td>
                        <td className="p-2">{transaction.description}</td>
                        <td className="p-2">
                            <select
                                aria-label={`Category for ${transaction.description}`}
                                className="border border-gray-300 rounded p-1"
                                value={overrides[index] ?? transaction.category ?? ""}
                                onChange={(e) => onOverride(index, e.target.value)}
                            >
                                <option value="">Uncategorised</option>
                                {categories.map((category) => (
                                    <option key={category} value={category}>{category}</option>
                                ))}
                            </select>
                        </td>
                        {optionalColumns.map((column) => (
                            <td key={column.key} className="p-2">{transaction[column.key] ?? ""}</td>
                        ))}
                        <td className="p-2 text-right whitespace-nowrap">
                            {money(transaction.amount, transaction.currency)}
                        </td>
                        {showBalance && (
                            <td className="p-2 text-right whitespace-nowrap">
                                {transaction.balance == null ? "" : money(transaction.balance, transaction.currency)}
                            </td>
                        )}
                    </tr>
                ))}
            </tbody>
        </table>
    );
}
