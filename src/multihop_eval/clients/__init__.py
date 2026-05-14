"""External integrations: ArangoDB gateway + OpenAI-compatible LLM client.

Both are wrapped behind small classes that the rest of the codebase depends
on; the unit-test suite substitutes in fakes via `tests/conftest.py`.

Import from the concrete submodule, e.g.:

    from multihop_eval.clients.arango_gateway import ArangoGateway
    from multihop_eval.clients.llm_client import LLMClient, ContextLengthError

(Eager re-exports here would create a circular dependency on
`multihop_eval.config`, which both submodules import from.)
"""
