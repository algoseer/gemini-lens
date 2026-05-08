"""Recipe Chat Service using Gemini AI.

Provides a chat engine that suggests recipes based on available
vegetables and meat from the fridge database.
"""

import os
import threading
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

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
Help users find inspiring recipes and cooking ideas.

GUIDELINES:
1. Suggest practical home-cooking recipes
2. Be creative but realistic
3. Keep responses concise but helpful
{recipes_doc_instruction}
Respond in a friendly tone. Use emojis sparingly."""

RECIPES_DOC_INSTRUCTION = """
5. The user has a Google Doc called "Recipes" - check it for their saved recipes."""


class RecipeChatEngine:
    """Chat engine for recipe suggestions using Gemini AI."""
    
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.conversation_history: List[Dict[str, str]] = []
        
        # Streaming state
        self._streaming_lock = threading.Lock()
        self._streaming_buffer = ""
        self._is_streaming = False
        self._streaming_complete = False
        self._streaming_error: Optional[str] = None
    
    def _build_system_prompt(self, use_recipes_doc: bool = False) -> str:
        """Build the system prompt."""
        recipes_instruction = RECIPES_DOC_INSTRUCTION if use_recipes_doc else ""
        return SYSTEM_PROMPT.format(
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
        msg += "\n\nLet me suggest a few things you can make..."
        return msg
    
    def get_initial_suggestions_prompt(self) -> Optional[str]:
        """
        Build a prompt for initial recipe suggestions based on available ingredients.
        Returns None if no ingredients are available.
        """
        items = get_vegetables_and_meat()
        
        if not items:
            return None
        
        ingredients_text = format_ingredients_for_prompt(items)
        
        # Build a prompt that asks for quick suggestions
        prompt = f"""Based on these ingredients I have in my fridge:

{ingredients_text}

Suggest 2-3 quick recipe ideas I could make. For each suggestion:
- Give a brief name
- List main ingredients from my fridge it would use
- Mention if it uses any expiring items (marked with ⚠️)

Keep it concise - just the highlights. I can ask for more details on any recipe I'm interested in."""
        
        return prompt
    
    def start_initial_suggestions(self, use_recipes_doc: bool = False) -> bool:
        """
        Start streaming initial recipe suggestions based on fridge contents.
        Returns True if streaming started, False if no ingredients or already streaming.
        """
        prompt = self.get_initial_suggestions_prompt()
        if prompt is None:
            return False
        
        return self.start_streaming_response(prompt, use_recipes_doc=use_recipes_doc)
    
    def start_streaming_response(self, user_message: str, use_recipes_doc: bool = False) -> bool:
        """
        Start streaming a response in a background thread.
        
        Returns True if streaming started successfully, False if already streaming.
        """
        with self._streaming_lock:
            if self._is_streaming:
                return False
            
            # Reset streaming state
            self._streaming_buffer = ""
            self._is_streaming = True
            self._streaming_complete = False
            self._streaming_error = None
        
        # Start background thread
        thread = threading.Thread(
            target=self._stream_worker,
            args=(user_message, use_recipes_doc),
            daemon=True
        )
        thread.start()
        return True
    
    def _stream_worker(self, user_message: str, use_recipes_doc: bool):
        """Background worker that streams the Gemini response."""
        if client is None:
            with self._streaming_lock:
                self._streaming_error = "❌ Gemini API not configured. Please set GOOGLE_API_KEY."
                self._streaming_complete = True
                self._is_streaming = False
            return
        
        try:
            system_prompt = self._build_system_prompt(use_recipes_doc)
            
            # Add user message to history
            self.conversation_history.append({"role": "user", "content": user_message})
            
            # Build contents for the API call
            contents = [system_prompt]
            for msg in self.conversation_history:
                prefix = "User: " if msg["role"] == "user" else "Assistant: "
                contents.append(prefix + msg["content"])
            
            # Use streaming API
            response_stream = client.models.generate_content_stream(
                model=MODEL_ID,
                contents="\n\n".join(contents)
            )
            
            # Process streaming chunks
            for chunk in response_stream:
                if chunk.text:
                    with self._streaming_lock:
                        self._streaming_buffer += chunk.text
            
            # Finalize
            with self._streaming_lock:
                final_response = self._streaming_buffer.strip()
                self.conversation_history.append({"role": "assistant", "content": final_response})
                self._trim_history()
                self._streaming_complete = True
                self._is_streaming = False
                
        except Exception as e:
            with self._streaming_lock:
                self._streaming_error = f"❌ Error generating response: {str(e)}"
                self._streaming_complete = True
                self._is_streaming = False
    
    def get_streaming_state(self) -> Tuple[str, bool, Optional[str]]:
        """
        Get the current streaming state.
        
        Returns:
            Tuple of (current_text, is_complete, error_message)
        """
        with self._streaming_lock:
            return (
                self._streaming_buffer,
                self._streaming_complete,
                self._streaming_error
            )
    
    def is_streaming(self) -> bool:
        """Check if currently streaming."""
        with self._streaming_lock:
            return self._is_streaming

