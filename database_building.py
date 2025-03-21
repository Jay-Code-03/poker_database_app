import os
import sqlite3
import pandas as pd
import numpy as np
from tqdm import tqdm
import time
import re
import json
import traceback
from concurrent.futures import ThreadPoolExecutor
from lxml import etree as ET

# For reproducibility
np.random.seed(42)

def optimize_sqlite_connection(conn):
    """Apply performance optimizations to SQLite connection"""
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA synchronous = NORMAL')
    conn.execute('PRAGMA cache_size = -64000')  # 64MB cache
    conn.execute('PRAGMA temp_store = MEMORY')
    conn.execute('PRAGMA page_size = 4096')

def create_database_schema(db_path, with_indexes=True):
    """Create the database schema for poker hand history analysis"""
    conn = sqlite3.connect(db_path)
    optimize_sqlite_connection(conn)
    c = conn.cursor()
    
    # Create tables without indexes first for faster bulk loading
    c.execute('''
    CREATE TABLE IF NOT EXISTS games (
        game_id TEXT PRIMARY KEY,
        session_id TEXT,
        start_date TEXT,
        small_blind REAL,
        big_blind REAL,
        ante REAL,
        table_name TEXT,
        player_count INTEGER,
        is_tournament INTEGER
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS players (
        player_id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_name TEXT UNIQUE
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS game_players (
        game_id TEXT,
        player_id INTEGER,
        position TEXT,
        position_numeric INTEGER,
        initial_stack REAL,
        is_hero INTEGER,
        is_dealer INTEGER,
        final_stack REAL,
        total_won REAL,
        total_bet REAL,
        PRIMARY KEY (game_id, player_id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS cards (
        card_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id TEXT,
        card_type TEXT,  -- Pocket, Flop, Turn, River
        player_id INTEGER NULL,
        card_values TEXT,
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    ''')
    
    c.execute('''
    CREATE TABLE IF NOT EXISTS actions (
        action_id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id TEXT,
        player_id INTEGER,
        action_round INTEGER,
        action_type INTEGER,
        simple_action_type TEXT,
        action_sum REAL,
        action_order INTEGER,
        pot_before_action REAL,
        players_remaining INTEGER,
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (player_id) REFERENCES players(player_id)
    )
    ''')
    
    # Only create indexes if requested (defer for bulk loading)
    if with_indexes:
        c.execute('CREATE INDEX IF NOT EXISTS idx_game_id ON actions(game_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_player_id ON actions(player_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_action_type ON actions(simple_action_type)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_game_players ON game_players(game_id, player_id)')
    
    conn.commit()
    conn.close()
    
    print(f"Database schema created at {db_path}")

# Helper functions
def safe_float(text):
    """Convert text to float, handling currency symbols and errors"""
    if text is None:
        return 0.0
    try:
        return float(re.sub(r"[^\d\.]", "", str(text)))
    except Exception:
        return 0.0

def get_action_type(type_code):
    """Convert action type code to readable format"""
    action_types = {
        0: "fold", 
        1: "small_blind", 
        2: "big_blind", 
        3: "call", 
        4: "check", 
        5: "bet", 
        7: "all_in", 
        15: "ante",
        23: "raise"
    }
    return action_types.get(int(type_code) if type_code else 0, f"unknown_{type_code}")

