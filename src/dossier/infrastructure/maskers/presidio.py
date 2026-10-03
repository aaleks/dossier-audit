"""The `presidio` masker: Presidio's analyzer over spaCy's `lg` models (spec 021).

Presidio finds candidate spans and nothing else. Which are masked, and what
each becomes, is `dossier.domain.masking`'s decision. Two of Presidio's
defaults reach the network, and neither may: the hash boundary has four
packages left of it (R0.19), and this is not one.

- **Models are never fetched (R21.10).** A plain `AnalyzerEngine()`, or a model
  name it cannot find, makes Presidio call `spacy.cli.download`, which fetches
  and then installs with `pip` in a subprocess. So each model is checked to be
  installed at its pinned version, loaded here with `spacy.load`, and handed
  to Presidio already loaded: an engine whose `nlp` is set never loads one.
- **The suffix list is never fetched (R21.11).** Presidio's e-mail recogniser
  asks `tldextract`, which fetches the public suffix list on a machine that
  has never fetched it, and caches whichever list it got. Pointed here at the
  list its wheel ships with and at no URL, it reaches nothing, and two
  machines read the same list.

Heavy imports happen inside the functions that need them, as `mlflow` is
imported: `dossier` without the `masking` extra must still import this module
to find out the masker is not installed.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from typing import Any

from dossier.domain.masking import Detection, MaskerUnavailable, MaskingDeclaration

# The model each language is read with, and the version pinned in the
# `masking-models` extra. The masker's version names every one of them: moving
# a pin is raising `VERSION` (R5.4).
MODELS: dict[str, tuple[str, str]] = {
    "en": ("en_core_web_lg", "3.8.0"),
    "de": ("de_core_news_lg", "3.8.0"),
    "fr": ("fr_core_news_lg", "3.8.0"),
    "it": ("it_core_news_lg", "3.8.0"),
}
# presidio-analyzer 2.2.364, spaCy 3.8.16, the four models above at 3.8.0,
# tldextract's bundled suffix list, and the recognisers built below.
VERSION = "1.0.0"

# What spaCy's models call an entity, as Presidio names it. The German, French
# and Italian models write PER, LOC and ORG; MISC is nothing Presidio masks.
_LABELS = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "LOCATION": "LOCATION",
    "ORG": "ORGANIZATION",
    "ORGANIZATION": "ORGANIZATION",
    "NORP": "NRP",
}
# Words that, beside a phone number, lift its score: a number alone scores 0.4,
# under a threshold of 0.5, and the German incident says `Telefon`, not `phone`.
_PHONE_CONTEXT = [
    "phone",
    "telephone",
    "call",
    "mobile",
    "telefon",
    "tel",
    "handy",
    "natel",
    "téléphone",
    "portable",
    "telefono",
    "cellulare",
]
# Every type the recognisers built below can find (R21.7 row 4).
BUILT_IN = frozenset(
    {
        "PERSON",
        "LOCATION",
        "ORGANIZATION",
        "NRP",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "IBAN_CODE",
        "CREDIT_CARD",
        "URL",
        "IP_ADDRESS",
    }
)


def _one_line(text: str) -> str:
    """`text` with each line break read as a space, every offset where it was.

    spaCy's models read a line break as a word, and one opening a paragraph
    hid the name after it: `de_core_news_lg` found no person in `PLAY-6002`'s
    paragraph "Hans Muster aus dem Filialnetz", and found him with the break
    before it read as a space (measured 2026-10-03, R21.12). One character for
    one, so a span found here is the same span in the text that is masked.
    """
    return text.replace("\r", " ").replace("\n", " ")


def install_command(model: str, pinned: str) -> str:
    """What puts `model` at its pinned version where `spacy.load` finds it."""
    return "uv sync --extra masking --extra masking-models"


class PresidioMasker:
    """Presidio's analyzer, one engine per language, each built on first use."""

    id = "presidio"
    version = VERSION

    def __init__(self, declaration: MaskingDeclaration) -> None:
        self.declaration = declaration
        self.entities = BUILT_IN | frozenset(declaration.patterns)
        self._engines: dict[str, Any] = {}

    def detect(self, text: str, *, language: str) -> list[Detection]:
        engine = self._engine(language)
        found = engine.analyze(
            text=_one_line(text),
            language=language,
            entities=sorted(set(self.declaration.entities) & self.entities),
        )
        return [
            Detection(
                start=result.start,
                end=result.end,
                entity=result.entity_type,
                score=result.score,
            )
            for result in found
        ]

    def _engine(self, language: str) -> Any:
        if language not in self._engines:
            self._engines[language] = _build(language, self.declaration)
        return self._engines[language]


def _checked(language: str) -> str:
    """The model `language` is read with, refused unless installed at its pin (R21.10)."""
    if language not in MODELS:
        raise MaskerUnavailable(
            f"the presidio masker reads {', '.join(sorted(MODELS))}; "
            f"it has no model for {language!r}"
        )
    model, pinned = MODELS[language]
    try:
        found = installed_version(model)
    except PackageNotFoundError:
        found = None
    if found != pinned:
        held = "is not installed" if found is None else f"is installed at {found}"
        raise MaskerUnavailable(
            f"spaCy model {model} {pinned} is needed to read {language!r} text, and "
            f"{held}. dossier never downloads a model. Install it: "
            f"{install_command(model, pinned)}"
        )
    return model


def _offline_suffix_list() -> None:
    """`tldextract` reading the suffix list its wheel ships with, from no URL (R21.11)."""
    import tldextract
    import tldextract.tldextract as extractor

    extractor.TLD_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def _build(language: str, declaration: MaskingDeclaration) -> Any:
    """An analyzer for `language`, whose model was loaded here and never fetched."""
    model = _checked(language)
    _offline_suffix_list()

    import spacy
    from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
    from presidio_analyzer.nlp_engine import NerModelConfiguration, SpacyNlpEngine
    from presidio_analyzer.predefined_recognizers import (
        CreditCardRecognizer,
        EmailRecognizer,
        IbanRecognizer,
        IpRecognizer,
        PhoneRecognizer,
        SpacyRecognizer,
        UrlRecognizer,
    )

    ner = NerModelConfiguration(
        model_to_presidio_entity_mapping=_LABELS, labels_to_ignore=["MISC"]
    )
    nlp_engine = SpacyNlpEngine(
        models=[{"lang_code": language, "model_name": model}], ner_model_configuration=ner
    )
    # Set before the analyzer sees the engine: an engine whose `nlp` is set is
    # loaded, and Presidio never calls `load()` -- the path that downloads.
    nlp_engine.nlp = {language: spacy.load(model)}

    registry = RecognizerRegistry(supported_languages=[language])
    for recogniser in (
        SpacyRecognizer(
            supported_language=language,
            supported_entities=["PERSON", "LOCATION", "ORGANIZATION", "NRP"],
        ),
        EmailRecognizer(supported_language=language),
        PhoneRecognizer(supported_language=language, context=_PHONE_CONTEXT),
        IbanRecognizer(supported_language=language),
        CreditCardRecognizer(supported_language=language),
        UrlRecognizer(supported_language=language),
        IpRecognizer(supported_language=language),
    ):
        registry.add_recognizer(recogniser)
    for entity, pattern in sorted(declaration.patterns.items()):
        registry.add_recognizer(
            PatternRecognizer(
                supported_entity=entity,
                supported_language=language,
                patterns=[Pattern(name=entity, regex=pattern.regex, score=pattern.score)],
                context=pattern.context or None,
            )
        )
    return AnalyzerEngine(
        nlp_engine=nlp_engine, registry=registry, supported_languages=[language]
    )
