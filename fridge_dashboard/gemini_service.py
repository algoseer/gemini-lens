"""Gemini API service for receipt parsing and shelf life lookup.

Uses the new google-genai SDK (google.genai) instead of the deprecated
google-generativeai package.
"""

import base64
import json
import os
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image
import io

from dotenv import load_dotenv
from google import genai
from google.genai import types

from .models import FridgeItem

# Load .env file from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Create Gemini client - it will auto-detect GOOGLE_API_KEY from environment
# or you can explicitly pass api_key parameter
api_key = os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

# Use Gemini 2.5 Flash for fast responses
MODEL_ID = "gemini-2.5-flash"


RECEIPT_PARSING_PROMPT = """
Analyze this grocery receipt image and extract all food items that would typically be stored in a refrigerator.

For each item, provide:
1. "item": The normalized name of the grocery item in standard English (fix any OCR errors)
2. "cost": The price as a number (or null if not visible)
3. "category": One of: dairy, meat, produce, beverages, condiments, leftovers, other

IMPORTANT: Only include items that are typically refrigerated. Skip items like:
- Canned goods, dry pasta, rice, cereals
- Cleaning supplies, paper products
- Snacks like chips, crackers, cookies

Output ONLY valid JSON in this exact format, no other text:
{
    "items": [
        {"item": "Milk", "cost": 4.99, "category": "dairy"},
        {"item": "Chicken Breast", "cost": 8.50, "category": "meat"},
        {"item": "Lettuce", "cost": 2.99, "category": "produce"}
    ]
}
"""


SHELF_LIFE_PROMPT = """
For the following list of refrigerated food items, provide the typical shelf life in days when stored in a refrigerator at standard temperature (35-40°F / 2-4°C).

Items: {items}

Consider:
- Fresh produce typically lasts 3-7 days
- Dairy products vary (milk ~7 days, hard cheese ~21 days)
- Raw meat typically lasts 2-5 days
- Cooked leftovers typically last 3-4 days

Output ONLY valid JSON in this exact format, no other text:
{{
    "shelf_life": {{
        "Milk": 7,
        "Chicken Breast": 2,
        "Lettuce": 5
    }}
}}
"""


def _get_image_mime_type(image_data: bytes) -> str:
    """Detect image MIME type from bytes."""
    # Check magic bytes for common image formats
    if image_data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    elif image_data[:2] == b'\xff\xd8':
        return 'image/jpeg'
    elif image_data[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    elif image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
        return 'image/webp'
    else:
        # Default to JPEG
        return 'image/jpeg'


def parse_receipt_image(image_data: bytes) -> List[Dict[str, Any]]:
    """
    Parse a receipt image and extract refrigerated food items.
    
    Args:
        image_data: Raw image bytes
        
    Returns:
        List of dictionaries with item, cost, and category
    """
    if client is None:
        print("Error: Gemini client not initialized. Set GOOGLE_API_KEY environment variable.")
        return []
    
    try:
        # Detect MIME type
        mime_type = _get_image_mime_type(image_data)
        
        # Create image part using the new SDK
        image_part = types.Part.from_bytes(data=image_data, mime_type=mime_type)
        
        # Call Gemini API with the new SDK
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[RECEIPT_PARSING_PROMPT, image_part]
        )
        
        # Parse JSON response
        response_text = response.text.strip()
        
        # Handle markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            response_text = "\n".join(lines[1:-1])
        
        result = json.loads(response_text)
        return result.get("items", [])
        
    except json.JSONDecodeError as e:
        print(f"Error parsing Gemini response as JSON: {e}")
        print(f"Response was: {response.text if 'response' in dir() else 'N/A'}")
        return []
    except Exception as e:
        print(f"Error processing receipt: {e}")
        return []


