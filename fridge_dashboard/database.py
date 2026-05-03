"""SQLite database operations for the Fridge Dashboard."""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from .models import FridgeItem

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()


def add_item(item: FridgeItem) -> int:
    """Add a new item to the fridge database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO fridge_items (name, purchase_date, shelf_life_days, cost, category)
        VALUES (?, ?, ?, ?, ?)
    """, (
        item.name,
        item.purchase_date.isoformat(),
        item.shelf_life_days,
        item.cost,
        item.category
    ))
    
    item_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return item_id


def add_items(items: List[FridgeItem]) -> List[int]:
    """Add multiple items to the fridge database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    item_ids = []
    for item in items:
        cursor.execute("""
            INSERT INTO fridge_items (name, purchase_date, shelf_life_days, cost, category)
            VALUES (?, ?, ?, ?, ?)
        """, (
            item.name,
            item.purchase_date.isoformat(),
            item.shelf_life_days,
            item.cost,
            item.category
        ))
        item_ids.append(cursor.lastrowid)
    
    conn.commit()
    conn.close()
    
    return item_ids


def get_all_items() -> List[FridgeItem]:
    """Get all items from the fridge database."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, purchase_date, shelf_life_days, cost, category
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
            category=row["category"]
        ))
    
    return items


def get_item_by_id(item_id: int) -> Optional[FridgeItem]:
    """Get a specific item by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, purchase_date, shelf_life_days, cost, category
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
            category=row["category"]
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


def update_item(item: FridgeItem) -> bool:
    """Update an existing item."""
    if item.id is None:
        return False
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE fridge_items
        SET name = ?, purchase_date = ?, shelf_life_days = ?, cost = ?, category = ?
        WHERE id = ?
    """, (
        item.name,
        item.purchase_date.isoformat(),
        item.shelf_life_days,
        item.cost,
        item.category,
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


# Initialize database on module import
init_database()
