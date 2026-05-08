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
from .recipe_chat_service import RecipeChatEngine, get_vegetables_and_meat

# Check if debug mode is enabled via environment variable
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() in ("true", "1", "yes")

# Initialize the Dash app
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="🍎 Food Freshness Tracker"
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
    """Create a card component for a food item with editable name and shelf life."""
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
                    html.Div(
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
                    ),
                    html.Div([
                        html.Span("Days left: ", className="label"),
                        html.Span(f"{item.days_remaining} days")
                    ])
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
    """Create a compact badge for a food item."""
    status_class = get_status_class(item.freshness_percentage)
    days_text = f"{item.days_remaining}d" if item.days_remaining >= 0 else "Exp"
    
    return html.Div(
        className=f"food-badge {status_class}",
        id={"type": "food-badge", "index": item.id},
        children=[
            html.Span(item.status_emoji, className="food-badge-emoji"),
            html.Span(item.name, className="food-badge-name"),
            html.Span(days_text, className=f"food-badge-days {status_class}"),
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
            dcc.Tab(label="🛒 Shopping List", value="shopping-tab", className="main-tab"),
            dcc.Tab(label="🍳 Recipe Chat", value="recipe-chat-tab", className="main-tab"),
        ]
    ),
    
    # Tab Content Container
    html.Div(id="tab-content"),
    
    # Hidden stores for triggering refreshes
    dcc.Store(id="refresh-trigger", data=0),
    dcc.Store(id="shopping-refresh-trigger", data=0),
    dcc.Store(id="chat-history", data=[]),
    
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


def create_shopping_tab_content():
    """Create the content for the Shopping List tab."""
    return html.Div(
        className="shopping-tab-content",
        children=[
            html.Div(
                className="shopping-columns",
                children=[
                    html.Div(
                        className="shopping-column suggestions-column",
                        children=[
                            html.H3("💡 Suggested Items"),
                            html.P("Items you've bought before but aren't in your fridge", className="column-description"),
                            html.Div(id="suggestions-container")
                        ]
                    ),
                    html.Div(
                        className="shopping-column list-column",
                        children=[
                            html.H3("📝 Your List"),
                            html.Div(
                                className="list-actions",
                                children=[
                                    html.Button("Clear Checked", id="clear-checked-btn", className="action-btn secondary", n_clicks=0),
                                    html.Button("Clear All", id="clear-all-btn", className="action-btn danger", n_clicks=0)
                                ]
                            ),
                            html.Div(id="shopping-list-container"),
                            html.Div(
                                className="add-item-form",
                                children=[
                                    html.H4("Add Item Manually"),
                                    html.Div(
                                        className="form-row",
                                        children=[
                                            dcc.Input(id="new-item-name", type="text", placeholder="Item name", className="form-input"),
                                            dcc.Dropdown(
                                                id="new-item-storage",
                                                options=[{"label": STORAGE_DISPLAY_NAMES[loc], "value": loc} for loc in STORAGE_LOCATIONS],
                                                value="fridge",
                                                className="form-dropdown",
                                                clearable=False
                                            ),
                                            html.Button("Add", id="add-manual-item-btn", className="action-btn primary", n_clicks=0)
                                        ]
                                    )
                                ]
                            )
                        ]
                    )
                ]
            ),
            html.Div(id="suppressed-container"),
        ]
    )


def create_recipe_chat_content():
    """Create the content for the Recipe Chat tab."""
    return html.Div(
        className="recipe-chat-container",
        children=[
            # Expiring Items Sidebar
            html.Details(
                className="ingredients-sidebar",
                open=True,
                children=[
                    html.Summary("⚠️ Expiring Soon", className="ingredients-header"),
                    html.Div(id="ingredients-list", className="ingredients-list")
                ]
            ),
            # Chat Area
            html.Div(
                className="chat-area",
                children=[
                    html.Div(id="chat-messages", className="chat-messages"),
                    html.Div(
                        className="chat-input-area",
                        children=[
                            dcc.Checklist(
                                id="use-recipes-doc",
                                options=[{"label": " Include my Recipes Doc", "value": "yes"}],
                                value=[],
                                className="recipes-doc-checkbox"
                            ),
                            html.Div(
                                className="chat-input-row",
                                children=[
                                    dcc.Input(
                                        id="chat-input",
                                        type="text",
                                        placeholder="What would you like to cook?",
                                        className="chat-input",
                                        debounce=False,
                                        n_submit=0
                                    ),
                                    html.Button("➤", id="chat-send-btn", className="chat-send-btn", n_clicks=0)
                                ]
                            )
                        ]
                    )
                ]
            ),
            # Streaming components
            dcc.Interval(
                id="chat-stream-interval",
                interval=100,  # Poll every 100ms
                disabled=True,
                n_intervals=0
            ),
            dcc.Store(id="streaming-state", data={"active": False, "pending_message": None, "use_doc": False})
        ]
    )