def simplify_action(action_details, round_no, blinds, pot_before_action, round_contributions, current_round_max, player_stacks=None):
    """
    Simplify the action into a single string category based on context.
    """
    allowed_types = {0: "fold", 3: "call", 4: "check", 5: "bet", 7: "all_in", 15: "ante", 23: "raise"}
    orig_type = action_details['action_type']
    if orig_type not in allowed_types:
        return None
    base_action = allowed_types[orig_type]
    new_action = action_details.copy()

    if base_action == "all_in":
        # Determine if this is an all-in call or all-in raise
        player_id = action_details['player_id']
        current_player_contrib = round_contributions.get(player_id, 0)
        
        # If the action sum is less than or equal to what would be needed to call,
        # it's an all-in call. Otherwise, it's an all-in raise.
        call_amount = max(0, current_round_max - current_player_contrib)
        
        if action_details['action_sum'] <= call_amount * 1.05:  # Allow small margin for rounding errors
            new_action["simple_action_type"] = "all_in_call"
        else:
            # It's an all-in raise
            if round_no == 1:  # Preflop
                new_action["simple_action_type"] = "all_in_preflop"
            else:
                new_action["simple_action_type"] = "all_in_postflop"
    
    elif base_action == "bet":
        # Bets only occur postflop (rounds 2+)
        if round_no > 1:
            effective_pot = pot_before_action
            ratio = action_details['action_sum'] / effective_pot if effective_pot > 0 else 0
            
            if ratio <= 0.33:
                new_action["simple_action_type"] = "small_bet_postflop"
            elif ratio <= 0.66:
                new_action["simple_action_type"] = "mid_bet_postflop"
            else:
                new_action["simple_action_type"] = "big_bet_postflop"
        else:
            # This shouldn't happen in normal play (a bet in pre-flop)
            new_action["simple_action_type"] = "unusual_bet_preflop"
    
    elif base_action == "raise":
        if round_no == 1:  # Preflop
            bb = blinds.get("big_blind", 1)
            ratio = action_details['action_sum'] / bb if bb != 0 else 0

            # Get player's stack size (if available)
            player_id = action_details['player_id']
            player_stack = player_stacks.get(player_id, float('inf')) if player_stacks else float('inf')
            
            # Check if this is an all-in
            is_all_in = action_details['action_sum'] >= 0.98 * player_stack

            if is_all_in:  
                new_action["simple_action_type"] = "all_in_preflop"
            elif ratio <= 2.2:
                new_action["simple_action_type"] = "small_raise_preflop"
            elif ratio <= 2.7:
                new_action["simple_action_type"] = "mid_raise_preflop"
            elif ratio <= 3.2:
                new_action["simple_action_type"] = "big_raise_preflop"
            else:
                new_action["simple_action_type"] = "consider_all_in_preflop"
        else:  # Postflop
            current_player_contrib = round_contributions.get(action_details['player_id'], 0)
            call_amount = max(0, current_round_max - current_player_contrib)
            effective_raise = action_details['action_sum'] - call_amount
            effective_pot = pot_before_action + call_amount
            ratio = effective_raise / effective_pot if effective_pot > 0 else 0
            
            if ratio <= 0.33:
                new_action["simple_action_type"] = "small_raise_postflop"
            elif ratio <= 0.66:
                new_action["simple_action_type"] = "mid_raise_postflop"
            else:
                new_action["simple_action_type"] = "big_raise_postflop"
    else:
        new_action["simple_action_type"] = base_action
        
    return new_action

