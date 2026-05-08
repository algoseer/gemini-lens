"""SQLite database operations for the Fridge Dashboard."""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from .models import FridgeItem, PurchaseHistoryItem, ShoppingListItem

# Database file path - use /app/data directory for Docker volume mount
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "fridge.db"


def get_connection() -> sqlite3.Connection:
    """Get a database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Initialize the database with required tables."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fridge_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            purchase_date DATE NOT NULL,
            shelf_life_days INTEGER NOT NULL,
            cost REAL,
            category TEXT,
            remaining_percentage INTEGER DEFAULT 100,
            storage_location TEXT DEFAULT 'fridge',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add remaining_percentage column if it doesn't exist (migration)
    try:
        cursor.execute("ALTER TABLE fridge_items ADD COLUMN remaining_percentage INTEGER DEFAULT 100")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Add storage_location column if it doesn't exist (migration)
    try:
        cursor.execute("ALTER TABLE fridge_items ADD COLUMN storage_location TEXT DEFAULT 'fridge'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Purchase history table for shopping recommendations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_name TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            category TEXT,
            storage_location TEXT DEFAULT 'fridge',
            purchase_count INTEGER DEFAULT 1,
            last_purchased DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Shopping list table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shopping_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            storage_location TEXT DEFAULT 'fridge',
            is_checked INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'manual'
        )
    """)
    
    # Suppressed suggestions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppressed_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_name TEXT NOT NULL UNIQUE,
            suppressed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()


def add_item(item: FridgeItem) -> int:
    """Add a new item to the database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO fridge_items (name, purchase_date, shelf_life_days, cost, category, storage_location)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        item.name,
        item.purchase_date.isoformat(),
        item.shelf_life_days,
        item.cost,
        item.category,
        item.storage_location
    ))
    
    item_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return item_id


def add_items(items: List[FridgeItem]) -> List[int]:
    """Add multiple items to the database and record in purchase history."""
    conn = get_connection()
    cursor = conn.cursor()
    
    item_ids = []
    for item in items:
        cursor.execute("""
            INSERT INTO fridge_items (name, purchase_date, shelf_life_days, cost, category, storage_location)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            item.name,
            item.purchase_date.isoformat(),
            item.shelf_life_days,
            item.cost,
            item.category,
            item.storage_location
        ))
        item_ids.append(cursor.lastrowid)
    
    conn.commit()
    conn.close()
    
    # Record purchases in history (done after to avoid transaction issues)
    for item in items:
        record_item_purchase(item.name, item.category, item.storage_location, item.purchase_date)
    
    return item_ids


def get_all_items(storage_location: Optional[str] = None) -> List[FridgeItem]:
    """Get all items from the database, optionally filtered by storage location."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if storage_location:
        cursor.execute("""
            SELECT id, name, purchase_date, shelf_life_days, cost, category, remaining_percentage, storage_location
            FROM fridge_items
            WHERE storage_location = ?
            ORDER BY purchase_date DESC
        """, (storage_location,))
    else:
        cursor.execute("""
            SELECT id, name, purchase_date, shelf_life_days, cost, category, remaining_percentage, storage_location
            FROM fridge_items
            ORDER BY purchase_date DESC
        """)
    
    rows = cursor.fetchall()
    conn.close()
    
    items = []
    for row in rows:
        items.append(FridgeItem(
            id=row["id"],
            name=row["name"],
            purchase_date=datetime.fromisoformat(row["purchase_date"]).date(),
            shelf_life_days=row["shelf_life_days"],
            cost=row["cost"],
            category=row["category"],
            remaining_percentage=row["remaining_percentage"] or 100,
            storage_location=row["storage_location"] or "fridge"
        ))
    
    return items


def get_item_by_id(item_id: int) -> Optional[FridgeItem]:
    """Get a specific item by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, purchase_date, shelf_life_days, cost, category, remaining_percentage, storage_location
        FROM fridge_items
        WHERE id = ?
    """, (item_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return FridgeItem(
            id=row["id"],
            name=row["name"],
            purchase_date=datetime.fromisoformat(row["purchase_date"]).date(),
            shelf_life_days=row["shelf_life_days"],
            cost=row["cost"],
            category=row["category"],
            remaining_percentage=row["remaining_percentage"] or 100,
            storage_location=row["storage_location"] or "fridge"
        )
    return None


def delete_item(item_id: int) -> bool:
    """Delete an item from the database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM fridge_items WHERE id = ?", (item_id,))
    
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted


