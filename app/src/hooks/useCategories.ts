import { useQuery } from "@tanstack/react-query";
import { fetchCategories } from "../api/categories";

// The preset list is static for the session, so no invalidation is wired up.
// `categories` is [] until the request settles; the dropdown just shows fewer
// options for that tick.
export function useCategories() {
    const query = useQuery({ queryKey: ["categories"], queryFn: fetchCategories });

    return { categories: query.data ?? [] };
}
