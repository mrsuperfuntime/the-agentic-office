"""
Social Media Office Service

Responsible for:
- Creating engaging social media content
- Scheduling and posting across platforms
- Monitoring engagement and analytics
- Building brand presence and community
"""
from fastapi import FastAPI
from datetime import datetime
import sys
import os
import re
import json
from pathlib import Path

import requests

# Add shared libs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from shared.libs import get_llm_client, generate_office_decision, OfficePromptsFactory

app = FastAPI(title="Social Media Office", version="1.0.0")

llm_client = get_llm_client()


class SocialMediaOfficeDirector:
    def __init__(self):
        self.name = "Jyn Erso"
        self.role = "Propaganda Director"
        self.teams = ["Campaign Strategy", "Content Ops", "Community Signals", "Publishing Command"]
        self.platforms = ["Twitter", "LinkedIn", "Instagram", "TikTok", "Facebook"]
        self.sub_agents = [
            {
                "name": "Poe Dameron",
                "role": "Campaign Strategist",
                "source": "social.strategy",
                "description": "Owns campaign framing, launch messaging, and channel-by-channel positioning.",
            },
            {
                "name": "Cassian Andor",
                "role": "Content Operations Lead",
                "source": "social.content",
                "description": "Builds execution-ready drafts, asset queues, and working content packets.",
            },
            {
                "name": "Hera Syndulla",
                "role": "Community Signals Analyst",
                "source": "social.community",
                "description": "Tracks audience sentiment, comment themes, and follow-up opportunities.",
            },
            {
                "name": "Lando Calrissian",
                "role": "Publishing Commander",
                "source": "social.publish",
                "description": "Coordinates scheduling cadence, platform sequencing, and publish readiness.",
            },
        ]
        self.llm_client = llm_client
        self.output_root = self._resolve_output_root()
        self.it_office_url = os.getenv("IT_OFFICE_URL", "http://it-office:8000").rstrip("/")

    def _resolve_output_root(self) -> Path:
        configured = os.getenv("SOCIAL_MEDIA_OUTPUT_ROOT", "").strip()
        if configured:
            root = Path(configured)
        else:
            root = (Path(__file__).resolve().parent / "../../data-output/social-media").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _safe_folder_name(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip().lower())
        cleaned = cleaned.strip("-")
        return cleaned[:80] if cleaned else "campaign"

    def _create_campaign_folder(self, instruction: str, folder_designation: str | None = None) -> Path:
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        suffix = self._safe_folder_name(folder_designation or instruction[:50])
        campaign_dir = self.output_root / f"{timestamp}-{suffix}"
        campaign_dir.mkdir(parents=True, exist_ok=True)
        (campaign_dir / "images").mkdir(parents=True, exist_ok=True)
        return campaign_dir

    def get_status(self):
        return {
            "manager": self.name,
            "role": self.role,
            "teams": self.teams,
            "sub_agents": self.sub_agents,
            "platforms": self.platforms,
            "llm_status": self.llm_client.get_status(),
        }

    def roster(self):
        return {
            "director": {
                "name": self.name,
                "role": self.role,
            },
            "sub_agents": self.sub_agents,
            "teams": self.teams,
        }

    def create_content(self, platform: str, topic: str, tone: str = "professional") -> str:
        try:
            return generate_office_decision(
                office_type="social-media",
                decision_type="create_content",
                llm_client=self.llm_client,
                platform=platform,
                topic=topic,
                tone=tone,
            )
        except Exception as e:
            return f"Error creating content: {str(e)}"

    def create_content_strategy(self, goal: str, audience: str, platforms: str) -> str:
        try:
            return generate_office_decision(
                office_type="social-media",
                decision_type="content_strategy",
                llm_client=self.llm_client,
                goal=goal,
                audience=audience,
                platforms=platforms,
            )
        except Exception as e:
            return f"Error creating strategy: {str(e)}"

    def analyze_trends(self, trends: str, brand: str) -> str:
        try:
            return generate_office_decision(
                office_type="social-media",
                decision_type="trending_analysis",
                llm_client=self.llm_client,
                trends=trends,
                brand=brand,
            )
        except Exception as e:
            return f"Error analyzing trends: {str(e)}"

    def respond_to_message(self, instruction: str) -> str:
        try:
            system_prompt = OfficePromptsFactory.get_system_prompt("social-media")
            return self.llm_client.generate(instruction, system_prompt)
        except Exception as e:
            return f"Error handling message: {str(e)}"

    def generate_post_drafts(self, instruction: str, count: int, requested_platforms: list[str] | None = None) -> list[str]:
        drafts = []
        platforms = requested_platforms or ["LinkedIn", "Instagram", "X"]
        for index in range(count):
            platform = platforms[index % len(platforms)]
            prompt = (
                f"Create draft social media post {index + 1} of {count} for {platform}. "
                f"Base request: {instruction}. Keep it concise and publish-ready."
            )
            draft = self.respond_to_message(prompt)
            cleaned = draft.strip() if isinstance(draft, str) else ""
            if not cleaned or cleaned.lower().startswith("error handling message"):
                cleaned = (
                    f"{platform} Draft {index + 1}: Summer internship applications are now open. "
                    "Learn from mentors, ship real work, and apply today."
                )
            drafts.append(cleaned)
        return drafts

    def build_image_briefs(self, posts: list[str]) -> list[str]:
        briefs = []
        for idx, post in enumerate(posts, start=1):
            summary = (post or "").strip().replace("\n", " ")
            if len(summary) > 140:
                summary = f"{summary[:140]}..."
            briefs.append(
                f"Image Brief {idx}: clean brand visual for this post theme -> {summary or 'general campaign announcement'}"
            )
        return briefs

    def store_campaign_artifacts(
        self,
        instruction: str,
        generated_posts: list[str],
        folder_designation: str | None = None,
    ) -> dict:
        campaign_dir = self._create_campaign_folder(instruction, folder_designation)
        image_briefs = self.build_image_briefs(generated_posts)

        metadata = {
            "created_at": datetime.utcnow().isoformat(),
            "instruction": instruction,
            "post_count": len(generated_posts),
            "generated_posts": generated_posts,
            "image_briefs": image_briefs,
        }

        files = []
        metadata_path = campaign_dir / "campaign.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        files.append(metadata_path.name)

        for idx, post in enumerate(generated_posts, start=1):
            post_path = campaign_dir / f"post_{idx}.txt"
            post_path.write_text((post or "").strip(), encoding="utf-8")
            files.append(post_path.name)

            brief_path = campaign_dir / "images" / f"post_{idx}_image_brief.txt"
            brief_path.write_text(image_briefs[idx - 1], encoding="utf-8")
            files.append(str(brief_path.relative_to(campaign_dir)).replace("\\", "/"))

        return {
            "output_root": str(self.output_root),
            "artifact_folder": str(campaign_dir),
            "files": files,
            "image_briefs": image_briefs,
        }

    def publish_via_it(self, generated_posts: list[str], platforms: list[str], artifact_folder: str) -> dict:
        payload = {
            "posts": generated_posts,
            "platforms": platforms,
            "artifact_folder": artifact_folder,
        }
        try:
            response = requests.post(f"{self.it_office_url}/publish", json=payload, timeout=20)
            if response.status_code != 200:
                return {
                    "status": "error",
                    "message": f"IT office publish failed with status {response.status_code}",
                }
            return response.json()
        except Exception as e:
            return {
                "status": "error",
                "message": f"IT office unavailable: {str(e)}",
            }

    def automated_task_router(self, action: str, payload: dict) -> dict:
        instruction = payload.get("instruction", "")

        if action == "campaign_strategy":
            result = self.create_content_strategy(
                payload.get("goal", instruction or "Campaign launch"),
                payload.get("audience", "General audience"),
                payload.get("platforms", ", ".join(self.platforms)),
            )
            return {
                "director": self.name,
                "delegated_to": "Poe Dameron",
                "workstream": "campaign_strategy",
                "result": result,
            }

        if action == "content_operations":
            requested_platforms = _extract_requested_platforms(instruction, payload.get("platforms") or [])
            drafts = self.generate_post_drafts(
                instruction or payload.get("topic", "Campaign update"),
                max(1, payload.get("count", 3)),
                [platform.title() if platform != "x" else "X" for platform in requested_platforms] or None,
            )
            return {
                "director": self.name,
                "delegated_to": "Cassian Andor",
                "workstream": "content_operations",
                "generated_posts": drafts,
            }

        if action == "community_signals":
            result = self.analyze_trends(
                payload.get("trends", instruction or "engagement follow-ups"),
                payload.get("brand", "The Agentic Office"),
            )
            return {
                "director": self.name,
                "delegated_to": "Hera Syndulla",
                "workstream": "community_signals",
                "result": result,
            }

        if action == "publishing_command":
            return {
                "director": self.name,
                "delegated_to": "Lando Calrissian",
                "workstream": "publishing_command",
                "next_steps": [
                    "Confirm final approved copy for each platform.",
                    "Sequence X, LinkedIn, Instagram, TikTok, and Facebook based on campaign timing.",
                    "Hand off publish-ready package to IT-connected publishing flow when required.",
                ],
            }

        message = self.respond_to_message(instruction or payload.get("topic", "Provide social media guidance"))
        return {
            "director": self.name,
            "delegated_to": self.name,
            "workstream": "message",
            "result": message,
        }


