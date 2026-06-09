"""Gemini API service for receipt parsing and shelf life lookup.

Uses the new google-genai SDK (google.genai) instead of the deprecated
google-generativeai package.
"""

import base64
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image
import io

from dotenv import load_dotenv
from google import genai
from google.genai import types

from .models import FridgeItem, STORAGE_FRIDGE, STORAGE_PANTRY, STORAGE_FREEZER, STORAGE_COUNTER

# Load .env file from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Create Gemini client - it will auto-detect GOOGLE_API_KEY from environment
# or you can explicitly pass api_key parameter
api_key = os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

# Primary model and fallback for when primary is unavailable (503)
MODEL_ID = "gemini-2.5-flash"
FALLBACK_MODEL_ID = "gemini-2.5-flash-lite"


RECEIPT_PARSING_PROMPT = """
Analyze this grocery receipt image and extract:
1. The purchase date from the receipt (look for date printed on receipt)
2. All FOOD items from the receipt

For each item, provide:
1. "item": The normalized name of the grocery item in standard English (fix any OCR errors)
2. "cost": The price as a number (or null if not visible)
3. "category": One of: dairy, meat, produce, beverages, condiments, grains, canned, snacks, frozen, bakery, other
4. "storage": Where the item should be stored. One of:
   - "fridge": Items that need refrigeration (dairy, fresh meat, eggs, fresh produce that needs cold)
   - "freezer": Frozen items (frozen vegetables, ice cream, frozen meals)
   - "pantry": Shelf-stable items (canned goods, dry pasta, rice, cereals, snacks, chips)
   - "counter": Fresh produce that stores at room temperature (bananas, potatoes, onions, tomatoes, avocados)

IMPORTANT: Include ALL food items. Skip only non-food items like:
- Cleaning supplies, paper products
- Personal care items

Output ONLY valid JSON in this exact format, no other text:
{
    "purchase_date": "2024-01-15",
    "items": [
        {"item": "Milk", "cost": 4.99, "category": "dairy", "storage": "fridge"},
        {"item": "Chicken Breast", "cost": 8.50, "category": "meat", "storage": "fridge"},
        {"item": "Lettuce", "cost": 2.99, "category": "produce", "storage": "fridge"},
        {"item": "Bananas", "cost": 1.49, "category": "produce", "storage": "counter"},
        {"item": "Pasta", "cost": 2.29, "category": "grains", "storage": "pantry"},
        {"item": "Frozen Peas", "cost": 3.49, "category": "frozen", "storage": "freezer"}
    ]
}

Note: For purchase_date, use ISO format (YYYY-MM-DD). If the date is not visible or unclear, use null.
"""


SHELF_LIFE_PROMPT = """
For the following list of food items, provide the typical shelf life in days for EACH storage location.

Items: {items}

For each item, provide shelf life (in days) for all four locations:
- fridge: refrigerated (35-38°F)
- freezer: frozen (0°F)
- pantry: cool, dry shelf storage
- counter: room temperature

Guidelines:
- Fridge: Fresh produce 3-7 days, dairy varies (milk ~7 days, hard cheese ~21 days), raw meat 2-5 days
- Freezer: Most items last 30-365 days when properly frozen (meat 90-180 days, vegetables 180-365 days)
- Pantry: Dry goods 180-365 days, canned goods 365-730 days; perishables like meat/dairy are NOT safe in pantry (use 0 or 1)
- Counter: Bananas ~5 days, potatoes ~14 days, onions ~30 days, tomatoes ~7 days; dairy/meat are NOT safe on counter (use 0 or 1)

Output ONLY valid JSON in this exact format, no other text:
{{
    "shelf_life": {{
        "Milk":          {{"fridge": 7,   "freezer": 90,  "pantry": 1,   "counter": 1}},
        "Chicken Breast":{{"fridge": 2,   "freezer": 180, "pantry": 1,   "counter": 1}},
        "Lettuce":       {{"fridge": 5,   "freezer": 180, "pantry": 1,   "counter": 2}},
        "Bananas":       {{"fridge": 7,   "freezer": 90,  "pantry": 5,   "counter": 5}},
        "Pasta":         {{"fridge": 3,   "freezer": 730, "pantry": 365, "counter": 180}},
        "Frozen Peas":   {{"fridge": 5,   "freezer": 365, "pantry": 3,   "counter": 1}}
    }}
}}
"""


