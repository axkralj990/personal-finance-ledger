from dash import Dash, dcc, html
from dash.dependencies import Input, Output

from ..data.source import DataSource
from . import ids
from .dropdown_helper import to_dropdown_options
from ..config.mapping import ComponentsMapping, TransactionsMapping


def render(app: Dash, source: DataSource) -> html.Div:
    @app.callback(
        Output(ids.YEAR_DROPDOWN, "value"),
        Input(ids.SELECT_ALL_YEARS_BUTTON, "n_clicks"),
    )
    def select_all_years(_: int) -> list[str]:
        return source.unique_years

    return html.Div(
        children=[
            html.H6(TransactionsMapping.YEAR["label"]),
            html.Div(
                style={
                    "display": "flex",
                    "alignItems": "center",
                },  # Use flexbox for layout
                children=[
                    dcc.Dropdown(
                        id=ids.YEAR_DROPDOWN,
                        options=to_dropdown_options(source.unique_years),
                        value=source.unique_years,
                        multi=True,
                        style={"min-width": "200px"},
                    ),
                    html.Button(
                        className="dropdown-button",
                        children=[ComponentsMapping.SELECT_ALL],
                        id=ids.SELECT_ALL_YEARS_BUTTON,
                        n_clicks=0,
                        style={
                            "marginLeft": "10px"
                        },  # Add space between dropdown and button
                    ),
                ],
            ),
        ]
    )
