"""Feishu API Service for ERA Assistant.

This module handles all interactions with Feishu (Lark) API:
- Authentication (tenant_access_token)
- Reading records from Feishu Base (多维表)
- Downloading file attachments
- Uploading files to Feishu Drive
- Creating shareable links
"""
import httpx
from typing import List, Dict, Optional, Any
import os
from pathlib import Path


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

    async def import_xlsx_to_sheet(
        self,
        file_content: bytes,
        file_name: str,
        folder_token: str
    ) -> str:
        """Import xlsx file to Feishu Sheet (电子表格).

        三步流程：
        1. 上传素材 (ccm_import_open)
        2. 创建导入任务
        3. 轮询查询导入结果

        Args:
            file_content: File content as bytes
            file_name: Name of the file (with .xlsx extension)
            folder_token: Target folder token

        Returns:
            URL of the imported sheet
        """
        import json
        import asyncio

        token = await self._get_tenant_access_token()
        file_size = len(file_content)

        # ========== Step 1: 上传素材 ==========
        upload_url = f"{self.BASE_URL}/drive/v1/medias/upload_all"

        # extra 参数：导入为电子表格
        extra = json.dumps({
            "obj_type": "sheet",
            "file_extension": "xlsx"
        })

        files = {
            "file": (file_name, file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        }
        data = {
            "file_name": file_name,
            "parent_type": "ccm_import_open",  # 导入模式
            "size": str(file_size),
            "extra": extra,
        }

        headers = {
            "Authorization": f"Bearer {token}"
        }

        print(f"📤 Step 1: Uploading media (import mode)...")

        timeout = httpx.Timeout(120.0, connect=10.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                upload_url,
                headers=headers,
                files=files,
                data=data
            )
            result = response.json()

            if result.get("code") != 0:
                raise Exception(f"Upload media failed: {result}")

            file_token = result.get("data", {}).get("file_token")
            if not file_token:
                raise Exception(f"No file_token in response: {result}")

            print(f"✅ Media uploaded, file_token: {file_token[:20]}...")

        # ========== Step 2: 创建导入任务 ==========
        import_url = f"{self.BASE_URL}/drive/v1/import_tasks"

        import_data = {
            "file_extension": "xlsx",
            "file_token": file_token,
            "type": "sheet",  # 导入为电子表格
            "file_name": file_name.replace(".xlsx", ""),  # 去掉后缀
            "point": {
                "mount_type": 1,  # 1 = 云空间
                "mount_key": ""  # 空表示云空间根目录
            }
        }

        print(f"📤 Step 2: Creating import task...")
        print(f"📤 Import data: {import_data}")

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                import_url,
                headers={**headers, "Content-Type": "application/json"},
                json=import_data
            )
            result = response.json()

            if result.get("code") != 0:
                raise Exception(f"Create import task failed: {result}")

            ticket = result.get("data", {}).get("ticket")
            if not ticket:
                raise Exception(f"No ticket in response: {result}")

            print(f"✅ Import task created, ticket: {ticket}")

        # ========== Step 3: 轮询查询导入结果 ==========
        print(f"📤 Step 3: Polling import result...")

        max_retries = 500  # 最多轮询500次（约33分钟）
        for i in range(max_retries):
            await asyncio.sleep(4)  # 等待4秒

            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    f"{self.BASE_URL}/drive/v1/import_tasks/{ticket}",
                    headers={**headers, "Content-Type": "application/json"}
                )
                result = response.json()

                if result.get("code") != 0:
                    raise Exception(f"Query import task failed: {result}")

                task_data = result.get("data", {})
                job_status = task_data.get("result", {}).get("job_status", -1)
                job_error_msg = task_data.get("result", {}).get("job_error_msg", "")

                # job_status: 0=成功, 1=初始化, 2=处理中, 3=错误, 100=加密, 116=需要特殊处理
                if job_status == 0:
                    url = task_data.get("result", {}).get("url", "")
                    doc_token = task_data.get("result", {}).get("token", "")
                    print(f"✅ Import success! URL: {url}")
                    return url
                elif job_status == 3:
                    raise Exception(f"Import failed: {job_error_msg or 'Unknown error'}")
                elif job_status == 100:
                    raise Exception("Import failed: Document is encrypted")
                elif job_error_msg and job_error_msg != "success":
                    # 有些情况 job_status 不是 3 但有错误信息
                    raise Exception(f"Import failed: {job_error_msg}")
                else:
                    print(f"⏳ Import in progress... (status: {job_status}, attempt {i+1}/{max_retries})")

        raise Exception(f"Import timeout after {max_retries} retries")

    def get_file_url(self, file_token: str) -> str:
        """Get the URL to access a file in Feishu Drive.

        Note: This link requires login and folder permission.

        Args:
            file_token: The file token from upload

        Returns:
            URL to view the file in Feishu
        """
        return f"https://space.feishu.cn/file/{file_token}"

    async def update_record_field(
        self,
        base_token: str,
        table_id: str,
        record_id: str,
        field_name: str,
        field_value: Any
    ) -> Dict[str, Any]:
        """Update a specific field of a record in Feishu Base.

        Args:
            base_token: The base/app token
            table_id: The table ID
            record_id: The record ID to update
            field_name: Name of the field to update
            field_value: Value to set

        Returns:
            Updated record data
        """
        endpoint = f"/bitable/v1/apps/{base_token}/tables/{table_id}/records/{record_id}"

        payload = {
            "fields": {
                field_name: field_value
            }
        }

        response = await self._make_request("PUT", endpoint, json=payload)

        if response.get("code") != 0:
            raise Exception(f"Failed to update record field: {response}")

        return response.get("data", {})


# Singleton instance for easy import
feishu_service: Optional[FeishuService] = None


def get_feishu_service() -> FeishuService:
    """Get or create Feishu service singleton."""
    global feishu_service
    if feishu_service is None:
        feishu_service = FeishuService()
    return feishu_service
