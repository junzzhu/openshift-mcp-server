def format_bytes(size: float) -> str:
    """Format bytes to human readable string (e.g. 1.2 Gi)."""
    power = 2**10
    n = size
    power_labels = {0 : '', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    count = 0
    # Use the logic from storage.py as it seems slightly cleaner for general purpose, 
    # but ensure we cover the range logic from resources.py if needed.
    # storage.py logic: while n > power
    # resources.py logic: while n > 1024 and count < 4
    
    # Combined refined logic:
    while n > 1024 and count < 4:
        n /= power
        count += 1
    return f"{n:.2f}{power_labels.get(count, 'Ti')}" 

def parse_quantity(value: str) -> float:
    """
    Parse kubernetes quantity string to float (cores or bytes).
    Handles m, k, M, G, T, P, E, Ki, Mi, Gi, Ti, Pi, Ei.
    """
    value = str(value).strip()
    if not value:
        return 0.0
        
    if value.endswith('m'): # milli-cores
        return float(value[:-1]) / 1000.0
    
    # Binary prefixes (bytes)
    binary_suffixes = {
        'Ki': 2**10, 'Mi': 2**20, 'Gi': 2**30, 'Ti': 2**40, 'Pi': 2**50, 'Ei': 2**60
    }
    for suffix, multiplier in binary_suffixes.items():
        if value.endswith(suffix):
            return float(value[:-len(suffix)]) * multiplier
            
    # Decimal suffixes
    decimal_suffixes = {
        'k': 10**3, 'M': 10**6, 'G': 10**9, 'T': 10**12, 'P': 10**15, 'E': 10**18
    }
    for suffix, multiplier in decimal_suffixes.items():
        if value.endswith(suffix): # Be careful with capitalization for 'm' vs 'M'
            return float(value[:-len(suffix)]) * multiplier
            
    # Pure number
    try:
        return float(value)
    except ValueError:
        return 0.0

def format_cpu(cores: float) -> str:
    """Format CPU cores nicely (e.g. 500m or 1.5)."""
    if cores < 1.0:
        return f"{int(cores * 1000)}m"
    return f"{cores:.2f}"
