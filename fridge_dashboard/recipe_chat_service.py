"""Recipe Chat Service using Gemini AI.

Provides a chat engine that suggests recipes based on available
vegetables and meat from the fridge database.
"""

import os
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

from .models import FridgeItem
from . import database as db

# Load .env file from project root
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Create Gemini client
api_key = os.environ.get("GOOGLE_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

MODEL_ID = "gemini-2.5-flash"


def get_vegetables_and_meat() -> List[FridgeItem]:
    """Get all vegetables (produce) and meat items from the database."""
    all_items = db.get_all_items()
    return [
        item for item in all_items
        if item.category in ('produce', 'meat')
    ]


def format_ingredients_for_prompt(items: List[FridgeItem]) -> str:
    """Format ingredients list for the Gemini prompt."""
    if not items:
        return "No vegetables or meat currently available."
    
    sorted_items = sorted(items, key=lambda x: x.freshness_percentage)
    lines = []
    for item in sorted_items:
        freshness_note = ""
        if item.freshness_percentage < 30:
            freshness_note = " ⚠️ EXPIRING - use first!"
        elif item.freshness_percentage < 60:
            freshness_note = " (use soon)"
        
        lines.append(
            f"- {item.name} ({item.category}): "
            f"{item.days_remaining} days left{freshness_note}"
        )
    return "\n".join(lines)


SYSTEM_PROMPT = """You are a helpful cooking assistant for a home kitchen.
Suggest recipes based on the ingredients the user has available.

AVAILABLE INGREDIENTS:
{ingredients}

GUIDELINES:
1. Prioritize ingredients expiring soon (marked with ⚠️)
2. Suggest practical home-cooking recipes
3. Be creative but realistic
4. Keep responses concise but helpful
{recipes_doc_instruction}
Respond in a friendly tone. Use emojis sparingly."""

RECIPES_DOC_INSTRUCTION = """
5. The user has a Google Doc called "Recipes" - check it for their saved recipes."""


class RecipeChatEngine:
    """Chat engine for recipe suggestions using Gemini AI."""
    
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.conversation_history: List[Dict[str, str]] = []
    
    def _build_system_prompt(self, use_recipes_doc: bool = False) -> str:
        """Build the system prompt with current ingredients."""
        items = get_vegetables_and_meat()
        ingredients = format_ingredients_for_prompt(items)
        recipes_instruction = RECIPES_DOC_INSTRUCTION if use_recipes_doc else ""
        return SYSTEM_PROMPT.format(
            ingredients=ingredients,
            recipes_doc_instruction=recipes_instruction
        )
    
    def _trim_history(self):
        """Trim conversation history to max_history messages."""
        if len(self.conversation_history) > self.max_history:
            self.conversation_history = self.conversation_history[-self.max_history:]
    
    def generate_response(self, user_message: str, use_recipes_doc: bool = False) -> str:
        """Generate a recipe response for the user's message."""
        if client is None:
            return "❌ Gemini API not configured. Please set GOOGLE_API_KEY."
        
        try:
            system_prompt = self._build_system_prompt(use_recipes_doc)
            self.conversation_history.append({"role": "user", "content": user_message})
            
            contents = [system_prompt]
            for msg in self.conversation_history:
                prefix = "User: " if msg["role"] == "user" else "Assistant: "
                contents.append(prefix + msg["content"])
            
            response = client.models.generate_content(
                model=MODEL_ID,
                contents="\n\n".join(contents)
            )
            
            assistant_message = response.text.strip()
            self.conversation_history.append({"role": "assistant", "content": assistant_message})
            self._trim_history()
            return assistant_message
            
        except Exception as e:
            return f"❌ Error generating response: {str(e)}"
    
    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []
    
    def get_welcome_message(self) -> str:
        """Get the initial welcome message."""
        items = get_vegetables_and_meat()
        
        if not items:
            return ("👋 Hi! I'm your recipe assistant. No vegetables or meat in your "
                    "fridge yet. Upload a receipt on the Food Tracker tab to start!")
        
        expiring = [i for i in items if i.freshness_percentage < 30]
        msg = f"👋 Hi! I can help you find recipes using your {len(items)} ingredients"
        
        if expiring:
            msg += f" — {len(expiring)} item(s) are expiring soon!"
        msg += "\n\nWhat would you like to cook today?"
        return msg
