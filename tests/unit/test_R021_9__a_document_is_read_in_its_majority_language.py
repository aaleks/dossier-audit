"""R21.9 — a document is read in the declared language whose function words it uses most.

Presidio's named-entity recognition is one spaCy model per language, and a
model reading the wrong language finds names that are not names and misses the
ones that are: the English model found 26 "people" in the German `INC-5699`,
and the German model missed the canaries' names in English text (spec 021,
measured 2026-10-02). So each document is read in one language, chosen here by
a pure vote over the words that carry no meaning of their own -- `der`, `the`,
`le`, `il` -- which every document has many of, and no client name is.

The texts below are the opening prose of the corpus documents each row names.
"""

from __future__ import annotations

FOUR = ["en", "de", "fr", "it"]

# `INC-5699-kassenterminals-offline-firewall.pdf`, the corpus's German postmortem.
INC_5699 = (
    "Am Montagmorgen waren die Kassenterminals in 14 Filialen nicht erreichbar. "
    "Die Ursache war eine Firewall-Regel, die bei der nächtlichen Änderung "
    "entfernt wurde. Der Störungsbericht wurde von J. Keller erstellt und mit "
    "dem Filialnetz abgestimmt."
)
# `INC-5102-orders-api-oom-postmortem.pdf`.
INC_5102 = (
    "The orders-api pods were OOMKilled under a retry storm, and order submission "
    "was degraded for 47 minutes. The heap limit had not been raised when the "
    "batch size was doubled, and the alert fired only after the second restart."
)
# `PLAY-6002`: German prose that names English systems.
PLAY_6002 = (
    "Erika Mustermann meldete, dass die orders-api nicht antwortete. Der Kafka "
    "consumer lag stieg auf 40000 Nachrichten, und die settlement pipeline wurde "
    "angehalten, bis das Team den Fehler im retry handler gefunden hatte."
)
# `PLAY-4004-incident-register.csv`: keys and numbers, no prose at all.
PLAY_4004 = "key,opened,minutes\nPLAY-4001,2026-08-02,41\nPLAY-4002,2026-08-09,7\n"


def _language(text: str, languages=FOUR) -> str:
    from dossier.domain.masking import language_of

    return language_of(text, languages)


class TestADocumentIsReadInItsMajorityLanguage:
    """R21.9 — the declared language whose function words a document uses most."""

    def test_a_german_postmortem_is_read_in_german(self):
        """Row 1: the one where `INC-5699` is written in German."""
        assert _language(INC_5699) == "de"

    def test_an_english_postmortem_is_read_in_english(self):
        """Row 2: the one where `INC-5102` is written in English."""
        assert _language(INC_5102) == "en"

    def test_german_prose_naming_english_systems_is_read_in_german(self):
        """Row 3: the one where a document is read in its majority language.

        `orders-api`, `consumer lag` and `retry handler` are English words in a
        German sentence; the sentence is German.
        """
        assert _language(PLAY_6002) == "de"

    def test_a_document_with_no_vote_falls_to_the_first_declared_language(self):
        """Row 4: the one where a vote with no votes falls to the order the author wrote.

        A CSV of keys and numbers holds none of the four languages' words.
        """
        assert _language(PLAY_4004) == "en"
        assert _language(PLAY_4004, ["it", "de"]) == "it"

    def test_the_vote_is_only_among_the_declared_languages(self):
        """Row 5, a counter-example: the one where English is all that is declared.

        `INC-5699` is German, and is read in English all the same: a language
        the author did not declare is never chosen, whatever the text says.
        """
        assert _language(INC_5699, ["en"]) == "en"
