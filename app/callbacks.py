import json
import traceback
from dash import Input, Output, State, callback_context, no_update, ALL
from dash.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from dash import html

from app.tree_analysis import get_node_by_path, get_next_numeric_id, _tree_data_cache
from app.visualization import create_action_chart, build_tree_elements
from app.hand_chart import create_hand_chart

def register_callbacks(app, db_path):
    """
    Register all callbacks for the Dash application
    
    Args:
        app: The Dash application
        db_path (str): Path to the SQLite database
    """
    from app.database_utils import load_decision_tree_data
    
    # Callback to update stack slider output
    @app.callback(
        Output('stack-slider-output', 'children'),
        Input('stack-slider', 'value')
    )
    def update_stack_output(value):
        return f"Stack range: {value[0]} BB to {value[1]} BB"
    
    # Store hero exclusion preference
    @app.callback(
        Output('exclude-hero-store', 'data'),
        Input('exclude-hero-switch', 'value')
    )
    def update_hero_exclusion(exclude_hero):
        return exclude_hero
    
    # Callback to load decision tree data
    @app.callback(
        [Output('decision-tree-data', 'data'),
         Output('loading-message-container', 'children'),
         Output('main-content-container', 'style'),
         Output('debug-info', 'children')],
        Input('apply-filters-button', 'n_clicks'),
        [State('stack-slider', 'value'),
         State('game-type-dropdown', 'value'),
         State('exclude-hero-switch', 'value')],
        prevent_initial_call=True
    )
    def load_data(n_clicks, stack_range, game_type, exclude_hero):
        if n_clicks is None:
            return None, html.H3("Select parameters and click Apply Filters"), {"display": "none"}, ""
        
        stack_min, stack_max = stack_range
        debug_info = f"Loading data with stack range {stack_min}-{stack_max}, game type: {game_type}, exclude hero: {exclude_hero}\n"
        
        try:
            # Show loading message
            loading_message = html.Div([
                html.H3("Loading data..."),
                dbc.Spinner(color="primary", type="grow")
            ])
            
            # OPTIMIZATION: Increase max_games for better statistics but cap for performance
            max_games = 1000000
            
            # Load decision tree data with hero exclusion preference
            tree_data = load_decision_tree_data(
                db_path, 
                stack_min=stack_min,
                stack_max=stack_max,
                game_type=game_type,
                max_games=max_games,
                exclude_hero=exclude_hero
            )
            
            if 'error' in tree_data:
                debug_info += f"Error: {tree_data['error']}"
                return (
                    tree_data, 
                    html.H3(f"Error: {tree_data['error']}"), 
                    {"display": "none"},
                    debug_info
                )
            
            # Store tree in global cache with ID as key
            global _tree_data_cache
            tree_data_id = id(tree_data)
            _tree_data_cache[tree_data_id] = tree_data
            
            game_count = tree_data.get('game_count', 0)
            success_message = html.H3(f"Data loaded successfully! Analyzed {game_count} games")
            
            debug_info += f"Successfully loaded {game_count} games"
            
            return tree_data, success_message, {"display": "block"}, debug_info
            
        except Exception as e:
            error_trace = traceback.format_exc()
            debug_info += f"Exception: {str(e)}\n\n{error_trace}"
            return {"error": str(e)}, html.H3(f"Error: {str(e)}"), {"display": "none"}, debug_info
    
    # Callback to update the tree visualization based on selected street
    @app.callback(
        [Output('cytoscape-container', 'style'),
         Output('cytoscape-tree', 'elements'),
         Output('current-node-path', 'data', allow_duplicate=True),
         Output('id-mapping', 'data')],
        [Input('street-selector', 'value'),
         Input('decision-tree-data', 'data'),
         Input('exclude-hero-store', 'data')],
        prevent_initial_call=True
    )
    def update_tree_visualization(street, tree_data, exclude_hero):
        if tree_data is None or 'error' in tree_data:
            return {"display": "none"}, [], no_update, {}
        
        # Navigate to the selected street
        if street and 'children' in tree_data and street in tree_data['children']:
            street_node = tree_data['children'][street]
            
            # For heads-up poker, look for first position based on street
            if street == 'preflop':
                positions = [pos for pos in street_node.get('children', {}).keys() 
                           if 'SB' in pos or 'BTN' in pos]
            else:
                positions = [pos for pos in street_node.get('children', {}).keys() 
                           if 'BB' in pos]
                
            default_position = positions[0] if positions else None
            
            if default_position:
                # If we have a position, show it as the starting point
                position_node = street_node['children'][default_position]
                
                # Set initial path
                initial_path = ["root", street, default_position]
                
                # Create graph elements starting from position node
                position_orig_id = f"{street}-{default_position}"
                nodes, edges, id_map = build_tree_elements(
                    tree_data, 
                    position_node, 
                    position_orig_id, 
                    max_depth=2,
                    exclude_hero=exclude_hero
                )
                
                # Create and add street node
                street_node_id = "street_" + street
                
                # Get the appropriate count based on hero exclusion preference
                if exclude_hero:
                    node_count = street_node.get('non_hero_count', 0)
                else:
                    node_count = street_node.get('total_count', 0)
                
                street_node_element = {
                    'data': {
                        'id': street_node_id,
                        'original_id': street,
                        'label': street,
                        'type': 'street',
                        'depth': 0,
                        'count': node_count
                    },
                    'classes': 'depth-0 street'
                }
                nodes.append(street_node_element)
                
                # Add mapping for street
                id_map[street] = street_node_id
                
                # Create edge from street to position
                first_position_id = id_map.get(position_orig_id)
                if first_position_id:
                    street_edge = {
                        'data': {
                            'id': f"e_street_pos",
                            'source': street_node_id,
                            'target': first_position_id,
                            'count': position_node.get('non_hero_count' if exclude_hero else 'total_count', 0)
                        }
                    }
                    edges.append(street_edge)
                
                # Combine nodes and edges
                elements = nodes + edges
                
                return {"display": "block"}, elements, initial_path, id_map
            else:
                # Just show the street level
                initial_path = ["root", street]
                
                # Build elements for street node
                nodes, edges, id_map = build_tree_elements(
                    tree_data,
                    street_node,
                    street,
                    max_depth=2,
                    exclude_hero=exclude_hero
                )
                
                elements = nodes + edges
                return {"display": "block"}, elements, initial_path, id_map
            
        return {"display": "none"}, [], no_update, {}
    
    # Callback to update breadcrumbs and show available options
    @app.callback(
        Output('path-breadcrumbs', 'children'),
        [Input('current-node-path', 'data'),
         Input('decision-tree-data', 'data'),
         Input('exclude-hero-store', 'data')]
    )
    def update_breadcrumbs(current_path, tree_data, exclude_hero):
        if not current_path or tree_data is None:
            return html.Div("No path selected")
        
        breadcrumbs = []
        
        # For each step in the path
        for i, step in enumerate(current_path):
            # Add separator except for first item
            if i > 0:
                breadcrumbs.append(html.Span(" > ", className="mx-1"))
            
            # Create button for each step
            btn_class = "btn-primary" if i == len(current_path) - 1 else "btn-outline-primary"
            
            # Extract readable label from path step
            if '-' in step:
                # For composite IDs, show only the last part
                label = step.split('-')[-1]
            else:
                label = step
            
            # Get node at this path
            node_path = current_path[:i+1]
            node = get_node_by_path(tree_data, node_path)
            
            # If node has children, create a dropdown button
            if node and 'children' in node and node['children']:
                # Create dropdown button with available options
                dropdown_items = []
                
                # Sort children by frequency (highest first) based on hero exclusion preference
                if exclude_hero:
                    sorted_children = sorted(
                        node['children'].items(),
                        key=lambda x: x[1].get('non_hero_count', 0) if not x[1].get('is_synthetic', False) else -1,
                        reverse=True
                    )
                else:
                    sorted_children = sorted(
                        node['children'].items(),
                        key=lambda x: x[1].get('total_count', 0) if not x[1].get('is_synthetic', False) else -1,
                        reverse=True
                    )
                
                # OPTIMIZATION: Limit number of options in dropdown for performance
                max_dropdown_items = 15
                for child_idx, (child_name, child_data) in enumerate(sorted_children):
                    if child_idx >= max_dropdown_items:
                        break
                        
                    # Get appropriate count based on hero exclusion
                    if exclude_hero:
                        count = child_data.get('non_hero_count', 0)
                        total = node.get('non_hero_count', 0)
                    else:
                        count = child_data.get('total_count', 0)
                        total = node.get('total_count', 0)
                    
                    percentage = 0
                    if total > 0:
                        percentage = (count / total) * 100
                    
                    # Create item with count and percentage
                    dropdown_items.append(
                        dbc.DropdownMenuItem(
                            f"{child_name} ({count}, {percentage:.1f}%)",
                            id={"type": "path-option", "index": i, "option": child_name},
                            className="path-option-item"
                        )
                    )
                
                # Add a "more options" item if there are more children
                if len(sorted_children) > max_dropdown_items:
                    dropdown_items.append(
                        dbc.DropdownMenuItem(
                            f"...{len(sorted_children) - max_dropdown_items} more options",
                            disabled=True
                        )
                    )
                
                breadcrumbs.append(
                    dbc.DropdownMenu(
                        label=label,
                        children=dropdown_items,
                        color=btn_class.replace("btn-", ""),
                        className="mx-1",
                        size="sm"
                    )
                )
            else:
                # Simple button for nodes without children
                breadcrumbs.append(
                    dbc.Button(
                        label,
                        id={"type": "breadcrumb-btn", "index": i},
                        className=f"btn-sm {btn_class} mx-1",
                        size="sm"
                    )
                )
        
        return html.Div(breadcrumbs, className="d-flex align-items-center flex-wrap")
    
    # Callback to navigate using breadcrumbs
    @app.callback(
        [Output('current-node-path', 'data', allow_duplicate=True),
         Output('cytoscape-tree', 'elements', allow_duplicate=True),
         Output('id-mapping', 'data', allow_duplicate=True)],
        [Input({"type": "breadcrumb-btn", "index": ALL}, 'n_clicks'),
         Input({"type": "path-option", "index": ALL, "option": ALL}, 'n_clicks')],
        [State('current-node-path', 'data'),
         State('decision-tree-data', 'data'),
         State('exclude-hero-store', 'data')],
        prevent_initial_call=True
    )
    def navigate_breadcrumb(breadcrumb_clicks, option_clicks, current_path, tree_data, exclude_hero):
        if (not breadcrumb_clicks or not any(n for n in breadcrumb_clicks)) and \
           (not option_clicks or not any(n for n in option_clicks)) or tree_data is None:
            return no_update, no_update, no_update
        
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update, no_update
        
        # Get which button was clicked
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
        button_data = json.loads(button_id)
        
        if button_data.get('type') == 'breadcrumb-btn':
            # Regular breadcrumb click - navigate to that level
            breadcrumb_index = button_data['index']
            
            # Truncate path to the selected breadcrumb
            new_path = current_path[:breadcrumb_index + 1]
        elif button_data.get('type') == 'path-option':
            # Option selected from dropdown
            path_index = button_data['index']
            option = button_data['option']
            
            # Truncate path to the parent level then add the selected option
            new_path = current_path[:path_index + 1]
            new_path.append(option)
        else:
            return no_update, no_update, no_update
        
        # Get the node at this path
        node = get_node_by_path(tree_data, new_path)
        
        if node is None:
            return no_update, no_update, no_update
        
        # Create an original ID for the node
        if len(new_path) > 1:  # Not root
            original_id = "-".join(new_path[1:])  # Skip "root"
        else:
            original_id = new_path[0]  # Just "root"
        
        # Generate visualization for this node
        nodes, edges, id_map = build_tree_elements(
            tree_data,
            node,
            original_id,
            max_depth=2,
            exclude_hero=exclude_hero
        )
        
        elements = nodes + edges
        
        return new_path, elements, id_map
    
    # Callback to handle node selection in the tree
    @app.callback(
        [Output('current-node-path', 'data', allow_duplicate=True),
         Output('current-node-details', 'data'),
         Output('node-details-title', 'children'),
         Output('node-details-content', 'children'),
         Output('node-actions-chart', 'children'),
         Output('available-decisions', 'children'),
         Output('node-hand-chart', 'children')],
        Input('cytoscape-tree', 'tapNodeData'),
        [State('decision-tree-data', 'data'),
         State('current-node-path', 'data'),
         State('id-mapping', 'data'),
         State('exclude-hero-store', 'data')],
        prevent_initial_call=True
    )
    def handle_node_tap(node_data, tree_data, current_path, id_mapping, exclude_hero):
        if not node_data or tree_data is None or 'error' in tree_data:
            return no_update, None, "Node Details", html.P("No node selected"), html.Div(), html.P("No node selected")
        
        # Get the original ID of the node
        original_id = node_data.get('original_id')
        if not original_id:
            return no_update, None, "Node Details", html.P("Invalid node selection"), html.Div(), html.P("Invalid node selection")
        
        # Build path based on original_id
        if '-' in original_id:
            path_parts = original_id.split('-')
            # If it's a child of a street, add root
            if len(path_parts) == 2 and path_parts[0] in ['preflop', 'flop', 'turn', 'river']:
                new_path = ['root'] + path_parts
            # Otherwise, assume correct structure
            else:
                new_path = ['root'] + path_parts
        else:
            # This is a street or root node
            if original_id in ['preflop', 'flop', 'turn', 'river']:
                new_path = ['root', original_id]
            else:
                new_path = [original_id]
        
        # Get the node data from the tree
        selected_node = get_node_by_path(tree_data, new_path)
        
        if selected_node is None:
            return no_update, None, "Node Details", html.P(f"Node not found in tree for path: {new_path}"), html.Div(), html.P("Node not found")
        
        # Extract node details
        node_name = node_data.get('label', 'Unknown')
        
        # Get appropriate count based on hero exclusion preference
        if exclude_hero:
            node_count = selected_node.get('non_hero_count', 0)
            count_type = "opponent"
        else:
            node_count = selected_node.get('total_count', 0)
            count_type = "total"
            
        node_type = node_data.get('type', 'unknown')
        is_synthetic = node_data.get('synthetic', False)
        is_terminal = node_data.get('terminal', False)
        
        # Create node details display
        details_title = f"Node: {node_name}"
        
        # Node status badges
        status_badges = []
        if is_synthetic:
            status_badges.append(html.Span("SYNTHETIC", className="badge bg-secondary me-2"))
        if is_terminal:
            status_badges.append(html.Span("TERMINAL", className="badge bg-danger me-2"))
        if node_type:
            status_badges.append(html.Span(node_type.upper(), className="badge bg-info me-2"))
            
        # Add hero exclusion badge
        if exclude_hero:
            status_badges.append(html.Span("HERO EXCLUDED", className="badge bg-warning me-2"))
            
        details_content = [
            html.P(status_badges) if status_badges else None,
            html.P(f"{count_type.capitalize()} hands: {node_count}"),
            html.P(f"Path: {' → '.join([p.split('-')[-1] if '-' in p else p for p in new_path])}"),
            html.P(f"Node Type: {node_type}")
        ]
        
        # Special message for synthetic nodes
        if is_synthetic:
            details_content.append(html.Div([
                html.P("This is a synthetic node added to complete the decision tree."),
                html.P("No actual hands in the database follow this exact path.")
            ], className="alert alert-warning"))
            
        # If the node has children, show them
        if 'children' in selected_node and selected_node['children']:
            # OPTIMIZATION: Limit number of child items shown
            max_child_items = 10
            child_items = []
            
            # Sort children by appropriate frequency
            if exclude_hero:
                sorted_children = sorted(
                    selected_node['children'].items(),
                    key=lambda x: x[1].get('non_hero_count', 0) if not x[1].get('is_synthetic', False) else -1,
                    reverse=True
                )
            else:
                sorted_children = sorted(
                    selected_node['children'].items(),
                    key=lambda x: x[1].get('total_count', 0) if not x[1].get('is_synthetic', False) else -1,
                    reverse=True
                )
                
            for idx, (child_name, child_data) in enumerate(sorted_children):
                if idx >= max_child_items:
                    child_items.append(html.Li(f"...{len(sorted_children) - max_child_items} more options"))
                    break
                    
                # Get the appropriate count
                if exclude_hero:
                    child_count = child_data.get('non_hero_count', 0)
                else:
                    child_count = child_data.get('total_count', 0)
                
                child_percentage = (child_count / node_count * 100) if node_count > 0 else 0
                child_synthetic = "SYNTHETIC" if child_data.get('is_synthetic', False) else ""
                
                child_items.append(html.Li([
                    f"{child_name}: {child_count} hands ({child_percentage:.1f}%) {child_synthetic}"
                ]))
            
            details_content.append(html.Div([
                html.H5("Child Nodes:"),
                html.Ul(child_items)
            ]))
        
        # Create action distribution chart with hero exclusion preference
        action_chart = create_action_chart(selected_node, exclude_hero)
        
        # Create available decisions panel
        available_decisions = []
        if 'children' in selected_node and selected_node['children']:
            # Sort children by appropriate frequency
            if exclude_hero:
                sorted_children = sorted(
                    selected_node['children'].items(),
                    key=lambda x: x[1].get('non_hero_count', 0) if not x[1].get('is_synthetic', False) else -1,
                    reverse=True
                )
            else:
                sorted_children = sorted(
                    selected_node['children'].items(),
                    key=lambda x: x[1].get('total_count', 0) if not x[1].get('is_synthetic', False) else -1,
                    reverse=True
                )
                
            # OPTIMIZATION: Limit number of decision buttons for performance
            max_decisions = 10
            for idx, (child_name, child_data) in enumerate(sorted_children):
                if idx >= max_decisions:
                    available_decisions.append(html.P(f"...and {len(sorted_children) - max_decisions} more options", 
                                                     className="text-muted"))
                    break
                    
                # Get appropriate count
                if exclude_hero:
                    count = child_data.get('non_hero_count', 0)
                else:
                    count = child_data.get('total_count', 0)
                    
                percentage = (count / node_count * 100) if node_count > 0 else 0
                is_child_synthetic = child_data.get('is_synthetic', False)
                
                # Determine button color based on action type
                btn_color = "secondary"
                if 'fold' in child_name:
                    btn_color = "danger"
                elif 'call' in child_name:
                    btn_color = "success"
                elif 'raise' in child_name or 'bet' in child_name:
                    btn_color = "warning"
                elif 'check' in child_name:
                    btn_color = "info"
                elif 'all_in' in child_name:
                    btn_color = "dark"
                
                # Create button for each option
                option_button = dbc.Button(
                    [
                        f"{child_name}: {percentage:.1f}%",
                        html.Span(f" ({count})", style={"fontSize": "0.8em", "opacity": "0.8"})
                    ],
                    id={"type": "decision-option", "option": child_name},
                    color=btn_color,
                    outline=is_child_synthetic,
                    className="mb-2 me-2",
                    style={"opacity": "0.7" if is_child_synthetic else "1"}
                )
                
                available_decisions.append(option_button)
        
        if not available_decisions:
            available_decisions = [html.P("No further decisions available (terminal node)")]
        
        # Add the hand chart creation
        hand_chart = create_hand_chart(selected_node, exclude_hero)
        
        return new_path, selected_node, details_title, details_content, action_chart, available_decisions, hand_chart
    
    # Callback to handle decision option selection
    @app.callback(
        [Output('current-node-path', 'data', allow_duplicate=True),
         Output('cytoscape-tree', 'elements', allow_duplicate=True),
         Output('id-mapping', 'data', allow_duplicate=True)],
        Input({"type": "decision-option", "option": ALL}, 'n_clicks'),
        [State('current-node-path', 'data'),
         State('decision-tree-data', 'data'),
         State('exclude-hero-store', 'data')],
        prevent_initial_call=True
    )
    def handle_decision_selection(option_clicks, current_path, tree_data, exclude_hero):
        if not option_clicks or not any(n for n in option_clicks) or tree_data is None:
            return no_update, no_update, no_update
        
        ctx = callback_context
        if not ctx.triggered:
            return no_update, no_update, no_update
        
        # Get which option was clicked
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
        button_data = json.loads(button_id)
        selected_option = button_data['option']
        
        # Add selected option to path
        new_path = current_path + [selected_option]
        
        # Get the node at this path
        node = get_node_by_path(tree_data, new_path)
        
        if node is None:
            return no_update, no_update, no_update
        
        # Create an original ID for the node
        if len(new_path) > 1:  # Not root
            original_id = "-".join(new_path[1:])  # Skip "root"
        else:
            original_id = new_path[0]  # Just "root"
        
        # Generate visualization for this node
        nodes, edges, id_map = build_tree_elements(
            tree_data,
            node,
            original_id,
            max_depth=2,
            exclude_hero=exclude_hero
        )
        
        elements = nodes + edges
        
        return new_path, elements, id_map
    
    # OPTIMIZATION: Improved expand node to only add new nodes
    @app.callback(
        [Output('cytoscape-tree', 'elements', allow_duplicate=True),
         Output('id-mapping', 'data', allow_duplicate=True)],
        Input('cytoscape-tree', 'tapNodeData'),
        [State('cytoscape-tree', 'elements'),
         State('decision-tree-data', 'data'),
         State('id-mapping', 'data'),
         State('exclude-hero-store', 'data')],
        prevent_initial_call=True
    )
    def expand_node(node_data, current_elements, tree_data, id_mapping, exclude_hero):
        if not node_data or tree_data is None or 'error' in tree_data:
            return no_update, no_update
        
        # Get original ID and check if already expanded
        original_id = node_data.get('original_id')
        node_id = node_data.get('id')
        is_terminal = node_data.get('terminal', False)
        
        # Don't expand terminal nodes
        if is_terminal:
            return no_update, no_update
            
        # OPTIMIZATION: Check if already expanded more efficiently
        if any(e.get('data', {}).get('source') == node_id for e in current_elements):
            return no_update, no_update  # Already expanded
            
        # Get the node data from original_id
        if '-' in original_id:
            path_parts = original_id.split('-')
            if len(path_parts) == 2 and path_parts[0] in ['preflop', 'flop', 'turn', 'river']:
                node_path = ['root'] + path_parts
            else:
                node_path = ['root'] + path_parts
        else:
            if original_id in ['preflop', 'flop', 'turn', 'river']:
                node_path = ['root', original_id]
            else:
                node_path = [original_id]
        
        # Get the node from the tree
        selected_node = get_node_by_path(tree_data, node_path)
        
        if selected_node is None or 'children' not in selected_node or not selected_node['children']:
            return no_update, no_update
        
        # Create only new child nodes and edges
        new_elements = []
        new_id_mapping = id_mapping.copy()
        
        # Get next available ID
        next_id = get_next_numeric_id(current_elements)
        
        # Sort children by frequency
        if exclude_hero:
            sorted_children = sorted(
                selected_node['children'].items(),
                key=lambda x: x[1].get('non_hero_count', 0) if not x[1].get('is_synthetic', False) else -1,
                reverse=True
            )
        else:
            sorted_children = sorted(
                selected_node['children'].items(),
                key=lambda x: x[1].get('total_count', 0) if not x[1].get('is_synthetic', False) else -1,
                reverse=True
            )
            
        # OPTIMIZATION: Limit number of children to expand for better performance
        max_children = 10
        for idx, (child_name, child_data) in enumerate(sorted_children):
            if idx >= max_children:
                break
                
            # Create child ID
            child_original_id = f"{original_id}-{child_name}"
            
            # Skip if this child is already in the mapping
            if child_original_id in new_id_mapping:
                continue
                
            child_simple_id = f"n{next_id}"
            next_id += 1
            
            # Store ID mapping
            new_id_mapping[child_original_id] = child_simple_id
            
            # Determine node type
            if any(pos in child_name for pos in ['SB', 'BB', 'BTN']):
                child_type = 'position'
            elif any(action in child_name for action in ['raise', 'bet', 'call', 'fold', 'check', 'all_in']):
                child_type = 'action'
            else:
                child_type = 'street'
            
            # Check special flags
            is_synthetic = child_data.get('is_synthetic', False)
            is_terminal = child_data.get('is_terminal', False) or 'fold' in child_name or (
                'call' in child_name and child_data.get('facing_all_in', False)
            )
            
            # Get the appropriate count
            if exclude_hero:
                node_count = child_data.get('non_hero_count', 0)
            else:
                node_count = child_data.get('total_count', 0)
            
            # Create child node
            child_node = {
                'data': {
                    'id': child_simple_id,
                    'original_id': child_original_id,
                    'label': child_name,
                    'type': child_type,
                    'count': node_count,
                    'synthetic': is_synthetic,
                    'terminal': is_terminal
                },
                'classes': f"{child_type}" + 
                         (' synthetic' if is_synthetic else '') +
                         (' terminal' if is_terminal else '')
            }
            
            new_elements.append(child_node)
            
            # Create edge
            edge_id = f"e{next_id}"
            next_id += 1
            
            child_edge = {
                'data': {
                    'id': edge_id,
                    'source': node_id,
                    'target': child_simple_id,
                    'count': node_count,
                    'synthetic': is_synthetic
                },
                'classes': ('synthetic' if is_synthetic else '')
            }
            
            new_elements.append(child_edge)
        
        # Only add new elements to existing ones
        if new_elements:
            updated_elements = current_elements + new_elements
            return updated_elements, new_id_mapping
        
        return no_update, no_update
    
    # Callback to handle hero exclusion toggle during analysis
    @app.callback(
        [Output('cytoscape-tree', 'elements', allow_duplicate=True),
         Output('node-actions-chart', 'children', allow_duplicate=True),
         Output('node-hand-chart', 'children', allow_duplicate=True)],
        Input('exclude-hero-switch', 'value'),
        [State('decision-tree-data', 'data'),
         State('current-node-path', 'data'),
         State('street-selector', 'value')],
        prevent_initial_call=True
    )
    def toggle_hero_exclusion(exclude_hero, tree_data, current_path, street):
        if tree_data is None or 'error' in tree_data:
            return no_update, no_update, no_update
        
        # Get the current selected node
        selected_node = get_node_by_path(tree_data, current_path)
        
        # Update the action chart with the new hero exclusion setting
        action_chart = create_action_chart(selected_node, exclude_hero) if selected_node else html.Div()
        
        # Update the hand chart
        hand_chart = create_hand_chart(selected_node, exclude_hero) if selected_node else html.Div()
        
        return no_update, action_chart, hand_chart
    
    # Callback for the reset view button
    @app.callback(
        [Output('current-node-path', 'data', allow_duplicate=True),
         Output('cytoscape-tree', 'elements', allow_duplicate=True),
         Output('id-mapping', 'data', allow_duplicate=True)],
        Input('reset-view-button', 'n_clicks'),
        [State('street-selector', 'value'),
         State('decision-tree-data', 'data'),
         State('exclude-hero-store', 'data')],
        prevent_initial_call=True
    )
    def reset_view(n_clicks, street, tree_data, exclude_hero):
        if n_clicks is None or tree_data is None:
            return no_update, no_update, no_update
        
        # Reset to the street level
        if 'children' in tree_data and street in tree_data['children']:
            street_node = tree_data['children'][street]
            
            # Look for appropriate position to show first based on street
            if street == 'preflop':
                positions = [pos for pos in street_node.get('children', {}).keys() 
                          if 'SB' in pos or 'BTN' in pos]
            else:
                positions = [pos for pos in street_node.get('children', {}).keys() 
                          if 'BB' in pos]
                
            default_position = positions[0] if positions else None
            
            if default_position:
                # If we have a position, show it as the starting point
                position_node = street_node['children'][default_position]
                
                # Set initial path
                initial_path = ["root", street, default_position]
                
                # Create elements
                position_orig_id = f"{street}-{default_position}"
                nodes, edges, id_map = build_tree_elements(
                    tree_data,
                    position_node,
                    position_orig_id,
                    max_depth=2,
                    exclude_hero=exclude_hero
                )
                
                # Add street node
                street_node_id = "street_" + street
                
                # Get appropriate count
                if exclude_hero:
                    node_count = street_node.get('non_hero_count', 0)
                else:
                    node_count = street_node.get('total_count', 0)
                    
                street_node_element = {
                    'data': {
                        'id': street_node_id,
                        'original_id': street,
                        'label': street,
                        'type': 'street',
                        'depth': 0,
                        'count': node_count
                    },
                    'classes': 'depth-0 street'
                }
                nodes.append(street_node_element)
                
                # Add mapping for street
                id_map[street] = street_node_id
                
                # Add edge from street to position
                first_position_id = id_map.get(position_orig_id)
                if first_position_id:
                    street_edge = {
                        'data': {
                            'id': f"e_street_pos",
                            'source': street_node_id,
                            'target': first_position_id,
                            'count': position_node.get('non_hero_count' if exclude_hero else 'total_count', 0)
                        }
                    }
                    edges.append(street_edge)
                
                elements = nodes + edges
                return initial_path, elements, id_map
            else:
                # Just show the street level
                initial_path = ["root", street]
                nodes, edges, id_map = build_tree_elements(
                    tree_data,
                    street_node,
                    street,
                    max_depth=2,
                    exclude_hero=exclude_hero
                )
                
                elements = nodes + edges
                return initial_path, elements, id_map
                
        return no_update, no_update, no_update
    
    # Callback for the back button
    @app.callback(
        [Output('current-node-path', 'data', allow_duplicate=True),
         Output('cytoscape-tree', 'elements', allow_duplicate=True),
         Output('id-mapping', 'data', allow_duplicate=True)],
        Input('back-button', 'n_clicks'),
        [State('current-node-path', 'data'),
         State('decision-tree-data', 'data'),
         State('exclude-hero-store', 'data')],
        prevent_initial_call=True
    )
    def go_back(n_clicks, current_path, tree_data, exclude_hero):
        if n_clicks is None or tree_data is None or len(current_path) <= 2:
            return no_update, no_update, no_update
        
        # Go back one level
        new_path = current_path[:-1]
        
        # Get the node at the new path
        parent_node = get_node_by_path(tree_data, new_path)
        
        if parent_node is None:
            return no_update, no_update, no_update
        
        # Create an original ID for the parent
        if len(new_path) > 1:  # Not root
            parent_id = "-".join(new_path[1:])  # Skip "root"
        else:
            parent_id = new_path[0]  # Just use "root"
            
        # Generate elements for parent node
        nodes, edges, id_map = build_tree_elements(
            tree_data,
            parent_node,
            parent_id,
            max_depth=2,
            exclude_hero=exclude_hero
        )
        
        elements = nodes + edges
        
        return new_path, elements, id_map
    
    # Clean up the cache periodically to prevent memory leaks
    @app.callback(
        Output('debug-info', 'children', allow_duplicate=True),
        Input('reset-view-button', 'n_clicks'),
        prevent_initial_call=True
    )
    def clean_cache(n_clicks):
        # Limit cache size by removing oldest entries if too many
        global _tree_data_cache
        if len(_tree_data_cache) > 5:
            # Keep only the 3 most recent entries
            _tree_data_cache = {k: _tree_data_cache[k] for k in list(_tree_data_cache.keys())[-3:]}
            
        # Also clear the lru_cache if it's getting too big
        from app.tree_analysis import get_node_by_path_cached
        get_node_by_path_cached.cache_clear()
        
        return f"Cache cleaned. Current size: {len(_tree_data_cache)} trees."