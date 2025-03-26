import sqlite3
import pandas as pd
import time
import traceback
from app.card_utils import parse_card_values, standardize_hand, categorize_hand

def optimize_database(conn):
    """Create necessary indexes to optimize query performance"""
    print("Creating database indexes for optimization...")
    cursor = conn.cursor()
    # Indexes for joining tables
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_players_game_id ON game_players(game_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_players_player_id ON game_players(player_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_game_id ON actions(game_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_player_id ON actions(player_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_action_order ON actions(action_order)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_actions_action_round ON actions(action_round)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_game_id ON games(game_id)")
    # Index for filtering
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_player_count ON games(player_count)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stack_size ON game_players(initial_stack)")
    print("Database optimization complete.")

def load_decision_tree_data(db_path, stack_min=0, stack_max=25, game_type="heads_up", max_games=1000, exclude_hero=True):
    """
    Load poker hand data and organize it in a decision tree structure with proper action sequencing
    
    Args:
        db_path (str): Path to the SQLite database
        stack_min (int): Minimum effective stack size in big blinds
        stack_max (int): Maximum effective stack size in big blinds
        game_type (str): Type of game to filter for ("heads_up" or "all")
        max_games (int): Maximum number of games to analyze
        exclude_hero (bool): Whether to exclude hero's actions from statistics
        
    Returns:
        dict: Decision tree structure with action frequencies
    """
    start_time = time.time()
    conn = None
    
    try:
        conn = sqlite3.connect(db_path)
        
        # OPTIMIZATION: Add indexes to database to speed up queries
        optimize_database(conn)
        
        # Filter for games with specified stack range and type
        game_filter = ""
        if game_type == "heads_up":
            game_filter = "AND g.player_count = 2"
        
        print(f"Starting query for games with stack range {stack_min}-{stack_max}...")
        
        # OPTIMIZATION: Use a more efficient query without temp tables
        # First get qualifying game IDs with a single query
        qualified_games_query = f"""
        WITH stack_info AS (
            -- Calculate effective stacks more efficiently
            SELECT 
                gp.game_id,
                MIN(gp.initial_stack / g.big_blind) AS effective_stack_bb
            FROM game_players gp
            JOIN games g ON gp.game_id = g.game_id
            WHERE 1=1 {game_filter}
            GROUP BY gp.game_id
            HAVING effective_stack_bb BETWEEN {stack_min} AND {stack_max}
            LIMIT {max_games}
        )
        SELECT game_id FROM stack_info
        """
        
        qualified_games = pd.read_sql_query(qualified_games_query, conn)
        print(f"Found {len(qualified_games)} qualified games. Query took {time.time() - start_time:.2f}s")
        
        if qualified_games.empty:
            if conn:
                conn.close()
            return {"error": f"No games found with effective stacks between {stack_min} and {stack_max} big blinds"}
        
        # Convert to list for more efficient IN clause
        game_id_list = qualified_games['game_id'].tolist()
        game_id_str = ', '.join(f"'{gid}'" for gid in game_id_list)
        
        # OPTIMIZATION: Fetch players and actions in a single batch per query instead of using temp tables
        print("Retrieving player positions...")
        players_query = f"""
        SELECT 
            gp.game_id,
            gp.player_id,
            gp.position,
            gp.is_hero,
            gp.initial_stack
        FROM game_players gp
        WHERE gp.game_id IN ({game_id_str})
        """
        
        players_df = pd.read_sql_query(players_query, conn)
        
        print("Retrieving actions...")
        actions_query = f"""
        SELECT 
            a.game_id,
            a.player_id,
            a.action_round,
            a.simple_action_type,
            a.action_sum,
            a.action_order,
            a.pot_before_action,
            gp.position,
            gp.is_hero
        FROM actions a
        JOIN game_players gp ON a.game_id = gp.game_id AND a.player_id = gp.player_id
        WHERE a.game_id IN ({game_id_str})
        ORDER BY a.game_id, a.action_order
        """
        
        # OPTIMIZATION: Read data in chunks for very large datasets
        actions_df = pd.DataFrame()
        chunk_size = 10000  # Adjust based on available memory
        
        for chunk in pd.read_sql_query(actions_query, conn, chunksize=chunk_size):
            actions_df = pd.concat([actions_df, chunk])
        
        # Query for hole cards
        print("Retrieving hole cards...")
        hole_cards_query = f"""
        SELECT 
            c.game_id,
            c.player_id,
            c.card_values,
            gp.is_hero
        FROM cards c
        JOIN game_players gp ON c.game_id = gp.game_id AND c.player_id = gp.player_id
        WHERE c.game_id IN ({game_id_str})
        AND c.card_type = 'Pocket'
        """

        # Execute the query before closing the connection
        hole_cards_df = pd.read_sql_query(hole_cards_query, conn)
        conn.close()  # Move this here from above

        print(f"Retrieved {len(hole_cards_df)} hole card records")

        # Create a dictionary of hole cards by game and player
        hole_cards_dict = {}
        for _, row in hole_cards_df.iterrows():
            game_id = row['game_id']
            player_id = row['player_id']
            is_hero = row['is_hero'] == 1
            
            if game_id not in hole_cards_dict:
                hole_cards_dict[game_id] = {}
            
            # Parse the raw card string
            cards = parse_card_values(row['card_values'])
            if cards:
                hole_cards_dict[game_id][player_id] = {
                    'raw': cards,
                    'standardized': standardize_hand(cards),
                    'category': categorize_hand(cards),
                    'is_hero': is_hero
                }

        print(f"Processed hole cards for {len(hole_cards_dict)} games. Building decision tree...")    
        
        print(f"Retrieved {len(actions_df)} actions. Building decision tree...")
        
        # Initialize decision tree with improved structure
        decision_tree = {
            'name': 'root',
            'children': {
                'preflop': {'name': 'preflop', 'children': {}},
                'flop': {'name': 'flop', 'children': {}},
                'turn': {'name': 'turn', 'children': {}},
                'river': {'name': 'river', 'children': {}}
            },
            'exclude_hero': exclude_hero  # Store preference
        }
        
        # Map action rounds to street names
        round_map = {1: 'preflop', 2: 'flop', 3: 'turn', 4: 'river'}
        
        # OPTIMIZATION: Process games in smaller batches
        game_ids = actions_df['game_id'].unique()
        total_games = len(game_ids)
        batch_size = 100  # Adjust based on complexity
        
        for batch_start in range(0, total_games, batch_size):
            batch_end = min(batch_start + batch_size, total_games)
            batch_game_ids = game_ids[batch_start:batch_end]
            print(f"Processing games {batch_start+1}-{batch_end} of {total_games}...")
            
            # Filter data for current batch
            batch_actions = actions_df[actions_df['game_id'].isin(batch_game_ids)]
            batch_players = players_df[players_df['game_id'].isin(batch_game_ids)]
            
            # Process each game in the batch
            for game_id in batch_game_ids:
                game_actions = batch_actions[batch_actions['game_id'] == game_id].sort_values('action_order')
                game_players = batch_players[batch_players['game_id'] == game_id]
                
                # Skip games with no actions
                if game_actions.empty:
                    continue
                
                # Process each street in the game
                for street_round, street_actions in game_actions.groupby('action_round'):
                    street = round_map.get(street_round, 'unknown')
                    
                    # Skip unknown streets
                    if street not in decision_tree['children']:
                        continue
                    
                    street_node = decision_tree['children'][street]
                    
                    # For heads-up games, create a proper action sequence tree
                    if game_type == "heads_up":
                        # Skip if not exactly 2 players
                        if len(game_players) != 2:
                            continue
                        
                        # Find BTN/SB and BB positions
                        btn_pos = None
                        bb_pos = None
                        for _, pos_row in game_players.iterrows():
                            if 'BTN' in pos_row['position'] or 'SB' in pos_row['position']:
                                btn_pos = pos_row['position']
                            elif 'BB' in pos_row['position']:
                                bb_pos = pos_row['position']
                        
                        # Skip if positions aren't clear
                        if not btn_pos or not bb_pos:
                            continue
                        
                        # Determine first actor by street
                        # Preflop: BTN acts first, Postflop: BB acts first
                        first_position = btn_pos if street == 'preflop' else bb_pos
                        second_position = bb_pos if first_position == btn_pos else btn_pos
                        
                        # Make sure position nodes exist
                        if first_position not in street_node['children']:
                            street_node['children'][first_position] = {
                                'name': first_position,
                                'children': {},
                                'actions': {},
                                'hero_actions': {}  # Track hero actions separately
                            }
                        
                        # Sort actions by order
                        sorted_actions = street_actions.sort_values('action_order')
                        
                        # Track action sequence and positions
                        current_position = first_position
                        next_position = second_position
                        current_node = street_node['children'][first_position]
                        
                        # Action sequence variables
                        facing_all_in = False
                        is_terminal = False
                        response_required = True  # Flag to indicate if a response is expected
                        
                        # Process each action in sequence
                        for _, action in sorted_actions.iterrows():
                            action_position = action['position']
                            action_type = action['simple_action_type']
                            is_hero = action['is_hero'] == 1  # Check if action is by hero
                            
                            # Skip if this action doesn't match expected position or we're done
                            if action_position != current_position or is_terminal:
                                continue
                            
                            # Handle facing all-in special case
                            if facing_all_in and action_type not in ['call', 'fold', 'all_in_call']:
                                continue
                                
                            # Update action counts in current position node
                            # Track hero actions separately
                            if action_type not in current_node['actions']:
                                current_node['actions'][action_type] = 0
                                current_node['hero_actions'][action_type] = 0
                            
                            # Increment appropriate counter
                            current_node['actions'][action_type] += 1
                            if is_hero:
                                current_node['hero_actions'][action_type] += 1

                            # Track hole cards for this player if available
                            if 'hole_cards' not in current_node:
                                current_node['hole_cards'] = {}
                                current_node['hero_hole_cards'] = {}

                            # If there are hole cards for this player in this game
                            if game_id in hole_cards_dict and action['player_id'] in hole_cards_dict[game_id]:
                                card_info = hole_cards_dict[game_id][action['player_id']]
                                category = card_info['category']
                                
                                # Track in appropriate dictionary
                                if is_hero:
                                    if category not in current_node['hero_hole_cards']:
                                        current_node['hero_hole_cards'][category] = 0
                                    current_node['hero_hole_cards'][category] += 1
                                else:
                                    if category not in current_node['hole_cards']:
                                        current_node['hole_cards'][category] = 0
                                    current_node['hole_cards'][category] += 1
                            
                            # Create action node if it doesn't exist
                            if action_type not in current_node['children']:
                                current_node['children'][action_type] = {
                                    'name': action_type,
                                    'children': {},
                                    'actions': {},
                                    'hero_actions': {},  # Track hero actions separately
                                    'hole_cards': {},    # Initialize hole card dictionary
                                    'hero_hole_cards': {}  # Initialize hero hole card dictionary
                                }
                            
                            # Advance to the action node
                            action_node = current_node['children'][action_type]

                            # Track hole card information for this action
                            if game_id in hole_cards_dict and action['player_id'] in hole_cards_dict[game_id]:
                                card_info = hole_cards_dict[game_id][action['player_id']]
                                category = card_info['category']
                                
                                # Skip unknown cards (X X)
                                if category != "Unknown":
                                    # Track in appropriate dictionary for the action node
                                    if is_hero:
                                        if category not in action_node['hero_hole_cards']:
                                            action_node['hero_hole_cards'][category] = 0
                                        action_node['hero_hole_cards'][category] += 1
                                    else:
                                        if category not in action_node['hole_cards']:
                                            action_node['hole_cards'][category] = 0
                                        action_node['hole_cards'][category] += 1
                            
                            # Handle terminal actions
                            if action_type == 'fold':
                                # Fold ends the hand immediately
                                is_terminal = True
                                response_required = False
                                continue
                            elif 'check' in action_type:
                                # Check doesn't require response if it's the final action
                                if len(sorted_actions) == 0:  # No more actions
                                    is_terminal = True
                                    response_required = False
                                    continue
                            elif 'all_in' in action_type and 'call' not in action_type:
                                # Player went all-in, opponent faces all-in decision
                                facing_all_in = True
                                
                                # Next player must respond to all-in
                                if next_position not in action_node['children']:
                                    action_node['children'][next_position] = {
                                        'name': next_position,
                                        'children': {},
                                        'actions': {},
                                        'hero_actions': {},  # Track hero actions separately
                                        'hole_cards': {},    # Initialize hole card dictionary
                                        'hero_hole_cards': {},  # Initialize hero hole card dictionary
                                        'facing_all_in': True
                                    }
                                    
                                # Continue with opponent decision
                                current_node = action_node['children'][next_position]
                                current_position, next_position = next_position, current_position
                            elif ('call' in action_type and facing_all_in) or 'all_in_call' in action_type:
                                # All-in call is terminal - showdown
                                is_terminal = True
                                response_required = False
                                continue
                            else:
                                # Regular action - continue sequence with next player
                                if next_position not in action_node['children']:
                                    action_node['children'][next_position] = {
                                        'name': next_position,
                                        'children': {},
                                        'actions': {},
                                        'hero_actions': {},  # Track hero actions separately
                                        'hole_cards': {},    # Initialize hole card dictionary
                                        'hero_hole_cards': {}  # Initialize hero hole card dictionary
                                    }
                                
                                # Switch to opponent
                                current_node = action_node['children'][next_position]
                                current_position, next_position = next_position, current_position
                    else:
                        # Non-HU game implementation with hero action tracking
                        for position, position_actions in street_actions.groupby('position'):
                            if position not in street_node['children']:
                                street_node['children'][position] = {
                                    'name': position,
                                    'children': {},
                                    'actions': {},
                                    'hero_actions': {}  # Track hero actions separately
                                }
                            
                            position_node = street_node['children'][position]
                            current_node = position_node
                            
                            # Process each action in sequence
                            for _, action in position_actions.iterrows():
                                action_type = action['simple_action_type']
                                is_hero = action['is_hero'] == 1
                                
                                # Update action counts, tracking hero actions separately
                                if action_type not in current_node['actions']:
                                    current_node['actions'][action_type] = 0
                                    current_node['hero_actions'][action_type] = 0
                                
                                current_node['actions'][action_type] += 1
                                if is_hero:
                                    current_node['hero_actions'][action_type] += 1

                                # Track hole cards for this player if available
                                if 'hole_cards' not in current_node:
                                    current_node['hole_cards'] = {}
                                    current_node['hero_hole_cards'] = {}

                                # If there are hole cards for this player in this game
                                if game_id in hole_cards_dict and action['player_id'] in hole_cards_dict[game_id]:
                                    card_info = hole_cards_dict[game_id][action['player_id']]
                                    category = card_info['category']
                                    
                                    # Track in appropriate dictionary
                                    if is_hero:
                                        if category not in current_node['hero_hole_cards']:
                                            current_node['hero_hole_cards'][category] = 0
                                        current_node['hero_hole_cards'][category] += 1
                                    else:
                                        if category not in current_node['hole_cards']:
                                            current_node['hole_cards'][category] = 0
                                        current_node['hole_cards'][category] += 1
                                
                                if action_type not in current_node['children']:
                                    current_node['children'][action_type] = {
                                        'name': action_type,
                                        'children': {},
                                        'actions': {},
                                        'hero_actions': {}  # Track hero actions separately
                                    }
                                
                                current_node = current_node['children'][action_type]
        
        # Post-processing: add missing terminal actions
        def complete_terminal_actions(node):
            """Add synthetic terminal actions where needed"""
            if 'facing_all_in' in node and node['facing_all_in']:
                # Player facing all-in must have fold and call options
                if 'call' not in node['children']:
                    node['children']['call'] = {
                        'name': 'call',
                        'children': {},
                        'actions': {},
                        'hero_actions': {},  # Track hero actions separately
                        'hole_cards': {},    # Initialize hole card dictionary
                        'hero_hole_cards': {},  # Initialize hero hole card dictionary
                        'is_synthetic': True,
                        'is_terminal': True
                    }
                if 'fold' not in node['children']:
                    node['children']['fold'] = {
                        'name': 'fold',
                        'children': {},
                        'actions': {},
                        'hero_actions': {},  # Track hero actions separately
                        'hole_cards': {},    # Initialize hole card dictionary
                        'hero_hole_cards': {},  # Initialize hero hole card dictionary
                        'is_synthetic': True,
                        'is_terminal': True
                    }
                    
            # Process all children recursively
            if 'children' in node:
                for child_name, child_node in list(node['children'].items()):
                    complete_terminal_actions(child_node)
        
        # Apply completion to each street
        for street_name, street_node in decision_tree['children'].items():
            complete_terminal_actions(street_node)
            
        print("Calculating frequencies...")
        # Import the function from tree_analysis.py to avoid circular imports
        from app.tree_analysis import calculate_frequencies
        
        # Calculate frequencies and percentages
        calculate_frequencies(decision_tree, exclude_hero)
        
        # Add game count information
        decision_tree['game_count'] = len(qualified_games)
        
        print(f"Decision tree built successfully. Total time: {time.time() - start_time:.2f}s")
        return decision_tree
    
    except Exception as e:
        print(f"Error in load_decision_tree_data: {str(e)}")
        print(traceback.format_exc())
        if conn:
            conn.close()
        return {"error": f"Error loading data: {str(e)}"}