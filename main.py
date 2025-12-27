"""
TikTok API Service
A REST API wrapper for the TikTok-Api library providing video stats, author stats, and publish dates.
"""

import os
import re
import sys
import asyncio
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

from TikTokApi import TikTokApi

# Load environment variables
load_dotenv()

# Configuration
MS_TOKEN = os.getenv("MS_TOKEN")
PROXY_URL = os.getenv("PROXY_URL")
TIKTOK_BROWSER = os.getenv("TIKTOK_BROWSER", "chromium")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))

# Global API instance and session state
api: Optional[TikTokApi] = None
session_initialized = False
session_error: Optional[str] = None


# Pydantic Models
class VideoStats(BaseModel):
    """Video statistics"""
    model_config = ConfigDict(populate_by_name=True)
    
    views: int = Field(alias="playCount", default=0)
    likes: int = Field(alias="diggCount", default=0)
    comments: int = Field(alias="commentCount", default=0)
    shares: int = Field(alias="shareCount", default=0)


class AuthorInfo(BaseModel):
    """Author basic information"""
    model_config = ConfigDict(populate_by_name=True)
    
    id: str = ""
    username: str = Field(alias="uniqueId", default="")
    nickname: str = ""
    avatar: Optional[str] = Field(alias="avatarThumb", default=None)


class AuthorStats(BaseModel):
    """Author statistics"""
    model_config = ConfigDict(populate_by_name=True)
    
    followers: int = Field(alias="followerCount", default=0)
    following: int = Field(alias="followingCount", default=0)
    likes: int = Field(alias="heartCount", default=0)
    video_count: int = Field(alias="videoCount", default=0)


class VideoResponse(BaseModel):
    """Full video response"""
    id: str
    description: str = ""
    create_time: datetime
    create_time_iso: str
    stats: VideoStats
    author: AuthorInfo


class UserResponse(BaseModel):
    """Full user response"""
    id: str
    username: str
    nickname: str
    bio: str = ""
    avatar: Optional[str] = None
    stats: AuthorStats


class VideoUrlRequest(BaseModel):
    """Request body for video URL endpoint"""
    url: str


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    ms_token_configured: bool
    proxy_configured: bool
    session_initialized: bool
    session_error: Optional[str] = None


class CommentAuthor(BaseModel):
    """Comment author info"""
    id: str = ""
    username: str = ""
    nickname: str = ""
    avatar: Optional[str] = None


class Comment(BaseModel):
    """Video comment"""
    id: str = ""
    text: str = ""
    create_time: Optional[datetime] = None
    create_time_iso: str = ""
    likes: int = 0
    reply_count: int = 0
    author: CommentAuthor


class CommentsResponse(BaseModel):
    """Comments response"""
    video_id: str
    count: int
    comments: list[Comment]


# Helper functions
def extract_video_id(url: str) -> str:
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


def parse_video_data(video_dict: dict) -> VideoResponse:
    """Parse video dictionary into response model"""
    stats_data = video_dict.get("stats", {})
    author_data = video_dict.get("author", {})
    
    # Handle createTime which could be string or integer
    create_time_raw = video_dict.get("createTime", 0)
    try:
        create_time_unix = int(create_time_raw) if create_time_raw else 0
        create_time = datetime.fromtimestamp(create_time_unix)
    except (ValueError, TypeError, OSError):
        # Fallback to current time if parsing fails
        create_time = datetime.now()
    
    return VideoResponse(
        id=video_dict.get("id", ""),
        description=video_dict.get("desc", ""),
        create_time=create_time,
        create_time_iso=create_time.isoformat(),
        stats=VideoStats(
            playCount=stats_data.get("playCount", 0),
            diggCount=stats_data.get("diggCount", 0),
            commentCount=stats_data.get("commentCount", 0),
            shareCount=stats_data.get("shareCount", 0)
        ),
        author=AuthorInfo(
            id=author_data.get("id", ""),
            uniqueId=author_data.get("uniqueId", ""),
            nickname=author_data.get("nickname", ""),
            avatarThumb=author_data.get("avatarThumb")
        )
    )



