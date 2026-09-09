import type { CategoryPresets } from "../types";

export async function fetchCategories(): Promise<string[]> {
    const res = await fetch("/api/categories");
    if (!res.ok) throw new Error("Failed to load categories");

    const body: CategoryPresets = await res.json();
    return body.categories;
}
