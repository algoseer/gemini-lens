# 🧊 Fridge Health Dashboard

A smart dashboard that tracks the freshness of your refrigerated items. Upload a grocery receipt, and the app uses Google's Gemini AI to:
1. Parse the receipt and extract refrigerated items
2. Estimate shelf life for each item
3. Display a color-coded dashboard showing item freshness

## Features

- **📷 Receipt Scanning**: Upload a photo of your grocery receipt
- **🤖 AI-Powered Parsing**: Gemini extracts item names and normalizes them
- **⏱️ Shelf Life Estimation**: Automatic shelf life lookup for each item
- **🎨 Visual Dashboard**: Color-coded cards (🟢 Fresh, 🟡 Use Soon, 🔴 Expired)
- **📊 Statistics**: Quick overview of your fridge contents
- **🗑️ Easy Management**: Delete items with one click

## Quick Start

### 1. Get a Google API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Click "Create API Key"
3. Copy the key

### 2. Set up environment

```bash
# Copy the example file and add your API key
cp .env.example .env
echo 'GOOGLE_API_KEY=your-actual-api-key' > .env
```

### 3. Run with Docker Compose

```bash
docker-compose up -d
```

### 4. Open the Dashboard

Visit: **http://localhost:8050**

## Project Structure

```
gemini-lens/
├── fridge_dashboard/           # Main application
│   ├── __init__.py
│   ├── dash_app.py             # Dash web application
│   ├── gemini_service.py       # Gemini API integration
│   ├── database.py             # SQLite operations
│   ├── models.py               # Data models
│   └── assets/
│       └── styles.css          # Dashboard styling
├── .env                        # Your API key (create from .env.example)
├── .env.example                # Template for environment variables
├── docker-compose.yml          # Docker Compose configuration
├── Dockerfile
├── fridge.db                   # SQLite database (auto-created)
├── requirements.txt
└── README.md
```

## How It Works

1. **Upload Receipt**: Take a photo of your grocery receipt and upload it
2. **AI Processing**: 
   - Gemini analyzes the receipt image
   - Extracts food items that need refrigeration
   - Looks up typical shelf life for each item
3. **Database Storage**: Items are stored in SQLite with purchase date
4. **Freshness Calculation**: 
   ```
   freshness = (shelf_life - days_since_purchase) / shelf_life × 100%
   ```
5. **Dashboard Display**: Items shown as color-coded cards

## Freshness Levels

| Level | Percentage | Color | Meaning |
|-------|------------|-------|---------|
| Fresh | ≥ 60% | 🟢 Green | Good to use |
| Use Soon | 30-59% | 🟡 Yellow | Use within a few days |
| Expired | < 30% | 🔴 Red | May be spoiled |

## Running Without Docker

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python -m fridge_dashboard.dash_app
```

## Archive

The original Streamlit image analysis app is preserved in the `archive/streamlit-image-analysis` branch.

## Technologies

- **Frontend**: Dash (Plotly), Dash Bootstrap Components
- **Backend**: Python, SQLite
- **AI**: Google Gemini 1.5 Flash
- **Container**: Docker

## License

MIT
