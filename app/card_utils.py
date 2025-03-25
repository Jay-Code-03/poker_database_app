# app/card_utils.py

def parse_card_values(card_string):
    """
    Parse card values string into a list of cards
    Example: "SK C6" -> ["SK", "C6"]
    """
    if not card_string or not isinstance(card_string, str):
        return []
        
    # Split on whitespace and filter out empty strings
    cards = [card.strip() for card in card_string.split() if card.strip()]
    return cards

def get_card_rank(card):
    """Extract the rank from a card (e.g., 'SK' -> 'K')"""
    if not card or len(card) < 2:
        return None
    rank = card[1:] if card[0] in "SCHD" else card[0]
    return rank

def get_card_suit(card):
    """Extract the suit from a card (e.g., 'SK' -> 'S')"""
    if not card or len(card) < 2:
        return None
    suit = card[0] if card[0] in "SCHD" else card[1]
    return suit

def standardize_card(card):
    """Convert card to standard notation (e.g., 'SK' -> 'Ks')"""
    if not card or len(card) < 2:
        return ""
    
    rank = get_card_rank(card)
    suit = get_card_suit(card).lower()
    
    # Map numeric ranks to letters
    if rank == "10":
        rank = "T"
    
    # For consistency, return rank then suit (e.g., 'Ks')
    return f"{rank}{suit}"

def standardize_hand(cards):
    """Convert hand to standard notation (e.g., ["SK", "C6"] -> "Ks6c")"""
    if not cards or len(cards) < 2:
        return ""
    
    return ''.join(standardize_card(card) for card in cards)

def categorize_hand(cards):
    """
    Categorize a hand into standard poker categories (e.g., "AA", "AKs", "AKo")
    Input: ["SK", "CQ"] -> Output: "KQo" (King-Queen offsuit)
    """
    if not cards or len(cards) != 2:
        return "Unknown"
    
    # Extract ranks and suits
    rank1 = get_card_rank(cards[0])
    rank2 = get_card_rank(cards[1])
    suit1 = get_card_suit(cards[0])
    suit2 = get_card_suit(cards[1])
    
    # Deal with 10 vs T representation
    if rank1 == '10': rank1 = 'T'
    if rank2 == '10': rank2 = 'T'
    
    # Map ranks for ordering
    rank_map = {
        'A': 14, 'K': 13, 'Q': 12, 'J': 11, 'T': 10,
        '9': 9, '8': 8, '7': 7, '6': 6, '5': 5, '4': 4, '3': 3, '2': 2
    }
    
    # Get the rank values
    rank1_val = rank_map.get(rank1, 0)
    rank2_val = rank_map.get(rank2, 0)
    
    # Determine high and low ranks
    if rank1_val > rank2_val:
        high_rank, low_rank = rank1, rank2
    elif rank2_val > rank1_val:
        high_rank, low_rank = rank2, rank1
    else:
        # Same rank = pair
        return f"{rank1}{rank1}"
    
    # Determine if suited or offsuit
    is_suited = suit1 == suit2
    suffix = "s" if is_suited else "o"
    
    # Return in standard format (high rank + low rank + s/o)
    return f"{high_rank}{low_rank}{suffix}"

def get_all_hand_categories():
    """Generate all 169 possible starting hand categories in correct poker order"""
    ranks = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']
    categories = []
    
    # Generate all pairs
    for rank in ranks:
        categories.append(f"{rank}{rank}")
    
    # Generate all non-pairs
    for i, high_rank in enumerate(ranks):
        for low_rank in ranks[i+1:]:
            categories.append(f"{high_rank}{low_rank}s")  # suited
            categories.append(f"{high_rank}{low_rank}o")  # offsuit
    
    return categories

def generate_hand_grid_positions():
    """
    Generate positions for the 169 hand types in a grid with standard poker ordering
    Returns a dictionary mapping hand category to (row, col) position
    """
    ranks = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2']
    positions = {}
    
    # Fill the grid with all 169 possible hands
    for i, r1 in enumerate(ranks):
        for j, r2 in enumerate(ranks):
            if i == j:
                # Pairs (diagonal) - AA, KK, etc.
                hand = f"{r1}{r1}"
            elif i < j:
                # Suited hands - AKs, AQs, etc.
                hand = f"{r1}{r2}s" 
            else:
                # Offsuit hands - AKo, AQo, etc.
                hand = f"{r2}{r1}o"
            
            positions[hand] = (i, j)
    
    # Verify we have 169 hands (13 pairs + 78 suited + 78 offsuit)
    if len(positions) != 169:
        print(f"WARNING: Generated {len(positions)} positions instead of 169!")
    
    return positions