"""Main Dash application for the Fridge Health Dashboard."""

import base64
import json
import os
from datetime import date, datetime
from typing import List, Dict, Any

import dash
from dash import dcc, html, Input, Output, State, callback, ALL, ctx
import dash_bootstrap_components as dbc

from . import database as db
from .models import FridgeItem, PurchaseHistoryItem, ShoppingListItem, STORAGE_LOCATIONS, STORAGE_DISPLAY_NAMES
from .gemini_service import process_receipt_to_fridge_items

# Check if debug mode is enabled via environment variable
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() in ("true", "1", "yes")

# Initialize the Dash app
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="🍎 Food Freshness Tracker",
    update_title=None,  # Prevents "Updating..." flicker in the browser tab title
    # Increase server-side callback timeout to 120 seconds (default is 30s)
    # This prevents "server did not respond" errors during long Gemini API calls
    server_timeout=120,
)

# Make server accessible for running
server = app.server


def get_status_class(freshness_pct: float, days_remaining: int = None) -> str:
    """Get CSS class based on freshness percentage and days remaining.
    
    An item is only 'danger' (expired) when days_remaining <= 0.
    Items with days remaining but low freshness % are 'warning' (use soon).
    """
    # If days_remaining is provided, use it as the primary expired check
    if days_remaining is not None and days_remaining <= 0:
        return "danger"
    if freshness_pct >= 40:
        return "fresh"
    else:
        return "warning"


def create_item_card(item: FridgeItem) -> html.Div:
    """Create a card component for a food item with editable name and shelf life."""
    status_class = "no-expiry" if item.ignore_expiry else get_status_class(item.freshness_percentage, item.days_remaining)
    
    # Build shelf life section - show differently for items with ignored expiry
    if item.ignore_expiry:
        shelf_life_section = html.Div(
            className="shelf-life-row no-expiry-indicator",
            children=[
                html.Span("♾️ No expiry tracking", className="no-expiry-text")
            ]
        )
        days_left_section = html.Div([
            html.Span("Days left: ", className="label"),
            html.Span("∞", className="infinity-days")
        ])
    else:
        shelf_life_section = html.Div(
            className="shelf-life-row",
            children=[
                html.Span("Shelf life: ", className="label"),
                html.Div(
                    className="shelf-life-control",
                    children=[
                        html.Button(
                            "−",
                            className="shelf-btn shelf-btn-down",
                            id={"type": "shelf-down-btn", "index": item.id},
                            n_clicks=0
                        ),
                        html.Span(
                            str(item.shelf_life_days),
                            className="shelf-life-value",
                            id={"type": "shelf-life-display", "index": item.id}
                        ),
                        html.Button(
                            "+",
                            className="shelf-btn shelf-btn-up",
                            id={"type": "shelf-up-btn", "index": item.id},
                            n_clicks=0
                        ),
                    ]
                ),
                html.Span(" days", className="days-label")
            ]
        )
        days_left_section = html.Div([
            html.Span("Days left: ", className="label"),
            html.Span(f"{item.days_remaining} days")
        ])
    
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
            # Item name with emoji - editable
            html.Div(
                className="item-name-container",
                children=[
                    html.Span(item.status_emoji, className="item-emoji"),
                    dcc.Input(
                        id={"type": "item-name-input", "index": item.id},
                        type="text",
                        value=item.name,
                        className="item-name-input",
                        debounce=True,
                        placeholder="Item name"
                    )
                ]
            ),
            # Storage location badge
            html.Div(
                className="item-storage-badge",
                children=item.storage_display
            ),
            # Category
            html.Div(
                className="item-category",
                children=item.category or "Other"
            ),
            # Dates with editable shelf life
            html.Div(
                className="item-dates",
                children=[
                    html.Div([
                        html.Span("Bought: ", className="label"),
                        html.Span(item.purchase_date.strftime("%b %d, %Y"))
                    ]),
                    shelf_life_section,
                    days_left_section
                ]
            ),
            # Remaining amount slider
            html.Div(
                className="remaining-section",
                children=[
                    html.Div(
                        className="remaining-header",
                        children=[
                            html.Span("Remaining: ", className="label"),
                            html.Span(
                                f"{item.remaining_percentage}%",
                                className="remaining-value",
                                id={"type": "remaining-display", "index": item.id}
                            )
                        ]
                    ),
                    dcc.Slider(
                        id={"type": "remaining-slider", "index": item.id},
                        min=0,
                        max=100,
                        step=10,
                        value=item.remaining_percentage,
                        marks={0: '0%', 50: '50%', 100: '100%'},
                        className="remaining-slider",
                        updatemode='mouseup'
                    )
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
            # Freshness text (status only, no percentage)
            html.Div(
                className=f"freshness-text {status_class}",
                children=[
                    html.Span(item.status_text)
                ]
            )
        ]
    )


def create_stats_cards(items: List[FridgeItem]) -> html.Div:
    """Create statistics cards showing item counts by status."""
    total = len(items)
    # Items with ignore_expiry are counted as "fresh" and not in warning/danger
    no_expiry = len([i for i in items if i.ignore_expiry])
    tracked_items = [i for i in items if not i.ignore_expiry]
    danger = len([i for i in tracked_items if i.days_remaining <= 0])
    warning = len([i for i in tracked_items if i.days_remaining > 0 and i.freshness_percentage < 40])
    fresh = len([i for i in tracked_items if i.days_remaining > 0 and i.freshness_percentage >= 40]) + no_expiry
    
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
                    html.Div(f"🟢 Fresh{f' (♾️{no_expiry})' if no_expiry else ''}", className="stat-label")
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
            html.Div("🍎", className="emoji"),
            html.H3("No food items yet!"),
            html.P(
                "Upload a grocery receipt to start tracking your food items. "
                "We'll analyze the receipt, identify all food items, determine "
                "where they should be stored, and help you track their freshness."
            )
        ]
    )