def _classify_api_error(exc: Exception) -> Dict[str, str]:
    """
    Classify a Gemini API exception into a user-friendly message and error type.

    Returns a dict with keys:
        - "type": one of "quota", "auth", "network", "unavailable", "unknown"
        - "user_message": human-readable message suitable for the frontend
    """
    err_str = str(exc).lower()
    exc_type = type(exc).__name__

    if "resource_exhausted" in err_str or "429" in err_str or "quota" in err_str or "rate" in err_str:
        return {
            "type": "quota",
            "user_message": (
                "⚠️ Gemini API quota exceeded. The free-tier limit has been reached. "
                "Please wait a few minutes and try again, or upgrade your plan at "
                "https://aistudio.google.com."
            ),
        }
    if "unauthenticated" in err_str or "api_key" in err_str or "invalid" in err_str or "401" in err_str or "403" in err_str:
        return {
            "type": "auth",
            "user_message": (
                "🔑 Gemini API authentication failed. Please check that your GOOGLE_API_KEY "
                "is valid and has not expired."
            ),
        }
    if "unavailable" in err_str or "503" in err_str or "high demand" in err_str:
        return {
            "type": "unavailable",
            "user_message": (
                "🌐 Gemini API is temporarily unavailable (high demand). "
                "Retrying with fallback model..."
            ),
        }
    if "deadline" in err_str or "timeout" in err_str or "504" in err_str:
        return {
            "type": "network",
            "user_message": (
                "🌐 Gemini API timed out. "
                "Please check your internet connection and try again."
            ),
        }
    return {
        "type": "unknown",
        "user_message": f"❌ Gemini API error: {str(exc)}",
    }


def _is_unavailable_error(exc: Exception) -> bool:
    """Return True if the exception is a transient 503/unavailable error worth retrying."""
    err_str = str(exc).lower()
    return "unavailable" in err_str or "503" in err_str or "high demand" in err_str


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


def parse_receipt_image(image_data: bytes) -> Tuple[List[Dict[str, Any]], Optional[date], Dict[str, Any]]:
    """
    Parse a receipt image and extract refrigerated food items and purchase date.
    
    Args:
        image_data: Raw image bytes
        
    Returns:
        Tuple of (list of item dictionaries, extracted purchase date or None, raw debug info)
    """
    debug_info = {
        "raw_response": None,
        "parsed_json": None,
        "error": None,
        "model": MODEL_ID
    }
    
    if client is None:
        debug_info["error"] = "Gemini client not initialized. Set GOOGLE_API_KEY environment variable."
        print(f"Error: {debug_info['error']}")
        return [], None, debug_info
    
    # Try primary model first, fall back to FALLBACK_MODEL_ID on 503/unavailable
    models_to_try = [MODEL_ID, FALLBACK_MODEL_ID]

    for attempt, model_id in enumerate(models_to_try):
        if attempt > 0:
            print(f"Retrying with fallback model: {model_id}")
            debug_info["fallback_model"] = model_id

        try:
            # Detect MIME type
            mime_type = _get_image_mime_type(image_data)
            debug_info["mime_type"] = mime_type

            # Create image part using the new SDK
            image_part = types.Part.from_bytes(data=image_data, mime_type=mime_type)

            # Call Gemini API with explicit timeout (60s) so it never hangs indefinitely
            response = client.models.generate_content(
                model=model_id,
                contents=[RECEIPT_PARSING_PROMPT, image_part],
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=60000)  # 60 seconds in ms
                )
            )

            debug_info["model_used"] = model_id

            # Store raw response
            raw_text = response.text
            debug_info["raw_response"] = raw_text

            # Parse JSON response
            response_text = raw_text.strip()

            # Handle markdown code blocks if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                # Remove first line (```json or ```) and last line (```)
                response_text = "\n".join(lines[1:-1])

            result = json.loads(response_text)
            debug_info["parsed_json"] = result

            items = result.get("items", [])

            # Extract purchase date if available
            extracted_date = None
            date_str = result.get("purchase_date")
            if date_str:
                try:
                    extracted_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    debug_info["date_parse_error"] = f"Could not parse date: {date_str}"
                    print(f"Could not parse date: {date_str}")

            return items, extracted_date, debug_info

        except json.JSONDecodeError as e:
            debug_info["error"] = f"JSON parse error: {str(e)}"
            debug_info["error_type"] = "parse"
            debug_info["user_message"] = "❌ Could not parse the AI response. Please try uploading the receipt again."
            print(f"Error parsing Gemini response as JSON: {e}")
            print(f"Response was: {response.text if 'response' in dir() else 'N/A'}")
            return [], None, debug_info
        except Exception as e:
            classified = _classify_api_error(e)
            if _is_unavailable_error(e) and attempt < len(models_to_try) - 1:
                # Transient 503 — try the next model
                print(f"Model {model_id} unavailable (503), will retry with fallback. Error: {e}")
                debug_info["primary_model_error"] = str(e)
                continue
            # Non-retryable error or we've exhausted all models
            debug_info["error"] = f"Processing error: {str(e)}"
            debug_info["error_type"] = classified["type"]
            debug_info["user_message"] = classified["user_message"]
            print(f"Error processing receipt: {e}")
            return [], None, debug_info

    # Should not reach here, but just in case
    return [], None, debug_info


