"""
Social Media API Service
A REST API wrapper for TikTok and Instagram providing video/post stats, author stats, and more.
"""

import os
import re
import sys
import asyncio
import random
import time
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

from TikTokApi import TikTokApi
from instagrapi import Client as InstaClient
from instagrapi.exceptions import (
    LoginRequired,
    ChallengeRequired,
    TwoFactorRequired,
    PleaseWaitFewMinutes,
)

# Load environment variables
load_dotenv()

# ===== Configuration =====
# TikTok
MS_TOKEN = os.getenv("MS_TOKEN")
TIKTOK_BROWSER = os.getenv("TIKTOK_BROWSER", "chromium")

# Instagram
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")
INSTAGRAM_SESSION_ID = os.getenv("INSTAGRAM_SESSION_ID")  # Alternative: use session ID from browser cookies
INSTAGRAM_SESSION_FILE = os.getenv("INSTAGRAM_SESSION_FILE", "instagram_session.json")
INSTAGRAM_PROXY = os.getenv("INSTAGRAM_PROXY")  # Rotating proxy for Instagram (e.g., http://user:pass@host:port)

# General
PROXY_URL = os.getenv("PROXY_URL")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))

# API Security
API_KEY = os.getenv("API_KEY")  # Secret key for API access

# Anti-detection settings
MIN_REQUEST_DELAY = float(os.getenv("MIN_REQUEST_DELAY", "1.0"))  # Minimum seconds between requests
MAX_REQUEST_DELAY = float(os.getenv("MAX_REQUEST_DELAY", "3.0"))  # Maximum seconds between requests
ENABLE_ANTI_DETECTION = os.getenv("ENABLE_ANTI_DETECTION", "true").lower() == "true"

# Track last request time for rate limiting
last_tiktok_request_time = 0
last_instagram_request_time = 0

# ===== Global State =====
# TikTok
tiktok_api: Optional[TikTokApi] = None
tiktok_session_initialized = False
tiktok_session_error: Optional[str] = None

# Instagram
instagram_client: Optional[InstaClient] = None
instagram_session_initialized = False
instagram_session_error: Optional[str] = None


# ===== Pydantic Models - TikTok =====
class TikTokVideoStats(BaseModel):
    """TikTok Video statistics"""
    model_config = ConfigDict(populate_by_name=True)
    
    views: int = Field(alias="playCount", default=0)
    likes: int = Field(alias="diggCount", default=0)
    comments: int = Field(alias="commentCount", default=0)
    shares: int = Field(alias="shareCount", default=0)


class TikTokAuthorInfo(BaseModel):
    """TikTok Author basic information"""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = ""
    username: str = Field(alias="uniqueId", default="")
    nickname: str = ""
    avatar: Optional[str] = Field(alias="avatarThumb", default=None)


class TikTokAuthorStats(BaseModel):
    """TikTok Author statistics"""
    model_config = ConfigDict(populate_by_name=True)
    
    followers: int = Field(alias="followerCount", default=0)
    following: int = Field(alias="followingCount", default=0)
    likes: int = Field(alias="heartCount", default=0)
    video_count: int = Field(alias="videoCount", default=0)


class TikTokVideoResponse(BaseModel):
    """TikTok Full video response"""
    id: str
    description: str = ""
    create_time: datetime
    create_time_iso: str
    stats: TikTokVideoStats
    author: TikTokAuthorInfo


class TikTokUserResponse(BaseModel):
    """TikTok Full user response"""
    id: str
    username: str
    nickname: str
    bio: str = ""
    avatar: Optional[str] = None
    stats: TikTokAuthorStats


class TikTokCommentAuthor(BaseModel):
    """TikTok Comment author info"""
    id: str = ""
    username: str = ""
    nickname: str = ""
    avatar: Optional[str] = None


class TikTokComment(BaseModel):
    """TikTok Video comment"""
    id: str = ""
    text: str = ""
    create_time: Optional[datetime] = None
    create_time_iso: str = ""
    likes: int = 0
    reply_count: int = 0
    author: TikTokCommentAuthor


class TikTokCommentsResponse(BaseModel):
    """TikTok Comments response"""
    video_id: str
    count: int
    comments: List[TikTokComment]


# ===== Pydantic Models - Instagram =====
class InstagramUserStats(BaseModel):
    """Instagram user statistics"""
    followers: int = 0
    following: int = 0
    posts_count: int = 0


class InstagramUserResponse(BaseModel):
    """Instagram user response"""
    id: str
    username: str
    full_name: str = ""
    bio: str = ""
    avatar: Optional[str] = None
    is_private: bool = False
    is_verified: bool = False
    external_url: Optional[str] = None
    stats: InstagramUserStats


class InstagramMediaStats(BaseModel):
    """Instagram media statistics"""
    likes: int = 0
    comments: int = 0
    views: Optional[int] = None  # For videos/reels


class InstagramMediaResponse(BaseModel):
    """Instagram media/post response"""
    id: str
    pk: str
    code: str  # Shortcode for URL
    media_type: str  # photo, video, album, reel, igtv
    caption: str = ""
    create_time: Optional[datetime] = None
    create_time_iso: str = ""
    thumbnail_url: Optional[str] = None
    video_url: Optional[str] = None
    stats: InstagramMediaStats
    author_username: str = ""


class InstagramCommentAuthor(BaseModel):
    """Instagram comment author"""
    id: str = ""
    username: str = ""
    full_name: str = ""
    avatar: Optional[str] = None


class InstagramComment(BaseModel):
    """Instagram comment"""
    id: str = ""
    text: str = ""
    create_time: Optional[datetime] = None
    create_time_iso: str = ""
    likes: int = 0
    author: InstagramCommentAuthor