def create_compact_food_badge(item: FridgeItem) -> html.Div:
    """Create a compact badge for a food item that opens edit modal on click."""
    status_class = "no-expiry" if item.ignore_expiry else get_status_class(item.freshness_percentage, item.days_remaining)
    days_text = "♾️" if item.ignore_expiry else (f"{item.days_remaining}d" if item.days_remaining > 0 else "Exp")
    
    return html.Div(
        className=f"food-badge {status_class}",
        children=[
            # Clickable area for opening edit modal
            html.Div(
                className="food-badge-clickable",
                id={"type": "food-badge-click", "index": item.id},
                n_clicks=0,
                children=[
                    html.Span(item.status_emoji, className="food-badge-emoji"),
                    html.Span(item.name, className="food-badge-name"),
                    html.Span(days_text, className=f"food-badge-days {status_class}"),
                ]
            ),
            html.Button(
                "×",
                className="food-badge-delete",
                id={"type": "delete-btn", "index": item.id},
                n_clicks=0
            )
        ]
    )


def create_items_grid(items: List[FridgeItem]) -> html.Div:
    """Create a compact view of items organized by storage location."""
    if not items:
        return create_empty_state()
    
    # Group items by storage location
    storage_groups = {
        "fridge": [],
        "freezer": [],
        "pantry": [],
        "counter": []
    }
    
    for item in items:
        location = item.storage_location or "fridge"
        if location in storage_groups:
            storage_groups[location].append(item)
        else:
            storage_groups["fridge"].append(item)  # Default fallback
    
    # Sort each group by freshness (most urgent first)
    for location in storage_groups:
        storage_groups[location].sort(key=lambda x: x.freshness_percentage)
    
    # Create storage sections
    sections = []
    
    storage_config = [
        ("fridge", "🧊 Fridge", "fridge-section"),
        ("freezer", "❄️ Freezer", "freezer-section"),
        ("pantry", "🗄️ Pantry", "pantry-section"),
        ("counter", "🍎 Counter", "counter-section"),
    ]
    
    for location, title, section_class in storage_config:
        items_in_location = storage_groups[location]
        if items_in_location:
            sections.append(
                html.Div(
                    className=f"storage-section {section_class}",
                    children=[
                        html.Div(
                            className="storage-section-header",
                            children=[
                                html.Span(title, className="storage-section-title"),
                                html.Span(f"({len(items_in_location)})", className="storage-section-count")
                            ]
                        ),
                        html.Div(
                            className="food-badges-container",
                            children=[create_compact_food_badge(item) for item in items_in_location]
                        )
                    ]
                )
            )
    
    return html.Div(
        className="compact-food-grid",
        children=sections
    )


# ============================================================================
# Shopping List Helper Functions
# ============================================================================

def create_suggestion_card(item: PurchaseHistoryItem) -> html.Div:
    """Create a card for a suggested item."""
    return html.Div(
        className="suggestion-card",
        children=[
            html.Div(
                className="suggestion-info",
                children=[
                    html.Div(
                        className="suggestion-name",
                        children=[
                            html.Span(item.display_name),
                            html.Span(f"({item.purchase_count}x)", className="purchase-count")
                        ]
                    ),
                    html.Div(
                        className="suggestion-meta",
                        children=[
                            html.Span(item.storage_display, className="storage-badge-small"),
                            html.Span(item.category or "Other", className="category-badge-small")
                        ]
                    )
                ]
            ),
            html.Div(
                className="suggestion-actions",
                children=[
                    html.Button(
                        "+",
                        className="add-suggestion-btn",
                        id={"type": "add-suggestion-btn", "name": item.display_name, 
                            "category": item.category or "", "storage": item.storage_location},
                        n_clicks=0,
                        title="Add to shopping list"
                    ),
                    html.Button(
                        "×",
                        className="suppress-suggestion-btn",
                        id={"type": "suppress-suggestion-btn", "name": item.normalized_name},
                        n_clicks=0,
                        title="Don't suggest this item"
                    )
                ]
            )
        ]
    )


# App Layout
def create_shopping_list_item(item: ShoppingListItem) -> html.Div:
    """Create a row for a shopping list item."""
    checked_class = "checked" if item.is_checked else ""
    source_badge = "💡" if item.source == "suggested" else ""
    
    return html.Div(
        className=f"shopping-list-item {checked_class}",
        children=[
            html.Div(
                className="shopping-item-check",
                children=[
                    html.Button(
                        "✓" if item.is_checked else "",
                        className=f"check-btn {checked_class}",
                        id={"type": "toggle-shopping-item", "index": item.id},
                        n_clicks=0
                    )
                ]
            ),
            html.Div(
                className="shopping-item-info",
                children=[
                    html.Span(item.name, className=f"shopping-item-name {checked_class}"),
                    html.Span(source_badge, className="source-badge"),
                    html.Div(
                        className="shopping-item-meta",
                        children=[
                            html.Span(item.storage_display, className="storage-badge-small"),
                        ]
                    )
                ]
            ),
            html.Button(
                "×",
                className="remove-shopping-item-btn",
                id={"type": "remove-shopping-item", "index": item.id},
                n_clicks=0,
                title="Remove from list"
            )
        ]
    )


