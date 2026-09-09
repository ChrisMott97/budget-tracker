import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";

/**
 * A fresh QueryClient per call, so cached data never leaks between tests, with
 * retries off so a failed request surfaces its error immediately instead of
 * after TanStack's backoff.
 */
export function createQueryWrapper() {
    const client = new QueryClient({
        defaultOptions: {
            queries: { retry: false },
            mutations: { retry: false },
        },
    });

    return function QueryWrapper({ children }: PropsWithChildren) {
        return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    };
}
