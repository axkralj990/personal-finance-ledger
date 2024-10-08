from dash import Dash, dcc, html
from dash.dependencies import Input, Output

from ..data.source import DataSource
from . import ids
from .dropdown_helper import to_dropdown_options
from ..config.mapping import ComponentsMapping, TransactionsMapping


def render(app: Dash, source: DataSource) -> html.Div:
    @app.callback(
        Output(ids.CATEGORY_1_DROPDOWN, "value"),
        Input(ids.SELECT_ALL_CATEGORIES_1_BUTTON, "n_clicks"),
    )
    def select_all_cat_1(_: int) -> list[str]:
        return source.unique_categories_1

    return html.Div(
        children=[
            html.H6(TransactionsMapping.CATEGORY_1["label"]),
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                },  # Use flexbox for layout
                children=[
                    dcc.Dropdown(
                        id=ids.CATEGORY_1_DROPDOWN,
                        options=to_dropdown_options(source.unique_categories_1),
                        value=source.unique_categories_1,
                        multi=True,
                        style={"min-width": "200px"},
                    ),
                    html.Button(
                        className="dropdown-button",
                        children=[ComponentsMapping.SELECT_ALL],
                        id=ids.SELECT_ALL_CATEGORIES_1_BUTTON,
                        n_clicks=0,
                        style={
                            "marginLeft": "10px"
                        },  # Add space between dropdown and button
                    ),
                ],
            ),
        ]
    )
