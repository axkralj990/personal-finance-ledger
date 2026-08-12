from abc import ABC, abstractmethod

import pandas as pd


class CategoryClassifier(ABC):
    @abstractmethod
    def predict(self, data: pd.DataFrame):
        pass
