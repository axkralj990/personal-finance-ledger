import type { Category, Identifier, Subcategory } from "../api/types";

export function subcategoriesFor(categories: Category[], categoryId: Identifier | null): Subcategory[] {
  if (!categoryId) return [];
  return categories.find((category) => category.id === categoryId)?.subcategories.filter((item) => item.active) ?? [];
}

export function taxonomyError(
  categories: Category[],
  categoryId: Identifier | null,
  subcategoryId: Identifier | null,
): string | null {
  if (!subcategoryId) return null;
  if (!categoryId) return "Choose a category before choosing a subcategory.";
  return subcategoriesFor(categories, categoryId).some((item) => item.id === subcategoryId)
    ? null
    : "That subcategory does not belong to the selected category.";
}

export function categoryName(categories: Category[], id: Identifier | null): string {
  return categories.find((category) => category.id === id)?.name ?? "Uncategorized";
}

export function subcategoryName(categories: Category[], id: Identifier | null): string {
  return categories.flatMap((category) => category.subcategories).find((item) => item.id === id)?.name ?? "None";
}
