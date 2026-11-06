class AppError(Exception):
    """Safe, stable application error; never includes upstream credentials or raw bodies."""

    def __init__(self, code: str, message: str, status: int = 400, *, details: dict | None = None):
        self.code, self.message, self.status = code, message, status
        self.details = details
        super().__init__(message)
