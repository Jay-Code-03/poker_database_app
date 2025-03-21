from functools import lru_cache

# IMPORTANT: Define the tree data cache at global scope
_tree_data_cache = {}

def calculate_frequencies(node, exclude_hero=True):
    """
    Calculate action frequencies and percentages for each node in the decision tree
    
    Args:
        node (dict): The node to calculate frequencies for
        exclude_hero (bool): Whether to exclude hero's actions
        
    Returns:
        tuple: (total_count, non_hero_count) - Counts for this node and its children
    """
    total_count = 0
    non_hero_count = 0
    
    # Calculate counts for this node
    if 'actions' in node and node['actions']:
        # Sum overall action counts
        total_actions_count = sum(node['actions'].values())
        
        # Calculate non-hero counts by subtracting hero actions
        if 'hero_actions' in node:
            non_hero_actions = {
                action: max(0, node['actions'].get(action, 0) - node['hero_actions'].get(action, 0))
                for action in node['actions']
            }
            non_hero_actions_count = sum(non_hero_actions.values())
        else:
            # Fallback if hero_actions not tracked
            non_hero_actions = node['actions']
            non_hero_actions_count = total_actions_count
        
        # Store both sets of counts
        node['total_action_count'] = total_actions_count
        node['non_hero_action_count'] = non_hero_actions_count
        
        # Calculate total percentages
        if total_actions_count > 0:
            node['action_percentages_total'] = {
                action: (count / total_actions_count) * 100 
                for action, count in node['actions'].items()
                if count > 0  # Skip zero counts for efficiency
            }
        
        # Calculate non-hero percentages
        if non_hero_actions_count > 0:
            node['action_percentages_non_hero'] = {
                action: (count / non_hero_actions_count) * 100 
                for action, count in non_hero_actions.items()
                if count > 0  # Skip zero counts for efficiency
            }
        
        # Add to running totals
        total_count += total_actions_count
        non_hero_count += non_hero_actions_count
    
    # Process children recursively
    if 'children' in node:
        for child_name, child_node in node['children'].items():
            child_total, child_non_hero = calculate_frequencies(child_node, exclude_hero)
            
            # Only add non-synthetic nodes to counts
            if not child_node.get('is_synthetic', False):
                total_count += child_total
                non_hero_count += child_non_hero
                
            # Store child counts
            if 'child_counts' not in node:
                node['child_counts'] = {}
                node['child_counts_non_hero'] = {}
            
            node['child_counts'][child_name] = child_total
            node['child_counts_non_hero'][child_name] = child_non_hero
    
    # Store total count in node
    node['total_count'] = total_count
    node['non_hero_count'] = non_hero_count
    
    return total_count, non_hero_count

def get_node_by_path(tree_data, path):
    """
    Get a node in the decision tree by following a path array
    
    Args:
        tree_data (dict): The decision tree data
        path (list): List of node names forming a path from root to target node
        
    Returns:
        dict: The node at the specified path, or None if not found
    """
    if not tree_data or not path:
        return tree_data
        
    current_node = tree_data
    visited_path = []
    
    for i, step in enumerate(path):
        # Root is the starting point (tree_data itself)
        if i == 0 and step == "root":
            visited_path.append("root")
            continue
            
        # Handle composite IDs with hyphens (parent-child format)
        if '-' in step:
            # Extract the actual node name after the last hyphen
            child_name = step.split('-')[-1]
        else:
            child_name = step
        
        visited_path.append(child_name)
            
        # Check if we can navigate to the next step
        if 'children' in current_node and child_name in current_node['children']:
            current_node = current_node['children'][child_name]
        else:
            # For debugging
            print(f"Failed at step {i}: {step} (looking for '{child_name}')")
            print(f"Path so far: {visited_path}")
            if 'children' in current_node:
                print(f"Available children: {list(current_node['children'].keys())}")
            else:
                print("No children in current node")
            return None
    
    return current_node

# Cache enabled variant that uses the global cache and accepts tuple for path
@lru_cache(maxsize=1024)
def get_node_by_path_cached(tree_data_id, path_tuple):
    """
    Cached version of get_node_by_path that accepts immutable arguments
    
    Args:
        tree_data_id: Unique identifier for the tree data
        path_tuple (tuple): Immutable path tuple
        
    Returns:
        dict: The node at the specified path, or None if not found
    """
    global _tree_data_cache
    
    # Convert tuple to list for processing
    path = list(path_tuple)
    
    # Access the actual tree data using the unique ID
    tree_data = _tree_data_cache.get(tree_data_id)
    
    if not tree_data or not path:
        return None
    
    return get_node_by_path(tree_data, path)

def get_next_numeric_id(elements):
    """
    Get the next available numeric ID by examining existing node IDs
    
    Args:
        elements (list): The elements to examine
        
    Returns:
        int: The next available numeric ID
    """
    # Extract numeric IDs using a faster approach
    max_id = 0
    for element in elements:
        if 'data' in element and 'id' in element['data']:
            node_id = element['data']['id']
            # Match 'n' followed by digits
            if node_id.startswith('n'):
                try:
                    num_id = int(node_id[1:])
                    max_id = max(max_id, num_id)
                except ValueError:
                    pass
    
    # Return next available ID
    return max_id + 1