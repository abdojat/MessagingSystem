"""Pure SHA-256 Merkle-tree primitives used by audit checkpoints.

Leaves and internal nodes are domain separated.  An unpaired final node is
promoted unchanged to the next level; it is never duplicated.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict


HASH_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_PROOF_SIBLINGS = 64


class MerkleProofNode(TypedDict):
    side: Literal["left", "right"]
    hash: str


@dataclass(frozen=True)
class MerkleProof:
    leaf_index: int
    leaf_count: int
    siblings: tuple[MerkleProofNode, ...]


def _hash_bytes(value: str, *, field: str = "hash") -> bytes:
    if not isinstance(value, str) or HASH_HEX_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase 64-character SHA-256 hex string")
    return bytes.fromhex(value)


def _validate_leaf_position(leaf_index: int, leaf_count: int) -> None:
    if not isinstance(leaf_count, int) or isinstance(leaf_count, bool) or leaf_count < 1:
        raise ValueError("leaf_count must be a positive integer")
    if not isinstance(leaf_index, int) or isinstance(leaf_index, bool) or not 0 <= leaf_index < leaf_count:
        raise ValueError("leaf_index is outside the Merkle batch")


def leaf_hash(event_hash: str) -> str:
    """Hash one raw 32-byte event digest with the 0x00 leaf domain."""

    return hashlib.sha256(b"\x00" + _hash_bytes(event_hash, field="event_hash")).hexdigest()


def parent_hash(left_child: str, right_child: str) -> str:
    """Hash two raw 32-byte child digests with the 0x01 node domain."""

    left = _hash_bytes(left_child, field="left_child")
    right = _hash_bytes(right_child, field="right_child")
    return hashlib.sha256(b"\x01" + left + right).hexdigest()


def build_merkle_root(leaves: Sequence[str]) -> str:
    """Return the root for already-domain-separated leaf hashes."""

    if not leaves:
        raise ValueError("a Merkle tree requires at least one leaf")
    level = [_hash_bytes(value, field="leaf_hash").hex() for value in leaves]
    while len(level) > 1:
        next_level: list[str] = []
        for index in range(0, len(level), 2):
            if index + 1 == len(level):
                next_level.append(level[index])
            else:
                next_level.append(parent_hash(level[index], level[index + 1]))
        level = next_level
    return level[0]


def build_merkle_proof(leaves: Sequence[str], leaf_index: int) -> MerkleProof:
    """Build an explicit left/right proof for one already-hashed leaf."""

    _validate_leaf_position(leaf_index, len(leaves))
    level = [_hash_bytes(value, field="leaf_hash").hex() for value in leaves]
    index = leaf_index
    siblings: list[MerkleProofNode] = []

    while len(level) > 1:
        if index % 2 == 1:
            siblings.append({"side": "left", "hash": level[index - 1]})
        elif index + 1 < len(level):
            siblings.append({"side": "right", "hash": level[index + 1]})

        next_level: list[str] = []
        for pair_index in range(0, len(level), 2):
            if pair_index + 1 == len(level):
                next_level.append(level[pair_index])
            else:
                next_level.append(parent_hash(level[pair_index], level[pair_index + 1]))
        level = next_level
        index //= 2

    if len(siblings) > MAX_PROOF_SIBLINGS:
        raise ValueError("Merkle proof exceeds the supported sibling bound")
    return MerkleProof(leaf_index=leaf_index, leaf_count=len(leaves), siblings=tuple(siblings))


def verify_merkle_proof(
    leaf_hash_value: str,
    *,
    leaf_index: int,
    leaf_count: int,
    siblings: Sequence[MerkleProofNode | dict[str, str]],
    merkle_root: str,
) -> bool:
    """Verify a proof while binding its path to both leaf index and count."""

    try:
        _validate_leaf_position(leaf_index, leaf_count)
        current = _hash_bytes(leaf_hash_value, field="leaf_hash").hex()
        expected_root = _hash_bytes(merkle_root, field="merkle_root").hex()
        if not isinstance(siblings, (list, tuple)) or len(siblings) > MAX_PROOF_SIBLINGS:
            return False

        proof_index = 0
        index = leaf_index
        width = leaf_count
        while width > 1:
            expected_side: Literal["left", "right"] | None
            if index % 2 == 1:
                expected_side = "left"
            elif index + 1 < width:
                expected_side = "right"
            else:
                expected_side = None

            if expected_side is not None:
                if proof_index >= len(siblings):
                    return False
                node = siblings[proof_index]
                if not isinstance(node, dict) or set(node) != {"side", "hash"}:
                    return False
                if node.get("side") != expected_side:
                    return False
                sibling = _hash_bytes(node.get("hash", ""), field="sibling_hash").hex()
                current = parent_hash(sibling, current) if expected_side == "left" else parent_hash(current, sibling)
                proof_index += 1

            index //= 2
            width = (width + 1) // 2

        return proof_index == len(siblings) and current == expected_root
    except (TypeError, ValueError):
        return False


def build_event_merkle_root(event_hashes: Sequence[str]) -> str:
    return build_merkle_root([leaf_hash(value) for value in event_hashes])


def verify_event_merkle_proof(
    event_hash: str,
    *,
    leaf_index: int,
    leaf_count: int,
    siblings: Sequence[MerkleProofNode | dict[str, str]],
    merkle_root: str,
) -> bool:
    try:
        hashed_leaf = leaf_hash(event_hash)
    except (TypeError, ValueError):
        return False
    return verify_merkle_proof(
        hashed_leaf,
        leaf_index=leaf_index,
        leaf_count=leaf_count,
        siblings=siblings,
        merkle_root=merkle_root,
    )
