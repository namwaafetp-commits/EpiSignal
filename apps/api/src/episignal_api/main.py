"""Production entry point.

Importing this module validates configuration first, so a misconfigured
deployment fails immediately instead of serving a half-working API.
"""

from episignal_api.factory import create_app, load_runtime_settings

app = create_app(load_runtime_settings())
