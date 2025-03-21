from dash import dcc, html
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto

# Load cytoscape extension
cyto.load_extra_layouts()

# Define default stylesheet for cytoscape
default_stylesheet = [
    # Base node style
    {
        'selector': 'node',
        'style': {
            'content': 'data(label)',
            'text-valign': 'center',
            'text-halign': 'center',
            'width': 'mapData(count, 0, 1000, 40, 100)',
            'height': 'mapData(count, 0, 1000, 40, 100)',
            'background-color': '#7FB3D5',
            'color': '#2C3E50',
            'font-size': '14px',
            'border-width': 2,
            'border-color': '#2471A3',
            'text-wrap': 'wrap',
            'text-max-width': '80px'
        }
    },
    # Position nodes
    {
        'selector': 'node[type = "position"]',
        'style': {
            'background-color': '#85C1E9',
            'border-color': '#3498DB',
            'border-width': 3,
            'shape': 'round-rectangle'
        }
    },
    # Standard action nodes
    {
        'selector': 'node[type = "action"]',
        'style': {
            'background-color': '#F7DC6F',
            'border-color': '#F1C40F',
            'border-width': 2,
            'shape': 'ellipse'
        }
    },
    # Specific action types
    {
        'selector': 'node[label *= "fold"]',
        'style': {
            'background-color': '#E74C3C',
            'border-color': '#C0392B'
        }
    },
    {
        'selector': 'node[label *= "raise"]',
        'style': {
            'background-color': '#F39C12',
            'border-color': '#D35400'
        }
    },
    {
        'selector': 'node[label *= "call"]',
        'style': {
            'background-color': '#2ECC71',
            'border-color': '#27AE60'
        }
    },
    {
        'selector': 'node[label *= "check"]',
        'style': {
            'background-color': '#3498DB',
            'border-color': '#2980B9'
        }
    },
    {
        'selector': 'node[label *= "all_in"]',
        'style': {
            'background-color': '#9B59B6',
            'border-color': '#8E44AD'
        }
    },
    # Terminal nodes
    {
        'selector': 'node[terminal = "true"]',
        'style': {
            'shape': 'diamond',
            'width': 'mapData(count, 0, 1000, 35, 80)',
            'height': 'mapData(count, 0, 1000, 35, 80)'
        }
    },
    # Synthetic nodes
    {
        'selector': 'node[synthetic = "true"]',
        'style': {
            'border-style': 'dashed',
            'opacity': 0.7
        }
    },
    # Selected node
    {
        'selector': ':selected',
        'style': {
            'border-color': '#C0392B',
            'border-width': 4,
            'font-weight': 'bold'
        }
    },
    # Edges
    {
        'selector': 'edge',
        'style': {
            'width': 'mapData(count, 0, 1000, 2, 8)',
            'line-color': '#95A5A6',
            'curve-style': 'bezier',
            'target-arrow-shape': 'triangle',
            'target-arrow-color': '#95A5A6',
            'opacity': 'mapData(count, 0, 1000, 0.6, 1)'
        }
    },
    # Synthetic edges
    {
        'selector': 'edge[synthetic = "true"]',
        'style': {
            'line-style': 'dashed',
            'opacity': 0.5,
            'line-color': '#BDC3C7'
        }
    },
    # Different colors for depths
    {
        'selector': '.depth-0',
        'style': {
            'background-color': '#3498DB',
            'font-size': '16px',
            'font-weight': 'bold'
        }
    },
    {
        'selector': '.depth-1',
        'style': {
            'font-size': '15px'
        }
    },
    {
        'selector': '.depth-2',
        'style': {
            'font-size': '14px'
        }
    },
    {
        'selector': '.depth-3',
        'style': {
            'font-size': '13px'
        }
    },
    {
        'selector': '.depth-4',
        'style': {
            'font-size': '12px'
        }
    }
]

