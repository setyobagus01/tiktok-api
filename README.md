# Social Media API 🚀

A unified REST API service for fetching data from **TikTok** and **Instagram**. Built with FastAPI and Python.

## Features

### TikTok
- ✅ Get video information (views, likes, comments, shares)
- ✅ Get video comments
- ✅ Get user profile and stats
- ✅ Get user's recent videos

### Instagram
- ✅ Get user profile and stats (followers, following, posts count)
- ✅ Get user's posts/media
- ✅ Get user's stories
- ✅ Get user's followers list
- ✅ Get user's following list
- ✅ Get post information (likes, comments, views)
- ✅ Get post comments
- ✅ Get post likers
- ✅ Search posts by hashtag

## Installation

### Prerequisites
- Python 3.9+
- Playwright (for TikTok)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/social-media-api.git
cd social-media-api
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Install Playwright browsers (for TikTok):
```bash
python -m playwright install chromium
```

5. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your credentials
```

## Configuration

Edit `.env` file with your credentials:

### TikTok
- `MS_TOKEN`: Your TikTok msToken (get from browser cookies)
- `TIKTOK_BROWSER`: Browser to use (chromium, firefox, webkit)

### Instagram
- `INSTAGRAM_USERNAME`: Your Instagram username
- `INSTAGRAM_PASSWORD`: Your Instagram password

> ⚠️ **WARNING**: Use a secondary/burner account for Instagram, NOT your main account! Instagram may flag or ban accounts used for automation.

### General
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000)
- `PROXY_URL`: Optional proxy for requests

## Usage

### Start the server:
```bash
python main.py
```

### Access the API documentation:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check for both platforms |
| POST | `/tiktok/init` | Initialize TikTok session |
| POST | `/instagram/init` | Initialize Instagram session |

### TikTok - Video
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/tiktok/video/{video_id}` | Get video info by ID |
| POST | `/tiktok/video/url` | Get video info from URL |
| GET | `/tiktok/video/{video_id}/comments` | Get video comments |

### TikTok - User
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/tiktok/user/{username}` | Get user info |
| GET | `/tiktok/user/{username}/videos` | Get user's videos |

### Instagram - User
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/instagram/user/{username}` | Get user info and stats |
| GET | `/instagram/user/{username}/posts` | Get user's posts |
| GET | `/instagram/user/{username}/stories` | Get user's stories |
| GET | `/instagram/user/{username}/followers` | Get followers list |
| GET | `/instagram/user/{username}/following` | Get following list |

### Instagram - Post
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/instagram/post/{media_id}` | Get post info (by ID or shortcode) |
| POST | `/instagram/post/url` | Get post info from URL |
| GET | `/instagram/post/{media_id}/comments` | Get post comments |
| GET | `/instagram/post/{media_id}/likers` | Get users who liked the post |

### Instagram - Hashtag
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/instagram/hashtag/{name}/posts` | Get top posts for hashtag |

## Example Requests

### Get TikTok Video Info
```bash
curl http://localhost:8000/tiktok/video/7123456789012345678
```

### Get Instagram User Info
```bash
curl http://localhost:8000/instagram/user/instagram
```

### Get Instagram Post from URL
```bash
curl -X POST http://localhost:8000/instagram/post/url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.instagram.com/p/ABC123/"}'
```

## Docker

### Build and run:
```bash
docker build -t social-media-api .
docker run -p 8000:8000 --env-file .env social-media-api
```

## Rate Limiting & Best Practices

### TikTok
- Uses browser automation, slower but more reliable
- No strict rate limits but don't abuse

### Instagram
- Has strict rate limits
- Add delays between requests (built-in session management)
- May require challenge verification on new logins
- Session is cached in `instagram_session.json`

## Troubleshooting

### Instagram "Challenge Required"
Instagram flagged your login as suspicious. Solutions:
1. Log in to Instagram from a browser on the same IP
2. Verify the login attempt via email/SMS
3. Try again

### Instagram 2FA Required
Currently 2FA is not supported. Disable 2FA on your burner account.

### TikTok Session Fails
- Make sure `MS_TOKEN` is valid and not expired
- Try refreshing your msToken from browser cookies

## License

MIT License - See LICENSE file
