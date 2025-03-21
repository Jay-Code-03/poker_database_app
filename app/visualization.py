import plotly.express as px
import html
from dash import dcc, html as dash_html
import dash_bootstrap_components as dbc

def create_action_chart(node, exclude_hero=True):
    """
    Create a chart and table showing action distributions with improved efficiency
    
    Args:
        node (dict): The node to create a chart for
        exclude_hero (bool): Whether to exclude hero's actions
        
    Returns:
        dash.html.Div: A Dash component with the chart and table
    """
    if 'actions' not in node or not node['actions']:
        return dash_html.Div("No action data available")
    
    # Extract action data
    # Determine which percentages to use
    percentages_key = 'action_percentages_non_hero' if exclude_hero else 'action_percentages_total'
    
    if percentages_key not in node or not node[percentages_key]:
        return dash_html.Div("No action data available for the selected filter")
    
    # OPTIMIZATION: Calculate non-hero action counts more efficiently
    if exclude_hero and 'hero_actions' in node:
        display_counts = {
            action: max(0, node['actions'].get(action, 0) - node['hero_actions'].get(action, 0))
            for action in node['actions']
        }
    else:
        display_counts = node['actions']
    
    # OPTIMIZATION: Filter out zero counts and sort in one step
    sorted_actions = [(action, count) for action, count in display_counts.items() if count > 0]
    sorted_actions.sort(key=lambda x: x[1], reverse=True)
    
    # Extract data for chart
    actions = []
    counts = []
    percentages = []
    
    for action, count in sorted_actions:
        actions.append(action)
        counts.append(count)
        percentage = node.get(percentages_key, {}).get(action, 0)
        percentages.append(percentage)
    
    if not actions:  # No data after filtering
        return dash_html.Div("No action data available for the selected filter")
    
    # Create a more efficient bar chart
    fig = px.bar(
        x=actions,
        y=counts,
        text=[f"{p:.1f}%" for p in percentages],
        labels={'x': 'Action Type', 'y': 'Count'},
        color=counts,
        color_continuous_scale='Viridis'
    )
    
    # OPTIMIZATION: Simplified layout with fewer properties
    fig.update_traces(texttemplate='%{text}', textposition='outside')
    fig.update_layout(
        uniformtext_minsize=10,
        uniformtext_mode='hide',
        height=300,
        margin=dict(t=10, l=50, r=10, b=50)
    )
    
    # Create a table with the same data - more efficient row creation
    table_header = [
        dash_html.Thead(dash_html.Tr([
            dash_html.Th("Action"),
            dash_html.Th("Count"),
            dash_html.Th("Percentage")
        ]))
    ]
    
    # OPTIMIZATION: Use list comprehension instead of append in a loop
    table_rows = [
        dash_html.Tr([
            dash_html.Td(action),
            dash_html.Td(count),
            dash_html.Td(f"{percentage:.1f}%")
        ])
        for action, count, percentage in zip(actions, counts, percentages)
    ]
    
    table_body = [dash_html.Tbody(table_rows)]
    table = dbc.Table(table_header + table_body, bordered=True, striped=True, hover=True, size="sm")
    
    # Add a note about what's being displayed
    count_type = "opponent" if exclude_hero else "all"
    total_count = node.get('non_hero_action_count', 0) if exclude_hero else node.get('total_action_count', 0)
    note = dash_html.Div([
        dash_html.Span(f"Showing {count_type} actions only. ", className="text-muted"),
        dash_html.Span(f"Total {count_type} actions: {total_count}", className="text-muted")
    ], className="mb-2")
    
    return dash_html.Div([
        note,
        dcc.Graph(figure=fig, config={'displayModeBar': False}),
        dash_html.Div(table, style={"maxHeight": "250px", "overflowY": "auto"})
    ])

def build_tree_elements(tree_data, start_node_data, start_node_id, max_depth=2, exclude_hero=True):
    """
    Build tree elements using a simple numeric ID approach with reduced initial depth
    
    Args:
        tree_data (dict): The decision tree data
        start_node_data (dict): The data for the starting node
        start_node_id (str): The ID of the starting node
        max_depth (int): Maximum depth to build the tree
        exclude_hero (bool): Whether to exclude hero's actions
        
    Returns:
        tuple: (nodes, edges, id_map) - List of nodes, list of edges, and mapping from original IDs to simple IDs
    """
    nodes = []
    edges = []
    id_map = {}  # Maps original IDs to simple numeric IDs
    
    # Queue for BFS traversal
    queue = [(start_node_data, start_node_id, 0, None)]
    next_id = 1  # Start from 1 for simplicity
    
    while queue:
        current_data, original_id, depth, parent_simple_id = queue.pop(0)
        
        if depth > max_depth:
            continue
        
        # Create simple numeric ID
        simple_id = f"n{next_id}"
        id_map[original_id] = simple_id
        next_id += 1
        
        # Determine node type
        if any(pos in original_id for pos in ['SB', 'BB', 'BTN']):
            node_type = 'position'
        elif any(action in original_id for action in ['raise', 'bet', 'call', 'fold', 'check', 'all_in']):
            node_type = 'action'
        else:
            node_type = 'street'
        
        # Get display label
        if '-' in original_id:
            label = original_id.split('-')[-1]
        else:
            label = current_data.get('name', original_id)
        
        # Check node flags
        is_synthetic = current_data.get('is_synthetic', False)
        is_terminal = current_data.get('is_terminal', False) or 'fold' in original_id or (
            'call' in original_id and current_data.get('facing_all_in', False)
        )
        
        # Get the appropriate count based on hero exclusion preference
        if exclude_hero:
            node_count = current_data.get('non_hero_count', 0)
        else:
            node_count = current_data.get('total_count', 0)
        
        # Create node
        node = {
            'data': {
                'id': simple_id,
                'original_id': original_id,
                'label': label,
                'type': node_type,
                'depth': depth,
                'count': node_count,
                'synthetic': is_synthetic,
                'terminal': is_terminal
            },
            'classes': f"depth-{depth} {node_type}" + 
                     (' synthetic' if is_synthetic else '') +
                     (' terminal' if is_terminal else '')
        }
        
        nodes.append(node)
        
        # Create edge if not root
        if parent_simple_id is not None:
            edge = {
                'data': {
                    'id': f"e{next_id}",
                    'source': parent_simple_id,
                    'target': simple_id,
                    'count': node_count,
                    'synthetic': is_synthetic
                },
                'classes': ('synthetic' if is_synthetic else '')
            }
            edges.append(edge)
            next_id += 1
        
        # Process children if not a terminal node
        if 'children' in current_data and not is_terminal and depth < max_depth:
            # Sort children by appropriate frequency
            if exclude_hero:
                sorted_children = sorted(
                    current_data['children'].items(),
                    key=lambda x: x[1].get('non_hero_count', 0) if not x[1].get('is_synthetic', False) else -1,
                    reverse=True
                )
            else:
                sorted_children = sorted(
                    current_data['children'].items(),
                    key=lambda x: x[1].get('total_count', 0) if not x[1].get('is_synthetic', False) else -1,
                    reverse=True
                )
            
            # OPTIMIZATION: Limit number of visible children for better performance
            max_visible_children = 10 if depth < 2 else 5
            for idx, (child_name, child_data) in enumerate(sorted_children):
                if idx >= max_visible_children:
                    break
                    
                child_original_id = f"{original_id}-{child_name}"
                queue.append((child_data, child_original_id, depth + 1, simple_id))
    
    return nodes, edges, id_map