"""
文件职责：定义 BankPilot 可预期的业务异常体系。

主要内容：认证、模型、导入冲突、关系校验、操作越权和工具执行失败。
关键边界：每类异常对应稳定错误码，供运行状态和审计事件持久化。
"""


class BankPilotError(Exception):
    code = "INTERNAL_ERROR"


class AuthenticationError(BankPilotError):
    code = "AUTHENTICATION_FAILED"


class ModelUnavailableError(BankPilotError):
    code = "MODEL_UNAVAILABLE"


class ModelOutputInvalidError(BankPilotError):
    code = "MODEL_OUTPUT_INVALID"


class ActionNotAllowedError(BankPilotError):
    code = "ACTION_NOT_ALLOWED"


class ToolExecutionError(BankPilotError):
    code = "TOOL_EXECUTION_FAILED"


class ReviewCapacityError(ToolExecutionError):
    """所选期间超过确定性核查容量；相同输入重试不能解决。"""


class ImportConflictError(BankPilotError):
    code = "IMPORT_CONFLICT"


class RelationError(BankPilotError):
    """携带关系工作区使用的稳定错误代码和 HTTP 状态。"""

    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