class InstagramCommentsResponse(BaseModel):
    """Instagram comments response with pagination"""
    media_id: str
    count: int
    comments: List[InstagramComment]
    next_cursor: Optional[str] = None
    has_more: bool = False


class InstagramFollowerResponse(BaseModel):
    """Instagram follower/following user"""
    id: str
    username: str
    full_name: str = ""
    avatar: Optional[str] = None
    is_private: bool = False
    is_verified: bool = False


class InstagramStoryResponse(BaseModel):
    """Instagram story item"""
    id: str
    pk: str
    media_type: str
    taken_at: Optional[datetime] = None
    taken_at_iso: str = ""
    thumbnail_url: Optional[str] = None
    video_url: Optional[str] = None


# ===== Pydantic Models - General =====
class VideoUrlRequest(BaseModel):
    """Request body for video/post URL endpoint"""
    url: str


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    tiktok: dict
    instagram: dict


# ===== TikTok Helper Functions =====
def extract_tiktok_video_id(url: str) -> str:
    """Extract video ID from TikTok URL"""
    patterns = [
        r'tiktok\.com/@[\w.-]+/video/(\d+)',
        r'vm\.tiktok\.com/(\w+)',
        r'tiktok\.com/t/(\w+)',
        r'/video/(\d+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    if url.isdigit():
        return url
    
    raise ValueError(f"Could not extract video ID from URL: {url}")


def parse_tiktok_video_data(video_dict: dict) -> TikTokVideoResponse:
    """Parse TikTok video dictionary into response model"""
    stats_data = video_dict.get("stats", {})
    author_data = video_dict.get("author", {})
    
    create_time_raw = video_dict.get("createTime", 0)
    try:
        create_time_unix = int(create_time_raw) if create_time_raw else 0
        create_time = datetime.fromtimestamp(create_time_unix)
    except (ValueError, TypeError, OSError):
        create_time = datetime.now()
    
    return TikTokVideoResponse(
        id=video_dict.get("id", ""),
        description=video_dict.get("desc", ""),
        create_time=create_time,
        create_time_iso=create_time.isoformat(),
        stats=TikTokVideoStats(
            playCount=stats_data.get("playCount", 0),
            diggCount=stats_data.get("diggCount", 0),
            commentCount=stats_data.get("commentCount", 0),
            shareCount=stats_data.get("shareCount", 0)
        ),
        author=TikTokAuthorInfo(
            id=author_data.get("id", ""),
            uniqueId=author_data.get("uniqueId", ""),
            nickname=author_data.get("nickname", ""),
            avatarThumb=author_data.get("avatarThumb")
        )
    )


def parse_tiktok_user_data(user_dict: dict) -> TikTokUserResponse:
    """Parse TikTok user dictionary into response model"""
    if "userInfo" in user_dict:
        user_info = user_dict["userInfo"]
        user_data = user_info.get("user", {})
        stats_data = user_info.get("stats", {})
    elif "user" in user_dict:
        user_data = user_dict["user"]
        stats_data = user_dict.get("stats", {})
    else:
        user_data = user_dict
        stats_data = user_dict.get("stats", {})
    
    return TikTokUserResponse(
        id=str(user_data.get("id", "")),
        username=user_data.get("uniqueId", "") or user_data.get("unique_id", ""),
        nickname=user_data.get("nickname", ""),
        bio=user_data.get("signature", ""),
        avatar=user_data.get("avatarThumb") or user_data.get("avatar_thumb"),
        stats=TikTokAuthorStats(
            followerCount=stats_data.get("followerCount", 0) or stats_data.get("follower_count", 0),
            followingCount=stats_data.get("followingCount", 0) or stats_data.get("following_count", 0),
            heartCount=stats_data.get("heartCount", 0) or stats_data.get("heart_count", 0) or stats_data.get("heart", 0),
            videoCount=stats_data.get("videoCount", 0) or stats_data.get("video_count", 0)
        )
    )


def parse_tiktok_comment(comment_dict: dict) -> TikTokComment:
    """Parse TikTok comment dictionary into Comment model"""
    author_data = comment_dict.get("user", {}) or comment_dict.get("author", {})
    
    create_time_raw = comment_dict.get("createTime", 0) or comment_dict.get("create_time", 0)
    try:
        create_time_unix = int(create_time_raw) if create_time_raw else 0
        create_time = datetime.fromtimestamp(create_time_unix) if create_time_unix else None
    except (ValueError, TypeError, OSError):
        create_time = None
    
    avatar_raw = author_data.get("avatarThumb") or author_data.get("avatar_thumb") or author_data.get("avatar")
    if isinstance(avatar_raw, dict):
        avatar = avatar_raw.get("uri") or avatar_raw.get("url") or str(avatar_raw)
    else:
        avatar = avatar_raw if isinstance(avatar_raw, str) else None
    
    return TikTokComment(
        id=str(comment_dict.get("cid", "") or comment_dict.get("id", "")),
        text=comment_dict.get("text", "") or comment_dict.get("comment", ""),
        create_time=create_time,
        create_time_iso=create_time.isoformat() if create_time else "",
        likes=comment_dict.get("diggCount", 0) or comment_dict.get("digg_count", 0) or comment_dict.get("likes", 0),
        reply_count=comment_dict.get("replyCommentTotal", 0) or comment_dict.get("reply_count", 0),
        author=TikTokCommentAuthor(
            id=str(author_data.get("id", "") or author_data.get("uid", "")),
            username=author_data.get("uniqueId", "") or author_data.get("unique_id", ""),
            nickname=author_data.get("nickname", ""),
            avatar=avatar
        )
    )


# ===== Anti-Detection Helper Functions =====
# Realistic user agents for different platforms
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Chrome on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

# Realistic viewport sizes
VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
]

