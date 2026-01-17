# API Self-Healing System Documentation

## Overview

The API Self-Healing System automatically detects when external APIs change their data structures and uses Claude AI to intelligently repair broken scripts without manual intervention.

## How It Works

### 1. API Structure Validation
```
┌─────────────────────────────────────────────────────┐
│  API Health Monitor                                 │
│  ─────────────────                                  │
│  1. Stores known API schemas (structure signatures) │
│  2. Validates responses against expected structures │
│  3. Detects structural changes (missing/extra keys) │
│  4. Logs validation history                         │
└─────────────────────────────────────────────────────┘
```

### 2. Self-Healing Process
```
API Change Detected
        ↓
Capture actual response structure
        ↓
Read broken script
        ↓
Build detailed prompt for Claude
        ↓
Claude analyzes differences
        ↓
Claude generates fix
        ↓
Create backup of original script
        ↓
Apply fix automatically
        ↓
Re-validate to confirm fix works
```

### 3. Integration with Orchestrator
```
Daily Grading Pipeline:
  [0/4] API Health Check
        ├─ Validate ESPN Scoreboard API
        ├─ Validate ESPN Summary API
        └─ Auto-heal if failures detected
  [1/4] Run grading script
  [2/4] Calculate metrics
  [3/4] Check calibration
```

## Features

### Automatic Detection
- Monitors API response structures
- Compares against known schemas
- Identifies missing/extra/changed keys
- Captures sample responses for analysis

### Intelligent Repair
- Uses Claude API to understand structural changes
- Generates production-ready code fixes
- Maintains existing functionality
- Adds explanatory comments
- Creates automatic backups

### Safety Mechanisms
- Always creates backup before modifying code
- Validates fixes before confirming success
- Logs all validation attempts
- Maintains version history of schemas

## Usage

### Integrated with Orchestrator (Automatic)

The system runs automatically during NBA grading:

```bash
python orchestrator.py --sport nba --mode once --operation grading
```

Output when API is healed:
```
[0/4] Running API health check...
   [WARN] ESPN Summary API validation failed
         Attempting auto-heal...
   [OK] Auto-healed ESPN Summary API
   APIs auto-healed: espn_nba_summary
```

### Standalone Health Check

Check all APIs manually:

```bash
python test_api_monitor.py --check
```

Output:
```
======================================================================
  API HEALTH CHECK - 2025-12-10 18:00:00
======================================================================

[1/2] Testing ESPN NBA Scoreboard API...
      ✅ PASS

[2/2] Testing ESPN NBA Summary API...
      ✅ PASS

======================================================================
  HEALTH CHECK COMPLETE
======================================================================

✅ All APIs passed validation!
```

### Manual Healing

Manually trigger healing on a specific script:

```bash
python test_api_monitor.py --heal nba/scripts/espn_nba_api.py
```

### Simulate Break & Auto-Heal (Testing)

Test the self-healing system:

```bash
python test_api_monitor.py --simulate-break
```

This will:
1. Create backup of working script
2. Break the script by reverting to old API structure
3. Validate (should fail)
4. Auto-heal the script
5. Re-validate (should pass)
6. Restore original code

## Configuration

### API Schemas

Schemas are stored in: `data/api_schemas/api_schemas.json`

Example schema:
```json
{
  "espn_nba_summary": {
    "api_name": "ESPN NBA Summary API",
    "endpoint": "https://site.api.espn.com/.../summary",
    "version": "2025-12-10",
    "expected_structure": {
      "boxscore": {
        "players": [
          {
            "team": {"abbreviation": "str"},
            "statistics": [...]
          }
        ]
      }
    },
    "last_validated": "2025-12-10T18:00:00",
    "validation_count": 142
  }
}
```

### Validation History

All validation attempts are logged to: `data/api_schemas/validation_history.jsonl`

Each line contains:
```json
{
  "api_name": "espn_nba_summary",
  "is_valid": false,
  "differences": ["Missing keys at boxscore.players: {'statistics'}"],
  "timestamp": "2025-12-10T18:00:00",
  "actual_structure": {...}
}
```

## Claude Prompt Structure

The healing prompt includes:

1. **API Context**: Which API changed
2. **Validation Failure**: Specific differences detected
3. **Expected Structure**: What the code expects
4. **Actual Structure**: What the API now returns
5. **Sample Response**: Real data for testing
6. **Broken Code**: The script that needs fixing
7. **Requirements**:
   - Fix all broken lines
   - Maintain functionality
   - Add explanatory comments
   - Return complete, production-ready code

