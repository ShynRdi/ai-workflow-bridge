from orchestrator_core import CoreMixin
from orchestrator_messages import MessageMixin
from orchestrator_response import ResponseMixin
from orchestrator_approval import ApprovalMixin
from orchestrator_execution import ExecutionMixin
from orchestrator_reporting import ReportingMixin


class Orchestrator(CoreMixin, MessageMixin, ResponseMixin, ApprovalMixin, ExecutionMixin, ReportingMixin):
    pass