# Initialize chat engine (module-level for persistence)
chat_engine = RecipeChatEngine()


def create_ingredient_item(item: FridgeItem) -> html.Div:
    """Create a single ingredient list item."""
    status_class = get_status_class(item.freshness_percentage)
    return html.Div(
        className=f"ingredient-item {status_class}",
        children=[
            html.Span(item.status_emoji, className="ingredient-emoji"),
            html.Span(item.name, className="ingredient-name"),
            html.Span(f"({item.days_remaining}d)", className="ingredient-days")
        ]
    )


@callback(
    Output("ingredients-list", "children"),
    [Input("main-tabs", "value"), Input("refresh-trigger", "data")]
)
def update_ingredients_list(tab, trigger):
    """Update the expiring items list when switching to Recipe Chat tab."""
    if tab != "recipe-chat-tab":
        return dash.no_update
    items = get_vegetables_and_meat()
    # Only show items that are expiring (freshness < 60%)
    expiring_items = [item for item in items if item.freshness_percentage < 60]
    if not expiring_items:
        return html.Div("All your food is fresh! 🎉", className="no-ingredients")
    sorted_items = sorted(expiring_items, key=lambda x: x.freshness_percentage)
    return [create_ingredient_item(item) for item in sorted_items]


@callback(
    [Output("chat-messages", "children"),
     Output("streaming-state", "data", allow_duplicate=True),
     Output("chat-stream-interval", "disabled", allow_duplicate=True)],
    [Input("main-tabs", "value")],
    [State("chat-history", "data")],
    prevent_initial_call=True
)
def initialize_chat(tab, history):
    """Initialize chat with welcome message and initial suggestions when tab is opened."""
    if tab != "recipe-chat-tab":
        return dash.no_update, dash.no_update, dash.no_update
    
    if not history:
        welcome = chat_engine.get_welcome_message()
        welcome_message = html.Div(className="chat-message bot", children=[
            html.Span("🤖", className="message-avatar"),
            html.Div(welcome, className="message-content")
        ])
        
        # Check if we have ingredients to suggest recipes
        initial_prompt = chat_engine.get_initial_suggestions_prompt()
        if initial_prompt:
            # Start streaming initial suggestions
            chat_engine.start_initial_suggestions(use_recipes_doc=False)
            
            # Show welcome + typing indicator, enable streaming interval
            messages = [welcome_message, render_typing_indicator()]
            streaming_state = {
                "active": True,
                "pending_message": initial_prompt,
                "use_doc": False,
                "history_before": [{"role": "assistant", "content": welcome}],
                "is_initial": True
            }
            return messages, streaming_state, False  # False = interval enabled
        else:
            # No ingredients, just show welcome message
            return [welcome_message], dash.no_update, dash.no_update
    
    return render_chat_messages(history), dash.no_update, dash.no_update


def render_chat_messages(history):
    """Render chat history as HTML components."""
    messages = []
    for msg in history:
        if msg["role"] == "user":
            messages.append(html.Div(className="chat-message user", children=[
                html.Div(msg["content"], className="message-content"),
                html.Span("👤", className="message-avatar")
            ]))
        else:
            messages.append(html.Div(className="chat-message bot", children=[
                html.Span("🤖", className="message-avatar"),
                html.Div(msg["content"], className="message-content")
            ]))
    return messages


def render_chat_messages_with_streaming(history, streaming_text=None):
    """Render chat history as HTML components, optionally with a streaming message."""
    messages = render_chat_messages(history)
    
    # Add streaming message if there's content
    if streaming_text is not None:
        messages.append(html.Div(className="chat-message bot", children=[
            html.Span("🤖", className="message-avatar"),
            html.Div(
                children=[
                    html.Span(streaming_text if streaming_text else ""),
                    html.Span(className="typing-cursor")
                ],
                className="message-content message-streaming"
            )
        ]))
    
    return messages


