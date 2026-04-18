def tier_from_edge(edge_pp: float) -> str:
    """Map edge (percentage points above break-even) to confidence tier."""
    if edge_pp >= 19:
        return "T1-ELITE"
    if edge_pp >= 14:
        return "T2-STRONG"
    if edge_pp >= 9:
        return "T3-GOOD"
    if edge_pp >= 0:
        return "T4-LEAN"
    return "T5-FADE"