# Instagram device settings for mobile API
INSTAGRAM_DEVICES = [
    {
        "app_version": "269.0.0.18.75",
        "android_version": 31,
        "android_release": "12.0",
        "dpi": "480dpi",
        "resolution": "1080x2400",
        "manufacturer": "Samsung",
        "device": "SM-G991B",
        "model": "Galaxy S21",
        "cpu": "exynos2100",
        "version_code": "314665256",
    },
    {
        "app_version": "269.0.0.18.75",
        "android_version": 33,
        "android_release": "13.0",
        "dpi": "420dpi",
        "resolution": "1080x2340",
        "manufacturer": "Google",
        "device": "Pixel 7",
        "model": "Pixel 7",
        "cpu": "tensor",
        "version_code": "314665256",
    },
    {
        "app_version": "269.0.0.18.75",
        "android_version": 32,
        "android_release": "12.1",
        "dpi": "440dpi",
        "resolution": "1440x3200",
        "manufacturer": "Samsung",
        "device": "SM-S908B",
        "model": "Galaxy S22 Ultra",
        "cpu": "exynos2200",
        "version_code": "314665256",
    },
]


def get_random_user_agent() -> str:
    """Get a random realistic user agent"""
    return random.choice(USER_AGENTS)


def get_random_viewport() -> dict:
    """Get a random realistic viewport size"""
    return random.choice(VIEWPORT_SIZES)


def get_random_device() -> dict:
    """Get a random Instagram device configuration"""
    return random.choice(INSTAGRAM_DEVICES)


async def apply_request_delay(platform: str = "tiktok"):
    """Apply a random delay between requests to avoid rate limiting"""
    global last_tiktok_request_time, last_instagram_request_time
    
    if not ENABLE_ANTI_DETECTION:
        return
    
    current_time = time.time()
    last_request_time = last_tiktok_request_time if platform == "tiktok" else last_instagram_request_time
    
    # Calculate time since last request
    time_since_last = current_time - last_request_time
    
    # Apply delay if needed
    min_delay = MIN_REQUEST_DELAY
    max_delay = MAX_REQUEST_DELAY
    
    if time_since_last < min_delay:
        # Add random delay
        delay = random.uniform(min_delay, max_delay)
        await asyncio.sleep(delay)
    
    # Update last request time
    if platform == "tiktok":
        last_tiktok_request_time = time.time()
    else:
        last_instagram_request_time = time.time()


def apply_request_delay_sync(platform: str = "instagram"):
    """Synchronous version of request delay for Instagram"""
    global last_tiktok_request_time, last_instagram_request_time
    
    if not ENABLE_ANTI_DETECTION:
        return
    
    current_time = time.time()
    last_request_time = last_instagram_request_time if platform == "instagram" else last_tiktok_request_time
    
    # Calculate time since last request
    time_since_last = current_time - last_request_time
    
    # Apply delay if needed
    if time_since_last < MIN_REQUEST_DELAY:
        delay = random.uniform(MIN_REQUEST_DELAY, MAX_REQUEST_DELAY)
        time.sleep(delay)
    
    # Update last request time
    if platform == "instagram":
        last_instagram_request_time = time.time()
    else:
        last_tiktok_request_time = time.time()


async def ensure_tiktok_session():
    """Ensure TikTok session is initialized with anti-detection measures"""
    global tiktok_api, tiktok_session_initialized, tiktok_session_error
    
    if tiktok_session_initialized:
        return
    
    if not MS_TOKEN:
        tiktok_session_error = "MS_TOKEN not configured"
        raise HTTPException(status_code=503, detail="TikTok MS_TOKEN not configured. Please set it in .env file.")
    
    try:
        tiktok_api = TikTokApi()
        
        # Get random viewport for fingerprint variation
        viewport = get_random_viewport() if ENABLE_ANTI_DETECTION else {"width": 1920, "height": 1080}
        
        # Stealth browser arguments to avoid detection
        stealth_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-background-networking",
            "--disable-breakpad",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-hang-monitor",
            "--disable-popup-blocking",
            "--disable-prompt-on-repost",
            "--disable-sync",
            "--disable-translate",
            "--metrics-recording-only",
            "--no-first-run",
            "--safebrowsing-disable-auto-update",
            "--password-store=basic",
            "--use-mock-keychain",
        ]
        
        # Random sleep before creating session (1-3 seconds)
        if ENABLE_ANTI_DETECTION:
            await asyncio.sleep(random.uniform(1, 3))
        
        await tiktok_api.create_sessions(
            ms_tokens=[MS_TOKEN],
            num_sessions=1,
            sleep_after=random.randint(3, 5) if ENABLE_ANTI_DETECTION else 3,
            browser=TIKTOK_BROWSER,
            headless=True,
            context_options={
                "viewport": viewport,
                "user_agent": get_random_user_agent() if ENABLE_ANTI_DETECTION else None,
                "locale": "en-US",
                "timezone_id": "America/New_York",
            },
            override_browser_args=stealth_args
        )
        tiktok_session_initialized = True
        tiktok_session_error = None
        print("✅ TikTok API session created successfully (with anti-detection)")
    except Exception as e:
        error_msg = str(e)
        tiktok_session_error = error_msg
        
        # Provide helpful error messages
        if "Timeout" in error_msg:
            detail = (
                "TikTok connection timed out. Possible causes:\n"
                "1. Your MS_TOKEN may be expired - get a fresh one from browser cookies\n"
                "2. TikTok may be blocking your IP - try using a VPN or proxy\n"
                "3. Network issues - check your internet connection\n"
                f"Original error: {error_msg}"
            )
        elif "ms_token" in error_msg.lower():
            detail = "Invalid MS_TOKEN. Please get a fresh msToken from TikTok cookies in your browser."
        else:
            detail = f"Failed to create TikTok session: {error_msg}"
        
        raise HTTPException(status_code=503, detail=detail)


