"""Opportunity intelligence: questionnaire → capability profile → dynamically
discovered opportunities → live market evidence → deterministic ranking.

The LLM (through the existing LiteLLM gateway) extracts structure and proposes
hypotheses. The market layer (seeded official statistics + live postings via
the Apify boundary) validates them. Ranking is a deterministic, configurable
formula — the LLM explains scores, it never sets them. Every market number
carries its source, metric, period and retrieval time; missing history is
reported as insufficient, never invented.
"""