Example prompt excerpt:
```
**VALIDATION FAILURE:**
The API response structure has changed. Here are the differences detected:
- Missing keys at : {'players'}
- Extra keys at boxscore: {'players'}

**EXPECTED STRUCTURE:**
{
  "players": [...]
}

**ACTUAL STRUCTURE:**
{
  "boxscore": {
    "players": [...]
  }
}

**YOUR TASK:**
1. Analyze the structural differences
2. Identify exact lines that are broken
3. Fix the code to work with new structure
4. Ensure same functionality
5. Add comments explaining changes
```

## Benefits

### Prevention of Future Breaks
- ✅ Detects API changes before they cause grading failures
- ✅ Auto-fixes scripts without manual intervention
- ✅ Reduces downtime from hours/days to seconds
- ✅ Maintains prediction pipeline continuity

### Intelligent Code Repair
- ✅ Claude understands context and intent
- ✅ Generates production-ready fixes
- ✅ Maintains code quality and style
- ✅ Adds explanatory documentation

### Safety & Reliability
- ✅ Always creates backups before changes
- ✅ Validates fixes work correctly
- ✅ Logs all actions for audit trail
- ✅ Falls back to manual review if auto-heal fails

## Real-World Example

### The ESPN API Change (Dec 2025)

**What Happened:**
ESPN changed their API structure from:
```python
data['players']  # Old structure
```

To:
```python
data['boxscore']['players']  # New structure
```

**Manual Fix Required:**
```python
# Before (broken)
players_data = data.get('players', [])

# After (fixed)
boxscore = data.get('boxscore', {})
players_data = boxscore.get('players', [])
```

**With Auto-Healing:**
1. Health check detects structure mismatch
2. Claude analyzes the change
3. Generates and applies fix automatically
4. Validates fix works
5. Grading continues without interruption

**Result:** 0 downtime instead of potential hours/days waiting for manual fix

## Extending to Other APIs

To add monitoring for additional APIs:

1. **Define Schema:**
```python
schemas['my_api'] = APISchema(
    api_name='My API',
    endpoint='https://api.example.com/v1/data',
    version='2025-12-10',
    expected_structure={
        'data': {
            'items': [{'id': 'int', 'name': 'str'}]
        }
    },
    sample_data={},
    last_validated=datetime.now().isoformat()
)
```

2. **Add Validation Method:**
```python
def validate_my_api(self, params) -> APIValidationResult:
    response = requests.get('https://api.example.com/v1/data', params=params)
    data = response.json()
    return self.validate_api('my_api', data)
```

3. **Integrate with Orchestrator:**
```python
# In _check_and_heal_apis method
my_api_check = self.api_monitor.validate_my_api(params)
if not my_api_check.is_valid:
    # Attempt auto-heal
    heal_result = self.api_monitor.self_heal_api_script(
        'my_api',
        my_api_check,
        script_path
    )
```

## Troubleshooting

### Health Check Shows API Failure

Check validation details:
```python
from shared.api_health_monitor import APIHealthMonitor

monitor = APIHealthMonitor()
result = monitor.validate_espn_nba_scoreboard("2025-12-08")

print(f"Valid: {result.is_valid}")
print(f"Differences: {result.differences}")
```

### Auto-Heal Fails

1. Check Claude API key is set correctly
2. Review the healing error message
3. Manually inspect the actual API response
4. Check if the broken script is too complex for auto-repair
5. Review the backup and attempt manual fix

### Schema Out of Date

Update schema manually:
```python
monitor = APIHealthMonitor()

# Force schema update with current working structure
monitor.schemas['espn_nba_summary'].expected_structure = new_structure
monitor.schemas['espn_nba_summary'].version = "2025-12-11"
monitor._save_schemas()
```

## Files Reference

| File | Purpose |
|------|---------|
| `shared/api_health_monitor.py` | Core monitoring & healing system |
| `orchestrator.py` | Integrated health checks (lines 90-97, 317-323, 522-534, 1389-1484) |
| `nba/scripts/espn_nba_api.py` | ESPN API client (auto-healed) |
| `test_api_monitor.py` | Testing & demonstration script |
| `data/api_schemas/api_schemas.json` | Known API structures |
| `data/api_schemas/validation_history.jsonl` | Validation log |

## Future Enhancements

Potential improvements:
- [ ] Add NHL API monitoring
- [ ] Implement ML-based anomaly detection
- [ ] Add Slack/Discord notifications on auto-heal
- [ ] Create dashboard for API health trends
- [ ] Auto-generate API documentation from schemas
- [ ] Support for GraphQL API monitoring
- [ ] Predictive alerts before APIs break

## Summary

The API Self-Healing System provides:
- **Automatic detection** of API structural changes
- **Intelligent repair** using Claude AI
- **Zero-downtime** grading pipeline
- **Safety mechanisms** (backups, validation)
- **Complete audit trail** of all changes

This ensures your prediction system continues running even when external APIs change without warning.
