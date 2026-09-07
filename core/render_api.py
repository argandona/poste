"""TECSUR es 100% local: no hay proyecto externo al cual escribir.

Se conserva la firma `actualizar_suministro` para no romper imports en
`serializers.py`, pero es un no-op. El estado del suministro local ya se
actualiza directamente en la base de datos dentro de la liquidación.
"""


def actualizar_suministro(suministro_id, payload):  # noqa: D401
    """No-op: TECSUR no sincroniza con ningún sistema externo."""
    return {}
