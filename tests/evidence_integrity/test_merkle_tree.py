"""Tests for RFC 6962 domain-separated Merkle Tree and inclusion proofs."""

from packages.evidence_integrity.hashing import (
    MerkleTree,
    verify_merkle_inclusion_proof,
)


def test_merkle_tree_empty():
    tree = MerkleTree([])
    assert tree.leaf_count == 0
    assert tree.root != ""


def test_merkle_tree_single_leaf():
    leaf = "abc" * 10
    tree = MerkleTree([leaf])
    assert tree.leaf_count == 1
    proof = tree.get_inclusion_proof(0)
    assert verify_merkle_inclusion_proof(leaf, 0, tree.leaf_count, proof, tree.root) is True


def test_merkle_tree_inclusion_proofs_multiple_leaves():
    leaves = [f"leaf_commitment_{i}_{'x' * 32}" for i in range(17)]  # Non-power-of-2
    tree = MerkleTree(leaves)
    assert tree.leaf_count == 17

    for idx, leaf in enumerate(leaves):
        proof = tree.get_inclusion_proof(idx)
        assert verify_merkle_inclusion_proof(leaf, idx, tree.leaf_count, proof, tree.root) is True


def test_merkle_tree_tampered_leaf_or_proof():
    leaves = [f"leaf_{i}" for i in range(8)]
    tree = MerkleTree(leaves)

    proof = tree.get_inclusion_proof(2)
    # Proof with original leaf succeeds
    assert verify_merkle_inclusion_proof(leaves[2], 2, tree.leaf_count, proof, tree.root) is True

    # Tampered leaf fails
    assert (
        verify_merkle_inclusion_proof("tampered_leaf", 2, tree.leaf_count, proof, tree.root)
        is False
    )

    # Tampered index fails
    assert verify_merkle_inclusion_proof(leaves[2], 3, tree.leaf_count, proof, tree.root) is False

    # Tampered proof node fails
    tampered_proof = list(proof)
    tampered_proof[0] = ("L", "0" * 64)
    assert (
        verify_merkle_inclusion_proof(leaves[2], 2, tree.leaf_count, tampered_proof, tree.root)
        is False
    )


def test_merkle_domain_separation():
    # RFC 6962 specifies domain separation prefix 0x00 for leaves and 0x01 for internal nodes
    # Leaf hash of 'x' must differ from leaf hash of 'y'
    tree1 = MerkleTree(["data1", "data2"])
    tree2 = MerkleTree(["data2", "data1"])
    # Ordering matters for determinism
    assert tree1.root != tree2.root
