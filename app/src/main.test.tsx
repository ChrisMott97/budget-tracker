import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";

// This imports main.tsx for real, so the QueryClientProvider at the app root is
// covered too. Without it, useCsvImport's useMutation throws during render and
// the form never appears — the hook tests cannot catch that, because they
// supply their own provider.
describe("app entry point", () => {
    it("mounts the app under a QueryClientProvider", async () => {
        document.body.innerHTML = '<div id="root"></div>';

        await import("./main.tsx");

        await waitFor(() => expect(screen.getByRole("button", { name: "Import CSV" })).toBeTruthy());
    });
});