def create_suggestions_panel(suggestions: List[PurchaseHistoryItem]) -> html.Div:
    """Create the suggestions panel."""
    if not suggestions:
        return html.Div(
            className="suggestions-empty",
            children=[
                html.Div("💡", className="empty-icon"),
                html.P("No suggestions yet!"),
                html.P(
                    "As you add items through receipt scanning, we'll learn your shopping habits "
                    "and suggest items you frequently buy.",
                    className="empty-hint"
                )
            ]
        )
    
    return html.Div(
        className="suggestions-list",
        children=[create_suggestion_card(item) for item in suggestions]
    )


def create_shopping_list_panel(items: List[ShoppingListItem]) -> html.Div:
    """Create the shopping list panel."""
    if not items:
        return html.Div(
            className="shopping-list-empty",
            children=[
                html.Div("🛒", className="empty-icon"),
                html.P("Your shopping list is empty!"),
                html.P("Add items from the suggestions or use the form below.", className="empty-hint")
            ]
        )
    
    unchecked = [i for i in items if not i.is_checked]
    checked = [i for i in items if i.is_checked]
    
    content = []
    if unchecked:
        content.extend([create_shopping_list_item(item) for item in unchecked])
    if checked:
        if unchecked:
            content.append(html.Div(className="shopping-list-divider"))
        content.append(html.Div("Completed", className="completed-header"))
        content.extend([create_shopping_list_item(item) for item in checked])
    
    return html.Div(className="shopping-list-items", children=content)


def create_suppressed_panel(suppressed: List[str]) -> html.Div:
    """Create the suppressed suggestions panel."""
    if not suppressed:
        return html.Div()
    
    return html.Details(
        className="suppressed-panel",
        children=[
            html.Summary(f"Hidden suggestions ({len(suppressed)})"),
            html.Div(
                className="suppressed-list",
                children=[
                    html.Div(
                        className="suppressed-item",
                        children=[
                            html.Span(name.title(), className="suppressed-name"),
                            html.Button(
                                "Restore",
                                className="restore-btn",
                                id={"type": "unsuppress-btn", "name": name},
                                n_clicks=0
                            )
                        ]
                    ) for name in suppressed
                ]
            )
        ]
    )


# Main App Layout
app.layout = html.Div([
    # Header
    html.Div(
        className="dashboard-header",
        children=[
            html.H1("🍎 Food Freshness Tracker"),
            html.P("Track the freshness of all your groceries - fridge, freezer, pantry & counter")
        ]
    ),
    
    # Tabs
    dcc.Tabs(
        id="main-tabs",
        value="food-tab",
        className="main-tabs",
        children=[
            dcc.Tab(label="🍎 My Food", value="food-tab", className="main-tab"),
        ]
    ),
    
    # Tab Content Container
    html.Div(id="tab-content"),
    
    # Hidden stores for triggering refreshes
    dcc.Store(id="refresh-trigger", data=0),
    dcc.Store(id="shopping-refresh-trigger", data=0),
    dcc.Store(id="edit-item-id", data=None),  # Store for tracking which item is being edited
    dcc.Store(id="pending-scanned-items", data=None),  # Store for pending items before confirmation
    
    # Edit Item Modal
    html.Div(
        id="edit-modal-overlay",
        className="edit-modal-overlay",
        style={"display": "none"},
        children=[
            html.Div(
                className="edit-modal",
                children=[
                    html.Div(
                        className="edit-modal-header",
                        children=[
                            html.H3("✏️ Edit Item", className="edit-modal-title"),
                            html.Button("×", id="edit-modal-close", className="edit-modal-close-btn", n_clicks=0)
                        ]
                    ),
                    html.Div(id="edit-modal-body", className="edit-modal-body"),
                    html.Div(
                        className="edit-modal-footer",
                        children=[
                            html.Button("Cancel", id="edit-modal-cancel", className="edit-modal-btn edit-modal-btn-cancel", n_clicks=0),
                            html.Button("Save Changes", id="edit-modal-save", className="edit-modal-btn edit-modal-btn-save", n_clicks=0)
                        ]
                    )
                ]
            )
        ]
    ),
    
    # Interval for auto-refresh (every 60 seconds)
    dcc.Interval(
        id="auto-refresh",
        interval=60 * 1000,  # 60 seconds
        n_intervals=0
    )
])


def create_food_tab_content():
    """Create the content for the My Food tab."""
    return html.Div([
        # Upload Section
        html.Div(
            className="upload-section",
            children=[
                html.H3("📷 Upload Receipt"),
                html.P(
                    "Upload a photo of your grocery receipt to add food items.",
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
                        "width": "100%", "height": "100px", "lineHeight": "60px",
                        "borderWidth": "2px", "borderStyle": "dashed", "borderRadius": "10px",
                        "textAlign": "center", "cursor": "pointer"
                    },
                    multiple=False,
                    accept="image/*"
                ),
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
                dcc.Loading(
                    id="upload-loading",
                    type="default",
                    color="#667eea",
                    children=[html.Div(id="upload-status", style={"marginTop": "15px"})],
                    fullscreen=False,
                    style={"marginTop": "20px"},
                    custom_spinner=html.Div([
                        html.Div(className="upload-spinner"),
                        html.Div("🔍 Analyzing receipt with Gemini AI...", className="upload-spinner-text")
                    ])
                )
            ]
        ),
        html.Div(id="alert-container"),
        html.Div(id="stats-container"),
        html.Div(id="items-container"),
    ])


