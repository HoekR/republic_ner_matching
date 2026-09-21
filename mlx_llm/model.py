"""Local LLM model loading, caching, and generation via mlx-lm."""

from __future__ import annotations

from typing import Any

# UNVERIFIED — this exact repo id/tag has not been confirmed against Hugging Face.
# Confirm with a small model smoke test before real use; see the package README.
DEFAULT_MODEL = "mlx-community/Qwen2.5-32B-Instruct-4bit"

_MODEL_CACHE: dict[str, tuple[Any, Any]] = {}


def _get_model(model: str, _loader: Any = None) -> tuple[Any, Any]:
    """Load and cache a model + tokenizer from mlx-lm.

    Args:
        model: Model identifier (e.g. "mlx-community/Qwen2.5-7B-Instruct-4bit").
        _loader: (testing only) Callable to load a model; defaults to mlx_lm.load.

    Returns:
        (model_obj, tokenizer) tuple.

    Raises:
        Any exception from the underlying loader (e.g., mlx_lm.load), allowing
        the caller to handle import errors, network issues, or model resolution
        failures. Caching succeeds only after a successful load.
    """
    if model in _MODEL_CACHE:
        return _MODEL_CACHE[model]

    if _loader is None:
        # Late import so mlx_lm is not required for imports of this module
        import mlx_lm
        _loader = mlx_lm.load

    model_obj, tokenizer = _loader(model)
    _MODEL_CACHE[model] = (model_obj, tokenizer)
    return model_obj, tokenizer


def check_available(model: str = DEFAULT_MODEL) -> bool:
    """Check if a model is available (resolvable and loadable).

    Attempts to import mlx_lm and load the given model via _get_model.
    Returns True only if both succeed; returns False on any exception
    (import error, model not found, network issues, etc.).

    Note:
        This is not a network/daemon check (no Ollama-style daemon ping).
        It actually attempts a load, so a slow/cold call may trigger a
        multi-GB download from Hugging Face the first time the model is used.

    Args:
        model: Model identifier. Defaults to DEFAULT_MODEL.

    Returns:
        True if the model is available, False otherwise. Never raises.
    """
    try:
        _get_model(model)
        return True
    except Exception:  # noqa: BLE001
        return False


def generate(
    prompt: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    max_tokens: int = 512,
    _loader: Any = None,
    _generate_fn: Any = None,
) -> str | None:
    """Generate text from a prompt using mlx-lm.

    Loads the model (cached on subsequent calls), calls mlx_lm.generate,
    and returns the generated text. Catches all exceptions and returns None
    on any failure (model load, generation, or otherwise).

    Note:
        Signature verified against the installed mlx-lm 0.31.3 by introspection
        (not assumed): ``generate(model, tokenizer, prompt, verbose=False,
        **kwargs)`` forwards ``**kwargs`` to ``stream_generate`` -> ``generate_step``,
        which reads sampling behavior from a ``sampler`` callable, not a bare
        ``temperature`` kwarg. Temperature is wired through explicitly via
        ``mlx_lm.sample_utils.make_sampler(temp=temperature)`` and passed as
        ``sampler=``. ``make_sampler``'s own default is ``temp=0.0`` (greedy),
        which is why every existing call site (all pass ``temperature=0.0`` for
        deterministic judging) happened to work even before this was wired
        through explicitly — but an uncalled parameter is a latent bug, not a
        safe default, so this is fixed rather than left as a documented no-op.

        Also verified by introspection: ``stream_generate`` does NOT apply a
        chat template — it calls ``tokenizer.encode(prompt, ...)`` on the raw
        string, full stop. A daemon-backed alternative (Ollama's ``/api/generate``,
        which applies the model's packaged ``Modelfile`` ``TEMPLATE`` server-side
        unless ``"raw": true`` is set; LM Studio's ``/v1/chat/completions``) would
        format an instruct-tuned model's prompt before this function ever sees
        it. Passing a raw instruction string straight through here, unformatted,
        risks the model treating it as free continuation text rather than an
        instruction to follow — a real quality regression versus what every one
        of this package's callers previously got from a daemon, not a cosmetic
        gap. Fixed below: apply the tokenizer's own chat template when one is
        configured, exactly what those daemons were doing on the caller's behalf.

    Args:
        prompt: The text prompt to complete.
        model: Model identifier. Defaults to DEFAULT_MODEL.
        temperature: Sampling temperature (0.0 = deterministic/greedy). Defaults to 0.0.
        max_tokens: Maximum tokens to generate. Defaults to 512.
        _loader: (testing only) Callable to load a model; defaults to mlx_lm.load.
        _generate_fn: (testing only) Callable matching mlx_lm.generate's
            signature; defaults to mlx_lm.generate. Lets tests observe the
            formatted prompt without mlx_lm installed or a real model loaded.

    Returns:
        Generated text as a string, or None on any failure. Never raises.
    """
    try:
        model_obj, tokenizer = _get_model(model, _loader=_loader)

        if _generate_fn is None:
            # Late import so mlx_lm is not required for imports of this module
            import mlx_lm
            _generate_fn = mlx_lm.generate

        from mlx_lm.sample_utils import make_sampler

        # Apply the tokenizer's chat template when the model has one, so a
        # plain instruction string gets the same instruct-formatting a
        # chat-completions endpoint would have applied server-side. Guarded
        # and wrapped in its own try/except: a malformed or unusual template
        # should degrade to the raw prompt, not take down generation entirely.
        formatted_prompt = prompt
        has_template = getattr(tokenizer, "has_chat_template", False)
        if has_template:
            try:
                formatted_prompt = tokenizer.apply_chat_template(
                    [{"role": "user", "content": prompt}],
                    tokenize=False,
                    add_generation_prompt=True,
                )
            except Exception:  # noqa: BLE001
                formatted_prompt = prompt

        sampler = make_sampler(temp=temperature)
        result = _generate_fn(
            model_obj,
            tokenizer,
            prompt=formatted_prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=False,
        )
        return result
    except Exception:  # noqa: BLE001
        return None
