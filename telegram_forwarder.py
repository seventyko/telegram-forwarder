#!/usr/bin/env python3
"""
Telegram Auto-Forward Bot + API for Railway Deployment
"""

import asyncio
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import threading
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Header

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

# API security for n8n
N8N_API_KEY = os.getenv('N8N_API_KEY', 'default-change-this-key')

# FastAPI app
app = FastAPI(title="Telegram Forwarder + n8n API", version="1.0.0")

# Global client reference
telegram_client = None
target_channel_id = None

async def verify_api_key(x_api_key: str = Header(...)):
    """Verify API key for n8n requests"""
    if x_api_key != N8N_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "telegram_connected": telegram_client is not None and telegram_client.is_connected()
    }

@app.get("/api/messages/{hours}")
async def get_recent_messages(
    hours: int = 24,
    api_key_valid: bool = Depends(verify_api_key)
):
    """Get recent messages from the target channel for n8n processing"""
    if not telegram_client or not telegram_client.is_connected():
        raise HTTPException(status_code=503, detail="Telegram client not connected")
    
    if not target_channel_id:
        raise HTTPException(status_code=503, detail="Target channel not configured")
    
    try:
        # Calculate time range
        time_threshold = datetime.now() - timedelta(hours=hours)
        
        # Fetch messages from target channel (where forwarded messages are stored)
        messages = []
        async for message in telegram_client.iter_messages(
            target_channel_id, 
            offset_date=time_threshold,
            reverse=False,  # Get newest first
            limit=200  # Reasonable limit
        ):
            if message.text and message.text.strip():
                # Extract channel ID without the -100 prefix for the link
                # -1002659193089 -> 2659193089
                channel_id_for_link = str(abs(target_channel_id))[3:]  # Remove -100 prefix
                message_link = f"https://t.me/c/{channel_id_for_link}/{message.id}"
                
                messages.append({
                    'message_id': message.id,
                    'text': message.text.strip(),
                    'date': int(message.date.timestamp()),
                    'readable_date': message.date.isoformat(),
                    'link': message_link,
                    'text_with_link': message.text.strip() + f"\n🔗 Source: {message_link}"
                })
        
        # Sort by date (newest first)
        messages.sort(key=lambda x: x['date'], reverse=True)
        
        logger.info(f"📊 API: Retrieved {len(messages)} messages from last {hours} hours")
        
        return {
            'success': True,
            'messages': messages,
            'message_count': len(messages),
            'hours_requested': hours,
            'time_threshold': time_threshold.isoformat(),
            'channel_id': str(target_channel_id)
        }
        
    except Exception as e:
        logger.error(f"❌ API Error fetching messages: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error fetching messages: {str(e)}"
        )

@app.get("/api/messages/{hours}/combined")
async def get_combined_messages(
    hours: int = 24,
    api_key_valid: bool = Depends(verify_api_key)
):
    """Get recent messages formatted for AI processing (combined text)"""
    try:
        # Get messages using the existing endpoint logic
        result = await get_recent_messages(hours, api_key_valid)
        
        # Create combined text for AI input
        combined_text = '\n\n---\n\n'.join([
            msg['text_with_link'] for msg in result['messages']
        ])
        
        logger.info(f"📝 API: Created combined text from {result['message_count']} messages")
        
        return {
            'success': True,
            'combined_text': combined_text,
            'message_count': result['message_count'],
            'messages': result['messages'],  # Include individual messages too
            'processing_date': datetime.now().date().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ API Error creating combined messages: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating combined messages: {str(e)}"
        )

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
        
        # Store globally for API access
        global telegram_client
        telegram_client = self.client
        
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
            
            # Store target channel ID globally for API access
            global target_channel_id
            target_channel_id = self.target_entity.id
            
            logger.info(f"📡 Source: {self.source_entity.title}")
            logger.info(f"📥 Target: {self.target_entity.title} (ID: {target_channel_id})")
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
        logger.info("🌐 API server will be available for n8n requests")
    
    async def run_forever(self):
        """Keep running on Railway"""
        try:
            await self.client.run_until_disconnected()
        except Exception as e:
            logger.error(f"❌ Runtime error: {e}")
            # Railway will restart automatically
            await asyncio.sleep(10)

def run_fastapi_server():
    """Run FastAPI server in a separate thread"""
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

async def main():
    """Main function for Railway - runs both forwarder and API"""
    
    # Validate environment variables
    required_vars = ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_PHONE', 'TARGET_CHANNEL']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"❌ Missing environment variables: {missing_vars}")
        return
    
    logger.info("🚀 Starting Telegram Forwarder + API on Railway...")
    logger.info(f"🔑 N8N API Key configured: {'Yes' if N8N_API_KEY != 'default-change-this-key' else 'No (using default)'}")
    
    # Start FastAPI server in background thread
    api_thread = threading.Thread(target=run_fastapi_server, daemon=True)
    api_thread.start()
    logger.info("🌐 FastAPI server started in background")
    
    # Start Telegram forwarder
    forwarder = TelegramForwarder()
    
    if await forwarder.start():
        await forwarder.setup_forwarding()
        await forwarder.run_forever()
    else:
        logger.error("❌ Failed to start Telegram client")

if __name__ == "__main__":
    asyncio.run(main())
