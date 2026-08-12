class TransactionsMapping:
    AMOUNT = {"file": "amount", "object": "amount", "label": "Amount"}

    CATEGORY_1 = {"file": "category", "object": "category_1", "label": "category"}

    CATEGORY_2 = {"file": "subcategory", "object": "category_2", "label": "subcategory"}

    DATE = {"file": "date", "object": "date", "label": "date", "format": "%Y-%m-%d %H:%M:%S"}

    MONTH = {"file": "month", "object": "month", "label": "month"}

    YEAR = {"file": "year", "object": "year", "label": "year"}

    YEAR_MONTH = {"file": "year_month", "object": "year_month", "label": "month"}


class ComponentsMapping:
    APP_TITLE = "Financial Transactions Dashboard"
    SELECT_ALL = "Select all"
