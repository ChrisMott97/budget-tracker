import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import TransactionsTable from "./TransactionsTable.tsx";
import type { Transaction } from "../types";

// vitest globals are off, so testing-library's afterEach auto-cleanup never
// registers; without this each test renders on top of the previous DOM.
afterEach(cleanup);

const PRESETS = [
    "Groceries", "Eating out", "Transport", "Shopping", "Bills", "Entertainment",
    "Health", "Housing", "Savings", "Income", "Transfers", "Fees & charges",
];

const bare: Transaction = { date: "2025-03-12", description: "TESCO STORES", amount: -12.5 };

const rich: Transaction = {
    date: "2026-09-07",
    description: "Tesco",
    amount: -31.62,
    balance: 4786.63,
    category: "Groceries",
    reference: "TESCO",
    txn_type: "Card payment",
    currency: "GBP",
};

function renderTable(
    transactions: Transaction[],
    opts: { categories?: string[]; overrides?: Record<number, string> } = {},
) {
    const onOverride = vi.fn();
    render(
        <TransactionsTable
            transactions={transactions}
            categories={opts.categories ?? PRESETS}
            overrides={opts.overrides ?? {}}
            onOverride={onOverride}
        />,
    );
    return { onOverride };
}

describe("TransactionsTable", () => {
    it("shows a column for each optional fact the rows carry", () => {
        renderTable([rich]);

        for (const name of ["Date", "Description", "Category", "Type", "Reference", "Amount", "Balance"]) {
            expect(screen.getByRole("columnheader", { name })).toBeTruthy();
        }
        // Category is an override control, pre-set to the row's resolved preset.
        const select = screen.getByRole("combobox", { name: "Category for Tesco" }) as HTMLSelectElement;
        expect(select.value).toBe("Groceries");
        // Currency folds into the money cells rather than a column of its own.
        expect(screen.getByRole("cell", { name: "GBP -31.62" })).toBeTruthy();
        expect(screen.getByRole("cell", { name: "GBP 4786.63" })).toBeTruthy();
    });

    it("omits the optional columns when no row carries them", () => {
        renderTable([bare]);

        for (const name of ["Date", "Description", "Category", "Amount"]) {
            expect(screen.getByRole("columnheader", { name })).toBeTruthy();
        }
        for (const name of ["Type", "Reference", "Balance"]) {
            expect(screen.queryByRole("columnheader", { name })).toBeNull();
        }
        // No currency on the row, so the amount falls back to a £ prefix.
        expect(screen.getByRole("cell", { name: "£-12.50" })).toBeTruthy();
    });

    it("renders an optional column only when at least one row fills it", () => {
        renderTable([bare, rich]);

        // rich carries a txn_type, bare does not: the column shows all the same.
        expect(screen.getByRole("columnheader", { name: "Type" })).toBeTruthy();
        expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2 data rows
    });

    it("renders a category select on every row selecting the row's current category", () => {
        renderTable([bare, rich]);

        const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
        expect(selects).toHaveLength(2);
        expect(selects[0].value).toBe(""); // bare has no category
        expect(selects[1].value).toBe("Groceries");
    });

    it("defaults an uncategorised row to Uncategorised and lists every preset", () => {
        renderTable([bare]);

        const select = screen.getByRole("combobox", { name: "Category for TESCO STORES" }) as HTMLSelectElement;
        expect(select.value).toBe("");
        const options = [...select.options].map((option) => option.textContent);
        expect(options).toEqual(["Uncategorised", ...PRESETS]);
    });

    it("calls onOverride with the row index and chosen value when a select changes", () => {
        const { onOverride } = renderTable([bare, rich]);

        const select = screen.getByRole("combobox", { name: "Category for Tesco" });
        fireEvent.change(select, { target: { value: "Bills" } });

        expect(onOverride).toHaveBeenCalledWith(1, "Bills");
    });

    it("shows an override value in place of the parsed category", () => {
        renderTable([rich], { overrides: { 0: "Bills" } });

        const select = screen.getByRole("combobox", { name: "Category for Tesco" }) as HTMLSelectElement;
        expect(select.value).toBe("Bills");
    });
});
