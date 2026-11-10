"""Optional: turn OFF SSL certificate checks (--insecure). Use only on a network you trust."""
import os
import ssl

_INSECURE = False


def enable_insecure():
    global _INSECURE
    _INSECURE = True
    os.environ["PYTHONHTTPSVERIFY"] = "0"
    try:
        import urllib3
        urllib3.disable_warnings()
    except ImportError:
        pass
    try:  # requests: used by Google login / token refresh
        import requests
        orig = requests.Session.merge_environment_settings

        def patched(self, url, proxies, stream, verify, cert):
            s = orig(self, url, proxies, stream, verify, cert)
            s["verify"] = False
            return s

        requests.Session.merge_environment_settings = patched
    except ImportError:
        pass


def insecure() -> bool:
    return _INSECURE


def ssl_context():
    return ssl._create_unverified_context() if _INSECURE else ssl.create_default_context()


def google_http():
    if not _INSECURE:
        return None
    import httplib2
    return httplib2.Http(disable_ssl_certificate_validation=True)


def anthropic_kwargs() -> dict:
    if not _INSECURE:
        return {}
    import anthropic
    return {"http_client": anthropic.DefaultHttpxClient(verify=False)}


def genai_kwargs() -> dict:
    if not _INSECURE:
        return {}
    from google.genai import types
    return {"http_options": types.HttpOptions(client_args={"verify": False})}


def groq_kwargs() -> dict:
    if not _INSECURE:
        return {}
    import httpx
    return {"http_client": httpx.Client(verify=False)}
