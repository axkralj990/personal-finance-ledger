import type { Category } from "../api/types";
import { subcategoriesFor, taxonomyError } from "./taxonomy";

const categories: Category[] = [
  { id: "food", name: "Food", sortOrder: 1, active: true, subcategories: [{ id: "cafes", categoryId: "food", name: "Cafes", sortOrder: 1, active: true }] },
  { id: "home", name: "Home", sortOrder: 2, active: true, subcategories: [{ id: "rent", categoryId: "home", name: "Rent", sortOrder: 1, active: true }] },
];

describe("dependent taxonomy selection", () => {
  it("offers only subcategories owned by the selected parent", () => {
    expect(subcategoriesFor(categories, "food").map((item) => item.id)).toEqual(["cafes"]);
    expect(subcategoriesFor(categories, "home").map((item) => item.id)).toEqual(["rent"]);
  });

  it("explains an invalid parent and child combination", () => {
    expect(taxonomyError(categories, "food", "rent")).toBe("That subcategory does not belong to the selected category.");
    expect(taxonomyError(categories, "home", "rent")).toBeNull();
  });
});
