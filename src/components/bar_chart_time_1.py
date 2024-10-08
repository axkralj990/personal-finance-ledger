import plotly.express as px
from dash import Dash, dcc, html
from dash.dependencies import Input, Output

from ..config.mapping import TransactionsMapping
from ..data.source import DataSource
from . import ids


def render(app: Dash, source: DataSource) -> html.Div:
    @app.callback(
        Output(ids.BAR_CHART_TIME_1, "children"),
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
            return html.Div("No data to display", id=ids.BAR_CHART_TIME_1)

        fig = px.bar(
            filtered_source.create_pivot_table(
                [
                    TransactionsMapping.YEAR_MONTH["object"],
                    TransactionsMapping.CATEGORY_1["object"],
                ]
            ),
            x=TransactionsMapping.YEAR_MONTH["object"],
            y=TransactionsMapping.AMOUNT["object"],
            color=TransactionsMapping.CATEGORY_1["object"],
            barmode="group",
            labels={
                TransactionsMapping.CATEGORY_1[
                    "object"
                ]: TransactionsMapping.CATEGORY_1["label"],
                TransactionsMapping.AMOUNT["object"]: TransactionsMapping.AMOUNT[
                    "label"
                ],
                TransactionsMapping.YEAR_MONTH[
                    "object"
                ]: TransactionsMapping.YEAR_MONTH["label"],
            },
        )

        fig.update_layout(
            plot_bgcolor="#2c2c2c",  # Background color of the plot area
            paper_bgcolor="#2c2c2c",  # Background color outside the plot area
            font=dict(color="#f9f9f9"),  # Font color
            xaxis=dict(
                showgrid=False,  # Disable gridlines for x-axis
                color="#f9f9f9",  # Text color for x-axis labels
            ),
            yaxis=dict(
                showgrid=True,  # Enable gridlines for y-axis
                gridcolor="#444",  # Color of gridlines
                color="#f9f9f9",  # Text color for y-axis labels
            ),
        )

        fig.update_layout(showlegend=False)

        return html.Div(dcc.Graph(figure=fig), id=ids.BAR_CHART_TIME_1)

    return html.Div(id=ids.BAR_CHART_TIME_1)
