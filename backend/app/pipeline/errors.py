class PermanentError(Exception):
    """The input is bad. Retrying cannot help, so the admin sees this message at once."""
