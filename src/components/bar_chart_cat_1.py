import plotly.express as px
from dash import Dash, dcc, html
from dash.dependencies import Input, Output

from ..config.mapping import TransactionsMapping
from ..data.source import DataSource
from . import ids


def render(app: Dash, source: DataSource) -> html.Div:
    @app.callback(
        Output(ids.BAR_CHART_1, "children"),
        [
            Input(ids.YEAR_DROPDOWN, "value"),
            Input(ids.MONTH_DROPDOWN, "value"),
            Input(ids.CATEGORY_1_DROPDOWN, "value"),
            Input(ids.CATEGORY_2_DROPDOWN, "value"),
        ],
    )
    def update_bar_chart(
        years: list[str],
        months: list[str],
        category_1: list[str],
        category_2: list[str],
    ) -> html.Div:
        filtered_source = source.filter(years, months, category_1, category_2)
        if not filtered_source.row_count:
            return html.Div("No data to display", id=ids.BAR_CHART_1)
        elif len(category_1) < 2:
            filtered_source = source.filter(years, months, category_1, category_2)
            return html.Div(
                html.H6(f"Total of {category_1[0]}: {filtered_source.total:.02f}")
            )

        fig = px.bar(
            filtered_source.create_pivot_table(
                [TransactionsMapping.CATEGORY_1["object"]]
            ),
            x=TransactionsMapping.CATEGORY_1["object"],
            y=TransactionsMapping.AMOUNT["object"],
            color=TransactionsMapping.CATEGORY_1["object"],
            labels={
                TransactionsMapping.CATEGORY_1[
                    "object"
                ]: TransactionsMapping.CATEGORY_1["label"],
                TransactionsMapping.AMOUNT["object"]: TransactionsMapping.AMOUNT[
                    "label"
                ],
            },
        )

        fig.update_layout(
            plot_bgcolor="#2c2c2c",
            paper_bgcolor="#2c2c2c",
            font=dict(color="#f9f9f9"),
            xaxis=dict(
                showgrid=False,
                color="#f9f9f9",
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor="#444",
                color="#f9f9f9",
            ),
            margin=dict(l=0, r=0, t=0, b=0),  # Remove margins
        )

        # return html.Div(
        #     dcc.Graph(
        #         figure=fig,
        #         # style={
        #         #     "height": "100vh",
        #         #     "width": "100vh",
        #         # },  # Full width, flexible height
        #     ),
        #     id=ids.BAR_CHART_1,
        #     style={
        #         "flex": "1",  # Allow this div to grow and shrink
        #         "display": "flex",
        #         "flex-direction": "column",
        #         "max-height": "100%",  # Set a max height for flexibility
        #         "overflow": "hidden",  # Prevent overflow
        #     },
        # )

        return html.Div(
            dcc.Graph(figure=fig, style={"height": "100%"}), id=ids.BAR_CHART_1
        )

    return html.Div(id=ids.BAR_CHART_1)

    # return html.Div(
    #     id=ids.BAR_CHART_1,
    #     style={
    #         "display": "flex",
    #         "flex-direction": "column",
    #         "height": "100vh",  # Full viewport height
    #         "overflow": "hidden",  # Prevent overflow
    #     },
    # )
