from __future__ import annotations

from typing import Any, Optional

from app.repositories.base import BaseRepository, serialize, to_object_id, utcnow


class OrganizationRepository(BaseRepository):
    collection_name = "organizations"

    async def create(self, name: str, industry: Optional[str] = None) -> dict[str, Any]:
        doc = {"name": name, "industry": industry, "created_at": utcnow()}
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize(doc)  # type: ignore[return-value]

    async def get(self, organization_id: str) -> Optional[dict[str, Any]]:
        return serialize(await self.collection.find_one({"_id": to_object_id(organization_id)}))


class UserRepository(BaseRepository):
    collection_name = "users"

    async def get_by_email(self, email: str) -> Optional[dict[str, Any]]:
        return serialize(await self.collection.find_one({"email": email.lower().strip()}))

    async def get_by_email_with_hash(self, email: str) -> Optional[dict[str, Any]]:
        """Includes hashed_password - only for the login path."""
        doc = await self.collection.find_one({"email": email.lower().strip()})
        return serialize(doc)

    async def get(self, user_id: str) -> Optional[dict[str, Any]]:
        return serialize(await self.collection.find_one({"_id": to_object_id(user_id)}))

    async def create(
        self,
        *,
        name: str,
        email: str,
        hashed_password: str,
        organization_id: str,
        role: str,
    ) -> dict[str, Any]:
        doc = {
            "name": name,
            "email": email.lower().strip(),
            "hashed_password": hashed_password,
            "organization_id": to_object_id(organization_id, "organization_id"),
            "role": role,
            "created_at": utcnow(),
        }
        result = await self.collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return serialize(doc)  # type: ignore[return-value]

    async def count_in_org(self, organization_id: str) -> int:
        return await self.collection.count_documents(
            {"organization_id": to_object_id(organization_id, "organization_id")}
        )
