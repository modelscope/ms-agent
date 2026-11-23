from typing import Literal

from pydantic import BaseModel


class SearchProvider(BaseModel):
    """One selectable web-search engine.

    `id` is the value the SDK's WebSearchTool expects in
    `tools.web_search.engine`; the set of valid ids comes from the SDK itself
    (see backends.ms_agent.search) rather than being duplicated here.
    """

    id: str
    label: str
    # arxiv talks to a public API and takes no credentials, so the UI hides the
    # key field for it entirely instead of asking for something unusable.
    requires_key: bool
    # Usable with no credentials, on a reduced free tier — distinct from
    # `requires_key`: Tavily still ACCEPTS a key (and a key lifts its quota), so
    # the key field stays visible, but running without one is a supported state
    # rather than a misconfiguration. This is what stops the UI from nagging
    # about an unconfigured engine that in fact works.
    supports_keyless: bool = False


class SearchSettings(BaseModel):
    """Global web-search configuration, as reported to the UI.

    Deliberately carries `has_key` and NOT the key: the secret is write-only,
    so a compromised read path (or a screenshot of the settings page) cannot
    leak it. The UI uses the flag for its "configured" tag and to pick which
    placeholder to show.

    `has_key` describes the stored config only — an environment variable the SDK
    might fall back to is not reported as configured, because the page could
    neither edit nor clear such a key and mixing the two made the tag
    meaningless. See the search adapter's module docstring.
    """

    enabled: bool
    provider: str
    has_key: bool
    key_status: Literal["unset", "configured", "unavailable"] = "unset"
    # Whether the SELECTED provider works without a key. Carried on the settings
    # object (not just the provider list) so the composer can decide whether to
    # warn from the one object it already loads.
    supports_keyless: bool = False


class SearchSettingsUpdate(BaseModel):
    enabled: bool
    provider: str
    # Tri-state, because the field starts blank on every page load and a blank
    # submit must not wipe a working key:
    #   None -> leave the stored key untouched
    #   ""   -> clear it
    #   text -> replace it
    api_key: str | None = None
