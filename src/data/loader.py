import pandas as pd
import numpy as np
from src.config.mapping import TransactionsMapping


def create_year_column(df: pd.DataFrame) -> pd.DataFrame:
    df[TransactionsMapping.YEAR["object"]] = df[TransactionsMapping.DATE["file"]].dt.year.astype(
        str
    )
    return df


def create_month_column(df: pd.DataFrame) -> pd.DataFrame:
    df[TransactionsMapping.MONTH["object"]] = df[TransactionsMapping.DATE["file"]].dt.month.astype(
        str
    )
    return df


def create_year_month_column(df: pd.DataFrame) -> pd.DataFrame:
    # df[TransactionsMapping.YEAR_MONTH['object']] = df[TransactionsMapping.DATE['file']].dt.to_period('M')
    df[TransactionsMapping.YEAR_MONTH["object"]] = df[
        TransactionsMapping.DATE["object"]
    ].dt.strftime("%Y-%m")
    return df


def load_transaction_data(path: str) -> pd.DataFrame:
    data = pd.read_csv(
        path,
        dtype={
            TransactionsMapping.AMOUNT["file"]: float,
            TransactionsMapping.CATEGORY_1["file"]: str,
            TransactionsMapping.CATEGORY_2["file"]: str,
            TransactionsMapping.DATE["file"]: str,
        },
    )
    data[TransactionsMapping.DATE["file"]] = pd.to_datetime(
        data[TransactionsMapping.DATE["file"]], format=TransactionsMapping.DATE["format"]
    )
    # replace missing values with misc
    data[TransactionsMapping.CATEGORY_2["file"]] = data[
        TransactionsMapping.CATEGORY_2["file"]
    ].fillna("Misc")

    data = data.rename(
        columns={
            TransactionsMapping.AMOUNT["file"]: TransactionsMapping.AMOUNT["object"],
            TransactionsMapping.CATEGORY_1["file"]: TransactionsMapping.CATEGORY_1["object"],
            TransactionsMapping.CATEGORY_2["file"]: TransactionsMapping.CATEGORY_2["object"],
            TransactionsMapping.DATE["file"]: TransactionsMapping.DATE["object"],
        }
    )

    # data[TransactionsMapping.AMOUNT["object"]] = np.abs(data[TransactionsMapping.AMOUNT["object"]])

    return data.pipe(create_year_column).pipe(create_month_column).pipe(create_year_month_column)