def process_xml_file(xml_file_path):
    """Process a single XML file and return extracted data"""
    try:
        # Data structures to collect results
        games_data = []
        game_players_data = []
        cards_data = []
        actions_data = []
        player_names = set()
        
        try:
            # Use safer XML parsing approach
            parser = ET.XMLParser(recover=True)
            tree = ET.parse(xml_file_path, parser)
            root = tree.getroot()
        except Exception as e:
            return {
                'success': False,
                'error': f"XML parsing error: {str(e)}",
                'filename': xml_file_path
            }
        
        # Get session info
        session_id = root.get('sessioncode', '')
        session_general = root.find('general')
        hero_nickname = session_general.findtext('nickname', '') if session_general is not None else ''
        
        # Process each game
        for game in root.findall('game'):
            game_id = game.get('gamecode', '')
            if not game_id:
                continue
                
            # Parse general game info
            general = game.find('general')
            if general is None:
                continue
                
            # Get blinds and ante
            small_blind = safe_float(general.findtext('smallblind', "0"))
            big_blind = safe_float(general.findtext('bigblind', "0"))
            ante = safe_float(general.findtext('ante', "0"))
            
            # Get start date
            start_date = general.findtext('startdate', '')
            
            # Get table info
            table_name = ''
            is_tournament = 0
            for parent_general in root.findall('general'):
                table_name = parent_general.findtext('tablename', '')
                is_tournament = 1 if parent_general.findtext('tournamentcode', '') else 0
            
            # Get player count
            players_elem = general.find('players')
            if players_elem is None:
                continue
            player_count = len(players_elem.findall('player'))
            
            # Store game info
            games_data.append({
                'game_id': game_id,
                'session_id': session_id,
                'start_date': start_date,
                'small_blind': small_blind,
                'big_blind': big_blind,
                'ante': ante,
                'table_name': table_name,
                'player_count': player_count,
                'is_tournament': is_tournament
            })
            
            # Process player positions
            player_positions = {}
            position_numeric = {}
            
            # Find button player
            button_player = None
            for p in players_elem.findall('player'):
                if p.get('dealer', '0') == '1':
                    button_player = p.get('name')
                    break
            
            # Find SB and BB from round 0 actions
            sb_player = None
            bb_player = None
            for r in game.findall('round'):
                if r.get('no') == '0':
                    for act in r.findall('action'):
                        action_type = act.get('type')
                        player = act.get('player')
                        if action_type == '1':
                            sb_player = player
                        elif action_type == '2':
                            bb_player = player
            
            # Assign positions
            heads_up = (player_count == 2)
            
            # For 2-player games
            if heads_up and button_player and sb_player:
                player_positions[button_player] = 'BTN/SB'
                position_numeric[button_player] = 0
                
                # In heads-up, the other player must be BB
                for p in players_elem.findall('player'):
                    player_name = p.get('name')
                    if player_name != button_player:
                        player_positions[player_name] = 'BB'
                        position_numeric[player_name] = 1
                        break
            # For 3+ player games
            else:
                if sb_player:
                    player_positions[sb_player] = 'SB'
                    position_numeric[sb_player] = 0
                if bb_player:
                    player_positions[bb_player] = 'BB'
                    position_numeric[bb_player] = 1
                
                # In 3-player games, the third position is button if not SB or BB
                if player_count == 3 and button_player:
                    if button_player not in (sb_player, bb_player):
                        player_positions[button_player] = 'BTN'
                        position_numeric[button_player] = 2
            
            # Process each player
            for p in players_elem.findall('player'):
                player_name = p.get('name')
                if not player_name:
                    continue
                    
                # Add to set of player names
                player_names.add(player_name)
                
                initial_stack = safe_float(p.get('chips', '0'))
                is_hero = 1 if player_name == hero_nickname else 0
                is_dealer = 1 if p.get('dealer', '0') == '1' else 0
                total_won = safe_float(p.get('win', '0'))
                total_bet = safe_float(p.get('bet', '0'))
                final_stack = initial_stack + total_won - total_bet
                
                position = player_positions.get(player_name, 'unknown')
                pos_num = position_numeric.get(player_name, -1)
                
                # Store player info for this game
                game_players_data.append({
                    'game_id': game_id,
                    'player_name': player_name,
                    'position': position,
                    'position_numeric': pos_num,
                    'initial_stack': initial_stack,
                    'is_hero': is_hero,
                    'is_dealer': is_dealer,
                    'final_stack': final_stack,
                    'total_won': total_won,
                    'total_bet': total_bet
                })
            
            # Process cards
            for r in game.findall('round'):
                for card in r.findall('cards'):
                    card_type = card.get('type')
                    player_name = card.get('player', None)
                    card_values = card.text.strip() if card.text else ''
                    
                    # Store card info
                    cards_data.append({
                        'game_id': game_id,
                        'card_type': card_type,
                        'player_name': player_name,
                        'card_values': card_values
                    })
            
            # Process actions with contextualized information
            active_players = {p.get('name'): True for p in players_elem.findall('player')}
            pot_size = 0.0
            action_order = 0
            
            # Track cumulative contributions
            player_contributions = {p.get('name'): 0.0 for p in players_elem.findall('player')}
            
            player_stacks = {p.get('name'): safe_float(p.get('chips', '0')) for p in players_elem.findall('player')}

            for r in game.findall('round'):
                round_no = int(r.get('no', '0'))
                
                # Reset round contributions and maximum for new betting rounds
                if round_no >= 1:
                    round_contributions = {player_name: 0.0 for player_name in player_contributions}
                    current_round_max = 0.0
                
                for action in r.findall('action'):
                    player_name = action.get('player')
                    if not player_name:
                        continue
                        
                    action_type = int(action.get('type', '0'))
                    action_sum = safe_float(action.get('sum', '0'))
                    action_order += 1
                    
                    # Update player's stack
                    player_stacks[player_name] = max(0, player_stacks.get(player_name, 0) - action_sum)
                    
                    # Prepare action details
                    action_details = {
                        'player_id': player_name,  # We'll resolve player_id later
                        'action_type': action_type,
                        'action_sum': action_sum,
                        'action_round': round_no
                    }
                    
                    current_pot = pot_size
                    players_remaining = sum(1 for v in active_players.values() if v)
                    
                    simple_action_type = get_action_type(action_type)
                    
                    # Skip round 0 for simplification analysis
                    # For rounds ≥ 1, analyze actions in context
                    if round_no >= 1:
                        # Simplify the action using the round-level data
                        simple_action = simplify_action(
                            action_details, 
                            round_no, 
                            {"big_blind": big_blind, "small_blind": small_blind, "ante": ante}, 
                            current_pot, 
                            round_contributions, 
                            current_round_max,
                            player_stacks  # Pass player stacks here
                        )
                        
                        if simple_action is not None:
                            # Store the action with context
                            actions_data.append({
                                'game_id': game_id,
                                'player_name': player_name,
                                'action_round': round_no,
                                'action_type': action_type,
                                'simple_action_type': simple_action.get("simple_action_type", simple_action_type),
                                'action_sum': action_sum,
                                'action_order': action_order,
                                'pot_before_action': current_pot,
                                'players_remaining': players_remaining
                            })
                        
                        # Update round-level contributions for this action
                        round_contributions[player_name] = round_contributions.get(player_name, 0) + action_sum
                        current_round_max = max(current_round_max, round_contributions[player_name])
                    else:
                        # For round 0 (blinds/antes), just record the action
                        actions_data.append({
                            'game_id': game_id,
                            'player_name': player_name,
                            'action_round': round_no,
                            'action_type': action_type,
                            'simple_action_type': simple_action_type,
                            'action_sum': action_sum,
                            'action_order': action_order,
                            'pot_before_action': pot_size,
                            'players_remaining': player_count
                        })
                    
                    # Update cumulative contributions and pot
                    player_contributions[player_name] = player_contributions.get(player_name, 0) + action_sum
                    pot_size += action_sum
                    
                    # Mark a player as inactive if they folded
                    if action_type == 0:  # fold
                        active_players[player_name] = False
        
        return {
            'games': games_data,
            'game_players': game_players_data,
            'cards': cards_data,
            'actions': actions_data,
            'players': list(player_names),
            'success': True
        }
        
    except Exception as e:
        print(f"Error processing {xml_file_path}: {str(e)}")
        traceback.print_exc()
        return {
            'games': [],
            'game_players': [],
            'cards': [],
            'actions': [],
            'players': [],
            'success': False,
            'error': str(e),
            'filename': xml_file_path
        }

