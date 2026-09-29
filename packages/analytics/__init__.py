"""Analytics package for SAT-SA supervisory assessments."""

from packages.analytics.claims import ClaimReconciler, ReconciliationInterval
from packages.analytics.context import AssessmentContext, SourceReference
from packages.analytics.detectors import (
    BaseDetector,
    DetectorResult,
    EscalationEvidenceDetector,
    InvestigationEvidenceDetector,
    KPIReconciliationDetector,
    MonitoringCoverageDetector,
    RecurrenceContextDetector,
)
from packages.analytics.obligations import ObligationEvaluator, PolicyException
from packages.analytics.peer_comparison import PeerCohortResult, PeerComparisonService
from packages.analytics.reconstruction import EvidenceGraphReconstructor
from packages.analytics.service import (
    AnalysisService,
    SubmissionNotCommittedError,
    SubmissionNotFoundError,
)
from packages.analytics.supervisory_summary import (
    SupervisoryOverviewResult,
    SupervisorySummaryService,
)
from packages.analytics.trends import PeriodTrendsResult, PeriodTrendsService
from packages.analytics.unusual_patterns import UnusualPatternService, UnusualPatternsResult

__all__ = [
    "AssessmentContext",
    "SourceReference",
    "ClaimReconciler",
    "ReconciliationInterval",
    "ObligationEvaluator",
    "PolicyException",
    "EvidenceGraphReconstructor",
    "BaseDetector",
    "DetectorResult",
    "InvestigationEvidenceDetector",
    "EscalationEvidenceDetector",
    "MonitoringCoverageDetector",
    "KPIReconciliationDetector",
    "RecurrenceContextDetector",
    "AnalysisService",
    "SubmissionNotCommittedError",
    "SubmissionNotFoundError",
    "SupervisorySummaryService",
    "SupervisoryOverviewResult",
    "PeerComparisonService",
    "PeerCohortResult",
    "PeriodTrendsService",
    "PeriodTrendsResult",
    "UnusualPatternService",
    "UnusualPatternsResult",
]
