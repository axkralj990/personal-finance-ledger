from abc import ABC, abstractmethod

import pandas as pd


class TransactionsSource(ABC):
    @abstractmethod
    def parse(self) -> pd.DataFrame:
        pass
