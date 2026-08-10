"""Provider adapters. No module outside this package may interpret provider claims."""

from clue_auth.providers.clerk import ClerkAuthenticator, ClerkJwtConfig

__all__ = ["ClerkAuthenticator", "ClerkJwtConfig"]