# ===== Instagram Helper Functions =====
def get_media_type_str(media_type: int, product_type: str = None) -> str:
    """Convert Instagram media type to string"""
    if product_type == "clips":
        return "reel"
    if product_type == "igtv":
        return "igtv"
    
    media_types = {
        1: "photo",
        2: "video",
        8: "album"
    }
    return media_types.get(media_type, "unknown")


def parse_instagram_user(user) -> InstagramUserResponse:
    """Parse instagrapi User object to response model"""
    return InstagramUserResponse(
        id=str(user.pk),
        username=user.username,
        full_name=user.full_name or "",
        bio=user.biography or "",
        avatar=str(user.profile_pic_url) if user.profile_pic_url else None,
        is_private=user.is_private,
        is_verified=user.is_verified,
        external_url=str(user.external_url) if user.external_url else None,
        stats=InstagramUserStats(
            followers=user.follower_count or 0,
            following=user.following_count or 0,
            posts_count=user.media_count or 0
        )
    )


def parse_instagram_media(media) -> InstagramMediaResponse:
    """Parse instagrapi Media object to response model"""
    taken_at = media.taken_at
    
    # For Reels, check play_count in addition to view_count
    view_count = (
        getattr(media, 'play_count', None) or 
        getattr(media, 'ig_play_count', None) or
        getattr(media, 'video_play_count', None) or
        getattr(media, 'view_count', None) or
        getattr(media, 'video_view_count', None)
    )
    
    return InstagramMediaResponse(
        id=str(media.id),
        pk=str(media.pk),
        code=media.code,
        media_type=get_media_type_str(media.media_type, getattr(media, 'product_type', None)),
        caption=media.caption_text or "",
        create_time=taken_at,
        create_time_iso=taken_at.isoformat() if taken_at else "",
        thumbnail_url=str(media.thumbnail_url) if media.thumbnail_url else None,
        video_url=str(media.video_url) if media.video_url else None,
        stats=InstagramMediaStats(
            likes=media.like_count or 0,
            comments=media.comment_count or 0,
            views=view_count
        ),
        author_username=media.user.username if media.user else ""
    )


def parse_instagram_media_dict(data: dict) -> InstagramMediaResponse:
    """Parse Instagram media from raw dict (for GQL responses)"""
    from datetime import datetime
    
    # Handle different response structures
    taken_at_raw = data.get('taken_at') or data.get('taken_at_timestamp')
    if taken_at_raw:
        try:
            taken_at = datetime.fromtimestamp(int(taken_at_raw))
        except:
            taken_at = None
    else:
        taken_at = None
    
    # Get media type
    media_type_raw = data.get('media_type', 1)
    product_type = data.get('product_type')
    media_type = get_media_type_str(media_type_raw, product_type)
    
    # Get thumbnail
    thumbnail = None
    if 'thumbnail_url' in data:
        thumbnail = data['thumbnail_url']
    elif 'image_versions2' in data:
        candidates = data['image_versions2'].get('candidates', [])
        if candidates:
            thumbnail = candidates[0].get('url')
    elif 'display_url' in data:
        thumbnail = data['display_url']
    
    # Get video url
    video_url = data.get('video_url')
    if not video_url and 'video_versions' in data:
        versions = data.get('video_versions', [])
        if versions:
            video_url = versions[0].get('url')
    
    # Get stats
    like_count = data.get('like_count', 0) or data.get('edge_media_preview_like', {}).get('count', 0)
    comment_count = data.get('comment_count', 0) or data.get('edge_media_to_comment', {}).get('count', 0)
    # For Reels, Instagram uses 'play_count' instead of 'view_count'
    view_count = (
        data.get('play_count') or 
        data.get('ig_play_count') or 
        data.get('video_play_count') or
        data.get('view_count') or 
        data.get('video_view_count') or
        data.get('fb_play_count') or
        data.get('clips_metadata', {}).get('play_count') if isinstance(data.get('clips_metadata'), dict) else None
    )
    
    # Get author
    user = data.get('user', {})
    author = user.get('username', '') if isinstance(user, dict) else ''
    
    return InstagramMediaResponse(
        id=str(data.get('id', '')),
        pk=str(data.get('pk', data.get('id', ''))),
        code=data.get('code', data.get('shortcode', '')),
        media_type=media_type,
        caption=data.get('caption', {}).get('text', '') if isinstance(data.get('caption'), dict) else (data.get('caption_text', '') or data.get('caption', '') or ''),
        create_time=taken_at,
        create_time_iso=taken_at.isoformat() if taken_at else "",
        thumbnail_url=thumbnail,
        video_url=video_url,
        stats=InstagramMediaStats(
            likes=like_count,
            comments=comment_count,
            views=view_count
        ),
        author_username=author
    )


def parse_instagram_comment(comment) -> InstagramComment:
    """Parse instagrapi Comment object to response model"""
    created_at = comment.created_at_utc
    
    return InstagramComment(
        id=str(comment.pk),
        text=comment.text or "",
        create_time=created_at,
        create_time_iso=created_at.isoformat() if created_at else "",
        likes=comment.like_count or 0,
        author=InstagramCommentAuthor(
            id=str(comment.user.pk) if comment.user else "",
            username=comment.user.username if comment.user else "",
            full_name=comment.user.full_name if comment.user else "",
            avatar=str(comment.user.profile_pic_url) if comment.user and comment.user.profile_pic_url else None
        )
    )