def parse_user_data(user_dict: dict) -> UserResponse:
    """Parse user dictionary into response model"""
    # TikTok-Api may return data in nested structure: userInfo.user and userInfo.stats
    # Or directly as a user dict
    
    # Check if data is nested under 'userInfo'
    if "userInfo" in user_dict:
        user_info = user_dict["userInfo"]
        user_data = user_info.get("user", {})
        stats_data = user_info.get("stats", {})
    elif "user" in user_dict:
        user_data = user_dict["user"]
        stats_data = user_dict.get("stats", {})
    else:
        # Assume the dict is the user data directly
        user_data = user_dict
        stats_data = user_dict.get("stats", {})
    
    return UserResponse(
        id=str(user_data.get("id", "")),
        username=user_data.get("uniqueId", "") or user_data.get("unique_id", ""),
        nickname=user_data.get("nickname", ""),
        bio=user_data.get("signature", ""),
        avatar=user_data.get("avatarThumb") or user_data.get("avatar_thumb"),
        stats=AuthorStats(
            followerCount=stats_data.get("followerCount", 0) or stats_data.get("follower_count", 0),
            followingCount=stats_data.get("followingCount", 0) or stats_data.get("following_count", 0),
            heartCount=stats_data.get("heartCount", 0) or stats_data.get("heart_count", 0) or stats_data.get("heart", 0),
            videoCount=stats_data.get("videoCount", 0) or stats_data.get("video_count", 0)
        )
    )


def parse_comment(comment_dict: dict) -> Comment:
    """Parse comment dictionary into Comment model"""
    author_data = comment_dict.get("user", {}) or comment_dict.get("author", {})
    
    # Handle createTime
    create_time_raw = comment_dict.get("createTime", 0) or comment_dict.get("create_time", 0)
    try:
        create_time_unix = int(create_time_raw) if create_time_raw else 0
        create_time = datetime.fromtimestamp(create_time_unix) if create_time_unix else None
    except (ValueError, TypeError, OSError):
        create_time = None
    
    # Handle avatar which can be string or dict with 'uri' key
    avatar_raw = author_data.get("avatarThumb") or author_data.get("avatar_thumb") or author_data.get("avatar")
    if isinstance(avatar_raw, dict):
        avatar = avatar_raw.get("uri") or avatar_raw.get("url") or str(avatar_raw)
    else:
        avatar = avatar_raw if isinstance(avatar_raw, str) else None
    
    return Comment(
        id=str(comment_dict.get("cid", "") or comment_dict.get("id", "")),
        text=comment_dict.get("text", "") or comment_dict.get("comment", ""),
        create_time=create_time,
        create_time_iso=create_time.isoformat() if create_time else "",
        likes=comment_dict.get("diggCount", 0) or comment_dict.get("digg_count", 0) or comment_dict.get("likes", 0),
        reply_count=comment_dict.get("replyCommentTotal", 0) or comment_dict.get("reply_count", 0),
        author=CommentAuthor(
            id=str(author_data.get("id", "") or author_data.get("uid", "")),
            username=author_data.get("uniqueId", "") or author_data.get("unique_id", ""),
            nickname=author_data.get("nickname", ""),
            avatar=avatar
        )
    )



async def ensure_session():
    """Ensure TikTok session is initialized (lazy initialization)"""
    global api, session_initialized, session_error
    
    if session_initialized:
        return
    
    if not MS_TOKEN:
        session_error = "MS_TOKEN not configured"
        raise HTTPException(status_code=503, detail="MS_TOKEN not configured. Please set it in .env file.")
    
    try:
        api = TikTokApi()
        await api.create_sessions(
            ms_tokens=[MS_TOKEN],
            num_sessions=1,
            sleep_after=3,
            browser=TIKTOK_BROWSER,
            headless=True
        )
        session_initialized = True
        session_error = None
        print("TikTok API session created successfully")
    except Exception as e:
        session_error = str(e)
        raise HTTPException(status_code=503, detail=f"Failed to create TikTok session: {str(e)}")


