import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import TransactionsTable from "./TransactionsTable.tsx";
import type { Transaction } from "../types";

// vitest globals are off, so testing-library's afterEach auto-cleanup never
// registers; without this each test renders on top of the previous DOM.
afterEach(cleanup);

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

describe("TransactionsTable", () => {
    it("shows a column for each optional fact the rows carry", () => {
        render(<TransactionsTable transactions={[rich]} />);

        for (const name of ["Date", "Description", "Category", "Type", "Reference", "Amount", "Balance"]) {
            expect(screen.getByRole("columnheader", { name })).toBeTruthy();
        }
        expect(screen.getByRole("cell", { name: "Groceries" })).toBeTruthy();
        // Currency folds into the money cells rather than a column of its own.
        expect(screen.getByRole("cell", { name: "GBP -31.62" })).toBeTruthy();
        expect(screen.getByRole("cell", { name: "GBP 4786.63" })).toBeTruthy();
    });

    it("omits the optional columns when no row carries them", () => {
        render(<TransactionsTable transactions={[bare]} />);

        for (const name of ["Date", "Description", "Amount"]) {
            expect(screen.getByRole("columnheader", { name })).toBeTruthy();
        }
        for (const name of ["Category", "Type", "Reference", "Balance"]) {
            expect(screen.queryByRole("columnheader", { name })).toBeNull();
        }
        // No currency on the row, so the amount falls back to a £ prefix.
        expect(screen.getByRole("cell", { name: "£-12.50" })).toBeTruthy();
    });

    it("renders a column only when at least one row fills it", () => {
        render(<TransactionsTable transactions={[bare, rich]} />);

        // rich carries a category, bare does not: the column shows, bare's cell is blank.
        expect(screen.getByRole("columnheader", { name: "Category" })).toBeTruthy();
        expect(screen.getAllByRole("row")).toHaveLength(3); // header + 2 data rows
    });
});