def create_app_layout():
    """
    Create the layout for the Dash application
    
    Returns:
        dbc.Container: A Dash Bootstrap container with the app layout
    """
    layout = dbc.Container([
        html.H1("Poker Game Tree Explorer", className="my-4 text-center"),
        
        # Game parameters row
        dbc.Row([
            # Stack size filter
            dbc.Col([
                html.Label("Effective Stack Size (BB)"),
                dcc.RangeSlider(
                    id='stack-slider',
                    min=0,
                    max=25,
                    step=1,
                    marks={i: str(i) for i in range(0, 26, 5)},
                    value=[18, 24]  # Default range
                ),
                html.Div(id='stack-slider-output')
            ], width=5),
            
            # Game type filter
            dbc.Col([
                html.Label("Game Type"),
                dcc.Dropdown(
                    id='game-type-dropdown',
                    options=[
                        {'label': 'Heads-Up Only', 'value': 'heads_up'},
                        {'label': 'All Games', 'value': 'all'}
                    ],
                    value='heads_up'
                )
            ], width=3),
            
            # Add hero action toggle switch
            dbc.Col([
                html.Label("Action Frequency"),
                dbc.Switch(
                    id='exclude-hero-switch',
                    label="Exclude Hero Actions",
                    value=True,  # Default to excluding hero
                    className="mt-1"
                )
            ], width=2),
            
            # Apply filters button
            dbc.Col([
                html.Br(),
                dbc.Button(
                    "Apply Filters",
                    id="apply-filters-button",
                    color="primary",
                    className="mt-2"
                )
            ], width=2)
        ], className="mb-4"),
        
        # Loading message container
        html.Div(
            id="status-container",
            children=html.Div(
                id="loading-message-container", 
                children=html.H3("Select parameters and click Apply Filters"),
                style={"textAlign": "center", "marginTop": "20px", "marginBottom": "20px"}
            )
        ),
        
        # Main content - tree visualization and node details
        dbc.Row([
            # Tree visualization
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Game Tree Visualization"),
                    dbc.CardBody([
                        # Control buttons for the tree
                        dbc.ButtonGroup([
                            dbc.Button("Reset View", id="reset-view-button", color="secondary", size="sm"),
                            dbc.Button("Back to Previous", id="back-button", color="info", size="sm")
                        ], className="mb-3"),
                        
                        # Enhanced Navigation breadcrumbs with tooltips
                        html.Div([
                            html.Label("Current Path:"),
                            html.Div(id="path-breadcrumbs", className="mb-3")
                        ]),
                        
                        # Street selector for root nodes
                        html.Div([
                            html.Label("Starting Street:"),
                            dcc.RadioItems(
                                id='street-selector',
                                options=[
                                    {'label': 'Preflop', 'value': 'preflop'},
                                    {'label': 'Flop', 'value': 'flop'},
                                    {'label': 'Turn', 'value': 'turn'},
                                    {'label': 'River', 'value': 'river'}
                                ],
                                value='preflop',
                                inline=True,
                                className="mb-3"
                            )
                        ]),
                        
                        # Legend for node types
                        html.Div([
                            html.Label("Legend:"),
                            html.Div([
                                html.Span("Position", className="badge bg-primary me-2"),
                                html.Span("Fold", className="badge bg-danger me-2"),
                                html.Span("Call", className="badge bg-success me-2"),
                                html.Span("Raise", className="badge bg-warning me-2"),
                                html.Span("Check", className="badge bg-info me-2"),
                                html.Span("All-in", className="badge bg-secondary me-2"),
                                html.Span("Terminal", style={"border": "2px solid #E74C3C", "padding": "2px 6px", "margin-right": "10px"}),
                                html.Span("Synthetic", style={"border": "2px dashed #95A5A6", "padding": "2px 6px"})
                            ], className="mb-3")
                        ]),
                        
                        # Network graph visualization
                        html.Div(
                            id="cytoscape-container",
                            children=cyto.Cytoscape(
                                id='cytoscape-tree',
                                layout={
                                    'name': 'dagre', 
                                    'rankDir': 'LR', 
                                    'spacingFactor': 1.2,
                                    'rankSep': 120,
                                    'nodeSep': 80,
                                    'animate': False
                                },
                                style={'width': '100%', 'height': '600px'},
                                elements=[],
                                stylesheet=default_stylesheet,
                                minZoom=0.5,
                                maxZoom=2
                            ),
                            style={"display": "none"}
                        )
                    ])
                ])
            ], width=8),
            
            # Node details panel
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H4("Node Details", id="node-details-title")),
                    dbc.CardBody([
                        html.Div(id="node-details-content", children=[
                            html.P("Click a node in the tree to see details")
                        ]),
                        html.Hr(),
                        html.Div(id="node-actions-chart")
                    ])
                ]),
                
                # New card for available decisions at current node
                dbc.Card([
                    dbc.CardHeader(html.H4("Available Decisions")),
                    dbc.CardBody([
                        html.Div(id="available-decisions", children=[
                            html.P("Select a node to see available decisions")
                        ])
                    ])
                ], className="mt-3")
            ], width=4)
        ], id="main-content-container", style={"display": "none"}),
        
        # Debug/Status information at the bottom
        dbc.Card([
            dbc.CardHeader("Debug Information"),
            dbc.CardBody(id="debug-info", style={"whiteSpace": "pre-wrap", "fontFamily": "monospace", "fontSize": "12px"})
        ], className="mt-4"),
        
        # Store components to keep track of state
        dcc.Store(id='decision-tree-data'),  # Full tree data
        dcc.Store(id='current-node-path', data=["root"]),  # Current node path
        dcc.Store(id='id-mapping', data={}),  # Mapping from original IDs to simple IDs
        dcc.Store(id='current-node-details'),  # Details of the selected node
        dcc.Store(id='exclude-hero-store', data=True)  # Store hero exclusion preference
    ], fluid=True)
    
    return layout