def delete_all_items() -> int:
    """Delete all items from the database. Returns count of deleted items."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM fridge_items")
    
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    return deleted_count


def update_item(item_id: int, **kwargs) -> bool:
    """Update specific fields of an existing item.
    
    Args:
        item_id: The ID of the item to update
        **kwargs: Fields to update (name, shelf_life_days, cost, category, purchase_date, storage_location)
    
    Returns:
        True if item was updated, False otherwise
    """
    if not kwargs:
        return False
    
    # Build the SET clause dynamically based on provided kwargs
    valid_fields = {'name', 'shelf_life_days', 'cost', 'category', 'purchase_date', 'remaining_percentage', 'storage_location'}
    updates = []
    values = []
    
    for field, value in kwargs.items():
        if field in valid_fields:
            updates.append(f"{field} = ?")
            # Convert date to ISO format if needed
            if field == 'purchase_date' and hasattr(value, 'isoformat'):
                value = value.isoformat()
            values.append(value)
    
    if not updates:
        return False
    
    values.append(item_id)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    query = f"UPDATE fridge_items SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, values)
    
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return updated


def update_item_full(item: FridgeItem) -> bool:
    """Update all fields of an existing item using a FridgeItem object."""
    if item.id is None:
        return False
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE fridge_items
        SET name = ?, purchase_date = ?, shelf_life_days = ?, cost = ?, category = ?, storage_location = ?
        WHERE id = ?
    """, (
        item.name,
        item.purchase_date.isoformat(),
        item.shelf_life_days,
        item.cost,
        item.category,
        item.storage_location,
        item.id
    ))
    
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return updated


def get_items_by_status(status: str) -> List[FridgeItem]:
    """Get items filtered by status (fresh, use_soon, expired)."""
    all_items = get_all_items()
    
    if status == "fresh":
        return [item for item in all_items if item.freshness_percentage >= 60]
    elif status == "use_soon":
        return [item for item in all_items if 30 <= item.freshness_percentage < 60]
    elif status == "expired":
        return [item for item in all_items if item.freshness_percentage < 30]
    else:
        return all_items


# ============================================================================
# Purchase History Functions (for shopping recommendations)
# ============================================================================

def record_item_purchase(name: str, category: Optional[str], storage_location: str, purchase_date: date) -> None:
    """Record an item purchase for history tracking.
    
    If the item already exists in history, increment the count and update last_purchased.
    Otherwise, create a new record.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    normalized_name = name.strip().lower()
    
    # Try to update existing record
    cursor.execute("""
        UPDATE purchase_history
        SET purchase_count = purchase_count + 1,
            last_purchased = ?,
            display_name = ?
        WHERE normalized_name = ?
    """, (purchase_date.isoformat(), name, normalized_name))
    
    # If no existing record, insert new one
    if cursor.rowcount == 0:
        cursor.execute("""
            INSERT INTO purchase_history (normalized_name, display_name, category, storage_location, purchase_count, last_purchased)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (normalized_name, name, category, storage_location, purchase_date.isoformat()))
    
    conn.commit()
    conn.close()


def record_items_purchase(items: List[FridgeItem]) -> None:
    """Record multiple item purchases for history tracking."""
    for item in items:
        record_item_purchase(item.name, item.category, item.storage_location, item.purchase_date)


def get_purchase_history(limit: int = 50) -> List[PurchaseHistoryItem]:
    """Get purchase history items sorted by purchase count (most frequent first)."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, normalized_name, display_name, category, storage_location, purchase_count, last_purchased
        FROM purchase_history
        ORDER BY purchase_count DESC, last_purchased DESC
        LIMIT ?
    """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    items = []
    for row in rows:
        items.append(PurchaseHistoryItem(
            id=row["id"],
            normalized_name=row["normalized_name"],
            display_name=row["display_name"],
            category=row["category"],
            storage_location=row["storage_location"] or "fridge",
            purchase_count=row["purchase_count"],
            last_purchased=datetime.fromisoformat(row["last_purchased"]).date()
        ))
    
    return items


