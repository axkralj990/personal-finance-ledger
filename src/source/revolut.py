from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from classifier.base import CategoryClassifier
from source.base import TransactionsSource


@dataclass
class RevolutSource(TransactionsSource):
    """
    A data source class for parsing exported Revolut CSV statement files.
    This class inherits from TransactionsSource and is designed to handle
    the import and parsing of transaction data from Revolut's exported CSV files.
    Attributes:
        raw_path (Path): The path to the exported Revolut CSV file.
    Methods:
        parse() -> pd.DataFrame:
            Parses the Revolut CSV file at raw_path and returns a DataFrame of transactions.
        predict_categories(predictor) -> pd.DataFrame:
            Reads the preprocessed transactions data from the silver path and predicts transaction
            categories using the provided predictor model.
            Args:
                predictor: A model object that takes transaction data as input and
                    returns predicted categories.
            Returns:
                pd.DataFrame: The transactions DataFrame with an additional column
                    containing the predicted categories.
    """

    bronze_path: Path
    silver_path: Path
    gold_path: Path

    def parse(self) -> pd.DataFrame:
        # remove Type==TOPUP
        return pd.DataFrame()

    def predict_categories(self, classifier: CategoryClassifier) -> pd.DataFrame:
        return pd.DataFrame()
