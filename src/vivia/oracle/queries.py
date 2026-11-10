"""SQL partage hors des outils d'exploration (resolution d'identifiants)."""

RESOLVE_OWNERS = "SELECT DISTINCT owner FROM all_objects WHERE object_name = :name"