def get_player_id_cache(conn, player_names):
    """Pre-cache player IDs to avoid repeated lookups"""
    cursor = conn.cursor()
    player_id_cache = {}
    
    # Get existing players
    cursor.execute("SELECT player_id, player_name FROM players")
    for player_id, player_name in cursor.fetchall():
        player_id_cache[player_name] = player_id
    
    # Insert any new players all at once
    new_players = [(name,) for name in player_names if name not in player_id_cache]
    if new_players:
        cursor.executemany("INSERT OR IGNORE INTO players (player_name) VALUES (?)", new_players)
        conn.commit()
        
        # Get the newly inserted IDs
        for name, in new_players:
            if name not in player_id_cache:
                cursor.execute("SELECT player_id FROM players WHERE player_name = ?", (name,))
                result = cursor.fetchone()
                if result:
                    player_id_cache[name] = result[0]
    
    return player_id_cache

def process_directory(directory_path, db_path, limit=None):
    """Process all XML files in a directory and store them in the database"""
    start_time = time.time()
    
    # Get all XML files
    xml_files = []
    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.endswith(".xml"):
                xml_files.append(os.path.join(root, file))
    
    # Limit files if requested
    if limit and limit > 0:
        if limit < len(xml_files):
            xml_files = xml_files[:limit]
    
    print(f"Found {len(xml_files)} XML files to process")
    
    # Create database schema without indexes for faster insertion
    if not os.path.exists(db_path):
        create_database_schema(db_path, with_indexes=False)
    
    # Set up database connection in main thread
    conn = sqlite3.connect(db_path)
    optimize_sqlite_connection(conn)
    
    # Check for existing games to avoid duplicates
    cursor = conn.cursor()
    cursor.execute("SELECT game_id FROM games")
    existing_games = {row[0] for row in cursor.fetchall()}
    
    # Determine optimal chunk size and number of workers
    chunk_size = 50  # A smaller batch size for better stability
    num_files = len(xml_files)
    num_chunks = max(1, (num_files + chunk_size - 1) // chunk_size)
    
    # Use thread-based parallelism (more reliable on Windows)
    max_workers = min(os.cpu_count() * 2, 16)  # More threads since they're lighter weight
    print(f"Processing with {max_workers} threads in {num_chunks} chunks")
    
    # Set up progress tracking
    processed_files = 0
    successful_files = 0
    total_games = 0
    total_actions = 0
    
    # Process files in batches
    for i in range(0, num_files, chunk_size):
        chunk = xml_files[i:i+chunk_size]
        chunk_start = time.time()
        print(f"Processing chunk {i//chunk_size + 1}/{num_chunks} ({len(chunk)} files)")
        
        # Process files with thread pool
        results = []
        
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_xml_file, file_path): file_path for file_path in chunk}
                
                # Use tqdm for progress tracking
                with tqdm(total=len(chunk), desc="Processing XML files") as pbar:
                    for future in futures:
                        try:
                            result = future.result()
                            results.append(result)
                            if result['success']:
                                successful_files += 1
                            pbar.update(1)
                        except Exception as e:
                            print(f"Error processing {futures[future]}: {str(e)}")
                            pbar.update(1)
        except Exception as e:
            print(f"Error with thread pool: {str(e)}")
            # If thread pool fails, try sequential processing
            print("Falling back to sequential processing...")
            results = []
            for file_path in tqdm(chunk, desc="Processing files sequentially"):
                result = process_xml_file(file_path)
                results.append(result)
                if result['success']:
                    successful_files += 1
        
        processed_files += len(chunk)
        
        # Collect data from successful results
        all_players = set()
        all_games = []
        all_game_players = []
        all_cards = []
        all_actions = []
        
        for result in results:
            if result.get('success', False):
                all_players.update(result.get('players', []))
                all_games.extend(result.get('games', []))
                all_game_players.extend(result.get('game_players', []))
                all_cards.extend(result.get('cards', []))
                all_actions.extend(result.get('actions', []))
        
        # Get player IDs
        player_id_cache = get_player_id_cache(conn, all_players)
        
        # Insert games
        games_to_insert = []
        for game in all_games:
            if game['game_id'] not in existing_games:
                games_to_insert.append((
                    game['game_id'], game['session_id'], game['start_date'],
                    game['small_blind'], game['big_blind'], game['ante'],
                    game['table_name'], game['player_count'], game['is_tournament']
                ))
                existing_games.add(game['game_id'])
        
        if games_to_insert:
            print(f"Inserting {len(games_to_insert)} games...")
            cursor.executemany('''
                INSERT OR IGNORE INTO games 
                (game_id, session_id, start_date, small_blind, big_blind, ante, table_name, player_count, is_tournament)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', games_to_insert)
            conn.commit()
            total_games += len(games_to_insert)
        
        # Insert game_players
        game_players_to_insert = []
        for gp in all_game_players:
            player_id = player_id_cache.get(gp['player_name'])
            if player_id:
                game_players_to_insert.append((
                    gp['game_id'], player_id, gp['position'], gp['position_numeric'],
                    gp['initial_stack'], gp['is_hero'], gp['is_dealer'],
                    gp['final_stack'], gp['total_won'], gp['total_bet']
                ))
        
        if game_players_to_insert:
            print(f"Inserting {len(game_players_to_insert)} game players...")
            cursor.executemany('''
                INSERT OR IGNORE INTO game_players
                (game_id, player_id, position, position_numeric, initial_stack, 
                 is_hero, is_dealer, final_stack, total_won, total_bet)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', game_players_to_insert)
            conn.commit()
        
        # Insert cards
        cards_to_insert = []
        for card in all_cards:
            player_id = player_id_cache.get(card['player_name']) if card['player_name'] else None
            cards_to_insert.append((
                card['game_id'], card['card_type'], player_id, card['card_values']
            ))
        
        if cards_to_insert:
            print(f"Inserting {len(cards_to_insert)} cards...")
            cursor.executemany('''
                INSERT INTO cards
                (game_id, card_type, player_id, card_values)
                VALUES (?, ?, ?, ?)
            ''', cards_to_insert)
            conn.commit()
        
        # Insert actions in smaller batches to avoid excessive memory usage
        action_batch_size = 5000
        total_batch_actions = len(all_actions)
        
        if total_batch_actions > 0:
            print(f"Inserting {total_batch_actions} actions in smaller batches...")
            
            with tqdm(total=total_batch_actions, desc="Inserting actions") as pbar:
                for j in range(0, total_batch_actions, action_batch_size):
                    actions_batch = all_actions[j:j+action_batch_size]
                    actions_to_insert = []
                    
                    for action in actions_batch:
                        player_id = player_id_cache.get(action['player_name'])
                        if player_id:
                            actions_to_insert.append((
                                action['game_id'], player_id, action['action_round'], action['action_type'],
                                action['simple_action_type'], action['action_sum'], action['action_order'],
                                action['pot_before_action'], action['players_remaining']
                            ))
                    
                    if actions_to_insert:
                        cursor.executemany('''
                            INSERT INTO actions
                            (game_id, player_id, action_round, action_type, simple_action_type, 
                             action_sum, action_order, pot_before_action, players_remaining)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', actions_to_insert)
                        conn.commit()
                        total_actions += len(actions_to_insert)
                        pbar.update(len(actions_batch))
        
        chunk_time = time.time() - chunk_start
        print(f"Chunk complete in {chunk_time:.2f}s. Progress: {processed_files}/{num_files} files, {successful_files} successful, {total_games} games, {total_actions} actions")
    
    # Add indexes after all data is inserted
    print("Adding indexes...")
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_game_id ON actions(game_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_id ON actions(player_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_action_type ON actions(simple_action_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_game_players ON game_players(game_id, player_id)')
    conn.commit()
    
    # Optimize database
    print("Optimizing database...")
    cursor.execute('PRAGMA optimize')
    conn.commit()
    conn.close()
    
    end_time = time.time()
    print(f"Total processing time: {end_time - start_time:.2f} seconds")
    print(f"Processed {processed_files} files, {successful_files} successful, inserted {total_games} games and {total_actions} actions")

def main():
    """Main function to demonstrate the workflow"""
    # Configuration
    db_path = "poker_analysis_optimized.db"
    xml_folder = "ipoker_hh"  # Folder containing XML files
    
    # Process files with optimized code
    process_directory(xml_folder, db_path, limit=None)  # Set a limit or None for all files
    
    print("Processing complete!")

if __name__ == "__main__":
    main()