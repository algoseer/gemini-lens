"""Data models for the Fridge Dashboard."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


# Storage location constants
STORAGE_FRIDGE = "fridge"
STORAGE_PANTRY = "pantry"
STORAGE_FREEZER = "freezer"
STORAGE_COUNTER = "counter"

STORAGE_LOCATIONS = [STORAGE_FRIDGE, STORAGE_PANTRY, STORAGE_FREEZER, STORAGE_COUNTER]

STORAGE_DISPLAY_NAMES = {
    STORAGE_FRIDGE: "🧊 Fridge",
    STORAGE_PANTRY: "🗄️ Pantry",
    STORAGE_FREEZER: "❄️ Freezer",
    STORAGE_COUNTER: "🍎 Counter",
}


@dataclass
class FridgeItem:
    """Represents a food item stored in any location (fridge, pantry, counter, etc.)."""
    
    id: Optional[int]
    name: str
    purchase_date: date
    shelf_life_days: int
    cost: Optional[float] = None
    category: Optional[str] = None
    remaining_percentage: int = 100  # How much of the item is left (0-100%)
    storage_location: str = STORAGE_FRIDGE  # Where the item is stored
    
    @property
    def days_elapsed(self) -> int:
        """Calculate days since purchase."""
        return (date.today() - self.purchase_date).days
    
    @property
    def days_remaining(self) -> int:
        """Calculate days remaining before expiration."""
        return max(0, self.shelf_life_days - self.days_elapsed)
    
    @property
    def freshness_percentage(self) -> float:
        """Calculate freshness as a percentage (0-100)."""
        if self.shelf_life_days <= 0:
            return 0
        freshness = (self.shelf_life_days - self.days_elapsed) / self.shelf_life_days * 100
        return max(0, min(100, freshness))
    
    @property
    def status_color(self) -> str:
        """Get color based on freshness level."""
        pct = self.freshness_percentage
        if pct >= 60:
            return "#28a745"  # Green
        elif pct >= 30:
            return "#ffc107"  # Yellow/Amber
        else:
            return "#dc3545"  # Red
    
    @property
    def status_emoji(self) -> str:
        """Get emoji based on freshness level."""
        pct = self.freshness_percentage
        if pct >= 60:
            return "🟢"
        elif pct >= 30:
            return "🟡"
        else:
            return "🔴"
    
    @property
    def status_text(self) -> str:
        """Get status text based on freshness level."""
        pct = self.freshness_percentage
        if pct >= 60:
            return "Fresh"
        elif pct >= 30:
            return "Use Soon"
        else:
            return "Expired/Bad"
    
    @property
    def storage_display(self) -> str:
        """Get display name for storage location."""
        return STORAGE_DISPLAY_NAMES.get(self.storage_location, "🧊 Fridge")
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "purchase_date": self.purchase_date.isoformat(),
            "shelf_life_days": self.shelf_life_days,
            "cost": self.cost,
            "category": self.category,
            "storage_location": self.storage_location,
            "days_elapsed": self.days_elapsed,
            "days_remaining": self.days_remaining,
            "freshness_percentage": round(self.freshness_percentage, 1),
            "status_color": self.status_color,
            "status_emoji": self.status_emoji,
            "status_text": self.status_text,
            "storage_display": self.storage_display,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "FridgeItem":
        """Create FridgeItem from dictionary."""
        purchase_date = data.get("purchase_date")
        if isinstance(purchase_date, str):
            purchase_date = datetime.fromisoformat(purchase_date).date()
        elif isinstance(purchase_date, datetime):
            purchase_date = purchase_date.date()
        
        return cls(
            id=data.get("id"),
            name=data["name"],
            purchase_date=purchase_date,
            shelf_life_days=data["shelf_life_days"],
            cost=data.get("cost"),
            category=data.get("category"),
            storage_location=data.get("storage_location", STORAGE_FRIDGE),
        )


@dataclass
class PurchaseHistoryItem:
    """Represents an item's purchase history for shopping recommendations."""
    
    id: Optional[int]
    normalized_name: str
    display_name: str
    category: Optional[str]
    storage_location: str
    purchase_count: int
    last_purchased: date
    
    @property
    def storage_display(self) -> str:
        """Get display name for storage location."""
        return STORAGE_DISPLAY_NAMES.get(self.storage_location, "🧊 Fridge")
    
    @property
    def frequency_label(self) -> str:
        """Get a human-readable frequency label."""
        if self.purchase_count >= 10:
            return "Very frequent"
        elif self.purchase_count >= 5:
            return "Frequent"
        elif self.purchase_count >= 3:
            return "Regular"
        else:
            return "Occasional"


@dataclass
class ShoppingListItem:
    """Represents an item on the shopping list."""
    
    id: Optional[int]
    name: str
    category: Optional[str]
    storage_location: str
    is_checked: bool
    added_at: datetime
    source: str  # 'manual' or 'suggested'
    
    @property
    def storage_display(self) -> str:
        """Get display name for storage location."""
        return STORAGE_DISPLAY_NAMES.get(self.storage_location, "🧊 Fridge")