def get_shelf_life_for_items(item_names: List[str]) -> Dict[str, Any]:
    """
    Get estimated shelf life in days for a list of food items, per storage location.
    
    Args:
        item_names: List of food item names
        
    Returns:
        Dictionary mapping item names to a dict of {fridge, freezer, pantry, counter} shelf life days.
        Falls back to a flat int (7) if the API returns the old format or fails.
    """
    if not item_names:
        return {}
    
    if client is None:
        print("Error: Gemini client not initialized. Set GOOGLE_API_KEY environment variable.")
        return {name: {"fridge": 7, "freezer": 180, "pantry": 30, "counter": 3} for name in item_names}
    
    try:
        items_str = ", ".join(item_names)
        prompt = SHELF_LIFE_PROMPT.format(items=items_str)
        
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(timeout=60000)  # 60 seconds in ms
            )
        )
        
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
        return {name: {"fridge": 7, "freezer": 180, "pantry": 30, "counter": 3} for name in item_names}
    except Exception as e:
        print(f"Error getting shelf life: {e}")
        return {name: {"fridge": 7, "freezer": 180, "pantry": 30, "counter": 3} for name in item_names}


def process_receipt_to_fridge_items(
    image_data: bytes,
    fallback_date: Optional[date] = None
) -> Tuple[List[FridgeItem], Optional[date], Dict[str, Any]]:
    """
    Process a receipt image and create FridgeItem objects.
    
    This is the main function that:
    1. Parses the receipt to extract items and purchase date
    2. Gets shelf life for each item
    3. Creates FridgeItem objects
    
    Args:
        image_data: Raw image bytes of the receipt
        fallback_date: Date to use if not found on receipt (defaults to today)
        
    Returns:
        Tuple of (List of FridgeItem objects, extracted purchase date or None, debug info dict)
    """
    if fallback_date is None:
        fallback_date = date.today()
    
    # Step 1: Parse receipt (now returns items, extracted date, and debug info)
    parsed_items, extracted_date, debug_info = parse_receipt_image(image_data)
    
    # Use extracted date if available, otherwise use fallback
    purchase_date = extracted_date if extracted_date else fallback_date
    debug_info["used_date"] = str(purchase_date)
    debug_info["date_source"] = "extracted" if extracted_date else "fallback"
    
    if not parsed_items:
        return [], extracted_date, debug_info
    
    # Step 2: Get shelf life for all items
    item_names = [item["item"] for item in parsed_items]
    shelf_life_map = get_shelf_life_for_items(item_names)
    debug_info["shelf_life_map"] = shelf_life_map
    
    # Step 3: Create FridgeItem objects
    fridge_items = []
    for item in parsed_items:
        name = item["item"]
        per_loc = shelf_life_map.get(name, {})

        # per_loc may be a dict {fridge, freezer, pantry, counter} or a plain int (legacy fallback)
        if isinstance(per_loc, dict):
            sl_fridge  = per_loc.get("fridge",  7)
            sl_freezer = per_loc.get("freezer", 180)
            sl_pantry  = per_loc.get("pantry",  30)
            sl_counter = per_loc.get("counter", 3)
        else:
            # Legacy flat int – use as fridge shelf life, derive rough values for others
            sl_fridge  = int(per_loc)
            sl_freezer = sl_fridge * 10
            sl_pantry  = sl_fridge * 3
            sl_counter = max(1, sl_fridge // 2)

        # Map storage value from API to our constants
        storage_value = item.get("storage", "fridge").lower()
        storage_map = {
            "fridge": STORAGE_FRIDGE,
            "freezer": STORAGE_FREEZER,
            "pantry": STORAGE_PANTRY,
            "counter": STORAGE_COUNTER,
        }
        storage_location = storage_map.get(storage_value, STORAGE_FRIDGE)

        # shelf_life_days = shelf life for the item's current storage location
        loc_to_sl = {
            STORAGE_FRIDGE:  sl_fridge,
            STORAGE_FREEZER: sl_freezer,
            STORAGE_PANTRY:  sl_pantry,
            STORAGE_COUNTER: sl_counter,
        }
        shelf_life_days = loc_to_sl.get(storage_location, sl_fridge)

        fridge_item = FridgeItem(
            id=None,
            name=name,
            purchase_date=purchase_date,
            shelf_life_days=shelf_life_days,
            cost=item.get("cost"),
            category=item.get("category"),
            storage_location=storage_location,
            shelf_life_fridge=sl_fridge,
            shelf_life_freezer=sl_freezer,
            shelf_life_pantry=sl_pantry,
            shelf_life_counter=sl_counter,
        )
        fridge_items.append(fridge_item)
    
    debug_info["items_created"] = len(fridge_items)
    return fridge_items, extracted_date, debug_info


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
