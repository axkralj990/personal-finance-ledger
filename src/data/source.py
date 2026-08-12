from __future__ import annotations  # Required for forward references

from dataclasses import dataclass

import pandas as pd

from ..config.mapping import TransactionsMapping


@dataclass
class DataSource:
    _data: pd.DataFrame

    def filter(
        self,
        years: list[str] | None = None,
        months: list[str] | None = None,
        categories_1: list[str] | None = None,
        categories_2: list[str] | None = None,
    ) -> DataSource:
        if years is None:
            years = self.unique_years
        if months is None:
            months = self.unique_months
        if categories_1 is None:
            categories_1 = self.unique_categories_1
        if categories_2 is None:
            categories_2 = self.unique_categories_2
        filtered_data = self._data.query(
            f"{TransactionsMapping.YEAR['object']} in @years and "
            f"{TransactionsMapping.MONTH['object']} in @months and "
            f"{TransactionsMapping.CATEGORY_1['object']} in @categories_1 and "
            f"{TransactionsMapping.CATEGORY_2['object']} in @categories_2"
        )
        return DataSource(filtered_data)

    def create_pivot_table(self, groups: list) -> pd.DataFrame:
        pt = self._data.pivot_table(
            values=TransactionsMapping.AMOUNT["object"],
            index=groups,
            aggfunc="sum",
            fill_value=0,
            dropna=False,
        )
        return pt.reset_index().sort_values(TransactionsMapping.AMOUNT["object"], ascending=False)

    @property
    def row_count(self) -> int:
        return self._data.shape[0]

    @property
    def column_count(self) -> int:
        return self._data.shape[1]

    @property
    def total(self) -> float:
        return self._data[TransactionsMapping.AMOUNT["object"]].sum()

    @property
    def all_years(self) -> list[str]:
        return self._data[TransactionsMapping.YEAR["object"]].tolist()

    @property
    def all_months(self) -> list[str]:
        return self._data[TransactionsMapping.MONTH["object"]].tolist()

    @property
    def all_categories_1(self) -> list[str]:
        return self._data[TransactionsMapping.CATEGORY_1["object"]].tolist()

    @property
    def all_categories_2(self) -> list[str]:
        return self._data[TransactionsMapping.CATEGORY_2["object"]].tolist()

    @property
    def all_amounts(self) -> list[str]:
        return self._data[TransactionsMapping.AMOUNT["object"]].tolist()

    @property
    def unique_years(self) -> list[str]:
        return sorted(set(self.all_years), key=int)

    @property
    def unique_months(self) -> list[str]:
        return sorted(set(self.all_months), key=int)

    @property
    def unique_categories_1(self) -> list[str]:
        all_categories_1_no_nan = [cat for cat in self.all_categories_1 if type(cat) is str]
        return sorted(set(all_categories_1_no_nan))

    @property
    def unique_categories_2(self) -> list[str]:
        all_categories_2_no_nan = [cat for cat in self.all_categories_2 if type(cat) is str]
        return sorted(set(all_categories_2_no_nan))
