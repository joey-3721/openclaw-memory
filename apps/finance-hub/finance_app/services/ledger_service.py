from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
from uuid import uuid4

from ..db import get_cursor


ZERO = Decimal("0.00")


LEDGER_CATEGORY_PRESETS = [
    {
        "code": "DINING",
        "name": "餐饮",
        "icon": "dining",
        "accent_class": "mint",
        "description": "日常吃喝与家庭补给",
        "subcategories": [
            {"name": "饮品", "icon": "drink"},
            {"name": "外卖", "icon": "takeout"},
            {"name": "食材", "icon": "ingredient"},
            {"name": "水果", "icon": "fruit"},
            {"name": "正餐", "icon": "meal"},
            {"name": "甜品", "icon": "dessert"},
        ],
    },
    {
        "code": "TRANSPORT",
        "name": "交通",
        "icon": "transport",
        "accent_class": "sky",
        "description": "通勤、城际与长途出行",
        "subcategories": [
            {"name": "地铁", "icon": "subway"},
            {"name": "打车", "icon": "taxi"},
            {"name": "自行车", "icon": "bike"},
            {"name": "高铁", "icon": "rail"},
            {"name": "飞机", "icon": "plane"},
            {"name": "公交", "icon": "bus"},
        ],
    },
    {
        "code": "LODGING",
        "name": "住宿",
        "icon": "lodging",
        "accent_class": "amber",
        "description": "长期居住与临时入住",
        "subcategories": [
            {"name": "租房", "icon": "rent"},
            {"name": "酒店", "icon": "hotel"},
            {"name": "民宿", "icon": "homestay"},
            {"name": "短租", "icon": "shortstay"},
        ],
    },
    {
        "code": "SHOPPING",
        "name": "购物",
        "icon": "shopping",
        "accent_class": "violet",
        "description": "服饰、设备和生活物件采购",
        "subcategories": [
            {"name": "衣服", "icon": "shirt"},
            {"name": "裤子", "icon": "pants"},
            {"name": "鞋子", "icon": "shoes"},
            {"name": "数码", "icon": "digital"},
            {"name": "配件", "icon": "accessory"},
            {"name": "家居", "icon": "homegoods"},
        ],
    },
    {
        "code": "GAME",
        "name": "游戏",
        "icon": "game",
        "accent_class": "violet",
        "description": "游戏消费、设备与娱乐硬件",
        "subcategories": [
            {"name": "手机游戏", "icon": "mobilegame"},
            {"name": "主机游戏", "icon": "consolegame"},
            {"name": "游戏设备", "icon": "gamegear"},
        ],
    },
    {
        "code": "MEDICAL",
        "name": "医疗",
        "icon": "medical",
        "accent_class": "sky",
        "description": "问诊、药房与检查支出",
        "subcategories": [
            {"name": "买药", "icon": "pharmacy"},
            {"name": "门诊", "icon": "clinic"},
            {"name": "检查", "icon": "checkup"},
            {"name": "牙科", "icon": "dental"},
        ],
    },
    {
        "code": "SERVICE",
        "name": "服务",
        "icon": "service",
        "accent_class": "rose",
        "description": "生活服务和个人护理",
        "subcategories": [
            {"name": "理发", "icon": "haircut"},
            {"name": "洗衣", "icon": "laundry"},
            {"name": "家政", "icon": "housekeeping"},
            {"name": "维修", "icon": "repair"},
        ],
    },
    {
        "code": "BILL",
        "name": "账单",
        "icon": "bill",
        "accent_class": "amber",
        "description": "日常固定支出与周期扣费",
        "subcategories": [
            {"name": "水电燃气", "icon": "utilities"},
            {"name": "话费网费", "icon": "network"},
            {"name": "订阅", "icon": "subscription"},
            {"name": "固定账单", "icon": "recurring"},
        ],
    },
    {
        "code": "OTHER",
        "name": "其他",
        "icon": "other",
        "accent_class": "amber",
        "description": "兜底分类，后续继续细分",
        "subcategories": [
            {"name": "红包", "icon": "redpacket"},
            {"name": "手续费", "icon": "fee"},
            {"name": "礼物", "icon": "gift"},
            {"name": "其他杂项", "icon": "misc"},
        ],
    },
]