def _extract_requested_post_count(instruction: str) -> int:
    text = (instruction or "").lower()
    match = re.search(r"\b(\d{1,2})\s+(?:social\s+media\s+)?posts?\b", text)
    if not match:
        if any(token in text for token in [" post", "post ", "tweet", "thread", "caption", "publish"]):
            return 1
        return 0
    requested = int(match.group(1))
    return max(1, min(requested, 10))


def _extract_requested_platforms(instruction: str, explicit_platforms: list[str] | None = None) -> list[str]:
    explicit_platforms = explicit_platforms or []
    normalized = []
    for platform in explicit_platforms:
        value = (platform or "").strip().lower()
        if value == "twitter":
            value = "x"
        if value and value not in normalized:
            normalized.append(value)

    text = (instruction or "").lower()
    token_map = {
        "x": ["twitter", "tweet", " x "],
        "instagram": ["instagram", "insta", " ig "],
        "linkedin": ["linkedin"],
        "tiktok": ["tiktok", "tik tok"],
        "facebook": ["facebook", " fb "],
    }
    padded_text = f" {text} "
    for platform, tokens in token_map.items():
        if any(token in padded_text for token in tokens) and platform not in normalized:
            normalized.append(platform)

    return normalized


manager = SocialMediaOfficeDirector()


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "office": "social-media",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/manager")
async def get_manager():
    return manager.get_status()


