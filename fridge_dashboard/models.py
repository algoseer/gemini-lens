"""Data models for the Fridge Dashboard."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class FridgeItem:
    """Represents an item stored in the fridge."""
    
    id: Optional[int]
    name: str
    purchase_date: date
    shelf_life_days: int
    cost: Optional[float] = None
    category: Optional[str] = None
    remaining_percentage: int = 100  # How much of the item is left (0-100%)
    
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
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "purchase_date": self.purchase_date.isoformat(),
            "shelf_life_days": self.shelf_life_days,
            "cost": self.cost,
            "category": self.category,
            "days_elapsed": self.days_elapsed,
            "days_remaining": self.days_remaining,
            "freshness_percentage": round(self.freshness_percentage, 1),
            "status_color": self.status_color,
            "status_emoji": self.status_emoji,
            "status_text": self.status_text,
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
        )
