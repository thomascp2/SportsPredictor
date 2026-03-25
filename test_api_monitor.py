"""
Test Script for API Health Monitor & Self-Healing System
==========================================================

This script demonstrates the self-healing capabilities.

Usage:
    # Run health check
    python test_api_monitor.py --check

    # Simulate API break and auto-heal
    python test_api_monitor.py --simulate-break

    # Manual heal attempt
    python test_api_monitor.py --heal nba/scripts/espn_nba_api.py
"""

import sys
from pathlib import Path

# Add shared to path
sys.path.insert(0, str(Path(__file__).parent / "shared"))

from api_health_monitor import APIHealthMonitor


def test_health_check():
    """Test API health check on current APIs."""
    print("\n" + "="*70)
    print("  TESTING API HEALTH MONITOR")
    print("="*70 + "\n")

    monitor = APIHealthMonitor()

    # Run full health check
    results = monitor.run_full_health_check("2025-12-08")

    # Summary
    print("\n" + "="*70)
    print("  SUMMARY")
    print("="*70)

    total = len(results)
    passed = sum(1 for r in results.values() if r.is_valid)
    failed = total - passed

    print(f"\nTotal APIs checked: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        print("\nFailed APIs:")
        for name, result in results.items():
            if not result.is_valid:
                print(f"\n  {name}:")
                print(f"    Differences: {len(result.differences)}")
                for diff in result.differences[:3]:
                    print(f"      - {diff}")

    return results


def simulate_api_break_and_heal():
    """Simulate an API break by modifying the ESPN API script, then auto-heal it."""
    print("\n" + "="*70)
    print("  SIMULATING API BREAK & AUTO-HEAL")
    print("="*70 + "\n")

    monitor = APIHealthMonitor()
    script_path = Path(__file__).parent / "nba" / "scripts" / "espn_nba_api.py"

    # Read original code
    with open(script_path, 'r') as f:
        original_code = f.read()

    # Create a backup first
    backup_path = monitor._create_backup(script_path)
    print(f"[BACKUP] Created backup: {backup_path}")

    try:
        # Simulate API break by reverting to old structure
        print("\n[SIMULATE] Breaking the API script...")
        broken_code = original_code.replace(
            "# Player data is under 'boxscore' -> 'players' (ESPN API structure)\n            boxscore = data.get('boxscore', {})\n            players_data = boxscore.get('players', [])",
            "# Player data is at top level under 'players'\n            players_data = data.get('players', [])"
        )

        with open(script_path, 'w') as f:
            f.write(broken_code)

        print("[SIMULATE] Script broken (reverted to old API structure)")

        # Validate - should fail
        print("\n[VALIDATE] Checking if API is now broken...")
        scoreboard = monitor.validate_espn_nba_scoreboard("2025-12-08")

        if scoreboard.raw_response_sample and 'events' in scoreboard.raw_response_sample:
            game_id = scoreboard.raw_response_sample['events'][0]['id']
            validation = monitor.validate_espn_nba_summary(game_id)

            if not validation.is_valid:
                print("[VALIDATE] ✅ API validation failed (as expected)")
                print(f"            Differences found: {len(validation.differences)}")

                # Attempt auto-heal
                print("\n[HEAL] Attempting auto-heal...")
                heal_result = monitor.self_heal_api_script(
                    'espn_nba_summary',
                    validation,
                    script_path
                )

                if heal_result.success:
                    print("\n[HEAL] ✅ AUTO-HEAL SUCCESSFUL!")
                    print(f"\n{heal_result.fix_description}")

                    # Re-validate
                    print("\n[RE-VALIDATE] Testing healed script...")
                    revalidation = monitor.validate_espn_nba_summary(game_id)

                    if revalidation.is_valid:
                        print("[RE-VALIDATE] ✅ Script is now working!")
                    else:
                        print("[RE-VALIDATE] ❌ Script still broken")
                        print(f"                Differences: {revalidation.differences}")
                else:
                    print(f"\n[HEAL] ❌ AUTO-HEAL FAILED")
                    print(f"         {heal_result.fix_description}")
            else:
                print("[VALIDATE] ❌ API is still valid (unexpected)")

    finally:
        # Restore original
        print("\n[RESTORE] Restoring original code from backup...")
        with open(backup_path, 'r') as f:
            original = f.read()
        with open(script_path, 'w') as f:
            f.write(original)
        print("[RESTORE] ✅ Original code restored")


def manual_heal(script_path: str):
    """Manually trigger healing on a specific script."""
    print("\n" + "="*70)
    print(f"  MANUAL HEAL: {script_path}")
    print("="*70 + "\n")

    monitor = APIHealthMonitor()
    path = Path(script_path)

    if not path.exists():
        print(f"ERROR: Script not found: {script_path}")
        return

    # Validate API first
    print("Validating API...")
    scoreboard = monitor.validate_espn_nba_scoreboard("2025-12-08")

    if scoreboard.raw_response_sample and 'events' in scoreboard.raw_response_sample:
        game_id = scoreboard.raw_response_sample['events'][0]['id']
        validation = monitor.validate_espn_nba_summary(game_id)

        if not validation.is_valid:
            print(f"❌ API validation failed")
            print(f"   Differences: {len(validation.differences)}")

            # Attempt heal
            print("\nAttempting heal...")
            heal_result = monitor.self_heal_api_script(
                'espn_nba_summary',
                validation,
                path
            )

            if heal_result.success:
                print("\n✅ HEAL SUCCESSFUL!")
                print(f"\nBackup: {heal_result.backup_path}")
                print(f"\n{heal_result.fix_description}")
            else:
                print("\n❌ HEAL FAILED")
                print(f"{heal_result.fix_description}")
        else:
            print("✅ API is healthy - no healing needed")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test API Health Monitor")
    parser.add_argument('--check', action='store_true', help='Run health check')
    parser.add_argument('--simulate-break', action='store_true', help='Simulate API break and auto-heal')
    parser.add_argument('--heal', type=str, help='Manually heal a specific script')

    args = parser.parse_args()

    if args.check:
        test_health_check()
    elif args.simulate_break:
        simulate_api_break_and_heal()
    elif args.heal:
        manual_heal(args.heal)
    else:
        parser.print_help()