@callback(
    Output("tab-content", "children"),
    Input("main-tabs", "value")
)
def render_tab_content(tab):
    """Render the content for the selected tab."""
    if tab == "food-tab":
        return create_food_tab_content()
    return html.Div()


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
    """Create a collapsible debug panel showing raw Gemini response.
    
    Only shown when DEBUG_MODE environment variable is set to true.
    """
    # Only show debug panel if DEBUG_MODE is enabled
    if not DEBUG_MODE:
        return html.Div()
    
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


def create_parsing_results_table(fridge_items: List[FridgeItem], scanned_date: date, is_date_extracted: bool) -> html.Div:
    """Create a detailed results table showing parsed items with editable date.
    
    Args:
        fridge_items: List of parsed FridgeItem objects
        scanned_date: The date extracted or used for the scan
        is_date_extracted: True if date was extracted from receipt, False if fallback was used
    """
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
    
    # Date source indicator
    if is_date_extracted:
        date_source_text = "📅 Date extracted from receipt"
        date_source_class = "date-extracted"
    else:
        date_source_text = "📅 Using fallback date"
        date_source_class = "date-fallback"
    
    return html.Div(
        className="parsing-results",
        children=[
            html.H4("📋 Scanned Items", style={"marginBottom": "15px", "color": "#333"}),
            
            # Editable date section
            html.Div(
                className="scanned-date-section",
                children=[
                    html.Div(
                        className=f"date-source-indicator {date_source_class}",
                        children=[date_source_text]
                    ),
                    html.Div(
                        className="scanned-date-editor",
                        children=[
                            html.Label("Purchase Date:", className="scanned-date-label"),
                            dcc.DatePickerSingle(
                                id="scanned-date-picker",
                                date=scanned_date,
                                display_format="MMM D, YYYY",
                                className="scanned-date-input"
                            ),
                            html.Span(
                                "You can update the date before saving",
                                className="scanned-date-hint"
                            )
                        ]
                    )
                ]
            ),
            
            # Items table
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
            ),
            
            # Confirm button
            html.Div(
                className="scanned-items-actions",
                children=[
                    html.Button(
                        "✓ Confirm & Save Items",
                        id="confirm-scanned-items-btn",
                        className="confirm-scanned-btn",
                        n_clicks=0
                    ),
                    html.Button(
                        "✗ Discard",
                        id="discard-scanned-items-btn",
                        className="discard-scanned-btn",
                        n_clicks=0
                    )
                ]
            )
        ]
    )


@callback(
    [Output("upload-status", "children"),
     Output("pending-scanned-items", "data"),
     Output("alert-container", "children")],
    [Input("upload-receipt", "contents")],
    [State("upload-receipt", "filename"),
     State("purchase-date-picker", "date")],
    prevent_initial_call=True
)
def process_receipt(contents, filename, purchase_date_str):
    """Process uploaded receipt image and store items for confirmation."""
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
            # Check if there's a classified API error to surface to the user
            api_error_msg = debug_info.get("user_message")
            error_type = debug_info.get("error_type")

            # Choose step icon/class and alert class based on error type
            if error_type == "quota":
                step_class = "progress-step error"
                step_icon = "✗"
                step_text = "API quota exceeded"
                alert_class = "alert alert-error"
                alert_msg = api_error_msg
            elif error_type == "auth":
                step_class = "progress-step error"
                step_icon = "✗"
                step_text = "API authentication failed"
                alert_class = "alert alert-error"
                alert_msg = api_error_msg
            elif error_type == "network":
                step_class = "progress-step error"
                step_icon = "✗"
                step_text = "API unavailable"
                alert_class = "alert alert-error"
                alert_msg = api_error_msg
            elif error_type == "parse":
                step_class = "progress-step warning"
                step_icon = "⚠"
                step_text = "Could not parse AI response"
                alert_class = "alert alert-error"
                alert_msg = api_error_msg
            elif api_error_msg:
                step_class = "progress-step error"
                step_icon = "✗"
                step_text = "Processing failed"
                alert_class = "alert alert-error"
                alert_msg = api_error_msg
            else:
                step_class = "progress-step warning"
                step_icon = "⚠"
                step_text = "No food items found"
                alert_class = "alert alert-info"
                alert_msg = ("ℹ️ No food items found in the receipt. "
                             "Make sure the image is clear and contains grocery items.")

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
                                html.Span("Receipt analyzed", className="step-text")
                            ]
                        ),
                        html.Div(
                            className=step_class,
                            children=[
                                html.Span(step_icon, className="step-icon"),
                                html.Span(step_text, className="step-text")
                            ]
                        )
                    ]
                ),
                # Debug panel (collapsible) - show even when no items found
                create_debug_panel(debug_info)
            ])
            alert = html.Div(
                className=alert_class,
                children=[alert_msg]
            )
            return status, None, alert
        
        # Determine which date was used for scanned items
        is_date_extracted = extracted_date is not None
        scanned_date = extracted_date if extracted_date else fallback_date
        
        # DON'T save items yet - store them as pending for user to review and confirm
        # Convert items to serializable format for storage
        pending_items_data = {
            "items": [item.to_dict() for item in fridge_items],
            "scanned_date": scanned_date.isoformat(),
            "is_date_extracted": is_date_extracted,
            "debug_info": debug_info
        }
        
        # Create progress display with results (items not saved yet)
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
                            html.Span(f"Found {len(fridge_items)} food items", className="step-text")
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
                        className="progress-step pending",
                        children=[
                            html.Span("⏳", className="step-icon"),
                            html.Span("Awaiting confirmation", className="step-text")
                        ]
                    )
                ]
            ),
            # Show detailed results table with editable date and confirm/discard buttons
            create_parsing_results_table(fridge_items, scanned_date, is_date_extracted),
            # Debug panel (collapsible)
            create_debug_panel(debug_info)
        ])
        
        # Info alert prompting user to confirm
        alert = html.Div(
            className="alert alert-info",
            children=[
                f"📋 Found {len(fridge_items)} items. Review the date and click 'Confirm & Save' to add them to your food tracker."
            ]
        )
        
        return status, pending_items_data, alert
        
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
        return status, None, alert


