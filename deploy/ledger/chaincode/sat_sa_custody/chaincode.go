package main

import (
	"encoding/json"
	"fmt"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

// EvidenceAnchor represents the minimal opaque audit metadata stored on the permissioned ledger.
type EvidenceAnchor struct {
	EventID            string `json:"eventId"`
	EntityID           string `json:"entityId"`
	EventType          string `json:"eventType"`
	SequenceNumber     int    `json:"sequenceNumber"`
	ObjectType         string `json:"objectType"`
	ObjectID           string `json:"objectId"`
	ObjectVersion      int    `json:"objectVersion"`
	EvidenceCommitment string `json:"evidenceCommitment"`
	PayloadDigest      string `json:"payloadDigest"`
	Signature          string `json:"signature"`
	SigningKeyID       string `json:"signingKeyId"`
	ActorID            string `json:"actorId"`
	Timestamp          string `json:"timestamp"`
	IdempotencyKey     string `json:"idempotencyKey"`
}

// CustodySmartContract provides chaincode functions for anchoring and verifying evidence commitments.
type CustodySmartContract struct {
	contractapi.Contract
}

func (s *CustodySmartContract) InitLedger(ctx contractapi.TransactionContextInterface) error {
	return nil
}

// AnchorCommitment records a verified evidence commitment onto the immutable ledger.
func (s *CustodySmartContract) AnchorCommitment(ctx contractapi.TransactionContextInterface, payloadJSON string) (*EvidenceAnchor, error) {
	// 1. Enforce submitter authorization
	clientMSPID, err := ctx.GetClientIdentity().GetMSPID()
	if err != nil {
		return nil, fmt.Errorf("failed to retrieve client MSP ID: %v", err)
	}

	allowedMSPs := map[string]bool{
		"RegulatorMSP":  true,
		"SupervisedMSP": true,
	}
	if !allowedMSPs[clientMSPID] {
		return nil, fmt.Errorf("unauthorized submitter MSP: %s", clientMSPID)
	}

	var anchor EvidenceAnchor
	err = json.Unmarshal([]byte(payloadJSON), &anchor)
	if err != nil {
		return nil, fmt.Errorf("failed to parse commitment JSON: %v", err)
	}

	if anchor.EventID == "" || anchor.EntityID == "" || anchor.PayloadDigest == "" {
		return nil, fmt.Errorf("missing required commitment fields (eventId, entityId, payloadDigest)")
	}

	// 2. Check Idempotency: prevent duplicates and handle retries cleanly
	idempotencyKey := fmt.Sprintf("IDEM_%s", anchor.IdempotencyKey)
	existingIdemBytes, err := ctx.GetStub().GetState(idempotencyKey)
	if err != nil {
		return nil, fmt.Errorf("failed reading idempotency state: %v", err)
	}

	if existingIdemBytes != nil {
		var existingAnchor EvidenceAnchor
		err = json.Unmarshal(existingIdemBytes, &existingAnchor)
		if err == nil && existingAnchor.PayloadDigest == anchor.PayloadDigest {
			// Idempotent retry: return previously anchored record
			return &existingAnchor, nil
		}
		return nil, fmt.Errorf("idempotency conflict: key %s already used for different commitment", anchor.IdempotencyKey)
	}

	// 3. Prevent duplicate anchor for same eventId
	anchorKey := fmt.Sprintf("ANCHOR_%s", anchor.EventID)
	existingAnchorBytes, err := ctx.GetStub().GetState(anchorKey)
	if err != nil {
		return nil, fmt.Errorf("failed reading anchor state: %v", err)
	}
	if existingAnchorBytes != nil {
		return nil, fmt.Errorf("commitment for event %s is already anchored", anchor.EventID)
	}

	// 4. Persist to ledger state
	anchorBytes, err := json.Marshal(anchor)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal anchor record: %v", err)
	}

	err = ctx.GetStub().PutState(anchorKey, anchorBytes)
	if err != nil {
		return nil, fmt.Errorf("failed to store anchor on ledger: %v", err)
	}

	err = ctx.GetStub().PutState(idempotencyKey, anchorBytes)
	if err != nil {
		return nil, fmt.Errorf("failed to store idempotency record on ledger: %v", err)
	}

	// Emit blockchain audit event
	_ = ctx.GetStub().SetEvent("EvidenceCommitmentAnchored", anchorBytes)

	return &anchor, nil
}

// GetCommitment retrieves an anchored commitment by eventId.
func (s *CustodySmartContract) GetCommitment(ctx contractapi.TransactionContextInterface, eventID string) (*EvidenceAnchor, error) {
	anchorKey := fmt.Sprintf("ANCHOR_%s", eventID)
	anchorBytes, err := ctx.GetStub().GetState(anchorKey)
	if err != nil {
		return nil, fmt.Errorf("failed reading state: %v", err)
	}
	if anchorBytes == nil {
		return nil, fmt.Errorf("commitment for event %s not found on ledger", eventID)
	}

	var anchor EvidenceAnchor
	err = json.Unmarshal(anchorBytes, &anchor)
	if err != nil {
		return nil, fmt.Errorf("failed to unmarshal anchor: %v", err)
	}
	return &anchor, nil
}

// VerifyCommitment verifies whether an eventId matches the expected payload digest.
func (s *CustodySmartContract) VerifyCommitment(ctx contractapi.TransactionContextInterface, eventID string, expectedDigest string) (bool, error) {
	anchor, err := s.GetCommitment(ctx, eventID)
	if err != nil {
		return false, err
	}
	return anchor.PayloadDigest == expectedDigest, nil
}

func main() {
	cc, err := contractapi.NewChaincode(&CustodySmartContract{})
	if err != nil {
		fmt.Printf("Error creating SAT-SA custody chaincode: %s\n", err)
		return
	}

	if err := cc.Start(); err != nil {
		fmt.Printf("Error starting SAT-SA custody chaincode: %s\n", err)
	}
}
