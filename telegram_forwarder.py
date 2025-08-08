#!/usr/bin/env python3
"""
Telegram Auto-Forward Bot for Railway Deployment - FIXED SESSION STRING
"""

import asyncio
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import logging

# Configure logging for Railway
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Railway Environment Variables
API_ID = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE_NUMBER = os.getenv('TELEGRAM_PHONE')

# Session string for Railway (no local files)
SESSION_STRING = os.getenv('SESSION_STRING', '')

# Channels
SOURCE_CHANNEL = 'WEB3_AGGREGATOR'
TARGET_CHANNEL = os.getenv('TARGET_CHANNEL', 'YourPrivateChannel')

class TelegramForwarder:
    def __init__(self):
        # Use session string for cloud deployment
        if SESSION_STRING:
            logger.info("📱 Using existing session string")
            self.client = TelegramClient(
                StringSession(SESSION_STRING), API_ID, API_HASH
            )
        else:
            # For initial setup - use StringSession to get session string
            logger.info("🔑 Creating new session for first-time setup")
            self.client = TelegramClient(
                StringSession(), API_ID, API_HASH
            )
        
    async def start(self):
        """Initialize and start the client"""
        try:
            await self.client.start(phone=PHONE_NUMBER)
            
            if await self.client.is_user_authorized():
                me = await self.client.get_me()
                logger.info(f"✅ Connected as {me.first_name}")
                
                # Print session string for Railway setup (first time only)
                if not SESSION_STRING:
                    session_str = self.client.session.save()
                    logger.info("=" * 80)
                    logger.info("🔑 COPY THIS SESSION STRING FOR RAILWAY:")
                    logger.info(f"{session_str}")
                    logger.info("=" * 80)
                    logger.info("⚠️  Add this as SESSION_STRING environment variable in Railway!")
                    logger.info("⚠️  Then redeploy your app!")
                    logger.info("=" * 80)
                
            else:
                logger.error("❌ Not authorized")
                return False
                
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False
            
        # Get channel entities
        try:
            self.source_entity = await self.client.get_entity(SOURCE_CHANNEL)
            self.target_entity = await self.client.get_entity(TARGET_CHANNEL)
            logger.info(f"📡 Source: {self.source_entity.title}")
            logger.info(f"📥 Target: {self.target_entity.title}")
        except Exception as e:
            logger.error(f"❌ Channel error: {e}")
            return False
            
        return True
    
    async def setup_forwarding(self):
        """Set up message forwarding"""
        
        @self.client.on(events.NewMessage(chats=[self.source_entity]))
        async def forward_handler(event):
            try:
                await self.client.forward_messages(
                    entity=self.target_entity,
                    messages=event.message,
                    from_peer=self.source_entity
                )
                logger.info(f"✅ Forwarded message {event.message.id}")
                
            except Exception as e:
                logger.error(f"❌ Forward failed: {e}")
        
        logger.info(f"🚀 Auto-forwarding: {SOURCE_CHANNEL} → {TARGET_CHANNEL}")
        logger.info("🔄 Bot is running... (Railway will keep it alive)")
    
    async def run_forever(self):
        """Keep running on Railway"""
        try:
            await self.client.run_until_disconnected()
        except Exception as e:
            logger.error(f"❌ Runtime error: {e}")
            # Railway will restart automatically
            await asyncio.sleep(10)

async def main():
    """Main function for Railway"""
    
    # Validate environment variables
    required_vars = ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_PHONE', 'TARGET_CHANNEL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"❌ Missing environment variables: {missing_vars}")
        return
    
    logger.info("🚀 Starting Telegram Forwarder on Railway...")
    
    forwarder = TelegramForwarder()
    
    if await forwarder.start():
        await forwarder.setup_forwarding()
        await forwarder.run_forever()
    else:
        logger.error("❌ Failed to start")

if __name__ == "__main__":
    asyncio.run(main())