@callback(
    [Output("upload-status", "children", allow_duplicate=True),
     Output("pending-scanned-items", "data", allow_duplicate=True),
     Output("refresh-trigger", "data"),
     Output("alert-container", "children", allow_duplicate=True)],
    [Input("confirm-scanned-items-btn", "n_clicks")],
    [State("pending-scanned-items", "data"),
     State("scanned-date-picker", "date"),
     State("refresh-trigger", "data")],
    prevent_initial_call=True
)
def confirm_scanned_items(n_clicks, pending_data, updated_date_str, current_trigger):
    """Confirm and save the scanned items with the (possibly updated) date."""
    if not n_clicks or not pending_data:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
    try:
        # Parse the updated date
        if updated_date_str:
            updated_date = datetime.fromisoformat(updated_date_str).date()
        else:
            updated_date = datetime.fromisoformat(pending_data["scanned_date"]).date()
        
        # Reconstruct FridgeItem objects with the updated date
        fridge_items = []
        for item_data in pending_data["items"]:
            item = FridgeItem.from_dict(item_data)
            # Update the purchase date to the user-selected date
            item.purchase_date = updated_date
            fridge_items.append(item)
        
        # Now save items to database
        db.add_items(fridge_items)
        
        # Create success status
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
                            html.Span(f"Found {len(fridge_items)} food items", className="step-text")
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
            # Show confirmed message
            html.Div(
                className="date-info date-extracted",
                children=[f"📅 Items saved with date: {updated_date.strftime('%b %d, %Y')}"]
            )
        ])
        
        # Success alert
        total_cost = sum(item.cost or 0 for item in fridge_items)
        cost_text = f" (Total: ${total_cost:.2f})" if total_cost > 0 else ""
        
        alert = html.Div(
            className="alert alert-success",
            children=[
                f"✅ Successfully added {len(fridge_items)} items to your food tracker{cost_text}"
            ]
        )
        
        # Clear pending items and trigger refresh
        return status, None, current_trigger + 1, alert
        
    except Exception as e:
        alert = html.Div(
            className="alert alert-error",
            children=[f"❌ Error saving items: {str(e)}"]
        )
        return dash.no_update, dash.no_update, dash.no_update, alert


@callback(
    [Output("upload-status", "children", allow_duplicate=True),
     Output("pending-scanned-items", "data", allow_duplicate=True),
     Output("alert-container", "children", allow_duplicate=True)],
    [Input("discard-scanned-items-btn", "n_clicks")],
    [State("pending-scanned-items", "data")],
    prevent_initial_call=True
)
def discard_scanned_items(n_clicks, pending_data):
    """Discard the scanned items without saving."""
    if not n_clicks or not pending_data:
        return dash.no_update, dash.no_update, dash.no_update
    
    # Clear the status and pending items
    status = html.Div()
    
    alert = html.Div(
        className="alert alert-info",
        children=["ℹ️ Scanned items discarded. Upload another receipt to try again."]
    )
    
    return status, None, alert


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


# ============================================================================
# Edit Modal Callbacks
# ============================================================================