@app.get("/team")
async def get_team():
    return manager.roster()


@app.post("/create-content")
async def create_content(request: dict):
    platform = request.get("platform", "twitter")
    topic = request.get("topic")
    tone = request.get("tone", "professional")

    if not topic:
        return {"status": "error", "message": "topic is required"}

    content = manager.create_content(platform, topic, tone)
    return {"status": "success", "content": content}


@app.post("/content-strategy")
async def content_strategy(request: dict):
    goal = request.get("goal", "")
    audience = request.get("audience", "")
    platforms = request.get("platforms", "")

    if not goal:
        return {"status": "error", "message": "goal is required"}

    strategy = manager.create_content_strategy(goal, audience, platforms)
    return {"status": "success", "strategy": strategy}


@app.post("/analyze-trends")
async def analyze_trends(request: dict):
    trends = request.get("trends", "")
    brand = request.get("brand", "")

    if not trends:
        return {"status": "error", "message": "trends are required"}

    analysis = manager.analyze_trends(trends, brand)
    return {"status": "success", "analysis": analysis}


@app.post("/handle-request")
async def handle_request(request: dict):
    action = request.get("action")

    if action == "get_social_stats":
        return {
            "status": "success",
            "data": {
                "top_platform": "LinkedIn",
                "engagement_rate": "8.5%",
                "follower_growth": "12.3%",
            },
        }
    if action == "get_follower_count":
        return {
            "status": "success",
            "data": {"total_followers": 50000, "monthly_growth": "5.2%"},
        }
    if action == "create_content":
        platform = request.get("platform", "twitter")
        topic = request.get("topic", "")
        tone = request.get("tone", "professional")
        content = manager.create_content(platform, topic, tone)
        return {"status": "success", "data": {"content": content}}
    if action == "campaign_strategy":
        return {"status": "success", "data": manager.automated_task_router("campaign_strategy", request)}
    if action == "content_operations":
        return {"status": "success", "data": manager.automated_task_router("content_operations", request)}
    if action == "community_signals":
        return {"status": "success", "data": manager.automated_task_router("community_signals", request)}
    if action == "publishing_command":
        return {"status": "success", "data": manager.automated_task_router("publishing_command", request)}
    if action == "message":
        instruction = (request.get("instruction") or "").strip()
        request_data = request.get("data") or {}
        if not instruction:
            return {"status": "error", "message": "instruction required"}
        response = manager.respond_to_message(instruction)

        requested_platforms = _extract_requested_platforms(instruction, request_data.get("platforms") or [])
        requested_posts = _extract_requested_post_count(instruction)
        if requested_posts == 1 and len(requested_platforms) > 1:
            requested_posts = len(requested_platforms)

        draft_platforms = [platform.title() if platform != "x" else "X" for platform in requested_platforms]
        generated_posts = manager.generate_post_drafts(instruction, requested_posts, draft_platforms) if requested_posts > 0 else []

        payload = {"response": response}
        if generated_posts:
            artifact_bundle = manager.store_campaign_artifacts(
                instruction,
                generated_posts,
                request_data.get("output_folder"),
            )
            payload["generated_posts"] = generated_posts
            payload["requested_post_count"] = requested_posts
            payload["artifact_output_root"] = artifact_bundle["output_root"]
            payload["artifact_folder"] = artifact_bundle["artifact_folder"]
            payload["artifact_files"] = artifact_bundle["files"]
            payload["image_briefs"] = artifact_bundle["image_briefs"]
            payload["recommended_platforms"] = requested_platforms

            if request_data.get("auto_publish"):
                platforms = request_data.get("platforms") or requested_platforms or ["x", "instagram"]
                payload["publish_result"] = manager.publish_via_it(
                    generated_posts,
                    platforms,
                    artifact_bundle["artifact_folder"],
                )

        return {"status": "success", "data": payload}

    return {"status": "unknown_action"}


@app.get("/")
async def root():
    return {
        "service": "Social Media Office",
        "version": "1.0.0",
        "description": "AI-powered social media content creation and management",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