PRESET_BY_CODE = {item["code"]: item for item in LEDGER_CATEGORY_PRESETS}
SUBCATEGORY_ICON_BY_NAME = {
    subcategory["name"]: subcategory["icon"]
    for category in LEDGER_CATEGORY_PRESETS
    for subcategory in category["subcategories"]
}


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value or "0")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _now_display(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%m 月 %d 日 %H:%M")


@dataclass
class SettlementTransfer:
    from_member_id: int
    to_member_id: int
    from_name: str
    to_name: str
    amount: Decimal


class LedgerService:
    """Ledger books, shared entries, and settlement helpers."""

    def get_categories(self) -> list[dict]:
        return LEDGER_CATEGORY_PRESETS

    def search_users(
        self, query: str, exclude_user_id: int | None = None
    ) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []

        like = f"%{query}%"
        with get_cursor() as cur:
            sql = """
                SELECT id, username, COALESCE(display_name, username) AS display_name
                FROM finance_users
                WHERE is_active=1
                  AND (username LIKE %s OR COALESCE(display_name, username) LIKE %s)
            """
            params: list[object] = [like, like]
            if exclude_user_id:
                sql += " AND id <> %s"
                params.append(exclude_user_id)
            sql += " ORDER BY username LIMIT 12"
            cur.execute(sql, params)
            return list(cur.fetchall())

    def ensure_main_book(self, user_id: int) -> int:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM ledger_books
                WHERE owner_user_id=%s AND is_default_main=1
                LIMIT 1
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if row:
                book_id = row["id"]
            else:
                cur.execute(
                    """
                    INSERT INTO ledger_books
                        (owner_user_id, book_type, name, description,
                         base_currency, is_default_main, display_location)
                    VALUES (%s, 'MAIN', '主账本', '默认个人账本，不可删除',
                            'CNY', 1, '默认总账')
                    """,
                    (user_id,),
                )
                book_id = cur.lastrowid
            self._ensure_member(cur, book_id, user_id, role="OWNER")
            return int(book_id)

    def list_books_for_user(self, user_id: int) -> list[dict]:
        self.ensure_main_book(user_id)
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    b.id,
                    b.owner_user_id,
                    b.book_type,
                    b.name,
                    b.description,
                    b.base_currency,
                    b.is_default_main,
                    b.country_name,
                    b.region_name,
                    b.city_name,
                    b.display_location,
                    b.updated_at,
                    COUNT(DISTINCT m_all.id) AS member_count,
                    COUNT(DISTINCT e.id) AS entry_count,
                    COUNT(DISTINCT CASE WHEN e.is_settled=0 THEN e.id END)
                        AS unsettled_entry_count
                FROM ledger_books b
                JOIN ledger_book_members mym
                  ON mym.ledger_book_id=b.id AND mym.user_id=%s
                LEFT JOIN ledger_book_members m_all
                  ON m_all.ledger_book_id=b.id
                LEFT JOIN ledger_entries e
                  ON e.ledger_book_id=b.id
                GROUP BY b.id
                ORDER BY b.is_default_main DESC, b.updated_at DESC, b.id DESC
                """,
                (user_id,),
            )
            books = list(cur.fetchall())

        for book in books:
            book["subtitle"] = self._book_subtitle(book)
            book["location_label"] = self._book_location_label(book)
            book["cover_label"] = (
                "Main Book"
                if book["book_type"] == "MAIN"
                else (
                    "Travel Book" if book["book_type"] == "TRAVEL" else "Shared Book"
                )
            )
            book["stats"] = [
                {
                    "label": "成员",
                    "value": f"{book.get('member_count') or 0} 人",
                },
                {
                    "label": "账单",
                    "value": f"{book.get('entry_count') or 0} 笔",
                },
                {
                    "label": "未结算",
                    "value": f"{book.get('unsettled_entry_count') or 0} 笔",
                },
            ]
            book["members_preview"] = self._member_preview_names(book["id"])
            book["my_total_spend_display"] = self._my_total_spend_display(
                book["id"], user_id
            )
            book["spend_label"] = (
                "本月支出" if book["book_type"] == "MAIN" else "我的支出"
            )
        return books

    def create_book(
        self,
        owner_user_id: int,
        *,
        book_type: str,
        name: str,
        description: str = "",
        country_name: str = "",
        region_name: str = "",
        city_name: str = "",
        member_user_ids: list[int] | None = None,
    ) -> int:
        normalized_type = (book_type or "").strip().upper()
        if normalized_type not in {"TRAVEL", "CUSTOM"}:
            raise ValueError("账本类型只支持旅行账本或其他共享账本")
        name = (name or "").strip()
        if not name:
            raise ValueError("账本名称不能为空")

        member_user_ids = [
            int(user_id)
            for user_id in (member_user_ids or [])
            if int(user_id) != owner_user_id
        ]
        display_location = " / ".join(
            part for part in [country_name.strip(), region_name.strip(), city_name.strip()] if part
        )

        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO ledger_books
                    (owner_user_id, book_type, name, description,
                     country_name, region_name, city_name, display_location)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    owner_user_id,
                    normalized_type,
                    name,
                    description.strip() or None,
                    country_name.strip() or None,
                    region_name.strip() or None,
                    city_name.strip() or None,
                    display_location or None,
                ),
            )
            book_id = int(cur.lastrowid)
            self._ensure_member(cur, book_id, owner_user_id, role="OWNER")
            for member_user_id in member_user_ids:
                self._ensure_member(cur, book_id, member_user_id, role="MEMBER")
            return book_id

    def rename_book(self, book_id: int, actor_user_id: int, new_name: str) -> None:
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("账本名称不能为空")
        self.get_book(book_id, actor_user_id)
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE ledger_books
                SET name=%s
                WHERE id=%s
                """,
                (new_name, book_id),
            )

    def add_book_members(
        self, book_id: int, actor_user_id: int, member_user_ids: list[int]
    ) -> None:
        book = self.get_book(book_id, actor_user_id)
        if book["book_type"] == "MAIN":
            raise ValueError("主账本不支持直接添加共享成员，请在单笔记录里共享")

        with get_cursor() as cur:
            for member_user_id in member_user_ids:
                if member_user_id == actor_user_id:
                    continue
                self._ensure_member(cur, book_id, member_user_id, role="MEMBER")

    def get_book(self, book_id: int, user_id: int) -> dict:
        self.ensure_main_book(user_id)
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT b.*
                FROM ledger_books b
                JOIN ledger_book_members m
                  ON m.ledger_book_id=b.id AND m.user_id=%s
                WHERE b.id=%s
                LIMIT 1
                """,
                (user_id, book_id),
            )
            row = cur.fetchone()
        if not row:
            raise ValueError("账本不存在或你无权访问")
        return row

    def get_book_user_ids(self, book_id: int) -> list[int]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT user_id
                FROM ledger_book_members
                WHERE ledger_book_id=%s
                  AND user_id IS NOT NULL
                """,
                (book_id,),
            )
            return [int(row["user_id"]) for row in cur.fetchall() if row.get("user_id")]

    def get_book_detail(self, book_id: int, user_id: int) -> dict:
        book = self.get_book(book_id, user_id)
        members = self.get_book_members(book_id)
        entries = self.get_book_entries(book_id)
        settlement = self.get_settlement_preview(book_id, user_id)
        book["eyebrow"] = (
            "Main Ledger"
            if book["book_type"] == "MAIN"
            else (
                "Travel Ledger"
                if book["book_type"] == "TRAVEL"
                else "Shared Ledger"
            )
        )
        book["location_label"] = self._book_location_label(book)
        my_spend = self._my_total_spend_display(book_id, user_id)
        current_member = next(
            (member for member in members if member.get("user_id") == user_id),
            None,
        )
        book["members"] = members
        book["entries"] = entries
        book["settlement_summary"] = settlement
        book["current_member_id"] = current_member["id"] if current_member else None
        book["current_member_name"] = current_member["name"] if current_member else "我"
        book["my_spend_label"] = (
            "本月支出" if book["book_type"] == "MAIN" else "我的支出"
        )
        book["my_spend_display"] = f"¥ {my_spend}"
        book["hero_metrics"] = [
            {
                "label": book["my_spend_label"],
                "value": book["my_spend_display"],
            },
            {
                "label": "应付款项",
                "value": settlement["my_payable_display"],
            },
            {
                "label": "待收款项",
                "value": settlement["my_receivable_display"],
            },
        ]
        return book

    def get_book_members(self, book_id: int) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.id,
                    m.user_id,
                    m.member_name AS name,
                    m.member_role AS role_code,
                    COALESCE(u.username, m.member_name) AS username
                FROM ledger_book_members m
                LEFT JOIN finance_users u ON u.id=m.user_id
                WHERE m.ledger_book_id=%s
                ORDER BY FIELD(m.member_role, 'OWNER', 'MEMBER', 'VIEWER'), m.id
                """,
                (book_id,),
            )
            rows = list(cur.fetchall())

        role_name_map = {
            "OWNER": "账本拥有者",
            "MEMBER": "共同成员",
            "VIEWER": "只读成员",
        }
        for row in rows:
            row["role"] = role_name_map.get(row["role_code"], "共同成员")
            row["share"] = row["username"]
        return rows

    def get_book_entries(self, book_id: int) -> list[dict]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.id,
                    e.title,
                    e.amount,
                    e.currency,
                    e.occurred_at,
                    e.subcategory_name,
                    e.note,
                    e.merchant_name,
                    e.is_settled,
                    e.shared_group_key,
                    e.is_mirror,
                    c.category_code,
                    c.category_name AS category,
                    payer.member_name AS payer_name,
                    payer.user_id AS payer_user_id
                FROM ledger_entries e
                LEFT JOIN ledger_categories c ON c.id=e.category_id
                LEFT JOIN ledger_book_members payer ON payer.id=e.payer_member_id
                WHERE e.ledger_book_id=%s
                ORDER BY e.occurred_at DESC, e.id DESC
                LIMIT 120
                """,
                (book_id,),
            )
            entries = list(cur.fetchall())

            entry_ids = [entry["id"] for entry in entries]
            participants_by_entry: dict[int, list[str]] = defaultdict(list)
            participant_ids_by_entry: dict[int, list[int]] = defaultdict(list)
            if entry_ids:
                placeholders = ", ".join(["%s"] * len(entry_ids))
                cur.execute(
                    f"""
                    SELECT ep.ledger_entry_id, m.member_name, m.user_id
                    FROM ledger_entry_participants ep
                    JOIN ledger_book_members m ON m.id=ep.member_id
                    WHERE ep.ledger_entry_id IN ({placeholders})
                      AND ep.is_included=1
                    ORDER BY ep.id
                    """,
                    entry_ids,
                )
                for row in cur.fetchall():
                    participants_by_entry[row["ledger_entry_id"]].append(
                        row["member_name"]
                    )
                    if row.get("user_id"):
                        participant_ids_by_entry[row["ledger_entry_id"]].append(
                            int(row["user_id"])
                        )

        for entry in entries:
            category = entry.get("category") or "其他"
            participants = participants_by_entry.get(entry["id"], [])
            entry["date"] = _now_display(entry["occurred_at"])
            entry["occurred_at_display"] = (
                entry["occurred_at"].strftime("%Y-%m-%d %H:%M:%S")
                if entry.get("occurred_at")
                else ""
            )
            entry["occurred_at_input"] = (
                entry["occurred_at"].strftime("%Y-%m-%dT%H:%M")
                if entry.get("occurred_at")
                else ""
            )
            entry["amount_value"] = f"{_to_decimal(entry['amount']):.2f}"
            entry["amount"] = f"{entry['currency']} {entry['amount']}"
            entry["meta"] = (
                f"{entry.get('payer_name') or '未知付款人'}付款"
                + (
                    f" · {len(participants)} 人参与"
                    if participants
                    else ""
                )
            )
            entry["category"] = category
            entry["subcategory_icon"] = SUBCATEGORY_ICON_BY_NAME.get(
                entry.get("subcategory_name") or ""
            )
            entry["participant_names"] = participants
            entry["participant_user_ids"] = participant_ids_by_entry.get(
                entry["id"], []
            )
        return entries

    def create_entry(
        self,
        book_id: int,
        actor_user_id: int,
        *,
        title: str,
        amount: str,
        occurred_at: str,
        category_code: str,
        subcategory_name: str = "",
        note: str = "",
        payer_user_id: int | None = None,
        participant_user_ids: list[int] | None = None,
        share_main_user_id: int | None = None,
        main_share_mode: str = "EQUAL",
        mark_settled: bool = False,
        merchant_name: str = "",
        ai_source: str | None = None,
        ai_confidence: float | None = None,
        ai_raw_payload: dict | list | None = None,
    ) -> None:
        amount_dec = _to_decimal(amount)
        if amount_dec <= ZERO:
            raise ValueError("金额必须大于 0")
        occurred = (
            datetime.fromisoformat(occurred_at)
            if (occurred_at or "").strip()
            else datetime.now()
        )
        main_share_mode = (main_share_mode or "EQUAL").upper()
        group_key = uuid4().hex
        payer_user_id = payer_user_id or actor_user_id

        with get_cursor() as cur:
            book = self._get_book_for_user(cur, book_id, actor_user_id)
            category_id = self._get_category_id_in_tx(cur, category_code)
            title = (
                (title or "").strip()
                or (subcategory_name or "").strip()
                or PRESET_BY_CODE.get((category_code or "").strip().upper(), {}).get("name")
                or "未命名账单"
            )
            member_cache: dict[tuple[int, int], dict] = {}
            user_cache: dict[int, dict] = {}

            owner_member = self._ensure_member(
                cur,
                book_id,
                actor_user_id,
                role="OWNER",
                member_cache=member_cache,
                user_cache=user_cache,
            )
            payer_member = self._ensure_member(
                cur,
                book_id,
                payer_user_id,
                member_cache=member_cache,
                user_cache=user_cache,
            )

            participant_user_ids = [int(user_id) for user_id in (participant_user_ids or [])]
            if book["book_type"] == "MAIN":
                participant_user_ids = self._build_main_participants(
                    actor_user_id=actor_user_id,
                    share_main_user_id=share_main_user_id,
                    share_mode=main_share_mode,
                )

            if not participant_user_ids:
                participant_user_ids = [actor_user_id]

            participant_rows = self._build_participant_rows(
                cur=cur,
                book_id=book_id,
                participant_user_ids=participant_user_ids,
                total_amount=amount_dec,
                member_cache=member_cache,
                user_cache=user_cache,
            )

            entry_id = self._insert_entry(
                cur=cur,
                book_id=book_id,
                creator_member_id=owner_member["id"],
                payer_member_id=payer_member["id"],
                category_id=category_id,
                title=title,
                amount=amount_dec,
                occurred_at=occurred,
                subcategory_name=subcategory_name,
                merchant_name=merchant_name,
                note=note,
                shared_group_key=group_key,
                is_settled=mark_settled,
                is_mirror=0,
                mirror_source_entry_id=None,
                ai_source=ai_source,
                ai_confidence=ai_confidence,
                ai_raw_payload=ai_raw_payload,
            )
            self._insert_participants(cur, entry_id, participant_rows)
            self._insert_settlement_items(
                cur=cur,
                book_id=book_id,
                entry_id=entry_id,
                payer_member_id=payer_member["id"],
                participant_rows=participant_rows,
                mark_settled=mark_settled,
            )

            if book["book_type"] == "MAIN" and share_main_user_id:
                target_main_book_id = self._ensure_main_book_in_tx(
                    cur, share_main_user_id
                )
                target_creator = self._ensure_member(
                    cur,
                    target_main_book_id,
                    share_main_user_id,
                    role="OWNER",
                    member_cache=member_cache,
                    user_cache=user_cache,
                )
                target_payer = self._ensure_member(
                    cur,
                    target_main_book_id,
                    payer_user_id,
                    member_cache=member_cache,
                    user_cache=user_cache,
                )
                target_participant_rows = self._build_participant_rows(
                    cur=cur,
                    book_id=target_main_book_id,
                    participant_user_ids=participant_user_ids,
                    total_amount=amount_dec,
                    member_cache=member_cache,
                    user_cache=user_cache,
                )
                mirror_entry_id = self._insert_entry(
                    cur=cur,
                    book_id=target_main_book_id,
                    creator_member_id=target_creator["id"],
                    payer_member_id=target_payer["id"],
                    category_id=category_id,
                    title=title,
                    amount=amount_dec,
                    occurred_at=occurred,
                    subcategory_name=subcategory_name,
                    merchant_name=merchant_name,
                    note=(note or "").strip() or f"来自共享记录 · {book['name']}",
                    shared_group_key=group_key,
                    is_settled=mark_settled,
                    is_mirror=1,
                    mirror_source_entry_id=entry_id,
                    ai_source=ai_source,
                    ai_confidence=ai_confidence,
                    ai_raw_payload=ai_raw_payload,
                )
                self._insert_participants(cur, mirror_entry_id, target_participant_rows)
                self._insert_settlement_items(
                    cur=cur,
                    book_id=target_main_book_id,
                    entry_id=mirror_entry_id,
                    payer_member_id=target_payer["id"],
                    participant_rows=target_participant_rows,
                    mark_settled=mark_settled,
                )

    def create_ai_entries(
        self,
        book_id: int,
        actor_user_id: int,
        items: list[dict],
        *,
        source_payload: dict | None = None,
    ) -> int:
        created = 0
        for item in items:
            amount = str(item.get("amount") or "").strip()
            if not amount or _to_decimal(amount) <= ZERO:
                continue
            title = str(item.get("title") or "").strip()
            category_code = str(item.get("category_code") or "OTHER").strip().upper()
            if category_code not in PRESET_BY_CODE:
                category_code = "OTHER"
            self.create_entry(
                book_id,
                actor_user_id,
                title=title,
                amount=amount,
                occurred_at=str(item.get("occurred_at") or ""),
                category_code=category_code,
                subcategory_name=str(item.get("subcategory_name") or "").strip(),
                note=str(item.get("note") or "").strip(),
                merchant_name=str(item.get("merchant_name") or "").strip(),
                payer_user_id=actor_user_id,
                participant_user_ids=[actor_user_id],
                ai_source=str(item.get("ai_source") or "MINIMAX").strip() or "MINIMAX",
                ai_confidence=float(item.get("confidence") or 0),
                ai_raw_payload={
                    "item": item,
                    "source": source_payload or {},
                },
            )
            created += 1
        return created

    def update_entry(
        self,
        book_id: int,
        entry_id: int,
        actor_user_id: int,
        *,
        title: str,
        amount: str,
        occurred_at: str,
        category_code: str,
        subcategory_name: str = "",
        note: str = "",
        payer_user_id: int | None = None,
        participant_user_ids: list[int] | None = None,
        mark_settled: bool = False,
    ) -> None:
        amount_dec = _to_decimal(amount)
        if amount_dec <= ZERO:
            raise ValueError("金额必须大于 0")
        occurred = (
            datetime.fromisoformat(occurred_at)
            if (occurred_at or "").strip()
            else datetime.now()
        )
        payer_user_id = payer_user_id or actor_user_id

        with get_cursor() as cur:
            book = self._get_book_for_user(cur, book_id, actor_user_id)
            existing = self._get_entry_for_update(cur, book_id, entry_id)
            category_id = self._get_category_id_in_tx(cur, category_code)
            title = (
                (title or "").strip()
                or (subcategory_name or "").strip()
                or PRESET_BY_CODE.get((category_code or "").strip().upper(), {}).get("name")
                or "未命名账单"
            )
            member_cache: dict[tuple[int, int], dict] = {}
            user_cache: dict[int, dict] = {}
            payer_member = self._ensure_member(
                cur,
                book_id,
                payer_user_id,
                member_cache=member_cache,
                user_cache=user_cache,
            )
            participant_user_ids = [int(user_id) for user_id in (participant_user_ids or [])]
            if book["book_type"] == "MAIN" or not participant_user_ids:
                participant_user_ids = [actor_user_id]
            participant_rows = self._build_participant_rows(
                cur=cur,
                book_id=book_id,
                participant_user_ids=participant_user_ids,
                total_amount=amount_dec,
                member_cache=member_cache,
                user_cache=user_cache,
            )

            cur.execute(
                """
                UPDATE ledger_entries
                SET payer_member_id=%s,
                    category_id=%s,
                    title=%s,
                    amount=%s,
                    amount_in_base=%s,
                    occurred_at=%s,
                    subcategory_name=%s,
                    note=%s,
                    is_settled=%s,
                    settled_at=%s
                WHERE id=%s AND ledger_book_id=%s
                """,
                (
                    payer_member["id"],
                    category_id,
                    title,
                    amount_dec,
                    amount_dec,
                    occurred,
                    subcategory_name.strip() or None,
                    note.strip() or None,
                    1 if mark_settled else 0,
                    datetime.now() if mark_settled else None,
                    entry_id,
                    book_id,
                ),
            )
            cur.execute(
                "DELETE FROM ledger_entry_participants WHERE ledger_entry_id=%s",
                (entry_id,),
            )
            cur.execute(
                "DELETE FROM ledger_settlement_items WHERE ledger_entry_id=%s",
                (entry_id,),
            )
            self._insert_participants(cur, entry_id, participant_rows)
            self._insert_settlement_items(
                cur=cur,
                book_id=book_id,
                entry_id=entry_id,
                payer_member_id=payer_member["id"],
                participant_rows=participant_rows,
                mark_settled=mark_settled,
            )

            if existing.get("mirror_source_entry_id"):
                cur.execute(
                    """
                    UPDATE ledger_entries
                    SET mirror_source_entry_id=%s
                    WHERE id=%s
                    """,
                    (existing["mirror_source_entry_id"], entry_id),
                )

    def delete_entry(self, book_id: int, entry_id: int, actor_user_id: int) -> None:
        with get_cursor() as cur:
            self._get_book_for_user(cur, book_id, actor_user_id)
            existing = self._get_entry_for_update(cur, book_id, entry_id)
            cur.execute(
                "DELETE FROM ledger_entries WHERE id=%s AND ledger_book_id=%s",
                (entry_id, book_id),
            )
            if existing.get("shared_group_key"):
                cur.execute(
                    """
                    DELETE FROM ledger_entries
                    WHERE shared_group_key=%s
                      AND id<>%s
                      AND is_mirror=1
                    """,
                    (existing["shared_group_key"], entry_id),
                )

    def get_settlement_preview(
        self, book_id: int, current_user_id: int | None = None
    ) -> dict:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT
                    si.from_member_id,
                    si.to_member_id,
                    si.amount_base,
                    from_member.user_id AS from_user_id,
                    to_member.user_id AS to_user_id,
                    from_member.member_name AS from_name,
                    to_member.member_name AS to_name
                FROM ledger_settlement_items si
                JOIN ledger_book_members from_member ON from_member.id=si.from_member_id
                JOIN ledger_book_members to_member ON to_member.id=si.to_member_id
                WHERE si.ledger_book_id=%s
                  AND si.status='PENDING'
                """,
                (book_id,),
            )
            settlement_rows = list(cur.fetchall())
            cur.execute(
                """
                SELECT
                    sp.from_member_id,
                    sp.to_member_id,
                    sp.amount_base,
                    from_member.user_id AS from_user_id,
                    to_member.user_id AS to_user_id,
                    from_member.member_name AS from_name,
                    to_member.member_name AS to_name
                FROM ledger_settlement_payments sp
                JOIN ledger_book_members from_member ON from_member.id=sp.from_member_id
                JOIN ledger_book_members to_member ON to_member.id=sp.to_member_id
                WHERE sp.ledger_book_id=%s
                """,
                (book_id,),
            )
            payment_rows = list(cur.fetchall())

        net_by_user: dict[int, Decimal] = defaultdict(lambda: ZERO)
        name_by_user: dict[int, str] = {}
        member_id_by_user: dict[int, int] = {}

        for row in settlement_rows:
            from_user_id = row.get("from_user_id")
            to_user_id = row.get("to_user_id")
            amount = _to_decimal(row["amount_base"])
            if from_user_id:
                net_by_user[from_user_id] -= amount
                name_by_user[from_user_id] = row["from_name"]
                member_id_by_user[from_user_id] = int(row["from_member_id"])
            if to_user_id:
                net_by_user[to_user_id] += amount
                name_by_user[to_user_id] = row["to_name"]
                member_id_by_user[to_user_id] = int(row["to_member_id"])

        for row in payment_rows:
            from_user_id = row.get("from_user_id")
            to_user_id = row.get("to_user_id")
            amount = _to_decimal(row["amount_base"])
            if from_user_id:
                net_by_user[from_user_id] += amount
                name_by_user[from_user_id] = row["from_name"]
                member_id_by_user[from_user_id] = int(row["from_member_id"])
            if to_user_id:
                net_by_user[to_user_id] -= amount
                name_by_user[to_user_id] = row["to_name"]
                member_id_by_user[to_user_id] = int(row["to_member_id"])

        transfers = self._build_transfers(
            net_by_user, name_by_user, member_id_by_user
        )
        total_open = sum(
            (transfer.amount for transfer in transfers), start=ZERO
        ).quantize(Decimal("0.01"))
        my_payable = ZERO
        my_receivable = ZERO
        transfer_items = []
        for transfer in transfers:
            if current_user_id and transfer.from_member_id == member_id_by_user.get(
                current_user_id
            ):
                my_payable += transfer.amount
            if current_user_id and transfer.to_member_id == member_id_by_user.get(
                current_user_id
            ):
                my_receivable += transfer.amount
            transfer_items.append(
                {
                    "from": transfer.from_name,
                    "to": transfer.to_name,
                    "amount": f"¥ {transfer.amount}",
                    "amount_value": f"{transfer.amount}",
                    "from_member_id": transfer.from_member_id,
                    "to_member_id": transfer.to_member_id,
                }
            )
        return {
            "headline": "最优结算路径",
            "summary_label": f"¥ {total_open}",
            "items": transfer_items,
            "my_payable_display": f"¥ {my_payable.quantize(Decimal('0.01'))}",
            "my_receivable_display": f"¥ {my_receivable.quantize(Decimal('0.01'))}",
            "total_transfer_count": len(transfer_items),
        }

    def settle_book(self, book_id: int, actor_user_id: int) -> int:
        self.get_book(book_id, actor_user_id)
        settlement = self.get_settlement_preview(book_id, actor_user_id)
        if not settlement["items"]:
            return 0
        created = 0
        with get_cursor() as cur:
            actor_member = self._ensure_member(cur, book_id, actor_user_id, role="OWNER")
            for item in settlement["items"]:
                cur.execute(
                    """
                    INSERT INTO ledger_settlement_payments
                        (ledger_book_id, from_member_id, to_member_id,
                         amount_base, note, created_by_member_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        book_id,
                        item["from_member_id"],
                        item["to_member_id"],
                        _to_decimal(item["amount_value"]),
                        "批量结清当前最优结算结果",
                        actor_member["id"],
                    ),
                )
                created += 1
        return created

    def settle_transfer(
        self,
        book_id: int,
        actor_user_id: int,
        *,
        from_member_id: int,
        to_member_id: int,
        amount: str,
    ) -> None:
        self.get_book(book_id, actor_user_id)
        amount_dec = _to_decimal(amount)
        if amount_dec <= ZERO:
            raise ValueError("结算金额必须大于 0")

        settlement = self.get_settlement_preview(book_id, actor_user_id)
        matched = next(
            (
                item
                for item in settlement["items"]
                if item["from_member_id"] == from_member_id
                and item["to_member_id"] == to_member_id
                and _to_decimal(item["amount_value"]) == amount_dec
            ),
            None,
        )
        if not matched:
            raise ValueError("这条结算关系已经变化，请刷新后重试")

        with get_cursor() as cur:
            actor_member = self._ensure_member(cur, book_id, actor_user_id, role="OWNER")
            cur.execute(
                """
                INSERT INTO ledger_settlement_payments
                    (ledger_book_id, from_member_id, to_member_id,
                     amount_base, note, created_by_member_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    book_id,
                    from_member_id,
                    to_member_id,
                    amount_dec,
                    "手动结清单条最优结算关系",
                    actor_member["id"],
                ),
            )

    def _ensure_member(
        self,
        cur,
        book_id: int,
        user_id: int,
        *,
        role: str = "MEMBER",
        member_cache: dict[tuple[int, int], dict] | None = None,
        user_cache: dict[int, dict] | None = None,
    ) -> dict:
        cache_key = (book_id, user_id)
        if member_cache is not None and cache_key in member_cache:
            return member_cache[cache_key]
        cur.execute(
            """
            SELECT id, user_id, member_name, member_role
            FROM ledger_book_members
            WHERE ledger_book_id=%s AND user_id=%s
            LIMIT 1
            """,
            (book_id, user_id),
        )
        row = cur.fetchone()
        if row:
            if member_cache is not None:
                member_cache[cache_key] = row
            return row

        user = user_cache.get(user_id) if user_cache is not None else None
        if not user:
            cur.execute(
                """
                SELECT username, COALESCE(display_name, username) AS display_name
                FROM finance_users
                WHERE id=%s
                LIMIT 1
                """,
                (user_id,),
            )
            user = cur.fetchone()
            if user and user_cache is not None:
                user_cache[user_id] = user
        if not user:
            raise ValueError("共享用户不存在")
        cur.execute(
            """
            INSERT INTO ledger_book_members
                (ledger_book_id, user_id, member_name, member_role, can_edit)
            VALUES (%s, %s, %s, %s, 1)
            """,
            (book_id, user_id, user["display_name"], role),
        )
        row = {
            "id": cur.lastrowid,
            "user_id": user_id,
            "member_name": user["display_name"],
            "member_role": role,
        }
        if member_cache is not None:
            member_cache[cache_key] = row
        return row

    def _get_category_id(self, category_code: str) -> int:
        with get_cursor() as cur:
            row = self._get_category_id_row(cur, category_code)
        if not row:
            raise ValueError("分类不存在")
        return int(row["id"])

    def _build_main_participants(
        self,
        *,
        actor_user_id: int,
        share_main_user_id: int | None,
        share_mode: str,
    ) -> list[int]:
        if not share_main_user_id:
            return [actor_user_id]
        if share_mode == "OTHER_ONLY":
            return [share_main_user_id]
        if share_mode == "SELF_ONLY":
            return [actor_user_id]
        return [actor_user_id, share_main_user_id]

    def _get_entry_for_update(self, cur, book_id: int, entry_id: int) -> dict:
        cur.execute(
            """
            SELECT id, ledger_book_id, shared_group_key, mirror_source_entry_id, is_mirror
            FROM ledger_entries
            WHERE id=%s AND ledger_book_id=%s
            LIMIT 1
            """,
            (entry_id, book_id),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("账单不存在")
        return row

    def _build_participant_rows(
        self,
        *,
        cur,
        book_id: int,
        participant_user_ids: list[int],
        total_amount: Decimal,
        member_cache: dict[tuple[int, int], dict] | None = None,
        user_cache: dict[int, dict] | None = None,
    ) -> list[dict]:
        unique_user_ids = list(dict.fromkeys(participant_user_ids))
        if not unique_user_ids:
            return []
        share_amount = (total_amount / len(unique_user_ids)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        rows: list[dict] = []
        remainder = total_amount - (share_amount * len(unique_user_ids))
        for index, participant_user_id in enumerate(unique_user_ids):
            member = self._ensure_member(
                cur,
                book_id,
                participant_user_id,
                member_cache=member_cache,
                user_cache=user_cache,
            )
            owed = share_amount + (remainder if index == 0 else ZERO)
            rows.append(
                {
                    "member_id": member["id"],
                    "share_ratio": Decimal("1.0000"),
                    "fixed_amount": None,
                    "amount_owed_base": owed,
                }
            )
        return rows

    def _insert_entry(
        self,
        *,
        cur,
        book_id: int,
        creator_member_id: int,
        payer_member_id: int,
        category_id: int,
        title: str,
        amount: Decimal,
        occurred_at: datetime,
        subcategory_name: str,
        merchant_name: str,
        note: str,
        shared_group_key: str,
        is_settled: bool,
        is_mirror: int,
        mirror_source_entry_id: int | None,
        ai_source: str | None,
        ai_confidence: float | None,
        ai_raw_payload: dict | list | None,
    ) -> int:
        cur.execute(
            """
            INSERT INTO ledger_entries
                (ledger_book_id, created_by_member_id, payer_member_id,
                 category_id, title, amount, currency, exchange_rate_to_base,
                 amount_in_base, occurred_at, subcategory_name, merchant_name, note,
                 ai_source, ai_confidence, ai_raw_payload,
                 status, shared_group_key, is_mirror, mirror_source_entry_id,
                 is_settled, settled_at)
            VALUES (%s, %s, %s, %s, %s, %s, 'CNY', 1, %s, %s, %s, %s, %s,
                    %s, %s, %s, 'CONFIRMED', %s, %s, %s, %s, %s)
            """,
            (
                book_id,
                creator_member_id,
                payer_member_id,
                category_id,
                title,
                amount,
                amount,
                occurred_at,
                subcategory_name.strip() or None,
                merchant_name.strip() or None,
                note.strip() or None,
                (ai_source or "").strip() or None,
                None if ai_confidence is None else round(float(ai_confidence) * 100, 2),
                json.dumps(ai_raw_payload, ensure_ascii=False)
                if ai_raw_payload is not None
                else None,
                shared_group_key,
                is_mirror,
                mirror_source_entry_id,
                1 if is_settled else 0,
                datetime.now() if is_settled else None,
            ),
        )
        return int(cur.lastrowid)

    def _insert_participants(self, cur, entry_id: int, rows: list[dict]) -> None:
        if not rows:
            return
        cur.executemany(
            """
            INSERT INTO ledger_entry_participants
                (ledger_entry_id, member_id, share_ratio,
                 fixed_amount, amount_owed_base, is_included)
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            [
                (
                    entry_id,
                    row["member_id"],
                    row["share_ratio"],
                    row["fixed_amount"],
                    row["amount_owed_base"],
                )
                for row in rows
            ],
        )

    def _insert_settlement_items(
        self,
        *,
        cur,
        book_id: int,
        entry_id: int,
        payer_member_id: int,
        participant_rows: list[dict],
        mark_settled: bool,
    ) -> None:
        payload = []
        for row in participant_rows:
            if row["member_id"] == payer_member_id:
                continue
            amount = _to_decimal(row["amount_owed_base"])
            if amount <= ZERO:
                continue
            payload.append(
                (
                    book_id,
                    entry_id,
                    row["member_id"],
                    payer_member_id,
                    amount,
                    "SETTLED" if mark_settled else "PENDING",
                    datetime.now() if mark_settled else None,
                )
            )
        if not payload:
            return
        cur.executemany(
            """
            INSERT INTO ledger_settlement_items
                (ledger_book_id, ledger_entry_id, from_member_id, to_member_id,
                 amount_base, status, settled_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            payload,
        )

    def _get_book_for_user(self, cur, book_id: int, user_id: int) -> dict:
        self._ensure_main_book_in_tx(cur, user_id)
        cur.execute(
            """
            SELECT b.*
            FROM ledger_books b
            JOIN ledger_book_members m
              ON m.ledger_book_id=b.id AND m.user_id=%s
            WHERE b.id=%s
            LIMIT 1
            """,
            (user_id, book_id),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("账本不存在或你无权访问")
        return row

    def _ensure_main_book_in_tx(self, cur, user_id: int) -> int:
        cur.execute(
            """
            SELECT id
            FROM ledger_books
            WHERE owner_user_id=%s AND is_default_main=1
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            book_id = int(row["id"])
        else:
            cur.execute(
                """
                INSERT INTO ledger_books
                    (owner_user_id, book_type, name, description,
                     base_currency, is_default_main, display_location)
                VALUES (%s, 'MAIN', '主账本', '默认个人账本，不可删除',
                        'CNY', 1, '默认总账')
                """,
                (user_id,),
            )
            book_id = int(cur.lastrowid)
        self._ensure_member(cur, book_id, user_id, role="OWNER")
        return book_id

    def _get_category_id_in_tx(self, cur, category_code: str) -> int:
        row = self._get_category_id_row(cur, category_code)
        if not row:
            raise ValueError("分类不存在")
        return int(row["id"])

    def _get_category_id_row(self, cur, category_code: str) -> dict | None:
        cur.execute(
            """
            SELECT id
            FROM ledger_categories
            WHERE category_code=%s
            LIMIT 1
            """,
            ((category_code or "").strip().upper(),),
        )
        return cur.fetchone()

    def _build_transfers(
        self,
        net_by_user: dict[int, Decimal],
        name_by_user: dict[int, str],
        member_id_by_user: dict[int, int],
    ) -> list[SettlementTransfer]:
        members: list[dict] = []
        for user_id, balance in net_by_user.items():
            rounded = balance.quantize(Decimal("0.01"))
            if rounded == ZERO:
                continue
            member_id = int(member_id_by_user.get(user_id, 0))
            if not member_id:
                continue
            members.append(
                {
                    "member_id": member_id,
                    "name": name_by_user.get(user_id, str(user_id)),
                    "balance_cents": int(rounded * 100),
                }
            )

        if not members:
            return []

        if len(members) > 12:
            return self._build_transfers_greedy(members)

        memo: dict[tuple[int, ...], list[tuple[int, int, int]]] = {}

        def search(state: tuple[int, ...]) -> list[tuple[int, int, int]]:
            if state in memo:
                return memo[state]

            start = 0
            while start < len(state) and state[start] == 0:
                start += 1
            if start >= len(state):
                return []

            best: list[tuple[int, int, int]] | None = None
            seen: set[int] = set()
            current = state[start]
            for index in range(start + 1, len(state)):
                candidate = state[index]
                if candidate == 0 or current * candidate > 0 or candidate in seen:
                    continue
                seen.add(candidate)
                amount = min(abs(current), abs(candidate))
                next_state = list(state)
                if current < 0:
                    next_state[start] += amount
                    next_state[index] -= amount
                    transfer = (start, index, amount)
                else:
                    next_state[start] -= amount
                    next_state[index] += amount
                    transfer = (index, start, amount)
                remainder = search(tuple(next_state))
                candidate_result = [transfer, *remainder]
                if best is None or len(candidate_result) < len(best):
                    best = candidate_result
                if abs(candidate) == abs(current):
                    break

            memo[state] = best or []
            return memo[state]

        transfer_specs = search(
            tuple(member["balance_cents"] for member in members)
        )
        return [
            SettlementTransfer(
                from_member_id=members[from_index]["member_id"],
                to_member_id=members[to_index]["member_id"],
                from_name=members[from_index]["name"],
                to_name=members[to_index]["name"],
                amount=Decimal(amount_cents).scaleb(-2).quantize(Decimal("0.01")),
            )
            for from_index, to_index, amount_cents in transfer_specs
        ]

    def _build_transfers_greedy(
        self, members: list[dict]
    ) -> list[SettlementTransfer]:
        creditors = [
            [index, member["balance_cents"]]
            for index, member in enumerate(members)
            if member["balance_cents"] > 0
        ]
        debtors = [
            [index, -member["balance_cents"]]
            for index, member in enumerate(members)
            if member["balance_cents"] < 0
        ]
        creditors.sort(key=lambda item: item[1], reverse=True)
        debtors.sort(key=lambda item: item[1], reverse=True)

        transfers: list[SettlementTransfer] = []
        c_idx = 0
        d_idx = 0
        while c_idx < len(creditors) and d_idx < len(debtors):
            creditor_index, creditor_amt = creditors[c_idx]
            debtor_index, debtor_amt = debtors[d_idx]
            amount_cents = min(creditor_amt, debtor_amt)
            transfers.append(
                SettlementTransfer(
                    from_member_id=members[debtor_index]["member_id"],
                    to_member_id=members[creditor_index]["member_id"],
                    from_name=members[debtor_index]["name"],
                    to_name=members[creditor_index]["name"],
                    amount=Decimal(amount_cents).scaleb(-2).quantize(
                        Decimal("0.01")
                    ),
                )
            )
            creditors[c_idx][1] -= amount_cents
            debtors[d_idx][1] -= amount_cents
            if creditors[c_idx][1] == 0:
                c_idx += 1
            if debtors[d_idx][1] == 0:
                d_idx += 1
        return transfers

    def _book_subtitle(self, book: dict) -> str:
        if book["book_type"] == "MAIN":
            return "你的默认个人账本，不可删除"
        if book["book_type"] == "TRAVEL":
            return "多人共享的旅行账本，支持结算"
        return "多人共享的自定义账本"

    def _book_location_label(self, book: dict) -> str:
        if book.get("display_location"):
            return book["display_location"]
        if book["book_type"] == "MAIN":
            return "默认总账 · 长期记录"
        return "共享账本 · 可后续补地点"

    def _member_preview_names(self, book_id: int) -> list[str]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT member_name
                FROM ledger_book_members
                WHERE ledger_book_id=%s
                ORDER BY FIELD(member_role, 'OWNER', 'MEMBER', 'VIEWER'), id
                LIMIT 3
                """,
                (book_id,),
            )
            return [row["member_name"] for row in cur.fetchall()]

    def _my_total_spend_display(self, book_id: int, user_id: int) -> str:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(
                    SUM(
                        CASE
                            WHEN b.book_type='MAIN'
                             AND DATE_FORMAT(e.occurred_at, '%%Y-%%m')
                                 = DATE_FORMAT(CURRENT_DATE(), '%%Y-%%m')
                            THEN ep.amount_owed_base
                            WHEN b.book_type<>'MAIN' THEN ep.amount_owed_base
                            ELSE 0
                        END
                    ),
                    0
                ) AS total_amount
                FROM ledger_entry_participants ep
                JOIN ledger_entries e ON e.id=ep.ledger_entry_id
                JOIN ledger_books b ON b.id=e.ledger_book_id
                JOIN ledger_book_members member ON member.id=ep.member_id
                WHERE e.ledger_book_id=%s
                  AND member.user_id=%s
                  AND ep.is_included=1
                """,
                (book_id, user_id),
            )
            row = cur.fetchone()
        total_amount = _to_decimal((row or {}).get("total_amount"))
        return f"{total_amount}"