def create_edit_modal_body(item: FridgeItem) -> html.Div:
    """Create the body content for the edit modal."""
    # Build per-location shelf life hints
    loc_labels = {"fridge": "🧊 Fridge", "freezer": "❄️ Freezer", "pantry": "🗄️ Pantry", "counter": "🍎 Counter"}
    loc_fields = {
        "fridge":  item.shelf_life_fridge,
        "freezer": item.shelf_life_freezer,
        "pantry":  item.shelf_life_pantry,
        "counter": item.shelf_life_counter,
    }
    has_per_loc = any(v is not None for v in loc_fields.values())
    per_loc_hints = []
    if has_per_loc:
        for loc, label in loc_labels.items():
            val = loc_fields[loc]
            if val is not None:
                is_current = (loc == item.storage_location)
                per_loc_hints.append(
                    html.Span(
                        f"{label}: {val}d",
                        className="shelf-life-loc-hint" + (" shelf-life-loc-current" if is_current else ""),
                        title=f"Shelf life in {label}: {val} days"
                    )
                )

    # Hidden store for per-location shelf life values (passed as JSON)
    import json as _json
    per_loc_json = _json.dumps({
        "fridge":  item.shelf_life_fridge,
        "freezer": item.shelf_life_freezer,
        "pantry":  item.shelf_life_pantry,
        "counter": item.shelf_life_counter,
    })

    return html.Div([
        # Hidden store for per-location shelf life
        dcc.Store(id="edit-item-per-loc-shelf-life", data=per_loc_json),

        html.Div(className="edit-form-group", children=[
            html.Label("Name", className="edit-form-label"),
            dcc.Input(id="edit-item-name", type="text", value=item.name,
                      className="edit-form-input", placeholder="Item name")
        ]),
        html.Div(className="edit-form-group", children=[
            html.Label("Storage Location", className="edit-form-label"),
            dcc.Dropdown(id="edit-item-storage", options=[
                {"label": "🧊 Fridge", "value": "fridge"}, {"label": "❄️ Freezer", "value": "freezer"},
                {"label": "🗄️ Pantry", "value": "pantry"}, {"label": "🍎 Counter", "value": "counter"}
            ], value=item.storage_location, className="edit-storage-dropdown", clearable=False)
        ]),
        html.Div(className="edit-form-group", children=[
            html.Label("Shelf Life (days)", className="edit-form-label"),
            html.Div(className="edit-shelf-life-control", children=[
                html.Button("−", id="edit-shelf-down", className="edit-shelf-btn", n_clicks=0),
                dcc.Input(id="edit-item-shelf-life", type="number", value=item.shelf_life_days,
                          className="edit-shelf-input", min=1, max=3650, disabled=item.ignore_expiry),
                html.Button("+", id="edit-shelf-up", className="edit-shelf-btn", n_clicks=0)
            ]),
            # Per-location shelf life hints
            html.Div(
                className="shelf-life-loc-hints",
                children=per_loc_hints if per_loc_hints else [
                    html.Span("No per-location data yet", className="shelf-life-loc-hint-empty")
                ]
            )
        ]),
        html.Div(className="edit-form-group ignore-expiry-group", children=[
            dcc.Checklist(
                id="edit-item-ignore-expiry",
                options=[{"label": " Don't track expiry date", "value": "ignore"}],
                value=["ignore"] if item.ignore_expiry else [],
                className="ignore-expiry-checkbox"
            ),
            html.Div("♾️ This item won't show expiry warnings", 
                     className="ignore-expiry-hint",
                     style={"display": "block" if item.ignore_expiry else "none"},
                     id="ignore-expiry-hint")
        ]),
        html.Div(className="edit-form-group", children=[
            html.Label("Remaining", className="edit-form-label"),
            html.Div(f"{item.remaining_percentage}%", className="edit-remaining-display", id="edit-remaining-display"),
            dcc.Slider(id="edit-item-remaining", min=0, max=100, step=10, value=item.remaining_percentage,
                       marks={0: '0%', 50: '50%', 100: '100%'}, className="edit-remaining-slider")
        ]),
        html.Div(className="edit-item-info", children=[
            html.Div([html.Span(item.status_emoji, style={"marginRight": "8px"}),
                      html.Span(item.status_text, className=f"status-badge {get_status_class(item.freshness_percentage, item.days_remaining)}")]),
            html.Div(f"Purchased: {item.purchase_date.strftime('%b %d, %Y')}", className="edit-info-text"),
            html.Div(f"Days remaining: {'∞' if item.ignore_expiry else item.days_remaining}", className="edit-info-text"),
            html.Div(f"Category: {item.category or 'Other'}", className="edit-info-text")
        ])
    ])


@callback(
    [Output("edit-modal-overlay", "style"),
     Output("edit-modal-body", "children"),
     Output("edit-item-id", "data")],
    Input({"type": "food-badge-click", "index": ALL}, "n_clicks"),
    prevent_initial_call=True
)
def open_edit_modal(n_clicks):
    """Open the edit modal when a food badge is clicked."""
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update, dash.no_update, dash.no_update
    
    item_id = ctx.triggered_id["index"]
    item = db.get_item_by_id(item_id)
    
    if not item:
        return dash.no_update, dash.no_update, dash.no_update
    
    return {"display": "flex"}, create_edit_modal_body(item), item_id


@callback(
    Output("edit-modal-overlay", "style", allow_duplicate=True),
    [Input("edit-modal-close", "n_clicks"),
     Input("edit-modal-cancel", "n_clicks")],
    prevent_initial_call=True
)
def close_edit_modal(close_clicks, cancel_clicks):
    """Close the edit modal."""
    if not ctx.triggered_id:
        return dash.no_update
    return {"display": "none"}


@callback(
    Output("edit-remaining-display", "children"),
    Input("edit-item-remaining", "value"),
    prevent_initial_call=True
)
def update_remaining_display(value):
    """Update the remaining percentage display."""
    if value is None:
        return dash.no_update
    return f"{value}%"


@callback(
    Output("edit-item-shelf-life", "value"),
    [Input("edit-shelf-up", "n_clicks"),
     Input("edit-shelf-down", "n_clicks"),
     Input("edit-item-storage", "value")],
    [State("edit-item-shelf-life", "value"),
     State("edit-item-per-loc-shelf-life", "data")],
    prevent_initial_call=True
)
def update_shelf_life_in_modal(up_clicks, down_clicks, storage_value, current_value, per_loc_data):
    """Update shelf life value when +/- buttons are clicked or storage location changes."""
    if not ctx.triggered_id:
        return dash.no_update

    triggered = ctx.triggered_id

    # When storage location changes, auto-fill shelf life from per-location data
    if triggered == "edit-item-storage" and storage_value and per_loc_data:
        try:
            per_loc = json.loads(per_loc_data) if isinstance(per_loc_data, str) else per_loc_data
            new_val = per_loc.get(storage_value)
            if new_val is not None:
                return int(new_val)
        except Exception:
            pass
        return dash.no_update

    if current_value is None:
        return dash.no_update

    if triggered == "edit-shelf-up":
        return min(3650, current_value + 1)
    elif triggered == "edit-shelf-down":
        return max(1, current_value - 1)
    return dash.no_update


