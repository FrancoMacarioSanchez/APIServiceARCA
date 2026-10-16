# audit/authentication.py
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings

class DummyInternalUser:
    """
    DRF requiere que la autenticación devuelva un objeto 'User'.
    Como acá los que consumen la API son sistemas y no personas,
    usamos un objeto dummy que siempre da True en is_authenticated.
    """
    is_authenticated = True

class StaticApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        api_key = request.headers.get('X-Api-Key')

        if not api_key:
            return None  # Deja que otras clases intenten, o falla si esta es la única

        valid_keys = getattr(settings, 'INTERNAL_API_KEYS', {})

        if api_key not in valid_keys.values():
            raise AuthenticationFailed('API Key inválida o no autorizada.')

        return (DummyInternalUser(), api_key)