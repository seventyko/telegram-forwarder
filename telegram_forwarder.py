#!/usr/bin/env python3
"""
Telegram Auto-Forward Bot + API for Railway Deployment - FIXED FORWARDING
"""

import asyncio
import os
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import logging
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Header
import uvicorn
from contextlib import asynccontextmanager

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

# API security for n8n (optional)
N8N_API_KEY = os.getenv('N8N_API_KEY', '')

# Global variables
telegram_client = None
target_channel_id = None
source_entity = None
target_entity = None

async def verify_api_key(x_api_key: str = Header(None)):
    """Verify API key for n8n requests (optional if no key set)"""
    if N8N_API_KEY and x_api_key != N8N_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

async def init_telegram():
    """Initialize Telegram client and forwarding"""
    global telegram_client, target_channel_id, source_entity, target_entity
    
    logger.info("🚀 Initializing Telegram client...")
    
    try:
        # Create Telegram client
        if SESSION_STRING:
            logger.info("📱 Using existing session string")
            telegram_client = TelegramClient(
                StringSession(SESSION_STRING), API_ID, API_HASH
            )
        else:
            logger.info("🔑 No session string - need to generate one")
            telegram_client = TelegramClient(
                StringSession(), API_ID, API_HASH
            )
        
        # Start client
        await telegram_client.start(phone=PHONE_NUMBER)
        
        if await telegram_client.is_user_authorized():
            me = await telegram_client.get_me()
            logger.info(f"✅ Telegram connected as {me.first_name}")
            
            # Print session string for first-time setup
            if not SESSION_STRING:
                session_str = telegram_client.session.save()
                logger.info("=" * 80)
                logger.info("🔑 COPY THIS SESSION STRING FOR RAILWAY:")
                logger.info(f"{session_str}")
                logger.info("=" * 80)
                logger.info("⚠️  Add this as SESSION_STRING environment variable in Railway!")
                logger.info("=" * 80)
            
            # Get channel entities
            try:
                source_entity = await telegram_client.get_entity(SOURCE_CHANNEL)
                target_entity = await telegram_client.get_entity(TARGET_CHANNEL)
                target_channel_id = target_entity.id
                
                logger.info(f"📡 Source: {source_entity.title}")
                logger.info(f"📥 Target: {target_entity.title} (ID: {target_channel_id})")
                
                # Set up message forwarding
                @telegram_client.on(events.NewMessage(chats=[source_entity]))
                async def forward_handler(event):
                    try:
                        await telegram_client.forward_messages(
                            entity=target_entity,
                            messages=event.message,
                            from_peer=source_entity
                        )
                        logger.info(f"✅ Forwarded message {event.message.id} from {source_entity.title}")
                        
                    except Exception as e:
                        logger.error(f"❌ Forward failed: {e}")
                
                logger.info(f"🚀 Auto-forwarding ACTIVE: {SOURCE_CHANNEL} → {TARGET_CHANNEL}")
                logger.info("🔄 Listening for new messages...")
                
                return True
                
            except Exception as e:
                logger.error(f"❌ Channel setup error: {e}")
                return False
                
        else:
            logger.error("❌ Telegram not authorized")
            return False
            
    except Exception as e:
        logger.error(f"❌ Telegram startup failed: {e}")
        return False

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Telegram client lifecycle"""
    logger.info("🌟 Starting application...")
    
    # Initialize Telegram
    success = await init_telegram()
    if success:
        logger.info("✅ Telegram forwarding initialized successfully")
    else:
        logger.error("❌ Telegram forwarding failed to initialize")
    
    yield
    
    # Cleanup
    if telegram_client:
        logger.info("🔄 Disconnecting Telegram client...")
        await telegram_client.disconnect()

# FastAPI app with lifespan management
app = FastAPI(
    title="Telegram Forwarder + n8n API", 
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
async def root():
    """Root endpoint with service info"""
    return {
        "service": "Telegram Forwarder + n8n API",
        "status": "running",
        "telegram_connected": telegram_client is not None and telegram_client.is_connected() if telegram_client else False,
        "target_channel": target_channel_id,
        "api_key_required": bool(N8N_API_KEY),
        "forwarding_active": source_entity is not None and target_entity is not None,
        "endpoints": {
            "health": "/health",
            "messages": "/api/messages/{hours}",
            "combined": "/api/messages/{hours}/combined",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "telegram_connected": telegram_client is not None and telegram_client.is_connected() if telegram_client else False,
        "target_channel_configured": target_channel_id is not None,
        "forwarding_configured": source_entity is not None and target_entity is not None,
        "api_auth": "enabled" if N8N_API_KEY else "disabled"
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
            'messages': result['messages'],
            'processing_date': datetime.now().date().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ API Error creating combined messages: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error creating combined messages: {str(e)}"
        )

# Run the server
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🌐 Starting Telegram Forwarder + FastAPI on port {port}")
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        log_level="info"
    )
