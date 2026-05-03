"""Main Dash application for the Fridge Health Dashboard."""

import base64
import json
from datetime import date, datetime
from typing import List, Dict, Any

import dash
from dash import dcc, html, Input, Output, State, callback, ALL, ctx
import dash_bootstrap_components as dbc

from . import database as db
from .models import FridgeItem
from .gemini_service import process_receipt_to_fridge_items

# Initialize the Dash app
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="🧊 Fridge Health Dashboard"
)

# Make server accessible for running
server = app.server


def get_status_class(freshness_pct: float) -> str:
    """Get CSS class based on freshness percentage."""
    if freshness_pct >= 60:
        return "fresh"
    elif freshness_pct >= 30:
        return "warning"
    else:
        return "danger"


def create_item_card(item: FridgeItem) -> html.Div:
    """Create a card component for a fridge item."""
    status_class = get_status_class(item.freshness_percentage)
    
    return html.Div(
        className=f"item-card {status_class}",
        children=[
            # Delete button
            html.Button(
                "×",
                className="delete-btn",
                id={"type": "delete-btn", "index": item.id},
                n_clicks=0
            ),
            # Item name with emoji
            html.Div(
                className="item-name",
                children=[
                    html.Span(item.status_emoji),
                    html.Span(item.name)
                ]
            ),
            # Category
            html.Div(
                className="item-category",
                children=item.category or "Other"
            ),
            # Dates
            html.Div(
                className="item-dates",
                children=[
                    html.Div([
                        html.Span("Bought: ", className="label"),
                        html.Span(item.purchase_date.strftime("%b %d, %Y"))
                    ]),
                    html.Div([
                        html.Span("Shelf life: ", className="label"),
                        html.Span(f"~{item.shelf_life_days} days")
                    ]),
                    html.Div([
                        html.Span("Days left: ", className="label"),
                        html.Span(f"{item.days_remaining} days")
                    ])
                ]
            ),
            # Freshness bar
            html.Div(
                className="freshness-bar",
                children=[
                    html.Div(
                        className=f"fill {status_class}",
                        style={"width": f"{item.freshness_percentage}%"}
                    )
                ]
            ),
            # Freshness text
            html.Div(
                className=f"freshness-text {status_class}",
                children=[
                    html.Span(item.status_text),
                    html.Span(f"{item.freshness_percentage:.0f}%")
                ]
            )
        ]
    )


def create_stats_cards(items: List[FridgeItem]) -> html.Div:
    """Create statistics cards showing item counts by status."""
    total = len(items)
    fresh = len([i for i in items if i.freshness_percentage >= 60])
    warning = len([i for i in items if 30 <= i.freshness_percentage < 60])
    danger = len([i for i in items if i.freshness_percentage < 30])
    
    return html.Div(
        className="stats-container",
        children=[
            html.Div(
                className="stat-card total",
                children=[
                    html.Div(str(total), className="stat-number"),
                    html.Div("Total Items", className="stat-label")
                ]
            ),
            html.Div(
                className="stat-card fresh",
                children=[
                    html.Div(str(fresh), className="stat-number"),
                    html.Div("🟢 Fresh", className="stat-label")
                ]
            ),
            html.Div(
                className="stat-card warning",
                children=[
                    html.Div(str(warning), className="stat-number"),
                    html.Div("🟡 Use Soon", className="stat-label")
                ]
            ),
            html.Div(
                className="stat-card danger",
                children=[
                    html.Div(str(danger), className="stat-number"),
                    html.Div("🔴 Expired", className="stat-label")
                ]
            )
        ]
    )


def create_empty_state() -> html.Div:
    """Create empty state when no items exist."""
    return html.Div(
        className="empty-state",
        children=[
            html.Div("🧊", className="emoji"),
            html.H3("Your fridge is empty!"),
            html.P(
                "Upload a grocery receipt to start tracking your food items. "
                "We'll analyze the receipt, identify refrigerated items, and "
                "help you track their freshness."
            )
        ]
    )


def create_items_grid(items: List[FridgeItem]) -> html.Div:
    """Create the grid of item cards."""
    if not items:
        return create_empty_state()
    
    # Sort items by freshness (most urgent first)
    sorted_items = sorted(items, key=lambda x: x.freshness_percentage)
    
    return html.Div(
        className="items-grid",
        children=[create_item_card(item) for item in sorted_items]
    )


