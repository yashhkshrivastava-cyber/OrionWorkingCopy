"""The Orion Copilot: an assistant that answers from the application's data and can act on a person's behalf.

    router (routers/ai_router.py)  ->  orchestrator  ->  provider (Claude)        the model, behind an interface
                                          |
                                          +-->  tools  ->  application services    the only way to data or actions
                                          +-->  store                              conversations, audit, confirmations
                                          +-->  safety                             untrusted data, limits, figure checks

See docs/features.md ("AI Copilot") for the rules.
"""
