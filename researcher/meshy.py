"""
Meshy AI client — text-to-3D model generation.
Docs: https://docs.meshy.ai/api-text-to-3d
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

MESHY_BASE = "https://api.meshy.ai"


class MeshyClient:
    def __init__(self):
        self.api_key  = os.getenv("MESHY_API_KEY", "").strip()
        self._session = requests.Session()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def configured(self) -> bool:
        return bool(self.api_key)

    def text_to_3d_preview(
        self,
        prompt:          str,
        art_style:       str = "realistic",
        negative_prompt: str = "",
    ) -> dict:
        if not self.api_key:
            return {"error": "MESHY_API_KEY not set in .env"}
        try:
            resp = self._session.post(
                f"{MESHY_BASE}/v2/text-to-3d",
                headers=self._headers(),
                json={
                    "mode":             "preview",
                    "prompt":           prompt,
                    "art_style":        art_style,
                    "negative_prompt":  negative_prompt or "low quality, low resolution, ugly, blurry",
                },
                timeout=20,
            )
            if resp.status_code in (200, 201, 202):
                data = resp.json()
                task_id = data.get("result") or data.get("id", "")
                return {"task_id": task_id, "mode": "preview"}
            logger.error("Meshy preview error %s: %s", resp.status_code, resp.text[:300])
            return {"error": f"Meshy API HTTP {resp.status_code}", "detail": resp.text[:200]}
        except Exception as e:
            logger.error("Meshy preview exception: %s", e)
            return {"error": str(e)}

    def image_to_3d(self, image_url: str, enable_pbr: bool = False) -> dict:
        if not self.api_key:
            return {"error": "MESHY_API_KEY not set in .env"}
        # image-to-3D uses v1; text-to-3D uses v2
        for api_path in ["/v1/image-to-3d", "/v2/image-to-3d"]:
            try:
                resp = self._session.post(
                    f"{MESHY_BASE}{api_path}",
                    headers=self._headers(),
                    json={"image_url": image_url, "enable_pbr": enable_pbr},
                    timeout=20,
                )
                if resp.status_code == 404:
                    logger.info("Meshy image-to-3d 404 at %s, trying next", api_path)
                    continue
                if resp.status_code in (200, 201, 202):
                    data = resp.json()
                    task_id = data.get("result") or data.get("id", "")
                    return {"task_id": task_id, "mode": "image-to-3d", "api_path": api_path}
                body = resp.text[:300]
                logger.error("Meshy image-to-3d %s at %s: %s", resp.status_code, api_path, body)
                return {"error": f"Meshy API HTTP {resp.status_code}", "detail": body}
            except Exception as e:
                logger.error("Meshy image-to-3d exception at %s: %s", api_path, e)
                return {"error": str(e)}
        return {"error": "Meshy image-to-3D endpoint not found at /v1 or /v2 — check Meshy API docs"}

    def get_image_to_3d_task(self, task_id: str) -> dict:
        if not self.api_key:
            return {"error": "MESHY_API_KEY not set in .env"}
        for api_path in [f"/v1/image-to-3d/{task_id}", f"/v2/image-to-3d/{task_id}"]:
            try:
                resp = self._session.get(
                    f"{MESHY_BASE}{api_path}",
                    headers=self._headers(),
                    timeout=10,
                )
                if resp.status_code == 404:
                    continue
                if resp.status_code == 200:
                    d = resp.json()
                    return {
                        "task_id":       task_id,
                        "status":        d.get("status", "UNKNOWN"),
                        "progress":      int(d.get("progress", 0) or 0),
                        "thumbnail_url": d.get("thumbnail_url", ""),
                        "model_urls":    d.get("model_urls") or {},
                        "error_msg":     (d.get("task_error") or {}).get("message", ""),
                    }
                return {"error": f"Meshy API HTTP {resp.status_code}", "detail": resp.text[:200]}
            except Exception as e:
                logger.error("Meshy get_image_to_3d_task exception: %s", e)
                return {"error": str(e)}
        return {"error": f"Image-to-3D task {task_id} not found at /v1 or /v2"}

    def text_to_3d_refine(self, preview_task_id: str) -> dict:
        if not self.api_key:
            return {"error": "MESHY_API_KEY not set in .env"}
        try:
            resp = self._session.post(
                f"{MESHY_BASE}/v2/text-to-3d",
                headers=self._headers(),
                json={"mode": "refine", "preview_task_id": preview_task_id},
                timeout=20,
            )
            if resp.status_code in (200, 201, 202):
                data = resp.json()
                task_id = data.get("result") or data.get("id", "")
                return {"task_id": task_id, "mode": "refine"}
            logger.error("Meshy refine error %s: %s", resp.status_code, resp.text[:300])
            return {"error": f"Meshy API HTTP {resp.status_code}", "detail": resp.text[:200]}
        except Exception as e:
            logger.error("Meshy refine exception: %s", e)
            return {"error": str(e)}

    def get_task(self, task_id: str) -> dict:
        if not self.api_key:
            return {"error": "MESHY_API_KEY not set in .env"}
        try:
            resp = self._session.get(
                f"{MESHY_BASE}/v2/text-to-3d/{task_id}",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                d = resp.json()
                return {
                    "task_id":       task_id,
                    "status":        d.get("status", "UNKNOWN"),
                    "progress":      int(d.get("progress", 0) or 0),
                    "thumbnail_url": d.get("thumbnail_url", ""),
                    "model_urls":    d.get("model_urls") or {},
                    "error_msg":     (d.get("task_error") or {}).get("message", ""),
                }
            logger.error("Meshy get_task %s error %s", task_id, resp.status_code)
            return {"error": f"Meshy API HTTP {resp.status_code}"}
        except Exception as e:
            logger.error("Meshy get_task exception: %s", e)
            return {"error": str(e)}