# App Layout
app.layout = html.Div([
    # Header
    html.Div(
        className="dashboard-header",
        children=[
            html.H1("🧊 Fridge Health Dashboard"),
            html.P("Track the freshness of your refrigerated items")
        ]
    ),
    
    # Upload Section
    html.Div(
        className="upload-section",
        children=[
            html.H3("📷 Upload Receipt"),
            html.P(
                "Upload a photo of your grocery receipt to add items to your fridge.",
                style={"color": "#666", "marginBottom": "15px"}
            ),
            dcc.Upload(
                id="upload-receipt",
                children=html.Div([
                    "Drag and drop or ",
                    html.A("click to select", style={"color": "#667eea", "fontWeight": "600"}),
                    " a receipt image"
                ]),
                className="dash-upload",
                style={
                    "width": "100%",
                    "height": "100px",
                    "lineHeight": "60px",
                    "borderWidth": "2px",
                    "borderStyle": "dashed",
                    "borderRadius": "10px",
                    "textAlign": "center",
                    "cursor": "pointer"
                },
                multiple=False,
                accept="image/*"
            ),
            # Date picker for purchase date
            html.Div(
                style={"marginTop": "15px", "display": "flex", "alignItems": "center", "gap": "10px"},
                children=[
                    html.Label("Purchase Date:", style={"fontWeight": "500"}),
                    dcc.DatePickerSingle(
                        id="purchase-date-picker",
                        date=date.today(),
                        display_format="MMM D, YYYY",
                        style={"marginLeft": "10px"}
                    )
                ]
            ),
            # Processing status with loading spinner
            dcc.Loading(
                id="upload-loading",
                type="default",
                color="#667eea",
                children=[
                    html.Div(id="upload-status", style={"marginTop": "15px"})
                ],
                fullscreen=False,
                style={"marginTop": "20px"},
                custom_spinner=html.Div([
                    html.Div(className="upload-spinner"),
                    html.Div("🔍 Analyzing receipt with Gemini AI...", 
                             className="upload-spinner-text")
                ])
            )
        ]
    ),
    
    # Alert messages
    html.Div(id="alert-container"),
    
    # Stats Cards
    html.Div(id="stats-container"),
    
    # Items Grid
    html.Div(id="items-container"),
    
    # Hidden store for triggering refreshes
    dcc.Store(id="refresh-trigger", data=0),
    
    # Interval for auto-refresh (every 60 seconds)
    dcc.Interval(
        id="auto-refresh",
        interval=60 * 1000,  # 60 seconds
        n_intervals=0
    )
])


@callback(
    [Output("stats-container", "children"),
     Output("items-container", "children")],
    [Input("refresh-trigger", "data"),
     Input("auto-refresh", "n_intervals")]
)
def refresh_dashboard(trigger, intervals):
    """Refresh the dashboard with current items."""
    items = db.get_all_items()
    return create_stats_cards(items), create_items_grid(items)


def create_debug_panel(debug_info: Dict[str, Any]) -> html.Div:
    """Create a collapsible debug panel showing raw Gemini response."""
    if not debug_info:
        return html.Div()
    
    # Format the debug info as pretty JSON
    formatted_json = json.dumps(debug_info, indent=2, default=str)
    
    return html.Details(
        className="debug-panel",
        children=[
            html.Summary("🔧 Debug: Raw Gemini Response", className="debug-summary"),
            html.Div(
                className="debug-content",
                children=[
                    html.Pre(
                        formatted_json,
                        className="debug-json"
                    )
                ]
            )
        ]
    )


def create_parsing_results_table(fridge_items: List[FridgeItem]) -> html.Div:
    """Create a detailed results table showing parsed items."""
    if not fridge_items:
        return html.Div()
    
    # Create table rows
    rows = []
    for item in fridge_items:
        status_class = get_status_class(item.freshness_percentage)
        rows.append(
            html.Tr([
                html.Td(item.name, style={"fontWeight": "500"}),
                html.Td(item.category or "Other", style={"textTransform": "capitalize"}),
                html.Td(f"${item.cost:.2f}" if item.cost else "—"),
                html.Td(f"{item.shelf_life_days} days"),
                html.Td(
                    html.Span(
                        f"{item.freshness_percentage:.0f}%",
                        className=f"badge {status_class}"
                    )
                )
            ])
        )
    
    return html.Div(
        className="parsing-results",
        children=[
            html.H4("📋 Parsed Items", style={"marginBottom": "15px", "color": "#333"}),
            html.Table(
                className="results-table",
                children=[
                    html.Thead(
                        html.Tr([
                            html.Th("Item"),
                            html.Th("Category"),
                            html.Th("Cost"),
                            html.Th("Shelf Life"),
                            html.Th("Freshness")
                        ])
                    ),
                    html.Tbody(rows)
                ]
            )
        ]
    )


