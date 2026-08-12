import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html
from dash.dependencies import Input, Output

from ..config.mapping import TransactionsMapping
from ..data.source import DataSource
from . import ids


def render(app: Dash, source: DataSource) -> html.Div:
    @app.callback(
        Output(ids.LINE_CHART_CAT_1, "children"),
        [
            Input(ids.YEAR_DROPDOWN, "value"),
            Input(ids.MONTH_DROPDOWN, "value"),
            Input(ids.CATEGORY_1_DROPDOWN, "value"),
            Input(ids.CATEGORY_2_DROPDOWN, "value"),
        ],
    )
    def update_line_chart(
        years: list[str],
        months: list[str],
        category_1: list[str],
        category_2: list[str],
    ) -> html.Div:
        filtered_source = source.filter(years, months, category_1, category_2)
        if not filtered_source.row_count:
            return html.Div("No data to display", id=ids.LINE_CHART_CAT_1)

        display_df = filtered_source.create_pivot_table(
            [
                TransactionsMapping.YEAR["object"],
                TransactionsMapping.MONTH["object"],
            ]
        )

        display_df[TransactionsMapping.MONTH["object"]] = pd.Categorical(
            display_df[TransactionsMapping.MONTH["object"]],
            categories=[str(i) for i in range(1, 13)],
            ordered=True,
        )

        display_df.sort_values(
            by=[
                TransactionsMapping.YEAR["object"],
                TransactionsMapping.MONTH["object"],
            ],
            inplace=True,
        )

        display_df[TransactionsMapping.YEAR["object"]] = pd.Categorical(
            display_df[TransactionsMapping.YEAR["object"]],
            categories=[str(i) for i in range(2021, 2026)],
            ordered=True,
        )

        fig = px.line(
            display_df,
            x=TransactionsMapping.MONTH["object"],
            y=TransactionsMapping.AMOUNT["object"],
            color=TransactionsMapping.YEAR["object"],
            markers=True,
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

        return html.Div(dcc.Graph(figure=fig), id=ids.LINE_CHART_CAT_1)

    return html.Div(id=ids.LINE_CHART_CAT_1)