@callback(
    [Output("edit-modal-overlay", "style", allow_duplicate=True),
     Output("refresh-trigger", "data", allow_duplicate=True)],
    Input("edit-modal-save", "n_clicks"),
    [State("edit-item-id", "data"),
     State("edit-item-name", "value"),
     State("edit-item-shelf-life", "value"),
     State("edit-item-remaining", "value"),
     State("edit-item-storage", "value"),
     State("edit-item-ignore-expiry", "value"),
     State("edit-item-per-loc-shelf-life", "data"),
     State("refresh-trigger", "data")],
    prevent_initial_call=True
)
def save_edit_modal(n_clicks, item_id, name, shelf_life, remaining, storage, ignore_expiry, per_loc_data, current_trigger):
    """Save the edited item and close the modal."""
    if not n_clicks or not item_id:
        return dash.no_update, dash.no_update
    
    # Convert ignore_expiry checklist value to boolean
    ignore_expiry_bool = bool(ignore_expiry and "ignore" in ignore_expiry)

    # Build per-location shelf life update: update the current location's value
    # with whatever the user set in the shelf life input
    per_loc_kwargs = {}
    if storage and shelf_life is not None:
        loc_col_map = {
            "fridge":  "shelf_life_fridge",
            "freezer": "shelf_life_freezer",
            "pantry":  "shelf_life_pantry",
            "counter": "shelf_life_counter",
        }
        col = loc_col_map.get(storage)
        if col:
            per_loc_kwargs[col] = shelf_life

    # Update the item in the database
    db.update_item(
        item_id,
        name=name.strip() if name else None,
        shelf_life_days=shelf_life,
        remaining_percentage=remaining,
        storage_location=storage,
        ignore_expiry=ignore_expiry_bool,
        **per_loc_kwargs
    )
    
    return {"display": "none"}, current_trigger + 1


