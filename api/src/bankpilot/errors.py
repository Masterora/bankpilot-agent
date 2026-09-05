"""
文件职责：定义 BankPilot 可预期的业务异常体系。

主要内容：认证、模型、导入冲突、操作越权和工具执行失败。
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


class ImportConflictError(BankPilotError):
    code = "IMPORT_CONFLICT"
