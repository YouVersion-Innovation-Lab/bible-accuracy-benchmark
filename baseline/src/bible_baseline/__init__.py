"""bible_baseline — a thin OpenAI-compatible wrapper around jittle (Jot & Tittle).

This package is *pure protocol glue*. It translates OpenAI Chat Completions
requests into jittle ``ChatRequest`` objects and jittle ``ChatResponse`` objects
back into OpenAI Chat Completions responses. It contains NO Scripture, routing,
translation, or verification logic — every such decision belongs to jittle. The
goal is simply to let an OpenAI-compatible client exercise jittle's system.

It is deliberately independent of the Bible Accuracy Benchmark: it imports only
``jot*`` packages and knows nothing about how (or whether) it is being evaluated.
"""

__version__ = "0.1.0"
