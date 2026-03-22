"""Feishu API Service for ERA Assistant.

This module handles all interactions with Feishu (Lark) API:
- Authentication (tenant_access_token)
- Reading records from Feishu Base (多维表)
- Downloading file attachments
"""
import httpx
from typing import List, Dict, Optional, Any
import os


class FeishuService:
    """Service for interacting with Feishu Open API."""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str = None, app_secret: str = None):
        """Initialize Feishu service with credentials.

        Args:
            app_id: Feishu app ID (from env FEISHU_APP_ID if not provided)
            app_secret: Feishu app secret (from env FEISHU_APP_SECRET if not provided)
        """
        self.app_id = app_id or os.getenv("FEISHU_APP_ID")
        self.app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")
        self._tenant_access_token: Optional[str] = None

        if not self.app_id or not self.app_secret:
            raise ValueError("Feishu app_id and app_secret are required")

    async def _get_tenant_access_token(self) -> str:
        """Get tenant access token from Feishu auth API.

        Returns:
            Tenant access token string
        """
        if self._tenant_access_token:
            return self._tenant_access_token

        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        # Use longer timeout for connection (10s) and read (30s)
        timeout = httpx.Timeout(30.0, connect=10.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 0:
                raise Exception(f"Feishu auth failed: {data}")

            self._tenant_access_token = data["tenant_access_token"]
            return self._tenant_access_token

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Make authenticated request to Feishu API.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for httpx

        Returns:
            API response data
        """
        token = await self._get_tenant_access_token()
        url = f"{self.BASE_URL}{endpoint}"

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                **kwargs
            )
            # Don't raise for status - let us handle Feishu's error response
            data = response.json()
            return data

    async def get_base_records(
        self,
        base_token: str,
        table_id: str,
        filter_status: str = "Submitted"
    ) -> List[Dict[str, Any]]:
        """Get records from Feishu Base (多维表).

        Args:
            base_token: The base/app token from Feishu
            table_id: The table ID to query
            filter_status: Only return records with this status (default: "Submitted")

        Returns:
            List of records from Feishu Base
        """
        endpoint = f"/bitable/v1/apps/{base_token}/tables/{table_id}/records/search"

        # Build filter to get records with specific status
        # Note: Feishu API expects value to be a list for "is" operator
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [
                    {
                        "field_name": "status",
                        "operator": "is",
                        "value": [filter_status]
                    }
                ]
            },
            "page_size": 500  # Adjust as needed
        }

        response = await self._make_request("POST", endpoint, json=payload)

        if response.get("code") != 0:
            raise Exception(f"Failed to get records: {response}")

        items = response.get("data", {}).get("items", [])
        return items

    async def download_file(self, file_token: str) -> bytes:
        """Download a file from Feishu.

        Args:
            file_token: The file token from Feishu

        Returns:
            File content as bytes
        """
        endpoint = f"/drive/v1/medias/{file_token}/download"

        token = await self._get_tenant_access_token()
        url = f"{self.BASE_URL}{endpoint}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=True,
                timeout=60.0
            )
            if response.status_code != 200:
                error_detail = response.text[:500] if response.text else "No error details"
                raise Exception(f"Feishu download failed (HTTP {response.status_code}): {error_detail}")
            return response.content

    async def update_record_status(
        self,
        base_token: str,
        table_id: str,
        record_id: str,
        status: str
    ) -> Dict[str, Any]:
        """Update the status field of a record in Feishu Base.

        Args:
            base_token: The base/app token
            table_id: The table ID
            record_id: The record ID to update
            status: New status value

        Returns:
            Updated record data
        """
        endpoint = f"/bitable/v1/apps/{base_token}/tables/{table_id}/records/{record_id}"

        payload = {
            "fields": {
                "status": status
            }
        }

        response = await self._make_request("PUT", endpoint, json=payload)

        if response.get("code") != 0:
            raise Exception(f"Failed to update record: {response}")

        return response.get("data", {})


# Singleton instance for easy import
feishu_service: Optional[FeishuService] = None


def get_feishu_service() -> FeishuService:
    """Get or create Feishu service singleton."""
    global feishu_service
    if feishu_service is None:
        feishu_service = FeishuService()
    return feishu_service
