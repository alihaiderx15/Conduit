class ToolEngineError(Exception): pass
class DuplicateToolError(ToolEngineError): pass
class ToolNotFoundError(ToolEngineError): pass
class ToolValidationError(ToolEngineError): pass
