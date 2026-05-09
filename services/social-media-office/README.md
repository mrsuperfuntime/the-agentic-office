# Social Media Office

## Overview

The Social Media Office is responsible for creating, scheduling, and publishing engaging content across multiple social media platforms. It manages brand presence, community engagement, and tracks analytics.

## Responsibilities

- **Content Creation**: Create engaging text, image, and video content
- **Scheduling**: Plan and schedule posts across multiple platforms
- **Publishing**: Publish content at optimal times for maximum engagement
- **Analytics**: Track engagement metrics and follower growth
- **Community Management**: Monitor comments and manage community interactions
- **Platform Management**: Manage presence across Twitter, LinkedIn, Instagram, TikTok, and Facebook

## Teams

- **Content Creators**: Design and write social media content
- **Community Managers**: Engage with audience and manage interactions
- **Analytics**: Track metrics and optimize content strategy
- **Schedulers**: Coordinate timing and publishing schedules

## API Endpoints

### GET /health
Health check endpoint for service status

### GET /manager
Get the office manager status and information

### POST /create-content
Create new social media content
```json
{
  "topic": "Product Launch",
  "type": "text"
}
```

### POST /schedule-post
Schedule a post for publishing
```json
{
  "post_id": 1,
  "platform": "LinkedIn",
  "scheduled_time": "2026-05-08T14:00:00"
}
```

### POST /publish-post
Publish a scheduled post
```json
{
  "post_id": 1
}
```

### GET /analytics
Get social media analytics and metrics

### GET /content-queue
Get current content queue

### GET /published-posts
Get recently published posts

### POST /handle-request
Handle requests from other offices
- `get_social_stats`: Get analytics data
- `get_content_queue`: Get current queued content
- `get_follower_count`: Get follower metrics

## Running the Service

```bash
python main.py
```

Or with Docker:
```bash
docker build -t social-media-office .
docker run -p 8000:8000 social-media-office
```

## Environment Variables

- `RABBITMQ_URL`: RabbitMQ connection URL (optional)
- `DATABASE_URL`: PostgreSQL connection URL (optional)
- `SERVICE_NAME`: Service identifier (default: social-media-office)
