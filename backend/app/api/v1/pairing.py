"""Device pairing endpoints (OR-47). See app/auth/pairing.py for the design."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DataResponse
from app.auth import pairing as service
from app.db.session import get_db

router = APIRouter(prefix="/pairing", tags=["pairing"])


class PairingOut(BaseModel):
    id: str
    code: str
    expires_at: datetime
    ttl_seconds: int


class PairingStatusOut(BaseModel):
    id: str
    status: str            # pending | redeemed | expired
    expires_at: datetime
    redeemed_at: datetime | None
    device_name: str | None


class RedeemIn(BaseModel):
    code: str = Field(max_length=64)
    device_name: str | None = Field(default=None, max_length=200)


class RedeemOut(BaseModel):
    api_key: str
    key_id: str
    identifier: str


def _require_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            400,
            "Pairing issues a key to a user, and this request authenticated with the "
            "deployment key, which has none. Sign in with an issued key to pair devices.",
        )
    return user_id


@router.post("", response_model=DataResponse[PairingOut], status_code=201)
async def create_pairing(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _require_user(request)
    issued = await service.create(db, user_id)
    await db.commit()
    return DataResponse(data=PairingOut(
        id=issued.id,
        code=issued.code,
        expires_at=issued.expires_at,
        ttl_seconds=int(service.TTL.total_seconds()),
    ))


@router.get("/{pairing_id}", response_model=DataResponse[PairingStatusOut])
async def pairing_status(pairing_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _require_user(request)
    found = await service.status(db, pairing_id, user_id)
    if found is None:
        raise HTTPException(404, "Pairing not found")
    return DataResponse(data=PairingStatusOut(**found))


@router.post("/redeem", response_model=DataResponse[RedeemOut])
async def redeem_pairing(body: RedeemIn, db: AsyncSession = Depends(get_db)):
    """Unauthenticated by necessity: the device redeeming has no key yet. The
    code is the credential — see the module docstring for why 50 bits and a
    five-minute life are enough without a rate limiter."""
    try:
        redeemed = await service.redeem(db, body.code, body.device_name)
    except service.PairingError:
        raise HTTPException(400, "That code is invalid or has expired. Ask for a new one.")
    await db.commit()
    return DataResponse(data=RedeemOut(
        api_key=redeemed.api_key, key_id=redeemed.key_id, identifier=redeemed.identifier,
    ))
