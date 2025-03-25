import sys
import os

import webbrowser
from dash import Dash
import dash_bootstrap_components as dbc

from app.database_utils import load_decision_tree_data
from app.layout import create_app_layout
from app.callbacks import register_callbacks
from app.hand_chart import create_hand_chart

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def create_tree_explorer_app(db_path):
    """
    Create a game tree explorer with interactive visualization
    
    Args:
        db_path (str): Path to the SQLite database
        
    Returns:
        dash.Dash: A Dash application
    """
    app = Dash(__name__, 
               external_stylesheets=[dbc.themes.BOOTSTRAP],
               suppress_callback_exceptions=True)
    
    # Set application layout
    app.layout = create_app_layout()
    
    # Register all callbacks
    register_callbacks(app, db_path)
    
    return app

def main():
    """Application entry point"""
    import webbrowser
    
    db_path = "poker_analysis_optimized.db"
    app = create_tree_explorer_app(db_path)
    
    # Print a clearer message
    print("\n")
    print("=" * 60)
    print("Poker Game Tree Explorer is running!")
    print("Open your web browser and go to: http://127.0.0.1:8050/")
    print("=" * 60)
    print("\n")
    
    # Automatically open the browser after a short delay
    webbrowser.open('http://127.0.0.1:8050/', new=1, autoraise=True)
    
    # Run the app
    app.run(debug=True)

if __name__ == "__main__":
    main()