@callback(
    Output("refresh-trigger", "data", allow_duplicate=True),
    Input({"type": "item-name-input", "index": ALL}, "value"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True
)
def update_item_name(names, current_trigger):
    """Update item name when edited."""
    if not ctx.triggered_id:
        return dash.no_update
    
    # Get the item ID and new name
    item_id = ctx.triggered_id["index"]
    
    # Find the new name from the triggered input
    # The names list contains all input values, we need to find which one changed
    items = db.get_all_items()
    sorted_items = sorted(items, key=lambda x: x.freshness_percentage)
    
    # Find the index of the item in the sorted list
    for i, item in enumerate(sorted_items):
        if item.id == item_id:
            new_name = names[i]
            if new_name and new_name.strip() and new_name != item.name:
                db.update_item(item_id, name=new_name.strip())
                return current_trigger + 1
            break
    
    return dash.no_update


@callback(
    Output("refresh-trigger", "data", allow_duplicate=True),
    [Input({"type": "shelf-up-btn", "index": ALL}, "n_clicks"),
     Input({"type": "shelf-down-btn", "index": ALL}, "n_clicks")],
    State("refresh-trigger", "data"),
    prevent_initial_call=True
)
def update_shelf_life_buttons(up_clicks, down_clicks, current_trigger):
    """Update shelf life when up/down buttons are clicked."""
    if not ctx.triggered_id:
        return dash.no_update
    
    # Get the item ID and button type
    item_id = ctx.triggered_id["index"]
    button_type = ctx.triggered_id["type"]
    
    # Get the item from database
    item = db.get_item_by_id(item_id)
    if not item:
        return dash.no_update
    
    # Calculate new shelf life
    if button_type == "shelf-up-btn":
        new_shelf_life = min(item.shelf_life_days + 1, 365)
    else:  # shelf-down-btn
        new_shelf_life = max(item.shelf_life_days - 1, 1)
    
    # Update if changed
    if new_shelf_life != item.shelf_life_days:
        db.update_item(item_id, shelf_life_days=new_shelf_life)
        return current_trigger + 1
    
    return dash.no_update


@callback(
    Output("refresh-trigger", "data", allow_duplicate=True),
    Input({"type": "remaining-slider", "index": ALL}, "value"),
    State("refresh-trigger", "data"),
    prevent_initial_call=True
)
def update_remaining_slider(slider_values, current_trigger):
    """Update remaining percentage when slider is moved."""
    if not ctx.triggered_id:
        return dash.no_update
    
    # Get the item ID
    item_id = ctx.triggered_id["index"]
    
    # Get the item from database
    item = db.get_item_by_id(item_id)
    if not item:
        return dash.no_update
    
    # Find the new value from the triggered slider
    items = db.get_all_items()
    sorted_items = sorted(items, key=lambda x: x.freshness_percentage)
    
    for i, it in enumerate(sorted_items):
        if it.id == item_id:
            new_remaining = slider_values[i]
            if new_remaining is not None and new_remaining != item.remaining_percentage:
                db.update_item(item_id, remaining_percentage=int(new_remaining))
                return current_trigger + 1
            break
    
    return dash.no_update


# ============================================================================
# Shopping List Callbacks
# ============================================================================

@callback(
    [Output("suggestions-container", "children"),
     Output("shopping-list-container", "children"),
     Output("suppressed-container", "children")],
    [Input("shopping-refresh-trigger", "data"),
     Input("main-tabs", "value")],
    prevent_initial_call=True
)
def refresh_shopping_tab(trigger, tab):
    """Refresh the shopping tab content."""
    if tab != "shopping-tab":
        return dash.no_update, dash.no_update, dash.no_update
    
    suggestions = db.get_suggested_items(min_purchase_count=1, limit=20)
    shopping_list = db.get_shopping_list()
    suppressed = db.get_suppressed_suggestions()
    
    return (
        create_suggestions_panel(suggestions),
        create_shopping_list_panel(shopping_list),
        create_suppressed_panel(suppressed)
    )


@callback(
    Output("shopping-refresh-trigger", "data", allow_duplicate=True),
    Input({"type": "add-suggestion-btn", "name": ALL, "category": ALL, "storage": ALL}, "n_clicks"),
    State("shopping-refresh-trigger", "data"),
    prevent_initial_call=True
)
def add_suggestion_to_list(n_clicks, current_trigger):
    """Add a suggested item to the shopping list."""
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update
    
    name = ctx.triggered_id["name"]
    category = ctx.triggered_id["category"] or None
    storage = ctx.triggered_id["storage"]
    
    db.add_to_shopping_list(name, category, storage, source="suggested")
    return current_trigger + 1


@callback(
    Output("shopping-refresh-trigger", "data", allow_duplicate=True),
    Input({"type": "suppress-suggestion-btn", "name": ALL}, "n_clicks"),
    State("shopping-refresh-trigger", "data"),
    prevent_initial_call=True
)
def suppress_suggestion_callback(n_clicks, current_trigger):
    """Suppress a suggestion from appearing."""
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update
    
    name = ctx.triggered_id["name"]
    db.suppress_suggestion(name)
    return current_trigger + 1


@callback(
    Output("shopping-refresh-trigger", "data", allow_duplicate=True),
    Input({"type": "unsuppress-btn", "name": ALL}, "n_clicks"),
    State("shopping-refresh-trigger", "data"),
    prevent_initial_call=True
)
def unsuppress_suggestion_callback(n_clicks, current_trigger):
    """Restore a suppressed suggestion."""
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update
    
    name = ctx.triggered_id["name"]
    db.unsuppress_suggestion(name)
    return current_trigger + 1


@callback(
    Output("shopping-refresh-trigger", "data", allow_duplicate=True),
    Input({"type": "toggle-shopping-item", "index": ALL}, "n_clicks"),
    State("shopping-refresh-trigger", "data"),
    prevent_initial_call=True
)
def toggle_shopping_item(n_clicks, current_trigger):
    """Toggle a shopping list item's checked status."""
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update
    
    item_id = ctx.triggered_id["index"]
    db.toggle_shopping_list_item(item_id)
    return current_trigger + 1


@callback(
    Output("shopping-refresh-trigger", "data", allow_duplicate=True),
    Input({"type": "remove-shopping-item", "index": ALL}, "n_clicks"),
    State("shopping-refresh-trigger", "data"),
    prevent_initial_call=True
)
def remove_shopping_item(n_clicks, current_trigger):
    """Remove an item from the shopping list."""
    if not ctx.triggered_id or not any(n_clicks):
        return dash.no_update
    
    item_id = ctx.triggered_id["index"]
    db.remove_from_shopping_list(item_id)
    return current_trigger + 1


@callback(
    Output("shopping-refresh-trigger", "data", allow_duplicate=True),
    [Input("clear-checked-btn", "n_clicks"),
     Input("clear-all-btn", "n_clicks")],
    State("shopping-refresh-trigger", "data"),
    prevent_initial_call=True
)
def clear_shopping_list_callback(clear_checked, clear_all, current_trigger):
    """Clear the shopping list (checked only or all)."""
    if not ctx.triggered_id:
        return dash.no_update
    
    if ctx.triggered_id == "clear-checked-btn" and clear_checked:
        db.clear_shopping_list(checked_only=True)
    elif ctx.triggered_id == "clear-all-btn" and clear_all:
        db.clear_shopping_list(checked_only=False)
    else:
        return dash.no_update
    
    return current_trigger + 1


@callback(
    [Output("shopping-refresh-trigger", "data", allow_duplicate=True),
     Output("new-item-name", "value")],
    Input("add-manual-item-btn", "n_clicks"),
    [State("new-item-name", "value"),
     State("new-item-storage", "value"),
     State("shopping-refresh-trigger", "data")],
    prevent_initial_call=True
)
def add_manual_item(n_clicks, name, storage, current_trigger):
    """Add a manually entered item to the shopping list."""
    if not n_clicks or not name or not name.strip():
        return dash.no_update, dash.no_update
    
    db.add_to_shopping_list(name.strip(), None, storage, source="manual")
    return current_trigger + 1, ""


def run_server(debug: bool = False, port: int = 8050, host: str = "0.0.0.0"):
    """Run the Dash server."""
    app.run(debug=debug, port=port, host=host)


if __name__ == "__main__":
    run_server(debug=True)