def parse_instagram_comment_dict(data: dict) -> InstagramComment:
    """Parse Instagram comment from raw dict"""
    from datetime import datetime
    
    # Handle created_at timestamp
    created_at_raw = data.get('created_at') or data.get('created_at_utc')
    if created_at_raw:
        try:
            created_at = datetime.fromtimestamp(int(created_at_raw))
        except:
            created_at = None
    else:
        created_at = None
    
    # Get user info
    user = data.get('user', {})
    
    return InstagramComment(
        id=str(data.get('pk', data.get('id', ''))),
        text=data.get('text', ''),
        create_time=created_at,
        create_time_iso=created_at.isoformat() if created_at else "",
        likes=data.get('comment_like_count', 0) or data.get('like_count', 0),
        author=InstagramCommentAuthor(
            id=str(user.get('pk', user.get('id', ''))),
            username=user.get('username', ''),
            full_name=user.get('full_name', ''),
            avatar=user.get('profile_pic_url')
        )
    )


def parse_instagram_follower(user) -> InstagramFollowerResponse:
    """Parse instagrapi UserShort object to follower response"""
    return InstagramFollowerResponse(
        id=str(user.pk),
        username=user.username,
        full_name=user.full_name or "",
        avatar=str(user.profile_pic_url) if user.profile_pic_url else None,
        is_private=getattr(user, 'is_private', False),
        is_verified=getattr(user, 'is_verified', False)
    )


def parse_instagram_story(story) -> InstagramStoryResponse:
    """Parse instagrapi Story object to response model"""
    taken_at = story.taken_at
    
    return InstagramStoryResponse(
        id=str(story.id),
        pk=str(story.pk),
        media_type=get_media_type_str(story.media_type),
        taken_at=taken_at,
        taken_at_iso=taken_at.isoformat() if taken_at else "",
        thumbnail_url=str(story.thumbnail_url) if story.thumbnail_url else None,
        video_url=str(story.video_url) if story.video_url else None
    )


def ensure_instagram_session():
    """Ensure Instagram session is initialized with anti-detection measures"""
    global instagram_client, instagram_session_initialized, instagram_session_error
    
    if instagram_session_initialized:
        return
    
    # Check if we have any credentials
    has_session_id = bool(INSTAGRAM_SESSION_ID)
    has_user_pass = bool(INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD)
    
    if not has_session_id and not has_user_pass:
        instagram_session_error = "Instagram credentials not configured"
        raise HTTPException(
            status_code=503, 
            detail="Instagram credentials not configured. Please set INSTAGRAM_SESSION_ID or (INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD) in .env file."
        )
    
    try:
        instagram_client = InstaClient()
        
        # Apply proxy if configured (helps avoid account suspension)
        if INSTAGRAM_PROXY:
            instagram_client.set_proxy(INSTAGRAM_PROXY)
            print(f"✅ Instagram proxy configured: {INSTAGRAM_PROXY.split('@')[-1] if '@' in INSTAGRAM_PROXY else 'proxy enabled'}")
        session_path = Path(INSTAGRAM_SESSION_FILE)
        
        # Apply anti-detection device settings
        if ENABLE_ANTI_DETECTION:
            device = get_random_device()
            instagram_client.set_device({
                "app_version": device["app_version"],
                "android_version": device["android_version"],
                "android_release": device["android_release"],
                "dpi": device["dpi"],
                "resolution": device["resolution"],
                "manufacturer": device["manufacturer"],
                "device": device["device"],
                "model": device["model"],
                "cpu": device["cpu"],
                "version_code": device["version_code"],
            })
            
            # Set realistic user agent for Instagram
            instagram_client.set_user_agent(
                f"Instagram {device['app_version']} Android ({device['android_version']}/{device['android_release']}; "
                f"{device['dpi']}; {device['resolution']}; {device['manufacturer']}; {device['device']}; "
                f"{device['device']}; {device['cpu']}; en_US; {device['version_code']})"
            )
            
            # Set request timeout and delays
            instagram_client.delay_range = [0, 0]  # Disable internal delays - we handle delays at endpoint level
            
            # Random delay before login
            time.sleep(random.uniform(1, 2))
        
        # Priority 1: Use session ID if provided (most reliable)
        if has_session_id:
            try:
                instagram_client.login_by_sessionid(INSTAGRAM_SESSION_ID)
                instagram_client.dump_settings(session_path)
                instagram_session_initialized = True
                instagram_session_error = None
                print("✅ Instagram login successful via session ID (with anti-detection)")
                return
            except Exception as e:
                print(f"⚠️ Session ID login failed: {e}, trying other methods...")
        
        # Priority 2: Try to load existing session file
        if session_path.exists():
            try:
                instagram_client.load_settings(session_path)
                # Re-apply device settings after loading
                if ENABLE_ANTI_DETECTION:
                    device = get_random_device()
                    instagram_client.set_device({
                        "app_version": device["app_version"],
                        "android_version": device["android_version"],
                        "android_release": device["android_release"],
                        "dpi": device["dpi"],
                        "resolution": device["resolution"],
                        "manufacturer": device["manufacturer"],
                        "device": device["device"],
                        "model": device["model"],
                        "cpu": device["cpu"],
                        "version_code": device["version_code"],
                    })
                
                # Validate session with a fast API call (instead of slow timeline fetch)
                apply_request_delay_sync("instagram")
                instagram_client.account_info()
                instagram_session_initialized = True
                instagram_session_error = None
                print("✅ Instagram session loaded from file (with anti-detection)")
                return
            except Exception:
                print("⚠️ Saved session expired, trying fresh login...")
                instagram_client = InstaClient()
                # Re-apply device settings for new client
                if ENABLE_ANTI_DETECTION:
                    device = get_random_device()
                    instagram_client.set_device({
                        "app_version": device["app_version"],
                        "android_version": device["android_version"],
                        "android_release": device["android_release"],
                        "dpi": device["dpi"],
                        "resolution": device["resolution"],
                        "manufacturer": device["manufacturer"],
                        "device": device["device"],
                        "model": device["model"],
                        "cpu": device["cpu"],
                        "version_code": device["version_code"],
                    })
                    instagram_client.delay_range = [0, 0]  # Disable internal delays
        
        # Priority 3: Username/password login
        if has_user_pass:
            apply_request_delay_sync("instagram")
            instagram_client.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            instagram_client.dump_settings(session_path)
            instagram_session_initialized = True
            instagram_session_error = None
            print("✅ Instagram login successful, session saved (with anti-detection)")
            return
        
        raise Exception("No valid login method available")
        
    except TwoFactorRequired:
        instagram_session_error = "Two-factor authentication required"
        raise HTTPException(status_code=503, detail="Instagram 2FA required. Please disable 2FA or use session ID login.")
    except ChallengeRequired:
        instagram_session_error = "Challenge required (suspicious login detected)"
        raise HTTPException(status_code=503, detail="Instagram challenge required. Please use session ID login instead.")
    except PleaseWaitFewMinutes:
        instagram_session_error = "Rate limited - please wait"
        raise HTTPException(status_code=429, detail="Instagram rate limited. Please wait a few minutes.")
    except Exception as e:
        instagram_session_error = str(e)
        raise HTTPException(status_code=503, detail=f"Failed to login to Instagram: {str(e)}")


