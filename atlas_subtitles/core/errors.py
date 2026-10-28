class AtlasError(Exception):
    """Base error; `code` is a stable key the GUI translates (see gui/strings.py)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class Cancelled(AtlasError):
    def __init__(self):
        super().__init__("cancelled")