def render_typing_indicator():
    """Render a typing indicator for the bot."""
    return html.Div(className="chat-message bot", children=[
        html.Span("🤖", className="message-avatar"),
        html.Div(className="message-content typing-indicator", children=[
            html.Span("●", className="dot dot-1"),
            html.Span("●", className="dot dot-2"),
            html.Span("●", className="dot dot-3"),
        ])
    ])


@callback(
    [Output("chat-messages", "children", allow_duplicate=True),
     Output("chat-input", "value"),
     Output("streaming-state", "data"),
     Output("chat-stream-interval", "disabled")],
    [Input("chat-send-btn", "n_clicks"), Input("chat-input", "n_submit")],
    [State("chat-input", "value"), State("chat-history", "data"), State("use-recipes-doc", "value")],
    prevent_initial_call=True
)
def start_chat_stream(n_clicks, n_submit, message, history, use_recipes):
    """Handle sending a chat message - starts streaming."""
    if not message or not message.strip():
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
    
    message = message.strip()
    use_doc = "yes" in (use_recipes or [])
    
    if not history:
        history = [{"role": "assistant", "content": chat_engine.get_welcome_message()}]
    
    # Add user message to display
    history_with_user = history + [{"role": "user", "content": message}]
    
    # Start streaming in background
    chat_engine.start_streaming_response(message, use_recipes_doc=use_doc)
    
    # Show user message + typing indicator
    messages = render_chat_messages(history_with_user)
    messages.append(render_typing_indicator())
    
    # Enable interval for polling, store pending message info
    streaming_state = {
        "active": True,
        "pending_message": message,
        "use_doc": use_doc,
        "history_before": history
    }
    
    return messages, "", streaming_state, False  # False = interval enabled


@callback(
    [Output("chat-messages", "children", allow_duplicate=True),
     Output("chat-history", "data"),
     Output("streaming-state", "data", allow_duplicate=True),
     Output("chat-stream-interval", "disabled", allow_duplicate=True)],
    Input("chat-stream-interval", "n_intervals"),
    [State("streaming-state", "data"), State("chat-history", "data")],
    prevent_initial_call=True
)
def poll_streaming_response(n_intervals, streaming_state, history):
    """Poll for streaming response updates."""
    if not streaming_state or not streaming_state.get("active"):
        return dash.no_update, dash.no_update, dash.no_update, True  # Disable interval
    
    # Get current streaming state from chat engine
    current_text, is_complete, error = chat_engine.get_streaming_state()
    
    # Check if this is the initial suggestions (no user message shown)
    is_initial = streaming_state.get("is_initial", False)
    
    if not history:
        history = [{"role": "assistant", "content": chat_engine.get_welcome_message()}]
    
    # For initial suggestions, we don't add a user message to display
    if is_initial:
        base_history = history
    else:
        # Reconstruct history with the user's message
        pending_message = streaming_state.get("pending_message")
        base_history = history + [{"role": "user", "content": pending_message}]
    
    if error:
        # Error occurred - show error message and stop
        new_history = base_history + [{"role": "assistant", "content": error}]
        return (
            render_chat_messages(new_history),
            new_history,
            {"active": False, "pending_message": None, "use_doc": False},
            True  # Disable interval
        )
    
    if is_complete:
        # Streaming complete - finalize message
        final_text = current_text.strip() if current_text else "I couldn't generate a response."
        new_history = base_history + [{"role": "assistant", "content": final_text}]
        return (
            render_chat_messages(new_history),
            new_history,
            {"active": False, "pending_message": None, "use_doc": False},
            True  # Disable interval
        )
    
    # Still streaming - update with current text
    messages = render_chat_messages_with_streaming(base_history, current_text)
    
    return messages, dash.no_update, dash.no_update, False  # Keep interval enabled


@callback(
    Output("tab-content", "children"),
    Input("main-tabs", "value")
)
def render_tab_content(tab):
    """Render the content for the selected tab."""
    if tab == "food-tab":
        return create_food_tab_content()
    elif tab == "shopping-tab":
        return create_shopping_tab_content()
    elif tab == "recipe-chat-tab":
        return create_recipe_chat_content()
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
            # No items found - show info message with debug panel
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
                            className="progress-step warning",
                            children=[
                                html.Span("⚠", className="step-icon"),
                                html.Span("No food items found", className="step-text")
                            ]
                        )
                    ]
                ),
                # Debug panel (collapsible) - show even when no items found
                create_debug_panel(debug_info)
            ])
            alert = html.Div(
                className="alert alert-info",
                children=[
                    "ℹ️ No food items found in the receipt. ",
                    "Make sure the image is clear and contains grocery items."
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
