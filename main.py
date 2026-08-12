from dash import Dash
from dash_bootstrap_components.themes import BOOTSTRAP

from src.components.layout import create_layout
from src.config.mapping import ComponentsMapping
from src.data.loader import load_transaction_data
from src.data.source import DataSource

DATA_PATH = "./data/dashboard/transactions.csv"


def main() -> None:
    # load the data and create the data manager
    data = load_transaction_data(DATA_PATH)
    data = DataSource(data)

    app = Dash(external_stylesheets=[BOOTSTRAP])
    app.title = ComponentsMapping.APP_TITLE
    app.layout = create_layout(app, data)
    app.run()


if __name__ == "__main__":
    main()