@callback(
    [Output("upload-status", "children"),
     Output("refresh-trigger", "data"),
     Output("alert-container", "children")],
    [Input("upload-receipt", "contents")],
    [State("upload-receipt", "filename"),
     State("purchase-date-picker", "date"),
     State("refresh-trigger", "data")],
    prevent_initial_call=True
)
def process_receipt(contents, filename, purchase_date_str, current_trigger):
    """Process uploaded receipt image."""
    if contents is None:
        return dash.no_update, dash.no_update, dash.no_update
    
    try:
        # Step 1: Decode the uploaded image
        content_type, content_string = contents.split(",")
        image_data = base64.b64decode(content_string)
        
        # Parse fallback purchase date from date picker
        if purchase_date_str:
            fallback_date = datetime.fromisoformat(purchase_date_str).date()
        else:
            fallback_date = date.today()
        
        # Process receipt with Gemini (this does the actual work)
        # Now returns tuple of (items, extracted_date, debug_info)
        fridge_items, extracted_date, debug_info = process_receipt_to_fridge_items(image_data, fallback_date)
        
        # Determine which date was used
        if extracted_date:
            date_source = f"📅 Date extracted from receipt: {extracted_date.strftime('%b %d, %Y')}"
            date_class = "date-extracted"
        else:
            date_source = f"📅 Using selected date: {fallback_date.strftime('%b %d, %Y')}"
            date_class = "date-fallback"
        
        if not fridge_items:
            # No items found - show info message
            status = html.Div(
                className="progress-container",
                children=[
                    html.Div(
                        className="progress-step completed",
                        children=[
                            html.Span("✓", className="step-icon"),
                            html.Span("Image uploaded", className="step-text")
                        ]
                    ),
                    html.Div(
                        className="progress-step completed",
                        children=[
                            html.Span("✓", className="step-icon"),
                            html.Span("Receipt analyzed", className="step-text")
                        ]
                    ),
                    html.Div(
                        className="progress-step warning",
                        children=[
                            html.Span("⚠", className="step-icon"),
                            html.Span("No refrigerated items found", className="step-text")
                        ]
                    )
                ]
            )
            alert = html.Div(
                className="alert alert-info",
                children=[
                    "ℹ️ No refrigerated items found in the receipt. ",
                    "Make sure the image is clear and contains grocery items like dairy, meat, or produce."
                ]
            )
            return status, current_trigger, alert
        
        # Add items to database
        db.add_items(fridge_items)
        
        # Create completed progress display with results
        status = html.Div([
            html.Div(
                className="progress-container",
                children=[
                    html.Div(
                        className="progress-step completed",
                        children=[
                            html.Span("✓", className="step-icon"),
                            html.Span("Image uploaded", className="step-text")
                        ]
                    ),
                    html.Div(
                        className="progress-step completed",
                        children=[
                            html.Span("✓", className="step-icon"),
                            html.Span(f"Found {len(fridge_items)} refrigerated items", className="step-text")
                        ]
                    ),
                    html.Div(
                        className="progress-step completed",
                        children=[
                            html.Span("✓", className="step-icon"),
                            html.Span("Shelf life estimates retrieved", className="step-text")
                        ]
                    ),
                    html.Div(
                        className="progress-step completed",
                        children=[
                            html.Span("✓", className="step-icon"),
                            html.Span("Items saved to database", className="step-text")
                        ]
                    )
                ]
            ),
            # Show extracted date info
            html.Div(
                className=f"date-info {date_class}",
                children=[date_source]
            ),
            # Show detailed results table
            create_parsing_results_table(fridge_items),
            # Debug panel (collapsible)
            create_debug_panel(debug_info)
        ])
        
        # Success alert with date info
        total_cost = sum(item.cost or 0 for item in fridge_items)
        cost_text = f" (Total: ${total_cost:.2f})" if total_cost > 0 else ""
        date_info = f" • Date: {fridge_items[0].purchase_date.strftime('%b %d, %Y')}" if fridge_items else ""
        
        alert = html.Div(
            className="alert alert-success",
            children=[
                f"✅ Successfully added {len(fridge_items)} items to your fridge{cost_text}{date_info}"
            ]
        )
        
        return status, current_trigger + 1, alert
        
    except Exception as e:
        # Error state
        status = html.Div(
            className="progress-container",
            children=[
                html.Div(
                    className="progress-step completed",
                    children=[
                        html.Span("✓", className="step-icon"),
                        html.Span("Image uploaded", className="step-text")
                    ]
                ),
                html.Div(
                    className="progress-step error",
                    children=[
                        html.Span("✗", className="step-icon"),
                        html.Span("Processing failed", className="step-text")
                    ]
                )
            ]
        )
        alert = html.Div(
            className="alert alert-error",
            children=[f"❌ Error processing receipt: {str(e)}"]
        )
        return status, current_trigger, alert


@callback(
    Output("refresh-trigger", "data", allow_duplicate=True),
    Input({"type": "delete-btn", "index": ALL}, "n_clicks"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True
)
def delete_item(n_clicks, current_trigger):
    """Delete an item when its delete button is clicked."""
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update
    
    # Get the item ID from the triggered button
    item_id = ctx.triggered_id["index"]
    
    # Delete from database
    db.delete_item(item_id)
    
    return current_trigger + 1


def run_server(debug: bool = False, port: int = 8050, host: str = "0.0.0.0"):
    """Run the Dash server."""
    app.run(debug=debug, port=port, host=host)


if __name__ == "__main__":
    run_server(debug=True)
