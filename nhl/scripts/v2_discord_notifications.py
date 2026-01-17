"""
Discord Webhook Notifications
==============================

Send notifications to Discord for:
- Daily workflow failures
- Weekly summaries
- Important alerts

Setup:
1. Create a Discord webhook in your server (Server Settings > Integrations > Webhooks)
2. Set environment variable: DISCORD_WEBHOOK_URL=your_webhook_url
3. Or edit this file and paste your webhook URL below
"""

import requests
import os
from datetime import datetime
from typing import Optional

# Discord webhook URL (get from Discord: Server Settings > Integrations > Webhooks)
# DISCORD_WEBHOOK_URL = os.getenv('DISCORD_WEBHOOK_URL', '')

# If not in environment, you can paste it here directly:
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1435509138687004672/YSOXw9z6gtGj9wSRAABiGLa-7P2eBhFgPRoAQp1vdV5f2_5YCmy1fYkj2EQpb-XIPnBQ"


def send_discord_notification(
    title: str,
    message: str,
    color: str = "blue",
    fields: Optional[list] = None
) -> bool:
    """
    Send notification to Discord
    
    Args:
        title: Notification title
        message: Main message body
        color: blue (info), green (success), red (error), yellow (warning)
        fields: List of {"name": "Field Name", "value": "Field Value", "inline": False}
    
    Returns:
        True if sent successfully, False otherwise
    """
    if not DISCORD_WEBHOOK_URL:
        print("[WARN] No Discord webhook URL configured")
        return False
    
    # Color codes
    color_map = {
        "blue": 3447003,    # Info
        "green": 3066993,   # Success
        "red": 15158332,    # Error
        "yellow": 16776960  # Warning
    }
    
    color_code = color_map.get(color, 3447003)
    
    # Build embed
    embed = {
        "title": title,
        "description": message,
        "color": color_code,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {
            "text": "NHL V2 Prediction System"
        }
    }
    
    # Add fields if provided
    if fields:
        embed["fields"] = fields
    
    payload = {
        "embeds": [embed]
    }
    
    try:
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send Discord notification: {e}")
        return False


def notify_workflow_success(script_name: str, stats: dict):
    """Notify successful workflow completion"""
    fields = [
        {"name": k.replace("_", " ").title(), "value": str(v), "inline": True}
        for k, v in stats.items()
    ]
    
    send_discord_notification(
        title=f"[OK] {script_name} - Success",
        message=f"{script_name} completed successfully",
        color="green",
        fields=fields
    )


def notify_workflow_failure(script_name: str, error: str):
    """Notify workflow failure"""
    send_discord_notification(
        title=f"[ERROR] {script_name} - Failed",
        message=f"Error: {error}",
        color="red"
    )


def notify_daily_summary(date: str, predictions: int, accuracy: float):
    """Send daily summary"""
    fields = [
        {"name": "Date", "value": date, "inline": True},
        {"name": "Predictions", "value": str(predictions), "inline": True},
        {"name": "Accuracy", "value": f"{accuracy:.1%}", "inline": True}
    ]
    
    send_discord_notification(
        title="[DATA] Daily Summary",
        message="Today's prediction statistics",
        color="blue",
        fields=fields
    )


def notify_weekly_calibration(week_end: str, tier_stats: dict):
    """Send weekly calibration report"""
    fields = [
        {"name": tier, "value": f"{stats['accuracy']:.1%} ({stats['count']} picks)", "inline": True}
        for tier, stats in tier_stats.items()
    ]
    
    send_discord_notification(
        title="📈 Weekly Calibration Report",
        message=f"Week ending {week_end}",
        color="blue",
        fields=fields
    )


if __name__ == "__main__":
    # Test Discord notifications
    print("Testing Discord webhook...")
    
    if not DISCORD_WEBHOOK_URL:
        print("\n[ERROR] NO WEBHOOK URL SET")
        print("\nTo set up Discord notifications:")
        print("1. Go to your Discord server")
        print("2. Server Settings > Integrations > Webhooks")
        print("3. Create a webhook, copy the URL")
        print("4. Set environment variable:")
        print('   set DISCORD_WEBHOOK_URL=your_webhook_url')
        print("\nOr edit this file and paste the URL directly.")
    else:
        print(f"Webhook URL: {DISCORD_WEBHOOK_URL[:50]}...")
        print("\nSending test notification...")
        
        success = send_discord_notification(
            title="🧪 Test Notification",
            message="If you see this, Discord notifications are working!",
            color="green",
            fields=[
                {"name": "System", "value": "NHL V2", "inline": True},
                {"name": "Status", "value": "Operational", "inline": True}
            ]
        )
        
        if success:
            print("[OK] Test notification sent successfully!")
        else:
            print("[ERROR] Failed to send test notification")
