from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class MerkleStatusResponse(BaseModel):
    total_events: int
    integrity_hashed_events: int
    checkpointed_events: int
    pending_events: int
    missing_integrity_events: int
    batch_count: int
    latest_sequence: int | None
    latest_root: str | None
    latest_checkpoint_hash: str | None
    latest_signing_key_id: str | None
    latest_signature_valid: bool | None
    checkpoint_chain_valid: bool
    reason_code: str | None


class MerkleBatchItem(BaseModel):
    id: UUID
    sequence_no: int
    leaf_count: int
    merkle_root: str
    checkpoint_hash: str
    previous_checkpoint_hash: str | None
    signing_key_id: str
    created_at: datetime


class MerkleBatchListResponse(BaseModel):
    items: list[MerkleBatchItem]
    total: int


class MerkleProofNodeResponse(BaseModel):
    side: Literal["left", "right"]
    hash: str


class MerkleCheckpointMetadata(BaseModel):
    checkpoint_version: int
    sequence_no: int
    merkle_version: int
    hash_algorithm: str
    leaf_count: int
    first_event_id: UUID
    last_event_id: UUID
    first_event_hash: str
    last_event_hash: str
    merkle_root: str
    previous_checkpoint_hash: str | None
    signing_key_id: str
    created_at: datetime


class MerkleVerificationResponse(BaseModel):
    valid: bool
    event_hash_valid: bool
    inclusion_proof_valid: bool
    checkpoint_hash_valid: bool
    signature_valid: bool
    checkpoint_chain_valid: bool | None
    reason_code: str | None


class MerkleProofResponse(BaseModel):
    proof_version: int
    event_id: UUID
    event_hash: str
    leaf_hash: str
    batch_id: UUID
    batch_sequence: int
    leaf_index: int
    leaf_count: int
    merkle_root: str
    siblings: list[MerkleProofNodeResponse]
    checkpoint: MerkleCheckpointMetadata
    checkpoint_hash: str
    signature: str
    verification: MerkleVerificationResponse
