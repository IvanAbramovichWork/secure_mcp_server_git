class SafeError(Exception):
    def __init__(self, code: str = "INTERNAL_ERROR") -> None:
        self.code = code
        super().__init__("Request could not be completed.")