def get_shelf_life_for_items(item_names: List[str]) -> Dict[str, int]:
    """
    Get estimated shelf life in days for a list of food items.
    
    Args:
        item_names: List of food item names
        
    Returns:
        Dictionary mapping item names to shelf life in days
    """
    if not item_names:
        return {}
    
    if client is None:
        print("Error: Gemini client not initialized. Set GOOGLE_API_KEY environment variable.")
        # Return default shelf life of 7 days for all items
        return {name: 7 for name in item_names}
    
    try:
        # Format the prompt with item names
        items_str = ", ".join(item_names)
        prompt = SHELF_LIFE_PROMPT.format(items=items_str)
        
        # Call Gemini API with the new SDK
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt
        )
        
        # Parse JSON response
        response_text = response.text.strip()
        
        # Handle markdown code blocks if present
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])
        
        result = json.loads(response_text)
        return result.get("shelf_life", {})
        
    except json.JSONDecodeError as e:
        print(f"Error parsing Gemini response as JSON: {e}")
        print(f"Response was: {response.text if 'response' in dir() else 'N/A'}")
        # Return default shelf life of 7 days for all items
        return {name: 7 for name in item_names}
    except Exception as e:
        print(f"Error getting shelf life: {e}")
        # Return default shelf life of 7 days for all items
        return {name: 7 for name in item_names}


def process_receipt_to_fridge_items(
    image_data: bytes,
    purchase_date: Optional[date] = None
) -> List[FridgeItem]:
    """
    Process a receipt image and create FridgeItem objects.
    
    This is the main function that:
    1. Parses the receipt to extract items
    2. Gets shelf life for each item
    3. Creates FridgeItem objects
    
    Args:
        image_data: Raw image bytes of the receipt
        purchase_date: Date of purchase (defaults to today)
        
    Returns:
        List of FridgeItem objects ready to be stored
    """
    if purchase_date is None:
        purchase_date = date.today()
    
    # Step 1: Parse receipt
    parsed_items = parse_receipt_image(image_data)
    
    if not parsed_items:
        return []
    
    # Step 2: Get shelf life for all items
    item_names = [item["item"] for item in parsed_items]
    shelf_life_map = get_shelf_life_for_items(item_names)
    
    # Step 3: Create FridgeItem objects
    fridge_items = []
    for item in parsed_items:
        name = item["item"]
        shelf_life = shelf_life_map.get(name, 7)  # Default to 7 days
        
        fridge_item = FridgeItem(
            id=None,
            name=name,
            purchase_date=purchase_date,
            shelf_life_days=shelf_life,
            cost=item.get("cost"),
            category=item.get("category")
        )
        fridge_items.append(fridge_item)
    
    return fridge_items


# Default shelf life values for common items (fallback)
DEFAULT_SHELF_LIFE = {
    # Dairy
    "milk": 7,
    "cheese": 21,
    "yogurt": 14,
    "butter": 30,
    "cream": 7,
    "eggs": 21,
    
    # Meat
    "chicken": 2,
    "beef": 3,
    "pork": 3,
    "fish": 2,
    "ground beef": 2,
    "bacon": 7,
    "deli meat": 5,
    
    # Produce
    "lettuce": 5,
    "spinach": 5,
    "tomatoes": 7,
    "carrots": 21,
    "celery": 14,
    "broccoli": 5,
    "peppers": 7,
    "onions": 30,
    "mushrooms": 5,
    "berries": 3,
    "grapes": 7,
    "apples": 21,
    
    # Condiments
    "ketchup": 180,
    "mustard": 365,
    "mayonnaise": 60,
    "salsa": 14,
    
    # Beverages
    "juice": 7,
    "almond milk": 7,
    "oat milk": 7,
}


def get_default_shelf_life(item_name: str) -> int:
    """Get default shelf life for an item from the fallback dictionary."""
    item_lower = item_name.lower()
    
    for key, days in DEFAULT_SHELF_LIFE.items():
        if key in item_lower or item_lower in key:
            return days
    
    return 7  # Default fallback