# ===== FastAPI Application =====
app = FastAPI(
    title="Social Media API Service",
    description="REST API for fetching TikTok and Instagram stats, posts, comments, and more",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== API Key Security =====
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Verify API key for protected endpoints"""
    if not API_KEY:
        # If no API key is configured, allow access (development mode)
        return True
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Please provide X-API-Key header."
        )
    
    if api_key != API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key."
        )
    
    return True


# ===== System Endpoints =====
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint for both platforms"""
    return HealthResponse(
        status="healthy",
        tiktok={
            "ms_token_configured": bool(MS_TOKEN),
            "session_initialized": tiktok_session_initialized,
            "session_error": tiktok_session_error
        },
        instagram={
            "credentials_configured": bool(INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD),
            "session_initialized": instagram_session_initialized,
            "session_error": instagram_session_error
        }
    )


@app.post("/tiktok/init", tags=["TikTok - System"], dependencies=[Depends(verify_api_key)])
async def init_tiktok_session():
    """Initialize TikTok session manually"""
    await ensure_tiktok_session()
    return {"status": "initialized", "message": "TikTok session initialized successfully"}


@app.post("/instagram/init", tags=["Instagram - System"], dependencies=[Depends(verify_api_key)])
async def init_instagram_session():
    """Initialize Instagram session manually"""
    ensure_instagram_session()
    return {"status": "initialized", "message": "Instagram session initialized successfully"}


# ===== TikTok Endpoints =====
@app.get("/tiktok/video/{video_id}", response_model=TikTokVideoResponse, tags=["TikTok - Video"], dependencies=[Depends(verify_api_key)])
async def get_tiktok_video_by_id(video_id: str):
    """Get TikTok video information by video ID"""
    await ensure_tiktok_session()
    await apply_request_delay("tiktok")
    
    try:
        video_url = f"https://www.tiktok.com/@user/video/{video_id}"
        video = tiktok_api.video(url=video_url)
        video_data = await video.info()
        return parse_tiktok_video_data(video_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching TikTok video: {str(e)}")


@app.post("/tiktok/video/url", response_model=TikTokVideoResponse, tags=["TikTok - Video"], dependencies=[Depends(verify_api_key)])
async def get_tiktok_video_by_url(request: VideoUrlRequest):
    """Get TikTok video information from URL"""
    await ensure_tiktok_session()
    await apply_request_delay("tiktok")
    
    try:
        video = tiktok_api.video(url=request.url)
        video_data = await video.info()
        return parse_tiktok_video_data(video_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching TikTok video: {str(e)}")


@app.get("/tiktok/video/{video_id}/comments", response_model=TikTokCommentsResponse, tags=["TikTok - Video"], dependencies=[Depends(verify_api_key)])
async def get_tiktok_video_comments(
    video_id: str,
    count: int = Query(default=50, ge=1, le=200, description="Number of comments to fetch")
):
    """Get comments from a TikTok video"""
    await ensure_tiktok_session()
    await apply_request_delay("tiktok")
    
    try:
        video_url = f"https://www.tiktok.com/@user/video/{video_id}"
        video = tiktok_api.video(url=video_url)
        
        comments = []
        async for comment in video.comments(count=count):
            comment_data = comment.as_dict if hasattr(comment, 'as_dict') else comment
            comments.append(parse_tiktok_comment(comment_data))
        
        return TikTokCommentsResponse(
            video_id=video_id,
            count=len(comments),
            comments=comments
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching TikTok comments: {str(e)}")


@app.get("/tiktok/user/{username}", response_model=TikTokUserResponse, tags=["TikTok - User"], dependencies=[Depends(verify_api_key)])
async def get_tiktok_user_by_username(username: str):
    """Get TikTok user information by username"""
    await ensure_tiktok_session()
    await apply_request_delay("tiktok")
    
    username = username.lstrip("@")
    
    try:
        user = tiktok_api.user(username=username)
        user_data = await user.info()
        return parse_tiktok_user_data(user_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching TikTok user: {str(e)}")


@app.get("/tiktok/user/{username}/videos", tags=["TikTok - User"], dependencies=[Depends(verify_api_key)])
async def get_tiktok_user_videos(
    username: str,
    count: int = Query(default=10, ge=1, le=50, description="Number of videos to fetch")
):
    """Get recent videos from a TikTok user"""
    await ensure_tiktok_session()
    await apply_request_delay("tiktok")
    
    username = username.lstrip("@")
    
    try:
        user = tiktok_api.user(username=username)
        videos = []
        
        async for video in user.videos(count=count):
            video_data = video.as_dict
            videos.append(parse_tiktok_video_data(video_data))
        
        return {"username": username, "count": len(videos), "videos": videos}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching TikTok user videos: {str(e)}")


# ===== Instagram Endpoints =====
@app.get("/instagram/user/{username}", response_model=InstagramUserResponse, tags=["Instagram - User"], dependencies=[Depends(verify_api_key)])
async def get_instagram_user_by_username(username: str):
    """Get Instagram user information by username"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    username = username.lstrip("@")
    
    try:
        # Use V1 API directly to avoid slow GQL timeout
        try:
            user = instagram_client.user_info_by_username_v1(username)
            return parse_instagram_user(user)
        except Exception as v1_error:
            print(f"V1 user lookup failed: {v1_error}, trying raw API...")
            # Fallback to raw API request
            response = instagram_client.private_request(
                f"users/web_profile_info/",
                params={"username": username}
            )
            user_data = response.get('data', {}).get('user', {})
            if not user_data:
                raise Exception("User not found")
            
            return InstagramUserResponse(
                id=str(user_data.get('id', '')),
                username=user_data.get('username', ''),
                full_name=user_data.get('full_name', ''),
                bio=user_data.get('biography', ''),
                avatar=user_data.get('profile_pic_url'),
                is_private=user_data.get('is_private', False),
                is_verified=user_data.get('is_verified', False),
                external_url=user_data.get('external_url'),
                stats=InstagramUserStats(
                    followers=user_data.get('edge_followed_by', {}).get('count', 0) or user_data.get('follower_count', 0),
                    following=user_data.get('edge_follow', {}).get('count', 0) or user_data.get('following_count', 0),
                    posts_count=user_data.get('edge_owner_to_timeline_media', {}).get('count', 0) or user_data.get('media_count', 0)
                )
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram user: {str(e)}")


@app.get("/instagram/user/{username}/posts", tags=["Instagram - User"], dependencies=[Depends(verify_api_key)])
async def get_instagram_user_posts(
    username: str,
    count: int = Query(default=12, ge=1, le=50, description="Number of posts to fetch")
):
    """Get recent posts from an Instagram user"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    username = username.lstrip("@")
    
    try:
        user_id = instagram_client.user_id_from_username(username)
        posts = []
        
        # Try GQL method first (more reliable)
        try:
            medias = instagram_client.user_medias_gql(user_id, count)
            for media in medias:
                try:
                    posts.append(parse_instagram_media(media))
                except Exception:
                    # If parsing fails, try raw dict
                    if hasattr(media, '__dict__'):
                        posts.append(parse_instagram_media_dict(media.__dict__))
        except Exception as gql_error:
            print(f"GQL method failed: {gql_error}, trying V1 API...")
            # Fallback to V1 API with raw request
            try:
                response = instagram_client.private_request(
                    f"feed/user/{user_id}/",
                    params={"count": count}
                )
                items = response.get('items', [])
                for item in items:
                    try:
                        posts.append(parse_instagram_media_dict(item))
                    except Exception as parse_error:
                        print(f"Failed to parse media: {parse_error}")
            except Exception as v1_error:
                print(f"V1 API also failed: {v1_error}")
        
        return {"username": username, "count": len(posts), "posts": posts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram posts: {str(e)}")


@app.get("/instagram/user/{username}/stories", tags=["Instagram - User"], dependencies=[Depends(verify_api_key)])
async def get_instagram_user_stories(username: str):
    """Get stories from an Instagram user"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    username = username.lstrip("@")
    
    try:
        user_id = instagram_client.user_id_from_username(username)
        stories = instagram_client.user_stories(user_id)
        
        story_list = [parse_instagram_story(story) for story in stories]
        
        return {"username": username, "count": len(story_list), "stories": story_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram stories: {str(e)}")


@app.get("/instagram/user/{username}/followers", tags=["Instagram - User"], dependencies=[Depends(verify_api_key)])
async def get_instagram_user_followers(
    username: str,
    count: int = Query(default=50, ge=1, le=200, description="Number of followers to fetch")
):
    """Get followers of an Instagram user"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    username = username.lstrip("@")
    
    try:
        user_id = instagram_client.user_id_from_username(username)
        followers = instagram_client.user_followers(user_id, amount=count)
        
        follower_list = [parse_instagram_follower(user) for user in followers.values()]
        
        return {"username": username, "count": len(follower_list), "followers": follower_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram followers: {str(e)}")


@app.get("/instagram/user/{username}/following", tags=["Instagram - User"], dependencies=[Depends(verify_api_key)])
async def get_instagram_user_following(
    username: str,
    count: int = Query(default=50, ge=1, le=200, description="Number of following to fetch")
):
    """Get users followed by an Instagram user"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    username = username.lstrip("@")
    
    try:
        user_id = instagram_client.user_id_from_username(username)
        following = instagram_client.user_following(user_id, amount=count)
        
        following_list = [parse_instagram_follower(user) for user in following.values()]
        
        return {"username": username, "count": len(following_list), "following": following_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram following: {str(e)}")


@app.get("/instagram/post/{media_id}", response_model=InstagramMediaResponse, tags=["Instagram - Post"], dependencies=[Depends(verify_api_key)])
async def get_instagram_post_by_id(media_id: str):
    """Get Instagram post information by media ID or shortcode"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    try:
        # Check if it's a shortcode (letters) or media PK (numbers)
        if media_id.isdigit():
            pk = media_id
        else:
            pk = instagram_client.media_pk_from_code(media_id)
        
        # Use raw API directly (faster, avoids slow internal methods)
        try:
            response = instagram_client.private_request(f"media/{pk}/info/")
            items = response.get('items', [])
            if items:
                return parse_instagram_media_dict(items[0])
            raise Exception("No media found in raw response")
        except Exception as raw_error:
            print(f"Raw API failed: {raw_error}, trying standard method...")
            # Fallback to standard method
            media = instagram_client.media_info(pk)
            return parse_instagram_media(media)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram post: {str(e)}")


@app.post("/instagram/post/url", response_model=InstagramMediaResponse, tags=["Instagram - Post"], dependencies=[Depends(verify_api_key)])
async def get_instagram_post_by_url(request: VideoUrlRequest):
    """Get Instagram post information from URL"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    try:
        pk = instagram_client.media_pk_from_url(request.url)
        
        # Use raw API directly (faster, avoids slow internal methods)
        try:
            response = instagram_client.private_request(f"media/{pk}/info/")
            items = response.get('items', [])
            if items:
                return parse_instagram_media_dict(items[0])
            raise Exception("No media found in raw response")
        except Exception as raw_error:
            print(f"Raw API failed: {raw_error}, trying standard method...")
            # Fallback to standard method
            media = instagram_client.media_info(pk)
            return parse_instagram_media(media)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram post: {str(e)}")


@app.get("/instagram/post/{media_id}/comments", response_model=InstagramCommentsResponse, tags=["Instagram - Post"], dependencies=[Depends(verify_api_key)])
async def get_instagram_post_comments(
    media_id: str,
    count: int = Query(default=50, ge=1, le=200, description="Number of comments to fetch per page"),
    cursor: Optional[str] = Query(default=None, description="Pagination cursor (min_id) from previous response")
):
    """Get comments from an Instagram post with pagination support.
    
    Instagram returns comments in pages. Use the 'next_cursor' from the response
    to fetch subsequent pages of comments.
    """
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    try:
        # Check if it's a shortcode or media PK
        if not media_id.isdigit():
            media_id = str(instagram_client.media_pk_from_code(media_id))
        
        comment_list = []
        next_cursor = None
        has_more = False
        
        # Try media_comments_chunk for pagination support
        try:
            comments, end_cursor = instagram_client.media_comments_chunk(
                media_id, 
                max_amount=count,
                min_id=cursor  # Use cursor for pagination
            )
            comment_list = [parse_instagram_comment(comment) for comment in comments]
            next_cursor = end_cursor
            has_more = bool(end_cursor)
        except Exception as e:
            print(f"media_comments_chunk failed: {e}, trying raw API...")
            # Fallback to raw API request with pagination
            try:
                params = {"count": count}
                if cursor:
                    params["min_id"] = cursor
                
                response = instagram_client.private_request(
                    f"media/{media_id}/comments/",
                    params=params
                )
                raw_comments = response.get('comments', [])
                for raw_comment in raw_comments:
                    try:
                        comment_list.append(parse_instagram_comment_dict(raw_comment))
                    except Exception as parse_error:
                        print(f"Failed to parse comment: {parse_error}")
                
                # Get pagination info from response
                next_cursor = response.get('next_min_id') or response.get('next_max_id')
                has_more = response.get('has_more_comments', False) or bool(next_cursor)
            except Exception as api_error:
                print(f"Raw API also failed: {api_error}")
        
        return InstagramCommentsResponse(
            media_id=str(media_id),
            count=len(comment_list),
            comments=comment_list,
            next_cursor=next_cursor,
            has_more=has_more
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram comments: {str(e)}")


@app.get("/instagram/post/{media_id}/likers", tags=["Instagram - Post"], dependencies=[Depends(verify_api_key)])
async def get_instagram_post_likers(media_id: str):
    """Get users who liked an Instagram post"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    try:
        # Check if it's a shortcode or media PK
        if not media_id.isdigit():
            media_id = instagram_client.media_pk_from_code(media_id)
        
        likers = instagram_client.media_likers(media_id)
        
        liker_list = [parse_instagram_follower(user) for user in likers]
        
        return {"media_id": str(media_id), "count": len(liker_list), "likers": liker_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram likers: {str(e)}")


@app.get("/instagram/hashtag/{name}/posts", tags=["Instagram - Hashtag"], dependencies=[Depends(verify_api_key)])
async def get_instagram_hashtag_posts(
    name: str,
    count: int = Query(default=20, ge=1, le=50, description="Number of posts to fetch")
):
    """Get top posts for a hashtag"""
    ensure_instagram_session()
    apply_request_delay_sync("instagram")
    
    name = name.lstrip("#")
    
    try:
        medias = instagram_client.hashtag_medias_top(name, amount=count)
        
        posts = [parse_instagram_media(media) for media in medias]
        
        return {"hashtag": name, "count": len(posts), "posts": posts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching Instagram hashtag posts: {str(e)}")


# ===== Backward Compatibility Endpoints (old paths still work) =====
@app.get("/video/{video_id}", response_model=TikTokVideoResponse, tags=["Legacy"], deprecated=True, dependencies=[Depends(verify_api_key)])
async def legacy_get_video_by_id(video_id: str):
    """[DEPRECATED] Use /tiktok/video/{video_id} instead"""
    return await get_tiktok_video_by_id(video_id)


@app.post("/video/url", response_model=TikTokVideoResponse, tags=["Legacy"], deprecated=True, dependencies=[Depends(verify_api_key)])
async def legacy_get_video_by_url(request: VideoUrlRequest):
    """[DEPRECATED] Use /tiktok/video/url instead"""
    return await get_tiktok_video_by_url(request)


@app.get("/user/{username}", response_model=TikTokUserResponse, tags=["Legacy"], deprecated=True, dependencies=[Depends(verify_api_key)])
async def legacy_get_user_by_username(username: str):
    """[DEPRECATED] Use /tiktok/user/{username} instead"""
    return await get_tiktok_user_by_username(username)


# ===== Run Server =====
if __name__ == "__main__":
    import uvicorn
    
    if sys.platform == "win32":
        uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
    else:
        uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