# FastAPI Application
app = FastAPI(
    title="TikTok API Service",
    description="REST API for fetching TikTok video stats, author stats, and publish dates",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        ms_token_configured=bool(MS_TOKEN),
        proxy_configured=bool(PROXY_URL),
        session_initialized=session_initialized,
        session_error=session_error
    )


@app.post("/init", tags=["System"])
async def init_session():
    """
    Initialize TikTok session manually.
    
    Call this endpoint to pre-initialize the TikTok session before making requests.
    If not called, the session will be initialized on the first request.
    """
    await ensure_session()
    return {"status": "initialized", "message": "TikTok session initialized successfully"}


@app.get("/video/{video_id}", response_model=VideoResponse, tags=["Video"])
async def get_video_by_id(video_id: str):
    """
    Get video information by video ID.
    
    Returns video stats (views, likes, comments, shares), publish date, and author info.
    """
    await ensure_session()
    
    try:
        # Construct URL from video ID for the TikTok-Api
        video_url = f"https://www.tiktok.com/@user/video/{video_id}"
        video = api.video(url=video_url)
        video_data = await video.info()
        return parse_video_data(video_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching video: {str(e)}")


@app.post("/video/url", response_model=VideoResponse, tags=["Video"])
async def get_video_by_url(request: VideoUrlRequest):
    """
    Get video information from a TikTok URL.
    
    Accepts various TikTok URL formats:
    - https://www.tiktok.com/@username/video/1234567890
    - https://vm.tiktok.com/abcdef
    - https://tiktok.com/t/abcdef
    """
    await ensure_session()
    
    try:
        # Use the URL directly with TikTok-Api
        video = api.video(url=request.url)
        video_data = await video.info()
        return parse_video_data(video_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching video: {str(e)}")


@app.get("/video/{video_id}/comments", response_model=CommentsResponse, tags=["Video"])
async def get_video_comments(
    video_id: str,
    count: int = Query(default=50, ge=1, le=200, description="Number of comments to fetch")
):
    """
    Get comments from a TikTok video.
    
    Returns comments with author info, like count, and reply count.
    """
    await ensure_session()
    
    try:
        # Construct URL from video ID
        video_url = f"https://www.tiktok.com/@user/video/{video_id}"
        video = api.video(url=video_url)
        
        comments = []
        async for comment in video.comments(count=count):
            comment_data = comment.as_dict if hasattr(comment, 'as_dict') else comment
            comments.append(parse_comment(comment_data))
        
        return CommentsResponse(
            video_id=video_id,
            count=len(comments),
            comments=comments
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching comments: {str(e)}")


@app.get("/user/{username}", response_model=UserResponse, tags=["User"])
async def get_user_by_username(username: str):
    """
    Get user/author information by username.
    
    Returns author stats (followers, following, total likes, video count).
    """
    await ensure_session()
    
    username = username.lstrip("@")
    
    try:
        user = api.user(username=username)
        user_data = await user.info()
        return parse_user_data(user_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user: {str(e)}")


@app.get("/user/{username}/videos", tags=["User"])
async def get_user_videos(
    username: str,
    count: int = Query(default=10, ge=1, le=50, description="Number of videos to fetch")
):
    """
    Get recent videos from a user.
    
    Returns a list of videos with their stats and publish dates.
    """
    await ensure_session()
    
    username = username.lstrip("@")
    
    try:
        user = api.user(username=username)
        videos = []
        
        async for video in user.videos(count=count):
            video_data = video.as_dict
            videos.append(parse_video_data(video_data))
        
        return {"username": username, "count": len(videos), "videos": videos}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching user videos: {str(e)}")


# Run with uvicorn when executed directly
if __name__ == "__main__":
    import uvicorn
    
    # For Windows, we need to use a workaround for subprocess in asyncio
    if sys.platform == "win32":
        # Use --reload without the proactor event loop issue
        uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
    else:
        uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
