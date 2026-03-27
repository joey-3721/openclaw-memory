from __future__ import annotations

import base64
import json
import mimetypes
import re
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageOps

from ..db import get_cursor
from .ledger_service import LEDGER_CATEGORY_PRESETS


@dataclass
class AiModelConfig:
    provider_code: str
    provider_name: str
    model_code: str
    model_name: str
    api_base_url: str
    api_path: str
    api_token: str
    request_timeout_seconds: int


class AiService:
    def create_ledger_job(
        self,
        *,
        book_id: int,
        user_id: int,
        input_type: str,
        source_text: str = "",
        source_file_name: str = "",
    ) -> str:
        job_id = uuid4().hex
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai_ledger_jobs
                    (job_id, ledger_book_id, user_id, input_type, status,
                     source_text, source_file_name)
                VALUES (%s, %s, %s, %s, 'QUEUED', %s, %s)
                """,
                (
                    job_id,
                    book_id,
                    user_id,
                    input_type,
                    (source_text or "").strip() or None,
                    (source_file_name or "").strip() or None,
                ),
            )
        return job_id

    def get_ledger_job(self, job_id: str, user_id: int) -> dict | None:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT job_id, ledger_book_id, user_id, input_type, status,
                       error_message, created_count, result_payload,
                       started_at, finished_at, created_at, updated_at
                FROM ai_ledger_jobs
                WHERE job_id=%s AND user_id=%s
                LIMIT 1
                """,
                (job_id, user_id),
            )
            row = cur.fetchone()
        return row

    def run_text_job(
        self,
        *,
        job_id: str,
        book_id: int,
        user_id: int,
        text: str,
    ) -> None:
        self._mark_job_running(job_id)
        try:
            result = self.extract_expenses_from_text(text)
            created_count = self._create_entries_from_result(
                book_id=book_id,
                user_id=user_id,
                result=result,
            )
            if created_count <= 0:
                raise ValueError("未检测到有效内容")
            self._mark_job_succeeded(job_id, book_id, result, created_count)
        except Exception as exc:
            self._mark_job_failed(job_id, str(exc))

    def run_image_job(
        self,
        *,
        job_id: str,
        book_id: int,
        user_id: int,
        image_bytes: bytes,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> None:
        self._mark_job_running(job_id)
        try:
            result = self.extract_expenses_from_image(
                image_bytes,
                filename=filename,
                content_type=content_type,
            )
            created_count = self._create_entries_from_result(
                book_id=book_id,
                user_id=user_id,
                result=result,
            )
            if created_count <= 0:
                raise ValueError("未检测到有效内容")
            self._mark_job_succeeded(job_id, book_id, result, created_count)
        except Exception as exc:
            self._mark_job_failed(job_id, str(exc))

    def get_default_model_config(self) -> AiModelConfig:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT provider_code, provider_name, model_code, model_name,
                       api_base_url, api_path, api_token, request_timeout_seconds
                FROM ai_model_configs
                WHERE is_enabled=1
                ORDER BY is_default DESC, id ASC
                LIMIT 1
                """
            )
            row = cur.fetchone()
        if not row:
            raise ValueError("还没有可用的 AI 模型配置")
        if not row.get("api_token"):
            raise ValueError("AI 模型 token 还没有填写")
        return AiModelConfig(**row)

    def extract_expenses_from_text(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("请输入要识别的文字")

        config = self.get_default_model_config()
        reference_now = self._now_shanghai()
        messages = self._build_messages(text, reference_now)
        content = self._call_text_model(config, messages)
        parsed = self._parse_json_payload(content)
        parsed["items"] = self._normalize_items(
            parsed.get("items") or [],
            source_text=text,
            reference_now=reference_now,
        )
        parsed["source"] = {
            "provider": config.provider_name,
            "model": config.model_code,
            "input_type": "text",
        }
        return parsed

    def extract_expenses_from_image(
        self,
        image_bytes: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> dict:
        if not image_bytes:
            raise ValueError("请先上传一张图片")

        config = self.get_default_model_config()
        image_url = self._build_data_url(
            image_bytes,
            filename=filename,
            content_type=content_type,
        )
        content = self._call_vlm_model(
            config,
            prompt=self._image_prompt(),
            image_url=image_url,
        )
        parsed = self._parse_json_payload(content)
        parsed["items"] = self._normalize_items(
            parsed.get("items") or [],
            source_text="",
            reference_now=self._now_shanghai(),
        )
        parsed["source"] = {
            "provider": config.provider_name,
            "model": config.model_code,
            "input_type": "image",
        }
        return parsed

    def _build_messages(self, text: str, reference_now: datetime) -> list[dict]:
        return [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {
                "role": "user",
                "content": (
                    f"当前北京时间：{reference_now.strftime('%Y-%m-%d %H:%M:%S')}。\n"
                    "请把“今天/昨天/前天/今晚/昨晚”等相对时间换算成准确时间。\n"
                    "请从下面这段记账相关文字里，提取出所有可能的消费记录。"
                    "如果文本里有多个商品、多个订单或多笔支付，请拆成多条 items。\n\n"
                    f"原始文本：\n{text}"
                ),
            },
        ]

    def _system_prompt(self) -> str:
        category_lines = []
        for category in LEDGER_CATEGORY_PRESETS:
            sub_names = "、".join(
                subcategory["name"] for subcategory in category["subcategories"]
            )
            category_lines.append(
                f"- {category['code']} / {category['name']}：{sub_names}"
            )

        return (
            "你是 Finance Hub 的记账识别助手。"
            "你的任务是把用户输入的消费文字，转换成固定 JSON。"
            "只输出 JSON，不要输出解释，不要输出 Markdown 代码块。\n\n"
            "分类规则：\n"
            + "\n".join(category_lines)
            + "\n\n"
            "返回格式必须始终是这个结构：\n"
            '{'
            '"items":['
            '{"title":"","amount":"0.00","currency":"CNY","occurred_at":"","category_code":"OTHER","subcategory_name":"其他杂项","merchant_name":"","note":"","confidence":0.0,"ai_source":"MINIMAX"}'
            "]}\n\n"
            "要求：\n"
            "1. items 必须是数组，即使只有一条也必须返回数组。\n"
            "2. title 如果无法确定，就优先使用二级分类名。\n"
            "3. amount 必须输出字符串格式的金额，例如 19.90。\n"
            "4. occurred_at 尽量输出 YYYY-MM-DD HH:MM:SS；无法确定时输出空字符串。\n"
            "5. category_code 必须从给定分类里选择；无法判断就用 OTHER。\n"
            "6. subcategory_name 尽量选择最贴近的二级分类；没有就用 其他杂项。\n"
            "7. note 可简短写识别依据，例如订单号、商品名、地点。\n"
            "8. confidence 输出 0 到 1 之间的小数。\n"
            "9. ai_source 固定输出 MINIMAX。\n"
            "10. 如果文本里没有明确消费记录，也要返回 {\"items\":[]}。"
        )

    def _image_prompt(self) -> str:
        return (
            self._system_prompt()
            + "\n\n"
            + "现在输入来源是一张图片，可能是支付截图、小票、订单页、商品清单或聊天截图。"
            + "请识别图片里所有可以形成记账记录的项目。"
            + "如果图片里有多个商品或多笔消费，必须拆成多条 items。"
            + "金额要尽量识别成最终支付金额；如果图片里有单价和总价，优先返回更适合记账的那条。"
            + "购买时间如果图片里能看出来，请尽量补全到 occurred_at。"
            + "如果无法确定分类，就用 OTHER。"
        )

    def _call_text_model(self, config: AiModelConfig, messages: list[dict]) -> str:
        url = config.api_base_url.rstrip("/") + "/" + config.api_path.lstrip("/")
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {config.api_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.model_code,
                "messages": messages,
                "temperature": 0.1,
            },
            timeout=config.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise ValueError("MiniMax 没有返回可用结果")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if not content:
            raise ValueError("MiniMax 返回内容为空")
        return content

    def _call_vlm_model(
        self,
        config: AiModelConfig,
        *,
        prompt: str,
        image_url: str,
    ) -> str:
        url = config.api_base_url.rstrip("/") + "/v1/coding_plan/vlm"
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {config.api_token}",
                "Content-Type": "application/json",
                "MM-API-Source": "Minimax-MCP",
            },
            json={
                "prompt": prompt,
                "image_url": image_url,
            },
            timeout=max(config.request_timeout_seconds, 120),
        )
        response.raise_for_status()
        payload = response.json()
        base_resp = payload.get("base_resp") or {}
        if base_resp.get("status_code") not in {None, 0}:
            raise ValueError(
                f"MiniMax 图片识别失败：{base_resp.get('status_msg') or '未知错误'}"
            )
        content = payload.get("content") or ""
        if not content:
            raise ValueError("MiniMax 图片识别返回内容为空")
        return content

    def _build_data_url(
        self,
        image_bytes: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> str:
        compressed_bytes, mime_type = self._compress_image_bytes(
            image_bytes,
            filename=filename,
            content_type=content_type,
        )
        encoded = base64.b64encode(compressed_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    def _compress_image_bytes(
        self,
        image_bytes: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> tuple[bytes, str]:
        original_mime = (
            (content_type or "").strip()
            or mimetypes.guess_type(filename or "")[0]
            or "image/png"
        )
        try:
            with Image.open(BytesIO(image_bytes)) as img:
                img = ImageOps.exif_transpose(img) if hasattr(ImageOps, "exif_transpose") else img
                img.load()
                max_side = 960
                if max(img.size) > max_side:
                    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")

                for quality in (68, 72):
                    output = BytesIO()
                    # OCR / vision usually tolerates moderate JPEG compression well.
                    img.save(
                        output,
                        format="JPEG",
                        quality=quality,
                        optimize=True,
                        progressive=True,
                    )
                    compressed = output.getvalue()
                    if len(compressed) <= 120_000 or quality == 72:
                        if len(compressed) < len(image_bytes):
                            return compressed, "image/jpeg"
        except Exception:
            pass
        return image_bytes, original_mime

    def _normalize_items(
        self,
        items: list[dict],
        *,
        source_text: str,
        reference_now: datetime,
    ) -> list[dict]:
        valid_categories = {
            category["code"]: {
                "name": category["name"],
                "subcategory_list": [
                    subcategory["name"] for subcategory in category["subcategories"]
                ],
                "subcategories": {
                    subcategory["name"] for subcategory in category["subcategories"]
                },
            }
            for category in LEDGER_CATEGORY_PRESETS
        }
        normalized = []
        for raw_item in items:
            item = raw_item if isinstance(raw_item, dict) else {}
            category_code = str(item.get("category_code") or "OTHER").strip().upper()
            if category_code not in valid_categories:
                category_code = "OTHER"

            subcategory_name = str(item.get("subcategory_name") or "").strip()
            if subcategory_name not in valid_categories[category_code]["subcategories"]:
                if category_code == "OTHER":
                    subcategory_name = "其他杂项"
                else:
                    subcategory_name = (
                        valid_categories[category_code]["subcategory_list"][0]
                        if valid_categories[category_code]["subcategory_list"]
                        else ""
                    )

            title = str(item.get("title") or "").strip() or subcategory_name or "未命名账单"
            amount = self._normalize_amount(item.get("amount"))
            occurred_at = self._normalize_occurred_at(
                item.get("occurred_at"),
                source_text=source_text,
                reference_now=reference_now,
            )

            try:
                confidence = float(item.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence > 1:
                confidence = round(min(confidence / 100.0, 1.0), 4)
            confidence = max(0.0, min(confidence, 1.0))

            normalized.append(
                {
                    "title": title,
                    "amount": amount,
                    "currency": str(item.get("currency") or "CNY").strip().upper() or "CNY",
                    "occurred_at": occurred_at,
                    "category_code": category_code,
                    "subcategory_name": subcategory_name,
                    "merchant_name": str(item.get("merchant_name") or "").strip(),
                    "note": str(item.get("note") or "").strip(),
                    "confidence": confidence,
                    "ai_source": "MINIMAX",
                }
            )
        return normalized

    def _normalize_amount(self, value: object) -> str:
        raw = str(value or "").strip().replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", raw)
        if not match:
            return "0.00"
        return f"{float(match.group(0)):.2f}"

    def _normalize_occurred_at(
        self,
        value: object,
        *,
        source_text: str,
        reference_now: datetime,
    ) -> str:
        raw = str(value or "").strip()
        if raw:
            normalized = raw.replace("T", " ").replace("/", "-")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", normalized):
                return normalized + ":00"
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
                return normalized + " 00:00:00"
            if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", normalized):
                return normalized
        return self._infer_relative_datetime(source_text, reference_now)

    def _infer_relative_datetime(
        self,
        text: str,
        reference_now: datetime,
    ) -> str:
        text = (text or "").strip()
        if not text:
            return ""

        base_date = None
        if "大前天" in text:
            base_date = reference_now.date() - timedelta(days=3)
        elif "前天" in text:
            base_date = reference_now.date() - timedelta(days=2)
        elif "昨天" in text or "昨晚" in text:
            base_date = reference_now.date() - timedelta(days=1)
        elif "今天" in text or "今晚" in text:
            base_date = reference_now.date()

        if base_date is None:
            return ""

        hour = 0
        minute = 0
        time_match = re.search(r"(?<!\d)(\d{1,2})[:点时](\d{1,2})?", text)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
        elif "中午" in text:
            hour = 12
        elif "下午" in text:
            hour = 15
        elif "晚上" in text or "昨晚" in text or "今晚" in text:
            hour = 20
        elif "早上" in text or "上午" in text:
            hour = 9

        if ("下午" in text or "晚上" in text or "昨晚" in text or "今晚" in text) and 1 <= hour <= 11:
            hour += 12

        return datetime(
            base_date.year,
            base_date.month,
            base_date.day,
            hour,
            minute,
            0,
            tzinfo=reference_now.tzinfo,
        ).strftime("%Y-%m-%d %H:%M:%S")

    def _now_shanghai(self) -> datetime:
        return datetime.now(ZoneInfo("Asia/Shanghai"))

    def _create_entries_from_result(
        self,
        *,
        book_id: int,
        user_id: int,
        result: dict,
    ) -> int:
        from .ledger_service import LedgerService

        return LedgerService().create_ai_entries(
            book_id,
            user_id,
            result.get("items") or [],
            source_payload=result.get("source"),
        )

    def _mark_job_running(self, job_id: str) -> None:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE ai_ledger_jobs
                SET status='RUNNING',
                    error_message=NULL,
                    started_at=NOW(),
                    finished_at=NULL
                WHERE job_id=%s
                """,
                (job_id,),
            )

    def _mark_job_succeeded(
        self,
        job_id: str,
        book_id: int,
        result: dict,
        created_count: int,
    ) -> None:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE ai_ledger_jobs
                SET status='SUCCEEDED',
                    created_count=%s,
                    result_payload=CAST(%s AS JSON),
                    finished_at=NOW()
                WHERE job_id=%s
                """,
                (
                    created_count,
                    json.dumps(result, ensure_ascii=False),
                    job_id,
                ),
            )
        from .ledger_service import LedgerService
        from .page_cache_service import PageCacheService

        PageCacheService().invalidate_ledger_users(
            LedgerService().get_book_user_ids(book_id)
        )

    def _mark_job_failed(self, job_id: str, error_message: str) -> None:
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE ai_ledger_jobs
                SET status='FAILED',
                    error_message=%s,
                    finished_at=NOW()
                WHERE job_id=%s
                """,
                ((error_message or "AI 任务失败")[:500], job_id),
            )

    def _parse_json_payload(self, content: str) -> dict:
        cleaned = content.strip()
        cleaned = re.sub(r"^```json\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end >= start:
            cleaned = cleaned[start : end + 1]
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AI 返回的 JSON 无法解析：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("AI 返回格式错误，顶层必须是对象")
        items = data.get("items")
        if not isinstance(items, list):
            raise ValueError("AI 返回格式错误，items 必须是数组")
        return data