def get_suggested_items(min_purchase_count: int = 2, limit: int = 20) -> List[PurchaseHistoryItem]:
    """Get items to suggest for shopping.
    
    Returns frequently purchased items that are NOT currently in the fridge
    and are NOT suppressed.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get normalized names of items currently in fridge
    cursor.execute("SELECT LOWER(name) FROM fridge_items")
    current_items = {row[0] for row in cursor.fetchall()}
    
    # Get suppressed items
    cursor.execute("SELECT normalized_name FROM suppressed_suggestions")
    suppressed_items = {row[0] for row in cursor.fetchall()}
    
    # Get purchase history items
    cursor.execute("""
        SELECT id, normalized_name, display_name, category, storage_location, purchase_count, last_purchased
        FROM purchase_history
        WHERE purchase_count >= ?
        ORDER BY purchase_count DESC, last_purchased DESC
    """, (min_purchase_count,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Filter out items that are in fridge or suppressed
    items = []
    for row in rows:
        normalized = row["normalized_name"]
        if normalized not in current_items and normalized not in suppressed_items:
            items.append(PurchaseHistoryItem(
                id=row["id"],
                normalized_name=normalized,
                display_name=row["display_name"],
                category=row["category"],
                storage_location=row["storage_location"] or "fridge",
                purchase_count=row["purchase_count"],
                last_purchased=datetime.fromisoformat(row["last_purchased"]).date()
            ))
            if len(items) >= limit:
                break
    
    return items


# ============================================================================
# Shopping List Functions
# ============================================================================

def add_to_shopping_list(name: str, category: Optional[str] = None, 
                         storage_location: str = "fridge", source: str = "manual") -> int:
    """Add an item to the shopping list."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO shopping_list (name, category, storage_location, source)
        VALUES (?, ?, ?, ?)
    """, (name, category, storage_location, source))
    
    item_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return item_id


def get_shopping_list() -> List[ShoppingListItem]:
    """Get all items from the shopping list."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, category, storage_location, is_checked, added_at, source
        FROM shopping_list
        ORDER BY is_checked ASC, added_at DESC
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    items = []
    for row in rows:
        items.append(ShoppingListItem(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            storage_location=row["storage_location"] or "fridge",
            is_checked=bool(row["is_checked"]),
            added_at=datetime.fromisoformat(row["added_at"]),
            source=row["source"] or "manual"
        ))
    
    return items


def toggle_shopping_list_item(item_id: int) -> bool:
    """Toggle the checked status of a shopping list item."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE shopping_list
        SET is_checked = CASE WHEN is_checked = 0 THEN 1 ELSE 0 END
        WHERE id = ?
    """, (item_id,))
    
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return updated


def remove_from_shopping_list(item_id: int) -> bool:
    """Remove an item from the shopping list."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
    
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted


def clear_shopping_list(checked_only: bool = False) -> int:
    """Clear the shopping list. If checked_only is True, only remove checked items."""
    conn = get_connection()
    cursor = conn.cursor()
    
    if checked_only:
        cursor.execute("DELETE FROM shopping_list WHERE is_checked = 1")
    else:
        cursor.execute("DELETE FROM shopping_list")
    
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    return deleted_count


def get_shopping_list_item_by_id(item_id: int) -> Optional[ShoppingListItem]:
    """Get a specific shopping list item by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, category, storage_location, is_checked, added_at, source
        FROM shopping_list
        WHERE id = ?
    """, (item_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return ShoppingListItem(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            storage_location=row["storage_location"] or "fridge",
            is_checked=bool(row["is_checked"]),
            added_at=datetime.fromisoformat(row["added_at"]),
            source=row["source"] or "manual"
        )
    return None


# ============================================================================
# Suppressed Suggestions Functions
# ============================================================================

def suppress_suggestion(name: str) -> bool:
    """Suppress an item from appearing in suggestions."""
    conn = get_connection()
    cursor = conn.cursor()
    
    normalized_name = name.strip().lower()
    
    try:
        cursor.execute("""
            INSERT INTO suppressed_suggestions (normalized_name)
            VALUES (?)
        """, (normalized_name,))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        # Already suppressed
        success = False
    
    conn.close()
    return success


def unsuppress_suggestion(name: str) -> bool:
    """Remove suppression for an item, allowing it to appear in suggestions again."""
    conn = get_connection()
    cursor = conn.cursor()
    
    normalized_name = name.strip().lower()
    
    cursor.execute("DELETE FROM suppressed_suggestions WHERE normalized_name = ?", (normalized_name,))
    
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    
    return deleted


def get_suppressed_suggestions() -> List[str]:
    """Get list of all suppressed item names."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT normalized_name FROM suppressed_suggestions ORDER BY suppressed_at DESC")
    
    names = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return names


# Initialize database on module import
init_database()
