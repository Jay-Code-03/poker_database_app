import plotly.graph_objects as go
from dash import html, dcc
import dash_bootstrap_components as dbc
import numpy as np
from app.card_utils import get_all_hand_categories, generate_hand_grid_positions

def create_hand_chart(node, exclude_hero=True):
    """
    Create a hand chart visualization for the specified node with correct poker ordering
    
    Args:
        node (dict): The node to create a chart for
        exclude_hero (bool): Whether to exclude hero's hands
        
    Returns:
        dash.html.Div: A Dash component with the chart
    """
    if node is None:
        return html.Div("No node selected")
    
    # Get the appropriate hole card dictionary
    if exclude_hero:
        hole_cards = node.get('hole_cards', {})
    else:
        # Combine both hero and opponent hands
        hole_cards = node.get('hole_cards', {}).copy()
        hero_hole_cards = node.get('hero_hole_cards', {})
        for category, count in hero_hole_cards.items():
            if category in hole_cards:
                hole_cards[category] += count
            else:
                hole_cards[category] = count
    
    # Use dictionary comprehension to filter out Unknown hands
    hole_cards = {k: v for k, v in hole_cards.items() if k != "Unknown"}
    
    # Also filter out any hands that might be None or contain None
    hole_cards = {k: v for k, v in hole_cards.items() if k and 'None' not in k}

    # If no hole cards data, return message
    if not hole_cards:
        return html.Div("No hole cards data available for this node")
    
    # Get total count for calculating percentages
    total_hands = sum(hole_cards.values())
    
    # Define ranks in CORRECT poker order (highest to lowest)
    ranks = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']
    n_ranks = len(ranks)
    
    # Get positions for each hand category
    positions = generate_hand_grid_positions()
    
    # Initialize the matrix with zeros
    matrix = np.zeros((n_ranks, n_ranks))
    annotations = []
    
    # Create a debug counter to make sure we're filling all cells
    filled_cells = 0
    
    # Fill the matrix with frequency percentages
    for category, count in hole_cards.items():
        if category in positions:
            i, j = positions[category]
            percentage = (count / total_hands) * 100
            matrix[i, j] = percentage
            filled_cells += 1
    
    print(f"Filled {filled_cells} cells out of {n_ranks*n_ranks} possible cells")
    
    # IMPORTANT: Create hand labels for ALL cells regardless of data
    text_matrix = []
    for i in range(n_ranks):
        row = []
        for j in range(n_ranks):
            # Get the hand type for this position
            if i == j:
                # Diagonal - pairs
                hand = f"{ranks[i]}{ranks[i]}"
            elif i < j:
                # Suited hands
                hand = f"{ranks[i]}{ranks[j]}s"
            else:
                # Offsuit hands
                hand = f"{ranks[j]}{ranks[i]}o"
            
            percentage = matrix[i][j]
            if percentage > 0:
                row.append(f"{hand}: {percentage:.2f}%")
            else:
                row.append(f"{hand}")  # Still show hand even with 0%
        text_matrix.append(row)
    
    # Create the heatmap 
    fig = go.Figure(data=go.Heatmap(
        z=matrix,
        x=ranks,
        y=ranks,
        colorscale='Viridis',
        showscale=True,
        text=text_matrix,
        hoverinfo='text',
        colorbar=dict(
            title=dict(
                text="Frequency %",
                side="right"
            )
        )
    ))
    
    # Update layout with BOTH axes properly configured
    fig.update_layout(
        title=f"Hand Distribution ({total_hands} hands)",
        #xaxis_title="Second Card Rank",
        #yaxis_title="First Card Rank",
        height=600,  # Increased height for better visibility
        margin=dict(l=50, r=50, t=50, b=50),
        xaxis=dict(
            tickvals=list(range(n_ranks)),
            #ticktext=ranks,
            categoryorder='array',
            categoryarray=ranks
        ),
        yaxis=dict(
            tickvals=list(range(n_ranks)),
            #ticktext=ranks,
            categoryorder='array',
            categoryarray=ranks,
            autorange="reversed"  # This ensures A is at the top
        )
    )
    
    # Create the summary table with the top 10 most frequent hands
    sorted_hands = sorted([(cat, count, (count/total_hands)*100) 
                          for cat, count in hole_cards.items()], 
                         key=lambda x: x[1], reverse=True)
    
    top_hands = sorted_hands[:10]
    
    table_header = [
        html.Thead(html.Tr([
            html.Th("Hand"), 
            html.Th("Count"), 
            html.Th("Percentage")
        ]))
    ]
    
    table_rows = [
        html.Tr([
            html.Td(hand),
            html.Td(f"{count}"),
            html.Td(f"{percentage:.1f}%")
        ])
        for hand, count, percentage in top_hands
    ]
    
    table_body = [html.Tbody(table_rows)]
    
    # Return the complete component
    return html.Div([
        html.H5("Hand Range Distribution"),
        html.P(f"Total hands: {total_hands}", className="text-muted"),
        dcc.Graph(figure=fig),
        html.H6("Top 10 Most Frequent Hands"),
        dbc.Table(table_header + table_body, bordered=True, striped=True, size="sm")
    ])